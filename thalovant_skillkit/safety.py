"""What a skill may say aloud and which addresses it may dial, when text and URL are not its own.

Names and titles come from a server the household controls but also from providers it does not, and
they end up in speakers that render SSML: a tag or a link in one must never reach them. A server URL
is typed by whoever configures the skill and the token travels with every request: a URL that would
leak it, or reach inside the cluster, is refused before a socket opens. Both rules were written
separately in the media skills and the Music Assistant skill and had begun to drift; this is the
reconciled, most careful copy. Pure functions: no OVOS, no network except `vetted_addresses`.

    from thalovant_skillkit.safety import speakable, url_problem

    line = speakable(track["name"])                  # words only, one line, at most 120 characters
    why = url_problem(normalize_base_url(typed))     # "" when it may be dialled

A skill whose kit floor is older than this module imports it behind a guard (`docs/reference.md`,
"Older kits"); the guard's fallback strips tags and addresses itself.
"""
from __future__ import annotations

import ipaddress
import re
import socket
import unicodedata
from typing import Any
from urllib.parse import urlsplit, urlunsplit

__all__ = [
    "MAX_SPOKEN_NAME",
    "UnsafeAddress",
    "address_problem",
    "contains_url",
    "normalize_base_url",
    "speakable",
    "url_problem",
    "vetted_addresses",
]

#: The longest name (title, show, room) said in one line.
MAX_SPOKEN_NAME = 120

_TAG = re.compile(r"<[^>]*>")
_URL = re.compile(r"(?:[a-z][a-z0-9+.-]*://|www\.)\S*", re.IGNORECASE)


def contains_url(value: Any) -> bool:
    """Whether `value` carries something address-like (a scheme, `://`, `www.`)."""
    return isinstance(value, str) and bool(_URL.search(value))


def speakable(value: Any, limit: int = MAX_SPOKEN_NAME) -> str:
    """`value` as words a voice can say: markup and addresses removed, angle brackets gone,
    control, format, surrogate, private-use and unassigned characters (bidi overrides included)
    turned into spaces, one line, at most `limit` characters. "" for anything that is not text.

    The text is cut before it is looked at (four times `limit`), so the work on a hostile title is
    bounded.
    """
    if not isinstance(value, str):
        return ""
    value = value[: max(0, limit) * 4]
    value = _URL.sub(" ", _TAG.sub(" ", value))
    value = "".join(" " if unicodedata.category(c)[0] == "C" or c in "<>" else c for c in value)
    return " ".join(value.split())[: max(0, limit)].strip()


# -- URLs
# ---------------------------------------------------------------------------------------------

#: Names that only ever mean the cluster or the machine the skill runs on.
_INTERNAL_SUFFIXES = (".svc", ".cluster.local", ".internal", ".localdomain")
# : Names a LAN gives its own machines: a plain http:// or ws:// to one of these never crosses the
# internet.
_LAN_SUFFIXES = (".local", ".lan", ".home.arpa", ".home")
_INTERNAL_NAMES = ("localhost.localdomain", "metadata.google.internal")
_PLAIN_SCHEMES = ("http", "ws")


def normalize_base_url(raw: str) -> str:
    """The base URL (`scheme://host:port/prefix`) for what the owner typed, or "" if unusable.

    Accepts `http(s)://host:port[/prefix]` and a bare `host:port` (taken as http). Credentials,
    query and fragment are dropped: the token is its own setting. Whitespace, control characters or
    more than 300 characters make it unusable.
    """
    text = (raw or "").strip() if isinstance(raw, str) else ""
    if not text or len(text) > 300 or any(c in text for c in "\r\n\t "):
        return ""
    if "://" not in text:
        text = "http://" + text
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return ""
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        return ""
    host = parts.hostname
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port else host
    return urlunsplit((scheme, netloc, parts.path.rstrip("/"), "", ""))


def address_problem(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str:
    """Why `address` is never a server's, or "" when it may be dialled.

    Link-local (169.254.0.0/16 and fe80::/10, where cloud metadata lives), the unspecified address
    and multicast are refused. An IPv4-mapped IPv6 address is judged as its IPv4.
    """
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    if address.is_link_local or address.is_unspecified or address.is_multicast:
        return "an address that is not a server's"
    return ""


def url_problem(url: str) -> str:
    """Why `url` (as `normalize_base_url` or the skill's own normaliser made it) must not be
    dialled, or "" when it may.

    * an address that is never a server's (`address_problem`), and the names a cluster or a host
      gives only to itself (`kubernetes.default.svc`, `*.cluster.local`, `*.internal`,
      `metadata.google.internal`);
    * a plain `http://` or `ws://` to anything that is not a literal private address, loopback, or a
      LAN name (`.local`, `.lan`, `.home.arpa`, `.home`, a single label): the token would cross the
      internet in clear.

    A name is not resolved here (a name can change its answer): a client that dials it calls
    `vetted_addresses` at the moment of the call and connects to what that returns.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return "no host"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        problem = address_problem(address)
        if problem:
            return problem
        mapped = getattr(address, "ipv4_mapped", None) or address
        if parts.scheme in _PLAIN_SCHEMES and not (mapped.is_private or mapped.is_loopback):
            return f"a plain {parts.scheme}:// to a public address"
        return ""
    if host.endswith(_INTERNAL_SUFFIXES) or host in _INTERNAL_NAMES:
        return "a cluster or host name"
    if parts.scheme in _PLAIN_SCHEMES and "." in host and not host.endswith(_LAN_SUFFIXES):
        return f"a plain {parts.scheme}:// to a public name"
    return ""


class UnsafeAddress(ValueError):
    """A name resolved to an address a server never has (see `address_problem`)."""


def vetted_addresses(host: str, port: int) -> list[str]:
    """The addresses `host` points to now, each checked with `address_problem`.

    Raises `UnsafeAddress` when any answer is link-local, unspecified or multicast (a name that
    answers differently the second time cannot move the client to cloud metadata), `socket.gaierror`
    when the name does not resolve, and `UnsafeAddress` when nothing usable came back. Connect to
    the returned address, not to the name again.
    """
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    out: list[str] = []
    for info in infos:
        text = str(info[4][0]).split("%")[0]
        try:
            address = ipaddress.ip_address(text)
        except ValueError:
            continue
        if address_problem(address):
            raise UnsafeAddress("address refused")
        if text not in out:
            out.append(text)
    if not out:
        raise UnsafeAddress("no address")
    return out
