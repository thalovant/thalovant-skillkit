"""Talking to the Thalovant services.

Five skills wrote `_request_headers` and each service call repeated the same
timeout-and-retry shape around `requests`. The headers matter operationally:
`X-Request-ID` is what makes one spoken answer findable in the service logs,
and it was missing from whichever skill last copied the function without it.
"""
from __future__ import annotations

import uuid
from typing import Any

import requests


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
    last: Exception | None = None
    for _attempt in range(max(1, attempts)):
        try:
            response = client.post(url, json=payload, timeout=timeout,
                                   headers=headers or {})
            response.raise_for_status()
            return response.json()
        except Exception as failure:  # noqa: BLE001 - the caller speaks, not raises
            last = failure
    if last is not None:
        return None
    return None
