"""Client for the Thalovant knowledge service.

This was vendored byte-identically into learning-lounge, safety-guide and
source-scout -- 210 lines, three copies, kept in step by a convention written
in its own docstring ("edit the canonical copy and mirror it verbatim") and by
a platform contracts gate that does not exist in the platform repository.

It lives here now, so the three skills import it instead of carrying it. Same
code; anything skill-specific still belongs in the caller, passed as an
argument, never in this module.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import requests

AI_AUGMENTATION_DEFAULT = "auto"
SUPPORTED_AUDIENCE_AGE_BOUNDARIES = (13, 16, 18, 21)
SUPPORTED_AUDIENCE_AGE_BOUNDARY_STRINGS = tuple(
    str(boundary) for boundary in SUPPORTED_AUDIENCE_AGE_BOUNDARIES
)

# Outcome of the service-side age policy for one request.
POLICY_NONE = ""
POLICY_BLOCKED = "blocked"
POLICY_UNAVAILABLE = "unavailable"
# The service found nothing for this question while working normally. Distinct
# from POLICY_UNAVAILABLE because the visitor is told a different thing: not
# knowing is honest, claiming the hub cannot reach its own service is not.
POLICY_NO_ANSWER = "no_answer"


def normalize_ai_augmentation(value) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    text = str(value or "").strip().casefold()
    if text in ("on", "true", "yes", "enabled", "enable", "force", "forced", "always"):
        return "on"
    if text in ("off", "false", "no", "disabled", "disable", "source", "sources",
                "source-only", "source_only", "none"):
        return "off"
    return AI_AUGMENTATION_DEFAULT


def parse_age_policy(configured) -> dict | None:
    """Validate a skill-settings age policy into a request payload.

    Returns None for an absent or disabled policy. Raises ValueError for an
    enabled policy that cannot be trusted, so a protected hub fails closed
    rather than asking the service for an unrestricted answer.
    """
    if configured is None:
        return None
    if not isinstance(configured, dict):
        raise ValueError("age_policy must be an object")  # noqa: TRY004 - a protected hub must fail closed
    enabled = configured.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("age_policy.enabled must be a boolean")  # noqa: TRY004
    if not enabled:
        return None
    audience_under_age = configured.get("audience_under_age", 13)
    if (
        isinstance(audience_under_age, str)
        and audience_under_age in SUPPORTED_AUDIENCE_AGE_BOUNDARY_STRINGS
    ):
        audience_under_age = int(audience_under_age)
    if not isinstance(audience_under_age, int) or isinstance(audience_under_age, bool):
        raise ValueError("age_policy.audience_under_age must be 13, 16, 18, or 21")  # noqa: TRY004
    if audience_under_age not in SUPPORTED_AUDIENCE_AGE_BOUNDARIES:
        raise ValueError("age_policy.audience_under_age must be 13, 16, 18, or 21")
    return {
        "enabled": True,
        "audience_under_age": audience_under_age,
    }


def request_headers(skill_name: str, skill_version: str, user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "X-Request-ID": f"{skill_name}-{uuid.uuid4().hex}",
        "X-Thalovant-Skill": skill_name,
        "X-Thalovant-Skill-Version": skill_version,
    }


PROVENANCE_SKILL = "skill"
PROVENANCE_SOURCE = "source"
PROVENANCE_LLM_AUGMENTED = "llm-augmented"


@dataclass(frozen=True)
class KnowledgeReply:
    """What the knowledge service said, and who wrote it: ``augmented`` is the
    service's own flag that a language model wrote the text from the evidence
    it cites, rather than quoting a source."""

    answer: str | None
    policy: str
    augmented: bool = False

    @property
    def provenance(self) -> str | None:
        if not self.answer:
            return None
        return PROVENANCE_LLM_AUGMENTED if self.augmented else PROVENANCE_SOURCE


def knowledge_answer(
    *,
    service_url: str,
    prompt: str,
    lang: str,
    mode: str,
    max_sources: int,
    augmentation: str,
    age_policy_setting,
    headers: dict[str, str],
    timeout: float,
    logger=None,
) -> tuple[str | None, str]:
    """Ask the knowledge service; see knowledge_reply for who wrote the answer."""
    reply = knowledge_reply(
        service_url=service_url,
        prompt=prompt,
        lang=lang,
        mode=mode,
        max_sources=max_sources,
        augmentation=augmentation,
        age_policy_setting=age_policy_setting,
        headers=headers,
        timeout=timeout,
        logger=logger,
    )
    return reply.answer, reply.policy


def knowledge_reply(
    *,
    service_url: str,
    prompt: str,
    lang: str,
    mode: str,
    max_sources: int,
    augmentation: str,
    age_policy_setting,
    headers: dict[str, str],
    timeout: float,
    logger=None,
) -> KnowledgeReply:
    """Ask the knowledge service and classify the age-policy outcome.

    Returns KnowledgeReply(answer, policy, augmented). POLICY_BLOCKED means the
    hub policy rated the content too mature; that reply is the policy speaking,
    so callers deliver it instead of substituting packaged content.
    POLICY_UNAVAILABLE means the age policy could not be evaluated, including
    invalid settings or an unavailable classifier. Callers report unavailability
    without repeating blocked-content wording. Both outcomes suppress packaged
    fallbacks.
    """
    if not service_url or not prompt:
        return KnowledgeReply(None, POLICY_NONE)
    try:
        age_policy = parse_age_policy(age_policy_setting)
    except ValueError as error:
        if logger is not None:
            logger.warning("Ignoring invalid age_policy setting: %s", error)
        return KnowledgeReply(None, POLICY_UNAVAILABLE)
    request_payload = {
        "prompt": prompt,
        "lang": lang,
        "mode": mode,
        "max_sources": max(1, int(max_sources)),
        "augmentation": augmentation,
    }
    if age_policy is not None:
        request_payload["age_policy"] = age_policy
    try:
        response = requests.post(
            f"{service_url.rstrip('/')}/v1/knowledge/answer",
            json=request_payload,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.HTTPError as error:
        status = getattr(error.response, "status_code", None)
        if status == 404:
            if logger is not None:
                logger.info("Knowledge service had no answer for this question")
            return KnowledgeReply(None, POLICY_NO_ANSWER)
        if logger is not None:
            logger.warning("Knowledge service request failed: %s", error)
        return KnowledgeReply(None, POLICY_NONE)
    except (requests.RequestException, ValueError) as error:
        if logger is not None:
            logger.warning("Knowledge service request failed: %s", error)
        return KnowledgeReply(None, POLICY_NONE)
    payload = payload or {}
    answer = str(payload.get("text") or "").strip()
    augmented = bool(payload.get("augmented"))
    result = payload.get("age_policy")
    if not isinstance(result, dict) or not result.get("filtered"):
        return KnowledgeReply(answer or None, POLICY_NONE, augmented)
    # The service fails closed when its classifier is unreachable, using the
    # same wording as a genuine ruling. That is an outage, not a ruling.
    if str(result.get("reason") or "") == "classifier_unavailable":
        if logger is not None:
            logger.warning("Knowledge age classifier unavailable; reporting an outage")
        return KnowledgeReply(None, POLICY_UNAVAILABLE)
    return KnowledgeReply(answer or None, POLICY_BLOCKED, augmented)
