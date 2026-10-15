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

import contextlib
import contextvars
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import requests
from babel import Locale
from babel.lists import format_list

from .locale import SkillResources
from .service import request_headers as request_headers

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
        def ask() -> requests.Response:
            response = requests.post(
                f"{service_url.rstrip('/')}/v1/knowledge/answer",
                json=request_payload,
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()
            return response

        response = run_noticing(ask, lang=lang, mode=mode)
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


# -- telling the visitor where the lookup is going ---------------------------------
#
# A lookup is slow on purpose: the service asks its providers in parallel and waits
# for the good ones. For those seconds the chat is blank, or a voice device is silent.
# So when a lookup takes longer than NOTICE_DELAY, the visitor is told which sources
# are being asked, once, while the request carries on. A quicker lookup says nothing:
# a notice that arrives with the answer is only noise.
#
# The notice belongs to the turn, not to a call. A skill opens it where it has the
# message to answer, and every knowledge call under it (this module's, or a skill's
# own request wrapped in `run_noticing`) uses it, so the skills behave alike.

NOTICE_DELAY = 0.6
# Not the matching tree (locale/): every folder there must declare a matching rule.
_NOTICE_RESOURCES = SkillResources(Path(__file__).parent / "shared_dialog")
#: The sources a question is put to, as the visitor knows them, and the provider
#: ids the service answers with for the same ones. Wikidata rides with Wikipedia
#: and is not named; an answer from a source not named here is still cited.
_ASKED = {"wikipedia": "Wikipedia", "duckduckgo": "DuckDuckGo"}
_ASKED_FOR_RESEARCH = {"openalex": "OpenAlex", "crossref": "Crossref", "arxiv": "arXiv"}
#: The service says "web-search" for DuckDuckGo's HTML fallback.
_SAME_SOURCE = {"web-search": "duckduckgo"}

T = TypeVar("T")


@dataclass
class LookupNotice:
    """One turn's notice: how to say it, and what it said."""

    speak: Callable[[str], None]
    #: Provider ids named in the notice; empty until it has been said.
    named: frozenset[str] = field(default_factory=frozenset)

    def names(self, provider: str) -> bool:
        """Whether the notice already told the visitor about this provider."""
        key = provider.casefold()
        return _SAME_SOURCE.get(key, key) in self.named


_CURRENT: contextvars.ContextVar[LookupNotice | None] = contextvars.ContextVar(
    "thalovant_lookup_notice", default=None)


@contextlib.contextmanager
def lookup_notice(speak: Callable[[str], None]) -> Iterator[LookupNotice]:
    """Open this turn's notice; `speak(text)` says one line to the visitor."""
    notice = LookupNotice(speak)
    token = _CURRENT.set(notice)
    try:
        yield notice
    finally:
        _CURRENT.reset(token)


def current_notice() -> LookupNotice | None:
    """The notice open for this turn, if any."""
    return _CURRENT.get()


def notice_text(lang: str | None, mode: str) -> tuple[str, frozenset[str]]:
    """The localized line for a lookup in this mode, and the providers it names."""
    asked = dict(_ASKED)
    if mode == "research":
        asked.update(_ASKED_FOR_RESEARCH)
    # The list is joined in the language of the line that carries it, which is the
    # requested one only when that language has a line: Japanese falls back to
    # English words and must not get a Japanese comma between them.
    spoken = next((candidate for candidate in _NOTICE_RESOURCES.candidate_langs(lang)
                   if _NOTICE_RESOURCES.lines(candidate, "dialog", "knowledge.notice.dialog")),
                  _NOTICE_RESOURCES.default_lang)
    sources = format_list(list(asked.values()), locale=Locale.parse(spoken, sep="-"))
    line = _NOTICE_RESOURCES.dialog("knowledge.notice", lang, {"sources": sources})
    return line, frozenset(asked)


def run_noticing(work: Callable[[], T], *, lang: str | None, mode: str,
                 delay: float | None = None) -> T:
    """Run `work`, which asks the service, and say where it is looking if it is slow.

    With no notice open (an API preview, a test) this is just `work()`. The
    notice is said at most once per turn, however many lookups the turn makes.
    """
    notice = _CURRENT.get()
    if notice is None or notice.named:
        return work()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="knowledge-lookup") as pool:
        future = pool.submit(work)
        try:
            return future.result(timeout=NOTICE_DELAY if delay is None else delay)
        except FutureTimeout:
            text, named = notice_text(lang, mode)
            notice.named = named
            notice.speak(text)
            return future.result()
