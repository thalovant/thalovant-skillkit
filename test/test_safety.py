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
    dial_vetted,
    normalize_base_url,
    speakable,
    strip_markup,
    url_problem,
    vetted_addresses,
)


def test_speakable_removes_markup_addresses_control_and_bidi():
    assert speakable("Hello <b>World</b> https://evil.example/a?x=1 now") == (
        "Hello World https evil.example/a?x=1 now"
    )
    assert speakable("Elf <audio src='https://evil/x.mp3'/> 2") == "Elf 2"
    assert speakable("a\x00b\u202ec\nd") == "a b c d"
    assert speakable("a‮b\u0000c​d\ne") == "a b c d e"
    assert speakable("a <b>c</b> d\n\te") == "a c d e"
    assert (
        "<" not in speakable("<speak>")
        and ">" not in speakable("a>b")
        and "<" not in speakable("a < b")
    )
    assert speakable("5 < 6 and 7 > 3") == "5 6 and 7 3"  # the words stay, the brackets go
    assert (
        speakable("AC/DC - Back in Black (Live) [Remastered]")
        == "AC/DC - Back in Black (Live) [Remastered]"
    )
    assert speakable("宇多田ヒカル \U0001f3a7 Café") == "宇多田ヒカル \U0001f3a7 Café"
    assert speakable("Tom &amp; Jerry") == "Tom & Jerry"


#: What a title, a player name or a relayed sentence may hold, and what it must never become.
HOSTILE = [
    '<audio src="https://evil.example/x.mp3"/>',
    '&lt;audio src="https://evil.example/x.mp3"/&gt;',  # the whole tag as entities
    'Playing <audio src="https://evil.example/x.mp3"/&gt; on Kitchen',  # only the closing bracket
    'Now playing <prosody volume="+40dB"&gt;LOUD&lt;/prosody&gt; on Kitchen',
    'Done <break time="10s"/&gt; ok',
    "&#60;break time='9s'/&#62;",  # numeric entities
    "&#x3c;break time='9s'/&#x3e;",
    "&#xFF1C;break time='9s'/&#xFF1E;",  # an entity that spells a fullwidth bracket
    '\uff1cbreak time="9s"/\uff1e hello',  # fullwidth brackets, folded by NFKC
    "\ufe64break/\ufe65",  # small form variants
    "\u226eaudio\u226f",  # NOT LESS-THAN: `<` plus a combining mark once decomposed
    "<au<b>dio src='x'>",  # a tag built from the pieces around another
    "<<<<b>>>>audio src='x'<<<</b>>>>",
    "<" * 40 + "break" + ">" * 40,
    "<!-- x --><?xml version='1.0'?><![CDATA[<speak>]]>",
    "go to http://evil.example/login now",
    "\uff48\uff54\uff54\uff50\uff1a\uff0f\uff0fevil.example",  # a fullwidth http://
    "x\u202e<speak>\u2066",
]


@pytest.mark.parametrize("value", HOSTILE)
def test_what_speakable_returns_can_never_be_markup_or_an_address(value):
    """The contract's promise, whatever the encoding: no angle bracket (in any form a fold makes
    one), no `://`, and so nothing the kit could promote to `utterance_ssml`."""
    import unicodedata

    from thalovant_skillkit.ssml import looks_like_ssml, speech_parts

    said = speakable(value, 600)
    for form in ("NFKC", "NFKD"):
        folded = "".join(
            c for c in unicodedata.normalize(form, said) if not unicodedata.combining(c)
        )
        assert "<" not in folded and ">" not in folded and "://" not in folded, (form, said)
    assert not looks_like_ssml(said)
    assert speech_parts(said) == (said, None)
    assert speakable(said, 600) == said  # cleaning twice changes nothing more


def test_the_proof_of_concept_sentences_keep_their_words_and_lose_the_tag():
    assert (
        speakable('Playing <audio src="https://evil.example/x.mp3"/&gt; on Kitchen', 600)
        == "Playing on Kitchen"
    )
    assert speakable("&lt;b&gt;Elf&lt;/b&gt; (2003)") == "Elf (2003)"
    assert speakable("&amp;lt;b&amp;gt;") == "&lt;b&gt;"  # entities are read ONCE: still no bracket


def test_the_bracket_like_set_is_every_character_that_folds_into_a_bracket():
    """`BRACKET_LIKE` is written by hand; this walks Unicode to prove nothing is missing. NFKC
    (step 1) turns the compatibility forms into the brackets themselves; what is left is what
    only a decomposition reveals."""
    import unicodedata

    def folds_to_bracket(char, form):
        return any(b in unicodedata.normalize(form, char) for b in "<>")

    after_nfkc = {
        chr(i)
        for i in range(0x110000)
        if folds_to_bracket(chr(i), "NFKD") and not folds_to_bracket(chr(i), "NFKC")
    }
    assert after_nfkc == set(safety.BRACKET_LIKE)


def test_strip_markup_loops_to_a_fixed_point_and_leaves_no_bracket():
    assert strip_markup("a <b>c</b> d").split() == ["a", "c", "d"]
    # one pass leaves `<au dio>`, a tag again: the second pass takes it
    assert strip_markup("<au<b>dio src='x'>").strip() == ""
    assert strip_markup("<<b>i>talic").split() == ["i", "talic"]
    assert strip_markup("x < y > z").split() == ["x", "y", "z"]
    nested = "<" * 30 + "b" + ">" * 30  # deeper than the pass limit: the brackets still go
    assert "<" not in strip_markup(nested) and ">" not in strip_markup(nested)
    assert strip_markup("&lt;b&gt;") == "&lt;b&gt;"  # entities are the caller's to read first


def test_speakable_is_bounded_and_for_text_only():
    assert len(speakable("x" * 5000)) == 120 and len(speakable("<" * 100000)) <= 120
    assert "<" not in speakable("<" * 1000 + "ok")
    assert speakable("x" * 20000 + " tail", 30000) == "x" * safety.READ_AT_MOST  # read at most
    assert (
        speakable(7) == ""
        and speakable(None) == ""
        and speakable(b"x") == ""
        and speakable("x", 0) == ""
        and speakable("xyz", -5) == ""
    )
    assert speakable("  \n  ") == ""


def test_cleaning_twice_is_cleaning_once_also_for_a_text_that_was_cut():
    """A skill cleans a relayed answer to 600 characters and says it with `untrusted=True`, which
    cleans again: NFKC used to turn the first cut's ellipsis into three full stops."""
    long = "The garage is open. " * 60
    once = speakable(long, 600)
    assert once.endswith("\u2026") and len(once) <= 600
    assert speakable(once, 600) == once and speakable(once, safety.READ_AT_MOST) == once
    assert (
        speakable("wait\u2026 what", 50) == "wait\u2026 what"
    )  # an ellipsis somebody wrote stays one
    assert speakable("a\uff1cb\uff1e\u2026", 50) == "a \u2026"  # the tag goes, the ellipsis stays
    assert "<" not in speakable("\uff1cb\uff1e\u2026\uff1caudio\uff1e", 50)
    assert speakable("word " * 100, 20) == speakable(speakable("word " * 100, 20), 20)


def test_a_long_text_is_cut_at_a_word_and_closed_with_an_ellipsis():
    assert speakable("word " * 100, 20) == "word word word\u2026"
    assert (
        speakable("The garage is open. The front door is locked.", 22) == "The garage is open\u2026"
    )
    assert speakable("x" * 50, 10) == "x" * 9 + "\u2026"  # no word to cut at
    for limit in range(0, 40):
        assert len(speakable("one two three four five six seven", limit)) <= limit
    assert speakable("exactly ten", 11) == "exactly ten"  # a text that fits is not touched
    assert speakable("ab", 1) == "a"


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
        # this machine: on a hub, 127.0.0.1:8181 is the hub's own message bus
        "http://127.0.0.1:8096",
        "ws://127.0.0.1:8181",
        "wss://127.0.0.1",
        "http://127.8.9.10",
        "ws://[::1]:8095",
        "http://[::ffff:127.0.0.1]",
        "http://localhost:8096",
        "wss://localhost",
        "https://foo.localhost",
        # a single label is whatever the resolver's search list makes of it
        "http://nas:8096",
        "http://truenas:8095",
        "ws://ovos-messagebus-rtg-abc:8181",
        "wss://secrets:8200",
        "https://kubernetes",
        # cluster names, any scheme
        "wss://secrets.infra.svc:8200",
        "https://x.svc.cluster.local",
        # metadata services outside the link-local range
        "http://100.100.100.200",
        "https://[fd00:ec2::254]",
        "http://169.254.170.2",
    ],
)
def test_urls_that_leak_the_token_or_reach_inside_are_refused(url):
    assert url_problem(url) != ""


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.5:8096",
        "http://jellyfin.local:8096",
        "http://nas.lan:8096",
        "https://media.example.com",
        "http://10.1.2.3",
        "http://[fd00::5]:8096",
        "ws://truenas.local:8095",
        "wss://music.example.com/ws",
        "http://x.home.arpa",
        "https://8.8.8.8",
        "wss://[2606:4700:4700::1111]/ws",
    ],
)
def test_urls_of_a_home_server_and_any_tls_server_are_allowed(url):
    assert url_problem(url) == ""


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:8096", "ws://[::1]:8095", "http://localhost:8096", "wss://localhost"],
)
def test_loopback_is_admitted_only_when_the_caller_says_so(url):
    """A test server, or a program meant to dial its own machine. Never the default."""
    assert url_problem(url) != "" and url_problem(url, loopback=True) == ""


def test_loopback_does_not_open_anything_else():
    for url in (
        "http://169.254.169.254",
        "http://nas",
        "https://kubernetes.default.svc",
        "http://0.0.0.0",
        "http://8.8.8.8",
    ):
        assert url_problem(url, loopback=True) != ""


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
    for mine in ("127.0.0.1", "127.255.255.254", "::1", "::ffff:127.0.0.1"):
        assert address_problem(ipaddress.ip_address(mine)) != ""
        assert address_problem(ipaddress.ip_address(mine), loopback=True) == ""
    for metadata in ("100.100.100.200", "fd00:ec2::254", "169.254.169.254"):
        assert address_problem(ipaddress.ip_address(metadata), loopback=True) != ""


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
    """`url_problem` cannot resolve: "http://nas.lan" passes it. The dial-time check refuses a name
    that answers with a public address, for http and ws; TLS keeps public addresses."""
    assert url_problem("http://nas.lan") == ""
    monkeypatch.setattr(safety.socket, "getaddrinfo", lambda *a, **k: _infos("8.8.8.8"))
    with pytest.raises(UnsafeAddress, match="plain"):
        vetted_addresses("nas.lan", 80, plain=True)
    assert vetted_addresses("nas.lan", 443) == ["8.8.8.8"]  # TLS: public is fine
    monkeypatch.setattr(
        safety.socket, "getaddrinfo", lambda *a, **k: _infos("192.168.1.5", "8.8.8.8")
    )
    with pytest.raises(UnsafeAddress, match="plain"):  # any public answer refuses the whole name
        vetted_addresses("nas.lan", 80, plain=True)
    monkeypatch.setattr(
        safety.socket, "getaddrinfo", lambda *a, **k: _infos("192.168.1.5", "10.0.0.2")
    )
    assert vetted_addresses("nas.lan", 80, plain=True) == ["192.168.1.5", "10.0.0.2"]
    monkeypatch.setattr(
        safety.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:8.8.8.8", 80, 0, 0))
        ],
    )
    with pytest.raises(UnsafeAddress, match="plain"):  # an IPv4-mapped public address is public
        vetted_addresses("nas.lan", 80, plain=True)


@pytest.mark.parametrize(
    "answer", ["127.0.0.1", "::1", "169.254.169.254", "0.0.0.0", "100.100.100.200", "fe80::1"]
)
def test_a_name_that_resolves_to_this_machine_or_to_metadata_is_refused_at_dial_time(
    monkeypatch, answer
):
    """The text of the URL is innocent (`https://music.example.com`); the address it finally
    means is not. One bad answer among good ones refuses the whole name (rebinding)."""
    family = socket.AF_INET6 if ":" in answer else socket.AF_INET
    tail = (answer, 443, 0, 0) if ":" in answer else (answer, 443)
    monkeypatch.setattr(
        safety.socket,
        "getaddrinfo",
        lambda *a, **k: _infos("10.0.0.5") + [(family, socket.SOCK_STREAM, 6, "", tail)],
    )
    with pytest.raises(UnsafeAddress):
        vetted_addresses("music.example.com", 443)
    with pytest.raises(UnsafeAddress):
        dial_vetted("music.example.com", 443)


def test_loopback_resolves_only_when_the_caller_says_so(monkeypatch):
    monkeypatch.setattr(safety.socket, "getaddrinfo", lambda *a, **k: _infos("127.0.0.1"))
    with pytest.raises(UnsafeAddress):
        vetted_addresses("127.0.0.1", 80, plain=True)
    with pytest.raises(UnsafeAddress):
        vetted_addresses("localhost", 80, plain=True)
    assert vetted_addresses("127.0.0.1", 80, plain=True, loopback=True) == ["127.0.0.1"]
    assert vetted_addresses("localhost", 80, plain=True, loopback=True) == ["127.0.0.1"]


@pytest.mark.parametrize(
    "name",
    [
        "nas",
        "secrets",
        "kubernetes",
        "ovos-messagebus",
        "kubernetes.default.svc",
        "x.cluster.local",
        "localhost",
    ],
)
def test_a_name_that_is_never_dialled_is_refused_before_it_is_resolved(monkeypatch, name):
    def never(*a, **k):
        raise AssertionError("resolved a name that is never dialled")

    monkeypatch.setattr(safety.socket, "getaddrinfo", never)
    with pytest.raises(UnsafeAddress):
        vetted_addresses(name, 443)


def test_a_name_is_resolved_as_a_full_name_so_the_search_list_never_applies(monkeypatch):
    """Inside a cluster `secrets.infra` resolves through the search list to the Service `secrets` of
    the namespace `infra`. Asked with the root's dot it is a name nobody has."""
    seen = []
    monkeypatch.setattr(
        safety.socket, "getaddrinfo", lambda host, *a, **k: seen.append(host) or _infos("10.0.0.5")
    )
    vetted_addresses("secrets.infra", 8200)
    vetted_addresses("music.example.com.", 443)
    vetted_addresses("192.168.1.5", 80, plain=True)
    vetted_addresses("localhost", 80, loopback=True)
    assert seen == ["secrets.infra.", "music.example.com.", "192.168.1.5", "localhost"]


def test_vetted_addresses_resolves_the_canonical_form_and_refuses_an_unencodable_name(monkeypatch):
    seen = []
    monkeypatch.setattr(
        safety.socket, "getaddrinfo", lambda host, *a, **k: seen.append(host) or _infos("10.0.0.5")
    )
    assert vetted_addresses("Bücher.Local.", 80, plain=True) == ["10.0.0.5"]
    assert vetted_addresses("134744072", 443) == ["10.0.0.5"] and seen == [
        "xn--bcher-kva.local.",
        "8.8.8.8",
    ]
    for bad in ("a" * 64, "", None):
        with pytest.raises(UnsafeAddress):
            vetted_addresses(bad, 80)


def test_dial_vetted_connects_to_the_checked_address_and_never_to_the_name(monkeypatch):
    dialled = []

    class Sock:
        pass

    def connect(address, timeout=None):
        dialled.append((address, timeout))
        if address[0] == "10.0.0.5":
            raise ConnectionRefusedError("down")
        return Sock()

    monkeypatch.setattr(
        safety.socket, "getaddrinfo", lambda *a, **k: _infos("10.0.0.5", "10.0.0.6")
    )
    monkeypatch.setattr(safety.socket, "create_connection", connect)
    assert isinstance(dial_vetted("music.example.com", 8095, timeout=2.5), Sock)
    assert dialled == [(("10.0.0.5", 8095), 2.5), (("10.0.0.6", 8095), 2.5)]  # addresses only


def test_dial_vetted_raises_the_last_failure_when_nothing_answers(monkeypatch):
    def refuse(address, timeout=None):
        raise TimeoutError("slow")

    monkeypatch.setattr(safety.socket, "getaddrinfo", lambda *a, **k: _infos("10.0.0.5"))
    monkeypatch.setattr(safety.socket, "create_connection", refuse)
    with pytest.raises(TimeoutError):
        dial_vetted("music.example.com", 8095)
    monkeypatch.setattr(safety, "vetted_addresses", lambda *a, **k: [])
    with pytest.raises(UnsafeAddress):
        dial_vetted("music.example.com", 8095)


def test_url_problem_says_no_to_an_unreadable_url_instead_of_raising():
    """A URL `normalize_base_url` did not make is refused too, not an exception."""
    from thalovant_skillkit.safety import url_problem

    for url in ("http://[::1", "http://[", "http://[fe80::1", None, 7, b"http://x"):
        assert url_problem(url) != "", url  # type: ignore[arg-type]
