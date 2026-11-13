"""Who is speaking: the router's stamp only, failing closed (thalovant_skillkit.device)."""

import inspect

import pytest

from thalovant_skillkit import device
from thalovant_skillkit.device import STAMP_KEYS, DeviceIdentity, device_allowed, device_identity

STAMPED = {
    "thalovant_home": {"link": "none", "device": "1580", "device_name": "Kitchen"},
    "thalovant_connector": {
        "link": {"music_assistant": "online"},
        "device": "1580",
        "device_name": "Kitchen",
    },
}


def test_the_identity_is_the_stamps_device_and_name():
    ident = device_identity(STAMPED)
    assert ident == DeviceIdentity("1580", "Kitchen") and ident.keys == ("1580", "Kitchen")
    assert device_identity(
        {"thalovant_home": {"device": "7", "device_name": "client-mark2"}}
    ).keys == ("7", "client-mark2", "mark2")
    assert device_identity({"thalovant_home": {"device_name": " Den "}}).keys == ("Den",)
    assert device_identity({"thalovant_home": {"device_name": "client-"}}).keys == ("client-",)
    assert STAMP_KEYS == ("thalovant_home", "thalovant_connector")


def test_thalovant_home_decides_and_a_connector_stamp_must_agree():
    """Before router 0.5.0 nothing overwrote `thalovant_connector`: a client could write its own,
    and the first stamp found used to win. The key every router since 0.4.1 overwrites decides."""
    home = {"device": "1", "device_name": "Den"}
    forged = {
        "thalovant_home": home,
        "thalovant_connector": {"device": "9", "device_name": "Kitchen"},
    }
    assert (
        device_identity(forged) is None
        and device_allowed(forged, ["Kitchen", "9", "Den", "1"]) is False
    )
    # a client-written connector stamp with no home stamp beside it
    assert (
        device_identity({"thalovant_connector": {"device": "9", "device_name": "Kitchen"}}) is None
    )
    # a connector stamp that names nobody or is unreadable disagrees too (never "skipped")
    for other in ({}, "nonsense", {"device": "x"}, {"link": "online"}):
        assert device_identity({"thalovant_home": home, "thalovant_connector": other}) is None
    # the same device under both keys, or no connector key at all (router 0.4.x): the home stamp
    same = {"thalovant_home": home, "thalovant_connector": {"link": {}, **home}}
    assert device_identity(same).keys == ("1", "Den")
    assert device_identity({"thalovant_home": home}).keys == ("1", "Den")


def test_the_retired_per_service_stamp_is_not_believed():
    """A client could write this key itself; only the router's own keys are trusted."""
    forged = {"thalovant_music": {"device": "1580", "device_name": "Kitchen"}}
    assert device_identity(forged) is None and device_allowed(forged, ["Kitchen", "1580"]) is False


@pytest.mark.parametrize(
    "context",
    [
        None,
        "x",
        [],
        3,
        {},
        {"thalovant_home": {"link": "online"}},
        {"thalovant_home": "stamp"},
        {"thalovant_home": {"device": "12a"}},
        {"thalovant_home": {"device": "١٢"}},  # not ASCII digits
        {"thalovant_home": {"device": 12}},
        {"thalovant_home": {"device_name": "   "}},
        {"thalovant_home": {"device": "", "device_name": ""}},
        {"thalovant_home": {"device_name": ["Kitchen"]}},
        {
            "thalovant_connector": {"device": "12", "device_name": "Kitchen"}
        },  # no home stamp: nobody
    ],
)
def test_no_usable_stamp_is_no_identity(context):
    assert device_identity(context) is None
    assert device_allowed(context, ["Kitchen", "12"]) is False


def test_peer_and_the_other_client_words_are_never_read():
    spoofed = {
        "peer": "ua::1580::Kitchen::x",
        "source": "a::b::c::1580::Kitchen",
        "site_id": "Kitchen",
        "client_id": "1580",
        "session": {"site_id": "Kitchen", "client_id": "1580"},
    }
    assert device_identity(spoofed) is None
    assert device_allowed(spoofed, ["Kitchen", "1580"]) is False
    # a `::` in the session cannot make the tail read as another client's id
    forged = {"peer": "ua::7::Den::x::1580::Kitchen", **STAMPED}
    assert device_identity(forged).keys == ("1580", "Kitchen")


def test_the_module_has_no_way_to_read_a_client_supplied_key():
    """Nothing in the module's code names `peer`, `source`, `site_id` or `client_id`: reading
    one would be new code that this test (and the review of it) has to see."""
    code = "\n".join(
        line
        for line in inspect.getsource(device).splitlines()
        if not line.lstrip().startswith(("#", '"""'))
    )
    body = code.split("STAMP_KEYS: tuple", 1)[1]
    for word in ('"peer"', '"source"', '"site_id"', '"client_id"', "'peer'"):
        assert word not in body


def test_the_gate_is_deny_by_default_and_exact():
    assert device_allowed(STAMPED, []) is False
    assert device_allowed(STAMPED, ["", None, 3.5, True, ("Kitchen",)]) is False
    assert device_allowed(STAMPED, ["Kitchen"]) is True
    assert device_allowed(STAMPED, ["kítchen"]) is True  # folded
    assert device_allowed(STAMPED, ["1580"]) is True and device_allowed(STAMPED, [1580]) is True
    assert device_allowed(STAMPED, ["Kitchen Display", "158", "kitch"]) is False  # whole names only
    assert device_allowed({"thalovant_home": {"device_name": "client-mark2"}}, ["mark2"]) is True
    assert (
        device_allowed({"thalovant_home": {"device_name": "client-mark2"}}, ["client-mark2"])
        is True
    )


def test_a_broken_allow_list_is_a_no_not_an_error():
    assert device_allowed(STAMPED, None) is False
    assert device_allowed(STAMPED, 5) is False

    def endless():
        raise TypeError("boom")
        yield  # pragma: no cover

    assert device_allowed(STAMPED, endless()) is False


def test_a_scalar_is_not_a_list():
    """A bare string read as characters would allow the devices "1", "5", "8", "0" for "1580"."""
    for stamp_device in ("1", "5", "8", "0", "1580"):
        ctx = {"thalovant_home": {"device": stamp_device, "device_name": "Den"}}
        assert device_allowed(ctx, "1580") is False and device_allowed(ctx, b"1580") is False
        assert device_allowed(ctx, ["1580"]) is (stamp_device == "1580")
    assert device_allowed(STAMPED, "Kitchen") is False


@pytest.mark.parametrize("error", [RuntimeError, ValueError, KeyError, OSError])
def test_an_allow_list_that_raises_after_an_entry_is_a_no(error):
    def partly():
        yield "Kitchen"  # it would have allowed this device
        raise error("boom")

    assert device_allowed(STAMPED, partly()) is False


def test_an_identity_may_have_only_an_id():
    assert DeviceIdentity("7", None).keys == ("7",)
    assert DeviceIdentity(None, None).keys == ()
    assert device_allowed({"thalovant_home": {"device": "7"}}, ["7"]) is True
