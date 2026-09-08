"""Talking to the Thalovant services.

Five skills wrote `_request_headers` and each service call repeated the same
timeout-and-retry shape around `requests`. The headers matter operationally:
`X-Request-ID` is what makes one spoken answer findable in the service logs,
and it was missing from whichever skill last copied the function without it.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import requests

LOG = logging.getLogger(__name__)


def request_headers(skill_name: str, skill_version: str, user_agent: str) -> dict[str, str]:
    """Identify the skill and give this call an id the service logs can be
    searched by."""
    return {
        "User-Agent": user_agent,
        "X-Request-ID": f"{skill_name}-{uuid.uuid4().hex}",
        "X-Thalovant-Skill": skill_name,
        "X-Thalovant-Skill-Version": skill_version,
    }


def post_json(
    url: str,
    payload: dict,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 2.4,
    attempts: int = 2,
    client: Any = requests,
) -> dict | None:
    """POST and return the decoded body, or None if the service did not answer.

    None rather than an exception, because every caller is inside a spoken
    reply: a skill that raises here says nothing at all, and a skill that says
    "I could not reach the service" is the honest outcome. The caller decides
    what to say; this only decides that there is nothing to say it about.
    """
    for attempt in range(max(1, attempts)):
        try:
            response = client.post(url, json=payload, timeout=timeout,
                                   headers=headers or {})
        except Exception as failure:  # noqa: BLE001 - the caller speaks, not raises
            # The connection failed; another attempt may not. Logged rather
            # than dropped: returning None tells the caller nothing about why,
            # and "the skill went quiet" is the hardest thing to debug from a
            # transcript.
            LOG.debug("POST %s failed (attempt %d): %s", url, attempt + 1, failure)
            continue
        status = getattr(response, "status_code", None)
        # A 4xx is the service saying the request itself is wrong, and asking
        # again with the same body gets the same answer -- while the person is
        # waiting for a spoken reply. Only retry what a retry can fix.
        if isinstance(status, int) and 400 <= status < 500:
            return None
        try:
            response.raise_for_status()
            return response.json()
        except Exception as failure:  # noqa: BLE001
            LOG.debug("POST %s returned an unusable response (attempt %d): %s",
                      url, attempt + 1, failure)
            if attempt == max(1, attempts) - 1:
                return None
    return None
