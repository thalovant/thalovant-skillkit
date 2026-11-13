"""What may be said aloud and which addresses may be dialled (thalovant_skillkit.safety)."""

import ipaddress
import socket

import pytest

from thalovant_skillkit import safety
from thalovant_skillkit.safety import (
    UnsafeAddress,
    address_problem,
    canonical_host,
    contains_url,
    normalize_base_url,
    speakable,
    url_problem,
    vetted_addresses,
)


def test_speakable_removes_markup_addresses_control_and_bidi():
    assert speakable("Hello <b>World</b> https://evil.example/a?x=1 now") == "Hello World now"
    assert speakable("Elf <audio src='https://evil/x.mp3'/> 2") == "Elf 2"
    assert speakable("www.evil.example is bad") == "is bad"
    assert speakable("a\x00b\u202ec\nd") == "a b c d"
    assert speakable("a‮b\u0000c​d\ne") == "a b c d e"
    assert speakable("a <b>c</b> d\n\te") == "a c d e"
    assert (
        "<" not in speakable("<speak>")
        and ">" not in speakable("a>b")
        and "<" not in speakable("a < b")
    )
    assert (
        speakable("AC/DC - Back in Black (Live) [Remastered]")
        == "AC/DC - Back in Black (Live) [Remastered]"
    )
    assert speakable("宇多田ヒカル \U0001f3a7 Café") == "宇多田ヒカル \U0001f3a7 Café"


def test_speakable_is_bounded_and_for_text_only():
    assert len(speakable("x" * 5000)) == 120 and len(speakable("<" * 100000)) <= 120
    assert "<" not in speakable("<" * 1000 + "ok")
    assert speakable("word " * 100, 20) == ("word " * 100)[:20].strip()
    assert (
        speakable(7) == ""
        and speakable(None) == ""
        and speakable(b"x") == ""
        and speakable("x", 0) == ""
    )
    assert speakable("  \n  ") == ""


def test_contains_url():
    assert contains_url("see http://x") and contains_url("x://y") and contains_url("www.x")
    assert not contains_url("AC/DC") and not contains_url(5) and not contains_url(None)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("http://192.168.1.5:8096", "http://192.168.1.5:8096"),
        ("jellyfin.local:8096/", "http://jellyfin.local:8096"),
        ("https://me.example.com/jf/", "https://me.example.com/jf"),
        ("http://user:pass@10.0.0.2:8096/x?api_key=1#f", "http://10.0.0.2:8096/x"),
        ("http://[fd00::5]:8096", "http://[fd00::5]:8096"),
        ("ftp://x", ""),
        ("", ""),
        ("http://", ""),
        ("http://a b", ""),
        ("javascript:alert(1)", ""),
        (None, ""),
        ("http://host:notaport", ""),
        ("h" * 400, ""),
        ("http://x\ny", ""),
    ],
)
def test_normalize_base_url(raw, expected):
    assert normalize_base_url(raw) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "ws://169.254.169.254:80",
        "wss://[fe80::1]/ws",
        "http://0.0.0.0:8095",
        "https://kubernetes.default.svc",
        "ws://thalovant-api.thalovant.svc.cluster.local:8000",
        "http://metadata.google.internal",
        "ws://[::ffff:169.254.169.254]",
        "http://224.0.0.1",
        "https://host.internal",
        "http://music.example.com:8095",
        "ws://music.example.com:8095",
        "http://8.8.8.8:8095",
        "ws://[2606:4700:4700::1111]:8095",
        "http://localhost.localdomain",
        "http://",
        "ws:///ws",
    ],
)
def test_urls_that_leak_the_token_or_reach_inside_are_refused(url):
    assert url_problem(url) != ""


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.5:8096",
        "http://127.0.0.1:8096",
        "http://jellyfin.local:8096",
        "http://nas:8096",
        "https://media.example.com",
        "http://10.1.2.3",
        "http://[fd00::5]:8096",
        "ws://127.0.0.1:8095",
        "ws://truenas.local:8095",
        "wss://music.example.com/ws",
        "http://truenas:8095",
        "http://x.home.arpa",
        "https://8.8.8.8",
        "wss://[2606:4700:4700::1111]/ws",
    ],
)
def test_urls_of_a_home_server_and_any_tls_server_are_allowed(url):
    assert url_problem(url) == ""


def test_the_reason_names_the_scheme():
    assert "ws://" in url_problem("ws://music.example.com") and "http://" in url_problem(
        "http://8.8.8.8"
    )


def test_address_problem():
    assert address_problem(ipaddress.ip_address("169.254.1.1")) and address_problem(
        ipaddress.ip_address("::")
    )
    assert address_problem(ipaddress.ip_address("::ffff:169.254.169.254"))
    assert (
        address_problem(ipaddress.ip_address("192.168.1.1")) == ""
        and address_problem(ipaddress.ip_address("8.8.8.8")) == ""
    )


def _infos(*addresses):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 80)) for a in addresses]


def test_vetted_addresses_resolves_and_refuses_what_is_never_a_server(monkeypatch):
    monkeypatch.setattr(
        safety.socket,
        "getaddrinfo",
        lambda *a, **k: (
            _infos("10.0.0.5", "10.0.0.5", "fe80::1%eth0")[:2]
            + [
                (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::7%eth0", 80, 0, 0)),
                (0, 0, 0, "", ("not an ip", 0)),
            ]
        ),
    )
    assert vetted_addresses("media.example.com", 80) == ["10.0.0.5", "2001:db8::7"]
    monkeypatch.setattr(
        safety.socket, "getaddrinfo", lambda *a, **k: _infos("10.0.0.5", "169.254.169.254")
    )
    with pytest.raises(UnsafeAddress):
        vetted_addresses("rebinding.example.com", 80)
    monkeypatch.setattr(safety.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("nope", 0))])
    with pytest.raises(UnsafeAddress):
        vetted_addresses("empty.example.com", 80)


def test_a_name_that_does_not_resolve_is_the_resolvers_own_error(monkeypatch):
    def boom(*a, **k):
        raise socket.gaierror("no such name")

    monkeypatch.setattr(safety.socket, "getaddrinfo", boom)
    with pytest.raises(socket.gaierror):
        vetted_addresses("nowhere.example.com", 80)


@pytest.mark.parametrize(
    "url",
    [
        "https://kubernetes.default。svc",  # an ideographic full stop, read as a dot
        "https://kubernetes.default．svc",  # a fullwidth full stop
        "https://kubernetes.default｡svc",  # a halfwidth ideographic full stop
        "https://metadata。google。internal",
        "http://134744072",  # inet_aton: a single integer is 8.8.8.8
        "http://0x08080808",
        "http://8.8.8",  # three parts: 8.8.0.8
        "http://0xa9.0xfe.0xa9.0xfe",  # 169.254.169.254
        "http://2852039166",  # 169.254.169.254 as an integer
        "https://" + "a" * 64 + ".example.com",  # a label over 63 characters cannot be encoded
    ],
)
def test_the_host_is_read_as_the_resolver_reads_it(url):
    assert url_problem(url) != ""


def test_the_canonical_host():
    assert canonical_host("Kubernetes.Default。SVC.") == "kubernetes.default.svc"
    assert canonical_host("bücher.example") == "xn--bcher-kva.example"
    assert canonical_host("134744072") == "8.8.8.8" and canonical_host("0x7f.1") == "127.0.0.1"
    assert canonical_host("010.0.0.1") == "8.0.0.1"
    assert canonical_host("[::1]".strip("[]")) == "::1" and canonical_host("") == ""
    assert canonical_host("nas") == "nas" and canonical_host("a" * 64) is None
    assert canonical_host(None) is None and canonical_host("256.1") is None


@pytest.mark.parametrize(
    "host",
    [
        "kubernetes.default.svc\x00.local",
        "a\x00b",
        "nas\x1f",
        "a b.local",
        "nas\x7f",
        "ho\u200bst.local",
        "x\u2028y",
        "\x00",
    ],
)
def test_a_host_with_a_control_or_format_character_is_not_a_host(host):
    """The IDNA codec keeps a NUL and the C resolver stops reading at one: the cluster's name
    would be judged as a `.local` name and resolved as the cluster's."""
    assert canonical_host(host) is None
    assert url_problem("http://" + host) != ""
    with pytest.raises(UnsafeAddress):
        vetted_addresses(host, 80, plain=True)


def test_url_problem_reads_an_unusable_host_and_the_idna_form_of_a_lan_name():
    assert "encoded" in url_problem("http://" + "a" * 64 + ".local")
    assert url_problem("http://bücher.local") == ""  # a LAN name, whatever the script


def test_plain_connections_must_resolve_to_a_private_address(monkeypatch):
    """`url_problem` cannot resolve: "http://nas" passes it. The dial-time check refuses a name that
    answers with a public address, for http and ws; TLS keeps public addresses."""
    assert url_problem("http://nas") == ""
    monkeypatch.setattr(safety.socket, "getaddrinfo", lambda *a, **k: _infos("8.8.8.8"))
    with pytest.raises(UnsafeAddress, match="plain"):
        vetted_addresses("nas", 80, plain=True)
    assert vetted_addresses("nas", 443) == ["8.8.8.8"]  # TLS: public is fine
    monkeypatch.setattr(
        safety.socket, "getaddrinfo", lambda *a, **k: _infos("192.168.1.5", "8.8.8.8")
    )
    with pytest.raises(UnsafeAddress, match="plain"):  # any public answer refuses the whole name
        vetted_addresses("nas", 80, plain=True)
    monkeypatch.setattr(
        safety.socket, "getaddrinfo", lambda *a, **k: _infos("192.168.1.5", "127.0.0.1", "10.0.0.2")
    )
    assert vetted_addresses("nas", 80, plain=True) == ["192.168.1.5", "127.0.0.1", "10.0.0.2"]
    monkeypatch.setattr(
        safety.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:8.8.8.8", 80, 0, 0))
        ],
    )
    with pytest.raises(UnsafeAddress, match="plain"):  # an IPv4-mapped public address is public
        vetted_addresses("nas", 80, plain=True)


def test_vetted_addresses_resolves_the_canonical_form_and_refuses_an_unencodable_name(monkeypatch):
    seen = []
    monkeypatch.setattr(
        safety.socket, "getaddrinfo", lambda host, *a, **k: seen.append(host) or _infos("10.0.0.5")
    )
    assert vetted_addresses("Bücher.Local.", 80, plain=True) == ["10.0.0.5"]
    assert vetted_addresses("134744072", 443) == ["10.0.0.5"] and seen == [
        "xn--bcher-kva.local",
        "8.8.8.8",
    ]
    for bad in ("a" * 64, "", None):
        with pytest.raises(UnsafeAddress):
            vetted_addresses(bad, 80)


def test_url_problem_says_no_to_an_unreadable_url_instead_of_raising():
    """A URL `normalize_base_url` did not make is refused too, not an exception."""
    from thalovant_skillkit.safety import url_problem

    for url in ("http://[::1", "http://[", "http://[fe80::1", None, 7, b"http://x"):
        assert url_problem(url) != "", url  # type: ignore[arg-type]
