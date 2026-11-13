"""What may be said aloud and which addresses may be dialled (thalovant_skillkit.safety)."""

import ipaddress
import socket

import pytest

from thalovant_skillkit import safety
from thalovant_skillkit.safety import (
    UnsafeAddress,
    address_problem,
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
