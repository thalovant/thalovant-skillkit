"""What a skill may say aloud and which addresses it may dial, when text and URL are not its own.

Names, titles and whole sentences come from servers the household controls but also from providers
it does not, and they end up in speakers that render SSML: a tag or a link in one must never reach
them. `speakable` is the ONE skill-side cleaner (the hub's router has its own twin with the same
steps): every skill passes text that came from outside through it before it is spoken, and a
cleaned text holds no angle bracket, so the kit can never read it as markup. A server URL is typed
by whoever configures the skill and the token travels with every request: a URL that would leak it,
reach this machine or reach inside the cluster is refused before a socket opens, and the address
that is finally dialled is checked again (`vetted_addresses`, `dial_vetted`). Pure functions: no
OVOS, no network except `vetted_addresses` and `dial_vetted`.

    from thalovant_skillkit.safety import speakable, url_problem

    line = speakable(track["name"])                  # words only, one line, at most 120 characters
    said = speakable(answer["speech"], 600)          # a whole sentence somebody else wrote
    why = url_problem(normalize_base_url(typed))     # "" when it may be dialled

A skill whose kit floor is older than this module imports it behind a guard (`docs/reference.md`,
"Older kits"); the guard's fallback strips tags and addresses itself.
"""

from __future__ import annotations

import html
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
    "canonical_host",
    "contains_url",
    "dial_vetted",
    "normalize_base_url",
    "speakable",
    "strip_markup",
    "url_problem",
    "vetted_addresses",
]

#: The longest name (title, show, room) said in one line.
MAX_SPOKEN_NAME = 120
#: Nothing beyond this many characters of a value is even looked at.
READ_AT_MOST = 8192
#: Tags are removed until nothing changes, and never more often than this.
MAX_TAG_PASSES = 8

# `<` followed by a letter, `/`, `!` or `?` and closed by `>`: a tag, a comment, a declaration.
# "5 < 6 and 7 > 3" holds none (its brackets are dropped afterwards, its words are kept).
_TAG = re.compile(r"<[A-Za-z/!?][^<>]*>")
_URL = re.compile(r"(?:[a-z][a-z0-9+.-]*://|www\.)\S*", re.IGNORECASE)
#: Characters that are not an angle bracket but become one when a text is decomposed (NFKD) and
#: its combining marks dropped, as every fold in the fleet does: "≮audio≯" folds to "<audio>".
#: `test_safety` walks every code point to prove the set is complete.
BRACKET_LIKE = frozenset("\u226e\u226f")
_NOT_SPOKEN = ("Cc", "Cf", "Cs", "Co")


def contains_url(value: Any) -> bool:
    """Whether `value` carries something address-like (a scheme, `://`, `www.`)."""
    return isinstance(value, str) and bool(_URL.search(value))


def strip_markup(text: str) -> str:
    """`text` with every tag removed and no angle bracket left.

    Tags go until nothing changes (a tag built from the pieces around another one, `<au<b>dio>`,
    goes on the next pass; at most `MAX_TAG_PASSES` passes), then every `<` and `>` that is left
    becomes a space, and so does a character that would fold into one. Entities are NOT read
    here: `speakable` and `ssml.strip_tags` read them first, so that `&lt;audio&gt;` is a tag
    before it is removed.
    """
    for _ in range(MAX_TAG_PASSES):
        stripped = _TAG.sub(" ", text)
        if stripped == text:
            break
        text = stripped
    return "".join(" " if c in "<>" or c in BRACKET_LIKE else c for c in text)


#: What closes a text that was cut. NFKC would turn it into three full stops, and a text that was
#: cut once (by the hub's cleaner, or by this one a moment ago) would come back two characters
#: longer the second time it is cleaned: the ellipsis is kept as it is.
ELLIPSIS = "\u2026"


def _fold(text: str) -> str:
    """`text` folded with NFKC, the ellipsis left alone."""
    return ELLIPSIS.join(unicodedata.normalize("NFKC", part) for part in text.split(ELLIPSIS))


def _cut(text: str, limit: int) -> str:
    """`text` in at most `limit` characters: cut at a word and closed with an ellipsis."""
    if len(text) <= limit:
        return text
    if limit < 2:
        return text[:limit]
    cut = text[: limit - 1]  # the ellipsis is one of the `limit` characters
    space = cut.rfind(" ")
    if space >= (limit - 1) * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:.-" + ELLIPSIS) + ELLIPSIS


def speakable(value: Any, limit: int = MAX_SPOKEN_NAME) -> str:
    """`value` as words a voice can say, never markup and never an address. "" for anything that
    is not text.

    The one skill-side cleaner. In this order:

    1. at most `READ_AT_MOST` characters are read (bounded work on a hostile value) and folded
       with NFKC, so a fullwidth `＜` is the bracket it reads as;
    2. HTML entities are read once, so an entity-encoded tag (`&lt;audio ...&gt;`, or only its
       closing `&gt;`) is a tag before it is removed, and the result is folded again (an entity
       can spell a fullwidth bracket);
    3. tags are removed until nothing changes, then every remaining `<` and `>` is dropped
       (`strip_markup`): what comes back never holds an angle bracket, so the kit can never read
       it as SSML;
    4. every `://` becomes a space: no address is said or followed;
    5. control, format, surrogate and private-use characters (bidi overrides included) become
       spaces;
    6. whitespace is collapsed to one line, and a text longer than `limit` is cut at a word and
       closed with an ellipsis. The result is never longer than `limit`.

    Cleaning what was already cleaned changes nothing more (an ellipsis is not folded into three
    full stops), so a skill may clean a value and the kit clean the sentence it went into.
    """
    if not isinstance(value, str):
        return ""
    limit = max(0, limit)
    text = _fold(value[:READ_AT_MOST])
    if "&" in text:
        text = _fold(html.unescape(text))
    text = strip_markup(text).replace("://", " ")
    text = "".join(" " if unicodedata.category(c) in _NOT_SPOKEN else c for c in text)
    return _cut(" ".join(text.split()), limit)


# -- URLs
# ---------------------------------------------------------------------------------------------

#: Names that only ever mean the cluster or the machine the skill runs on.
_INTERNAL_SUFFIXES = (".svc", ".cluster.local", ".internal", ".localdomain")
#: Names a LAN gives its own machines: a plain http:// or ws:// to one of these never crosses the
#: internet.
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


#: Unicode full stops the IDNA codec reads as label separators ("kubernetes.default。svc").
_UNICODE_DOTS = str.maketrans({"\u3002": ".", "\uff0e": ".", "\uff61": "."})
#: Numbers-and-dots hosts that `getaddrinfo` accepts on Linux (`inet_aton`: `134744072`, `0x7f.1`).
_NUMERIC_HOST = re.compile(r"^(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+)){0,3}$")


def canonical_host(host: str) -> str | None:
    """The host as the resolver will read it: lower case, ASCII (IDNA), no trailing dot, and a
    numbers-and-dots form (`134744072`) as the dotted quad it means. "" for no host, None for a name
    that cannot be encoded (a label over 63 characters, an invalid code point)."""
    if not isinstance(host, str):
        return None
    host = host.translate(_UNICODE_DOTS).lower().rstrip(".")
    # The IDNA codec keeps ASCII NUL and other control characters, and the C resolver stops reading
    # at a NUL: "kubernetes.default.svc\x00.local" would pass for a ".local" name and resolve as the
    # cluster's. A host holds no control, format or space character at all.
    if any(unicodedata.category(char)[0] in "CZ" for char in host):
        return None
    if not host or ":" in host:  # empty, or an IPv6 literal (judged as an address)
        return host
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    if _NUMERIC_HOST.match(host):
        try:
            return socket.inet_ntoa(socket.inet_aton(host))
        except OSError:
            return None
    return host


def _lan_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(address, "ipv4_mapped", None) or address
    return bool(mapped.is_private or mapped.is_loopback)


#: Cloud metadata services that do not sit in a link-local range (the link-local ones,
#: 169.254.169.254 and 169.254.170.2, are refused with their range).
_METADATA = frozenset(
    ipaddress.ip_address(text) for text in ("100.100.100.200", "fd00:ec2::254", "192.0.0.192")
)


def address_problem(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address, *, loopback: bool = False
) -> str:
    """Why `address` is never a household server's, or "" when it may be dialled.

    Refused: link-local (169.254.0.0/16 and fe80::/10, where cloud metadata lives) and the
    metadata addresses outside that range, the unspecified address, multicast, and loopback (on a
    hub, 127.0.0.1 is the hub's own message bus, not somebody's media server). An IPv4-mapped
    IPv6 address is judged as its IPv4.

    `loopback=True` admits loopback: for a test server, or a program that is meant to dial the
    machine it runs on. A skill on a hub never passes it.
    """
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    if (
        address.is_link_local
        or address.is_unspecified
        or address.is_multicast
        or address in _METADATA
    ):
        return "an address that is not a server's"
    if address.is_loopback and not loopback:
        return "this machine's own address"
    return ""


def _local_name(host: str) -> bool:
    """`localhost` and the names under it (RFC 6761): this machine, by name."""
    return host == "localhost" or host.endswith(".localhost")


def _name_problem(host: str, *, loopback: bool = False) -> str:
    """Why the NAME `host` (canonical, not an address) is never dialled, or ""."""
    if _local_name(host):
        return "" if loopback else "this machine's own name"
    if host.endswith(_INTERNAL_SUFFIXES) or host in _INTERNAL_NAMES:
        return "a cluster or host name"
    if "." not in host:
        # `nas`, `secrets`, `ovos-messagebus`: a single label is whatever the resolver's search
        # list makes of it, and inside a cluster that is a Service of the hub's own namespace.
        return "a name without a domain"
    return ""


def url_problem(url: str, *, loopback: bool = False) -> str:
    """Why `url` (as `normalize_base_url` or the skill's own normaliser made it) must not be
    dialled, or "" when it may.

    * an address that is never a household server's (`address_problem`: link-local, metadata,
      unspecified, multicast, loopback), `localhost`, and the names a cluster or a host gives only
      to itself (`kubernetes.default.svc`, `*.svc`, `*.cluster.local`, `*.internal`,
      `metadata.google.internal`);
    * a name of a single label (`nas`, `secrets`): the resolver completes it from its search list,
      and inside a cluster that names a Service beside the hub. Type the full name
      (`nas.lan`, `nas.local`) or the address;
    * a plain `http://` or `ws://` to anything that is not a literal private address or a LAN
      name (`.local`, `.lan`, `.home.arpa`, `.home`): the token would cross the internet in clear.

    The host is read as the resolver will read it (`canonical_host`): Unicode full stops and IDNA
    labels are folded to ASCII, and a numbers-and-dots host (`134744072`, `2852039166`) is the
    address it means.

    A name is not resolved here (a name can change its answer). The client dials through
    `dial_vetted(host, port, plain=...)` (or connects to what `vetted_addresses` returns) at the
    moment of the call: that is where a name which resolves to loopback, link-local or metadata
    is refused, where a LAN name which resolves publicly is refused for a plain scheme, and where
    a short cluster name (`secrets.infra`) stops resolving at all. A redirect is a new URL: check it
    with this function and dial it the same way, or do not follow it.

    `loopback=True` admits loopback addresses and `localhost` (a test server); a skill on a hub
    never passes it.
    """
    try:
        parts = urlsplit(url)
        hostname = parts.hostname or ""
    except (ValueError, TypeError, AttributeError):  # `http://[::1`: a gate says no
        return "an address that cannot be read"
    host = canonical_host(hostname)
    if host is None:
        return "a host name that cannot be encoded"
    if not host:
        return "no host"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        problem = address_problem(address, loopback=loopback)
        if problem:
            return problem
        if parts.scheme in _PLAIN_SCHEMES and not _lan_address(address):
            return f"a plain {parts.scheme}:// to a public address"
        return ""
    problem = _name_problem(host, loopback=loopback)
    if problem:
        return problem
    if (
        parts.scheme in _PLAIN_SCHEMES
        and not host.endswith(_LAN_SUFFIXES)
        and not _local_name(host)
    ):
        return f"a plain {parts.scheme}:// to a public name"
    return ""


class UnsafeAddress(ValueError):
    """A name that is never dialled, or one that resolved to an address a household server never
    has (see `address_problem`)."""


def vetted_addresses(
    host: str, port: int, *, plain: bool = False, loopback: bool = False
) -> list[str]:
    """The addresses `host` points to now, each checked with `address_problem`.

    Raises `UnsafeAddress` for a name that is never dialled (a single label, a cluster name,
    `localhost`), when any answer is loopback, link-local, metadata, unspecified or multicast (a
    name that answers differently the second time cannot move the client to cloud metadata or to
    the hub's own bus), and when nothing usable came back; `socket.gaierror` when the name does
    not resolve. Connect to the returned address, not to the name again (`dial_vetted` does).

    A name is resolved as a full name (with the root's trailing dot), so the resolver's search
    list is never applied: inside a cluster `secrets.infra` no longer means the Service `secrets` of
    the namespace `infra`, it means nothing.

    Pass `plain=True` for an `http://` or `ws://` connection: the token would cross the network in
    clear, so an answer that is not a private address is refused too (a LAN name that resolves to
    a public address). TLS schemes keep public addresses. `loopback=True` admits loopback (a test
    server); a skill on a hub never passes it.
    """
    canonical = canonical_host(host)
    if not canonical:
        raise UnsafeAddress(
            "a host name that cannot be encoded" if canonical is None else "no host"
        )
    try:
        ipaddress.ip_address(canonical)
        lookup = canonical
    except ValueError:
        problem = _name_problem(canonical, loopback=loopback)
        if problem:
            raise UnsafeAddress(problem) from None
        # `localhost` is answered from the hosts file, which knows it without the dot.
        lookup = canonical if _local_name(canonical) else canonical + "."
    infos = socket.getaddrinfo(lookup, port, type=socket.SOCK_STREAM)
    out: list[str] = []
    for info in infos:
        text = str(info[4][0]).split("%")[0]
        try:
            address = ipaddress.ip_address(text)
        except ValueError:
            continue
        if address_problem(address, loopback=loopback):
            raise UnsafeAddress("address refused")
        if plain and not _lan_address(address):
            raise UnsafeAddress("a plain connection to a public address")
        if text not in out:
            out.append(text)
    if not out:
        raise UnsafeAddress("no address")
    return out


def dial_vetted(
    host: str,
    port: int,
    *,
    plain: bool = False,
    loopback: bool = False,
    timeout: float = 4.0,
) -> socket.socket:
    """A TCP socket connected to an address `vetted_addresses` allowed, never to the name again.

    The name is resolved once, every answer is checked, and the socket is opened to one of those
    answers: a name that answers differently a moment later cannot move the connection. The
    caller wraps TLS around the socket (with `server_hostname=host`) and speaks its protocol on
    it. Raises `UnsafeAddress` (refused), `socket.gaierror` (does not resolve) or the last
    `OSError` of the addresses tried (`TimeoutError` when the time ran out).
    """
    last: OSError | None = None
    for address in vetted_addresses(host, port, plain=plain, loopback=loopback):
        try:
            return socket.create_connection((address, port), timeout=timeout)
        except OSError as exc:
            last = exc
    raise last if last is not None else UnsafeAddress("no address")
