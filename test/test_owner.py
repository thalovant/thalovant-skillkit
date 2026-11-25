"""Whose items a message reaches: what the hub stamps, never what a device says.

Carried from the alarm skill (test_hub_identity), which owned this module
before skillkit 0.40.0.
"""
import pytest

from thalovant_skillkit import owner as owners

ME = "7b02b734-c6b2-4194-b9e4-d9002c9d9cb6"
THEM = "11111111-2222-4333-8444-555555555555"
BRIDGE = "hub-f7544458-9fe9-4f8f-bf2e-79ece48357a5-preview-bridge"


def label(client_uuid: str, number: int = 1573, declared: str = "phone-session") -> str:
    return f"ThalovantKotlinSDK/0.7.13::{number}::client-{client_uuid}::{declared}"


def bridge(conversation: str) -> dict:
    peer = f"ThalovantPublicPreviewBridge::7::{BRIDGE}::thalovant-public-preview-bridge"
    return {"peer": peer, "source": peer,
            "session": {"session_id": (
                f"0123456789abcdef:thalovant-public-preview-bridge:conversation:{conversation}")}}


@pytest.mark.parametrize("peer, owner", [
    ("ThalovantKotlinSDK/0.7.13::1573::client-7b02b734-c6b2-4194-b9e4-d9002c9d9cb6"
     "::thalovant-kotlin-a69b401d-db7f-4590-ba4b-bc89f17670ad",
     "client-7b02b734-c6b2-4194-b9e4-d9002c9d9cb6"),
    (f"ThalovantSwiftSDK/0.11.0::12::client-{ME}::s", f"client-{ME}"),
    # MQTT puts the access key first; the HTTP listener lets the name be empty.
    (f"f3a9c0de12345678::12::client-{ME}::s", f"client-{ME}"),
    (f"::12::client-{ME}::s", f"client-{ME}"),
    # Announcing another client's name, or naming it in the session, changes nothing.
    (f"client-{ME}::1999::client-{THEM}::attacker", f"client-{THEM}"),
    (f"galaxy-s24::1999::client-{THEM}::x::1573::client-{ME}::y", f"client-{THEM}"),
    # Not a label the hub writes: nobody.
    (f"client-{ME}", None),
    (f"client-{ME}::session", None),
    ("ThalovantKotlinSDK/0.7.13::not-a-number::client-x::s", None),
    ("", None),
    (None, None),
])
def test_the_owner_is_the_hubs_name_for_the_client(peer, owner):
    context = {"peer": peer, "site_id": "galaxy-s24", "client_id": f"client-{ME}"}
    assert owners.owner_of(context) == owner


def test_a_message_that_never_crossed_hivemind_is_the_local_devices():
    assert owners.owner_of({"site_id": "galaxy-s24", "client_id": f"client-{ME}"}) == owners.LOCAL


def test_each_preview_conversation_is_its_own_owner_with_one_shared_limit():
    first, second = owners.owner_of(bridge("a")), owners.owner_of(bridge("b"))
    assert first != second and first.startswith(BRIDGE + "|")
    assert owners.limit_group(first) == owners.limit_group(second) == BRIDGE
    assert owners.limit_group(f"client-{ME}") == f"client-{ME}"


def test_a_preview_visitor_without_a_session_is_nobody():
    context = bridge("a")
    del context["session"]["session_id"]
    assert owners.owner_of(context) is None


def test_an_item_that_is_nobodys_is_never_anybodys():
    assert owners.owns({"owner": None}, None) is False
    assert owners.owns({"owner": f"client-{ME}"}, f"client-{ME}") is True
    assert owners.owns({"owner": f"client-{ME}"}, f"client-{THEM}") is False


def test_asked_by_takes_the_label_from_the_bus_message_only():
    class Message:
        context = {"peer": label(ME), "session": {"session_id": "ns:me"}}

    said = {"peer": label(THEM), "site_id": "x",
            "session": {"session_id": "ns:them", "lang": "en-US"}}
    trusted = owners.asked_by(said, Message())
    assert trusted["peer"] == label(ME)
    assert trusted["session"] == {"session_id": "ns:me", "lang": "en-US"}
    assert "peer" not in owners.asked_by(said, None)


def test_stored_items_are_decided_again_once_from_their_routing():
    mine = {"owner": "galaxy-s24", "context": {"destination": label(ME)}}
    planted = {"owner": "galaxy-s24", "context": {"destination": label(THEM, 1999)}}
    local = {"owner": "default", "context": {"source": "audio", "destination": ["skills"]}}
    unlabelled = {"owner": "galaxy-s24", "context": None}
    items = [mine, planted, local, unlabelled]

    assert owners.migrate(items) is True
    expected = [f"client-{ME}", f"client-{THEM}", owners.LOCAL, None]
    assert [item["owner"] for item in items] == expected
    mine["context"] = {"destination": label(THEM, 1999)}
    assert owners.migrate(items) is False
    assert mine["owner"] == f"client-{ME}"
