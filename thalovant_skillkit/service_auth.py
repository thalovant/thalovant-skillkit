"""The runtime group's service token, sent to the platform's own services only.

The platform's shared services (the LLM, the embedder, and the knowledge,
weather, joke, news and popculture services) identify the runtime that calls
them by one header, ``Authorization: Bearer <token>``. The token belongs to the
runtime group and is short-lived; the runtime finds it in the file named by
``THALOVANT_SERVICE_TOKEN_FILE``, which is replaced in place when the token is
renewed.

Three rules make it safe to attach from shared helpers:

- **Only to an allow-listed in-cluster host.** A skill's ``service_url`` is a
  setting its owner can edit, and some skills send their request headers to
  feeds the owner configured. The token goes to the seven Services in namespace
  ``thalovant`` by name (``<service>.thalovant``, ``.thalovant.svc`` or
  ``.thalovant.svc.cluster.local``), over http or https, and nowhere else: not
  to a bare ``<service>`` (from a runtime pod that name is never the platform's
  Service, and it falls through the pod's DNS search list), not to an address,
  not to a URL carrying userinfo. Headers the kit built for an allow-listed URL
  lose the token again when they are sent anywhere else.
- **No token, no header, no error.** While the file is missing or holds no
  token, requests go out exactly as before.
- **Read when it changes, and once more after a 401.** The file is read again
  when its inode, size or modification time change, which is how a mounted
  secret is replaced; a 401 forces one re-read, and the request is repeated once
  only if that gave a different token. A 401 means the request was refused
  before it was handled, so the repeat cannot run an action twice.

The token is never logged.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from collections import deque
from collections.abc import Mapping
from urllib.parse import urlsplit

LOG = logging.getLogger(__name__)

TOKEN_FILE_ENV = "THALOVANT_SERVICE_TOKEN_FILE"
SERVICE_NAMESPACE = "thalovant"
#: The Services that verify the token, all in namespace ``thalovant``.
SERVICES = (
    "thalovant-llm",
    "thalovant-embedder",
    "thalovant-knowledge-service",
    "thalovant-weather-service",
    "thalovant-joke-service",
    "thalovant-news-service",
    "thalovant-popculture-service",
)
#: Every host name the token may be sent to.
SERVICE_HOSTS = frozenset(
    f"{service}.{SERVICE_NAMESPACE}{suffix}"
    for service in SERVICES
    for suffix in ("", ".svc", ".svc.cluster.local")
)
_SCHEMES = frozenset({"http", "https"})
# A compact JWS: three base64url segments. Anything else in the file is not
# sent, so a stray newline or a wrong file cannot become a header.
_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_MAX_TOKEN_BYTES = 16 * 1024
_UNSAFE_URL_CHARS = re.compile(r"[\x00-\x20\x7f\\]")


def is_service_url(url: object) -> bool:
    """Whether the service token may be sent to this URL."""
    if not isinstance(url, str) or not url or _UNSAFE_URL_CHARS.search(url):
        return False
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError for a port that is not one
    except ValueError:
        return False
    if parts.scheme.lower() not in _SCHEMES or "@" in parts.netloc or not host:
        return False
    if host.endswith("."):
        host = host[:-1]
    return host in SERVICE_HOSTS


class ServiceToken:
    """The token file named by ``THALOVANT_SERVICE_TOKEN_FILE``, cached by its stat."""

    def __init__(self, env: str = TOKEN_FILE_ENV):
        self.env = env
        self._lock = threading.Lock()
        self._key: tuple | None = None
        self._token: str | None = None
        self._warned: tuple | None = None
        # Every token this process put in a header, so a header built for a
        # service and then sent elsewhere can be recognised and dropped.
        self._sent: deque[str] = deque(maxlen=8)

    def path(self) -> str | None:
        return os.environ.get(self.env, "").strip() or None

    def get(self) -> str | None:
        """The current token, or None when there is none to send."""
        path = self.path()
        if path is None:
            return None
        try:
            stat = os.stat(path)
        except OSError:
            with self._lock:
                self._key, self._token = None, None
            return None
        key = (path, stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        with self._lock:
            if key == self._key:
                return self._token
        token = self._read(path, key)
        with self._lock:
            self._key, self._token = key, token
        return token

    def reload(self) -> str | None:
        """Forget the cached token and read the file again."""
        with self._lock:
            self._key = None
        return self.get()

    def after_unauthorized(self, sent: str | None) -> str | None:
        """A token worth one more attempt after a 401, or None.

        Only a token that differs from the one the refused request carried:
        the same token would be refused again.
        """
        token = self.reload()
        return token if token is not None and token != sent else None

    def remember(self, token: str) -> None:
        with self._lock:
            if token not in self._sent:
                self._sent.append(token)

    def is_ours(self, value: object) -> bool:
        token = _bearer(value)
        if token is None:
            return False
        with self._lock:
            return token in self._sent or token == self._token

    def _read(self, path: str, key: tuple) -> str | None:
        try:
            with open(path, "rb") as handle:
                raw = handle.read(_MAX_TOKEN_BYTES + 1)
        except OSError:
            return None
        token = raw.decode("ascii", "replace").strip()
        if not token:
            return None
        if len(raw) > _MAX_TOKEN_BYTES or not _TOKEN_SHAPE.fullmatch(token):
            if self._warned != key:
                self._warned = key
                # The content is never logged: it may be a token after all.
                LOG.warning("%s does not hold a service token (%d bytes); none is sent",
                            path, len(raw))
            return None
        return token


_TOKEN = ServiceToken()


def service_token() -> str | None:
    """The runtime group's service token, or None (no file, empty, or not a token)."""
    return _TOKEN.get()


def with_service_token(url: str, headers: Mapping[str, str] | None = None) -> dict[str, str]:
    """A copy of ``headers`` fit to send to ``url``.

    For an allow-listed service URL the current token is set as
    ``Authorization: Bearer``, replacing one this kit set earlier; a caller's
    own ``Authorization`` is left as it is. For any other URL an
    ``Authorization`` this kit set is removed, and nothing else changes.
    """
    result = dict(headers or {})
    names = [name for name in result if name.lower() == "authorization"]
    ours = [name for name in names if _TOKEN.is_ours(result[name])]
    if not is_service_url(url):
        for name in ours:
            del result[name]
        return result
    if len(ours) < len(names):
        return result  # the caller authenticates this request itself
    token = _TOKEN.get()
    for name in ours:
        del result[name]
    if token is not None:
        _TOKEN.remember(token)
        result["Authorization"] = f"Bearer {token}"
    return result


def sent_token(headers: Mapping[str, str] | None) -> str | None:
    """The service token these headers carry, if this kit put it there."""
    for name, value in (headers or {}).items():
        if name.lower() == "authorization" and _TOKEN.is_ours(value):
            return _bearer(value)
    return None


def retry_headers(url: str, headers: Mapping[str, str] | None,
                  status: object) -> dict[str, str] | None:
    """Headers for one more attempt after a 401 from a service, or None.

    A 401 makes the kit read the token file again. Only a different token is
    worth a second request; None means: report the 401 as it is.
    """
    if status != 401 or not is_service_url(url):
        return None
    current = dict(headers or {})
    if any(name.lower() == "authorization" for name in current) and sent_token(current) is None:
        return None  # the caller's own credential was refused, not the token
    fresh = _TOKEN.after_unauthorized(sent_token(current))
    if fresh is None:
        return None
    LOG.info("A service refused the token; retrying once with the re-read token")
    return with_service_token(url, current)


def _bearer(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    scheme, _, token = value.strip().partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None
