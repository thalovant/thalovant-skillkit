"""Who is speaking: the router's stamp only, failing closed (thalovant_skillkit.device)."""

import inspect

import pytest

from thalovant_skillkit import device
from thalovant_skillkit.device import (
    LINK_STATES,
    LINKED,
    STAMP_KEYS,
    DeviceIdentity,
    device_allowed,
    device_identity,
    device_value,
    link_allowed,
    link_state,
)

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
    mark2 = device_identity({"thalovant_home": {"device": "7", "device_name": "client-mark2"}})
    assert mark2.keys == ("7", "client-mark2", "mark2") and mark2.names == ("client-mark2", "mark2")
    assert device_identity({"thalovant_home": {"device": "7", "device_name": " Den "}}).names == (
        "Den",
    )
    assert device_identity({"thalovant_home": {"device": "7", "device_name": "client-"}}).names == (
        "client-",
    )
    assert device_identity({"thalovant_home": {"device": "7"}}) == DeviceIdentity("7", None)
    assert STAMP_KEYS == ("thalovant_home", "thalovant_connector")


@pytest.mark.parametrize(
    "stamp",
    [
        {"link": "online", "device_name": "client-abc"},
        {"device_name": " Den "},
        {"device": "", "device_name": "Kitchen"},
        {"device": None, "device_name": "Kitchen"},
        {"device": 1580, "device_name": "Kitchen"},  # the router writes a string
        {"device": "15 80", "device_name": "Kitchen"},
        {"device": "\u0661\u0665\u0668\u0660", "device_name": "Kitchen"},  # Arabic-Indic digits
        {"device": "\uff11\uff15\uff18\uff10", "device_name": "Kitchen"},  # fullwidth digits
    ],
)
def test_a_stamp_that_carries_only_a_name_names_nobody(stamp):
    """The recheck's proof of concept: `{"link": "online", "device_name": "client-abc"}` passed
    the gate for `allowed_devices: ["client-abc"]` and for `["abc"]`. A label is not an identity:
    the router writes `device` for every connection it vouches for."""
    context = {"thalovant_home": stamp}
    assert device_identity(context) is None
    for allowed in (["client-abc"], ["abc"], ["Kitchen"], ["Den"], ["1580"], [1580]):
        assert device_allowed(context, allowed) is False
    assert link_allowed(context) is False and device_value(context, {"Kitchen": "x"}) is None


@pytest.mark.parametrize(
    "name", ["client-1580", "1580", "Client-\uff11\uff15\uff18\uff10", " 1580 "]
)
def test_a_row_named_after_an_id_does_not_pass_for_that_id(name):
    """The recheck's proof of concept: ids and names shared one set and `client-` was stripped,
    so the entry "1580" (a device id) admitted device 999 once its row was NAMED `client-1580`
    or `1580`. An entry made of digits is an id and is compared with the id only."""
    context = {"thalovant_home": {"link": "online", "device": "999", "device_name": name}}
    assert device_allowed(context, ["1580"]) is False and device_allowed(context, [1580]) is False
    assert device_allowed(context, ["\uff11\uff15\uff18\uff10"]) is False  # nor "digits" that fold
    assert device_allowed(context, ["999"]) is True  # its own id still does
    assert device_value(context, {"1580": "Kitchen"}) is None
    assert device_value(context, {"999": "Den", "1580": "Kitchen"}) == "Den"


def test_ids_are_compared_with_ids_and_names_with_names():
    kitchen = DeviceIdentity("1580", "client-Kitchen")
    assert kitchen.matches("1580") and kitchen.matches(1580) and kitchen.matches(" 1580 ")
    assert (
        not kitchen.matches("01580") and not kitchen.matches("158") and not kitchen.matches(-1580)
    )
    assert (
        kitchen.matches("kitchen")
        and kitchen.matches("Client-Kitchen")
        and kitchen.matches("k\u00edtchen")
    )
    assert not kitchen.matches("kitch") and not kitchen.matches("Kitchen Display")
    assert not kitchen.matches(True) and not kitchen.matches(None) and not kitchen.matches(15.8)
    assert not kitchen.matches("") and not kitchen.matches(("1580",))
    # a label made of digits is never compared with anything
    numbered = DeviceIdentity("7", "42")
    assert numbered.matches("7") and not numbered.matches("42") and not numbered.matches(42)
    assert not DeviceIdentity("7", "client-42").matches("42")
    assert DeviceIdentity("7", "client-42").matches("client-42")  # the full label is a name


def test_a_per_device_mapping_is_read_by_id_first_then_by_label():
    context = {"thalovant_home": {"device": "7", "device_name": "client-mark2"}}
    assert device_value(context, {"mark2": "Den", "7": "Kitchen"}) == "Kitchen"
    assert device_value(context, {"MARK2": "Den"}) == "Den"
    assert device_value(context, {"client-mark2": "Den", "mark2": "Attic"}) == "Den"  # first label
    assert device_value(context, {"8": "x", "mark": "y", "": "z", None: "w"}) is None
    assert device_value(context, None) is None and device_value(context, ["7"]) is None
    assert device_value({}, {"7": "Kitchen"}) is None
    assert (
        device_value({"thalovant_home": {"device_name": "client-mark2"}}, {"mark2": "Den"}) is None
    )

    class Broken(dict):
        def items(self):
            raise RuntimeError("boom")

    assert device_value(context, Broken({"7": "Kitchen"})) is None
    assert DeviceIdentity("7", "client-mark2").value_in({"mark2": "Den"}) == "Den"
    assert DeviceIdentity("7").value_in({"mark2": "Den"}) is None


def test_the_first_label_that_matches_wins_even_when_it_maps_to_nothing():
    """Found in review: the first label was told from "none yet" by its VALUE, so a first match
    that maps to None let a later alias replace it. The rule is the first label, whatever it
    says; the id still goes before any label."""
    mark2 = DeviceIdentity("7", "client-mark2")
    assert mark2.value_in({"client-mark2": None, "mark2": "Attic"}) is None
    assert mark2.value_in({"mark2": "", "client-mark2": "Attic"}) == ""
    assert mark2.value_in({"client-mark2": None, "7": "Kitchen"}) == "Kitchen"
    assert mark2.value_in({"7": None, "mark2": "Attic"}) is None


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
        {"thalovant_home": {"device_name": "Kitchen"}},  # a label alone names nobody
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
    mark2 = {"thalovant_home": {"device": "7", "device_name": "client-mark2"}}
    assert device_allowed(mark2, ["mark2"]) is True
    assert device_allowed(mark2, ["client-mark2"]) is True
    assert device_allowed(mark2, ["7"]) is True and device_allowed(mark2, ["mark"]) is False


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
    assert DeviceIdentity("7", None).keys == ("7",) and DeviceIdentity("7").names == ()


# -- the link gate: a household's own link, nobody listed -----------------------------------------


def stamped(home="none", music="online", device="1580"):
    who = {"device": device, "device_name": "client-kitchen"} if device else {}
    return {
        "thalovant_home": {"link": home, **who},
        "thalovant_connector": {"link": {"music_assistant": music, "jellyfin": "none"}, **who},
    }


@pytest.mark.parametrize("state", LINK_STATES)
def test_the_link_state_is_what_the_router_wrote_for_that_connector(state):
    context = stamped(home="offline", music=state)
    assert link_state(context, "music_assistant") == state
    assert link_allowed(context, "music_assistant") is (state in ("online", "offline"))
    assert (
        link_state(context) == "offline" and link_allowed(context) is True
    )  # Home Assistant's own
    assert link_state(context, "jellyfin") == "none" and not link_allowed(context, "jellyfin")
    assert link_state(context, "plex") == "unavailable"  # a connector the router did not name
    assert LINKED == {"online", "offline"}


def test_a_stranger_with_no_link_is_a_no_for_every_route():
    for state in ("none", "unavailable"):
        context = stamped(home=state, music=state)
        assert not link_allowed(context, "music_assistant") and not link_allowed(context)


@pytest.mark.parametrize(
    "context",
    [
        None,
        "x",
        {},
        {"thalovant_connector": {"link": {"music_assistant": "online"}, "device": "7"}},  # no home
        stamped(device=None),  # a link nobody is behind
        {
            **stamped(),
            "thalovant_connector": {"link": {"music_assistant": "online"}, "device": "9"},
        },
        {**stamped(), "thalovant_connector": "online"},
        {"thalovant_home": {"link": "online", "device_name": "client-kitchen"}},
        {"thalovant_music": {"link": "online", "device": "7"}},  # the retired stamp
    ],
)
def test_a_link_without_a_vouched_device_is_not_believed(context):
    assert link_state(context, "music_assistant") == "unavailable"
    assert link_state(context) == "unavailable"
    assert link_allowed(context, "music_assistant") is False and link_allowed(context) is False


@pytest.mark.parametrize("link", [None, 1, True, ["online"], {"x": "online"}, "ONLINE", "up", ""])
def test_a_link_value_the_router_never_writes_is_unavailable(link):
    who = {"device": "7"}
    context = {
        "thalovant_home": {"link": link, **who},
        "thalovant_connector": {"link": {"music_assistant": link}, **who},
    }
    assert link_state(context) == "unavailable"
    assert link_state(context, "music_assistant") == "unavailable"
    context["thalovant_connector"]["link"] = link  # not a mapping at all
    assert link_state(context, "music_assistant") == "unavailable"


def test_the_gate_cannot_tell_who_wrote_the_stamp_and_says_so():
    """The honest limit (the recheck's routerless proof of concept): on a hub that does not load
    the home router nothing overwrites these keys, so a client that sends them is believed. The
    module's own description must keep saying it, so nobody reads the gate as more than it is."""
    forged = {"thalovant_home": {"device": "1580"}, "thalovant_connector": {"device": "1580"}}
    assert device_allowed(forged, ["1580"]) is True
    assert "does not\nload the home router" in device.__doc__ or "does not load" in " ".join(
        device.__doc__.split()
    )
    assert device_allowed({"thalovant_home": {"device": "7"}}, ["7"]) is True
