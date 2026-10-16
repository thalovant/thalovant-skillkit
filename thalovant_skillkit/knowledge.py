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
import itertools
import json
import logging
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import requests

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
        payload = ask_service(
            service_url=service_url, request_payload=request_payload, headers=headers,
            timeout=timeout, lang=lang)
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


# -- telling the visitor where the answer comes from, while it is written ---------------
#
# A slow answer leaves the chat blank, or a voice device silent, for seconds. Most of
# them are spent after the service has chosen its source: translating the answer and
# having the model write it. The service says which source that is, before it starts
# (`Accept: application/x-ndjson`, see its README), and when the answer is still not
# there NOTICE_DELAY later the visitor is told "From Wikipedia…". An answer that follows
# at once says nothing first: a notice that arrives with the answer is only noise. One
# that comes from the cache or needs no provider never announces a source at all.
#
# The notice belongs to the turn, not to a call. A skill opens it where it has the
# message to answer, and every call to the service under it (`knowledge_reply`, or a
# skill's own request through `ask_service`) uses it, so the skills behave alike. The
# source is named once, up front; an answer that cites its sources can ask the notice
# which it already named, and not say them again at its end.

NOTICE_DELAY = 0.5
NDJSON = "application/x-ndjson"
# Not the matching tree (locale/): every folder there must declare a matching rule.
_NOTICE_RESOURCES = SkillResources(Path(__file__).parent / "shared_dialog")
#: Provider ids the service answers with, as the visitor knows them. These are proper
#: nouns, the same in every language.
PROVIDER_NAMES = {
    "wikipedia": "Wikipedia",
    "wikidata": "Wikidata",
    "wikihow": "wikiHow",
    "duckduckgo": "DuckDuckGo",
    "web-search": "DuckDuckGo",
    "wolfram": "WolframAlpha",
    "wolframalpha": "WolframAlpha",
    "openalex": "OpenAlex",
    "crossref": "Crossref",
    "arxiv": "arXiv",
    "pubmed": "PubMed",
    "semantic-scholar": "Semantic Scholar",
}
#: The service says "web-search" for DuckDuckGo's HTML fallback.
_SAME_SOURCE = {"web-search": "duckduckgo", "wolframalpha": "wolfram"}

T = TypeVar("T")
_LOG = logging.getLogger(__name__)


def provider_name(provider: str) -> str:
    """The name a visitor knows a provider id by."""
    key = provider.casefold()
    return PROVIDER_NAMES.get(key) or " ".join(
        part.capitalize() for part in key.replace("_", "-").split("-") if part)


@dataclass
class LookupNotice:
    """One turn's notice: how to say it, and what it said."""

    speak: Callable[[str], None]
    #: Provider ids the notice named; empty until it has been said.
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


def notice_text(lang: str | None, provider: str) -> str:
    """The localized line naming one source: "From Wikipedia…"."""
    return _NOTICE_RESOURCES.dialog("knowledge.notice", lang, {"source": provider_name(provider)})


def run_noticing(work: Callable[[], T], *, lang: str | None = None, mode: str = "",
                 delay: float | None = None) -> T:
    """Deprecated: runs `work` and says nothing.

    0.26.0 guessed which sources a question was put to and listed them, which named
    sources that did not answer. The source is now announced by the service itself;
    a skill with its own request calls `ask_service`. Kept so a skill written for
    0.26.0 still imports and answers.
    """
    return work()


def ask_service(*, service_url: str, request_payload: dict, headers: dict[str, str],
                timeout: float, lang: str | None = None) -> dict:
    """Post one question to the knowledge service and return its response document.

    Raises what `requests` raises, as the plain call does: `HTTPError` for a status
    (404 means no answer), another `RequestException` for a connection, `ValueError`
    for a body that is not JSON.

    With a notice open the call asks to hear the source first. Where the service
    announces one and the answer is still not there NOTICE_DELAY later, the visitor
    is told. Without a notice, or from a service that does not stream, this is the
    plain request it always was.
    """
    url = f"{service_url.rstrip('/')}/v1/knowledge/answer"
    notice = _CURRENT.get()
    if notice is None:
        response = requests.post(url, json=request_payload, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.json()
    response = requests.post(
        url, json=request_payload, headers={**headers, "Accept": f"{NDJSON}, application/json"},
        timeout=timeout, stream=True)
    with response:
        response.raise_for_status()
        if not response.headers.get("Content-Type", "").startswith(NDJSON):
            return response.json()
        return _streamed_answer(response, notice, lang)


class _StreamedStatus:
    """The part of a response `HTTPError` readers look at: the status."""

    def __init__(self, status_code: int):
        self.status_code = status_code


def _event(line: str) -> dict:
    """One line of the stream, checked: a service that sends anything else is a failed request."""
    event = json.loads(line)
    if not isinstance(event, dict) or not isinstance(event.get("event"), str):
        raise ValueError(
            f"the knowledge service sent a stream line that is not an event: {line[:80]!r}")
    kind = event["event"]
    if kind == "source" and not isinstance(event.get("provider"), str):
        raise ValueError("the knowledge service announced a source without naming it")
    if kind == "answer" and not isinstance(event.get("answer"), dict):
        raise ValueError("the knowledge service sent an answer that is not a document")
    if kind == "error" and not (
            isinstance(event.get("status"), int) and isinstance(event.get("detail"), str)):
        raise ValueError("the knowledge service sent an error without a status and a detail")
    return event


def _streamed_answer(response: requests.Response, notice: LookupNotice, lang: str | None) -> dict:
    lines = (_event(line) for line in response.iter_lines(decode_unicode=True) if line)

    def final(events) -> dict:
        for event in events:
            if event["event"] == "answer":
                return event["answer"]
            if event["event"] == "error":
                raise requests.HTTPError(
                    event["detail"], response=_StreamedStatus(event["status"]))
        raise ValueError("the knowledge service ended its stream without an answer")

    first = next(lines, None)
    if first is None:
        raise ValueError("the knowledge service sent an empty stream")
    if first["event"] != "source":
        # An answer or an error with no source announced first: nothing to say. `chain`
        # hands `first` back without reading the next line, which may not exist yet.
        return final(itertools.chain([first], lines))
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="knowledge-stream") as pool:
        future = pool.submit(contextvars.copy_context().run, final, lines)
        try:
            return future.result(timeout=NOTICE_DELAY)
        except FutureTimeout:
            if not notice.named:
                provider = first["provider"]
                key = provider.casefold()
                notice.named = frozenset({_SAME_SOURCE.get(key, key)})
                try:
                    notice.speak(notice_text(lang, provider))
                except Exception:  # noqa: BLE001 - the notice is a courtesy; the answer is the job
                    # A client that cannot take the line must not lose a good answer. It
                    # is logged, and the answer is returned as usual.
                    _LOG.warning("Could not say where the answer comes from", exc_info=True)
            return future.result()
