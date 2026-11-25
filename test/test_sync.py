"""A connection's other open screens hear of a change; nobody else ever does."""
from thalovant_skillkit import sync
from test_owner import BRIDGE, ME, THEM, label


def screen(client_uuid: str, declared: str, opted_in: bool = True) -> dict:
    context = {"peer": label(client_uuid, declared=declared), "session": {"session_id": f"ns:{declared}"}}
    if opted_in:
        context[sync.OPT_IN] = True
    return context


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Bus:
    def __init__(self) -> None:
        self.emitted = []

    def emit(self, message) -> None:
        self.emitted.append(message)


def test_a_session_must_ask_and_a_string_is_not_asking():
    peers = sync.Peers()
    peers.seen(screen(ME, "laptop", opted_in=False))
    context = screen(ME, "home", opted_in=False)
    context[sync.OPT_IN] = "true"
    peers.seen(context)
    assert peers.others(f"client-{ME}") == []


def test_another_clients_sessions_are_never_returned():
    peers = sync.Peers()
    peers.seen(screen(ME, "laptop"))
    peers.seen(screen(THEM, "their-board"))
    assert peers.others(f"client-{ME}") == [label(ME, declared="laptop")]
    assert peers.others(f"client-{THEM}") == [label(THEM, declared="their-board")]


def test_a_label_the_hub_did_not_stamp_is_not_remembered():
    peers = sync.Peers()
    context = screen(ME, "laptop")
    context["peer"] = "galaxy-s24"
    peers.seen(context)
    assert peers.others(f"client-{ME}") == [] and peers.others("galaxy-s24") == []


def test_the_local_device_and_the_preview_bridge_are_never_shared():
    peers = sync.Peers()
    peers.seen({sync.OPT_IN: True})
    peer = f"ThalovantPublicPreviewBridge::7::{BRIDGE}::thalovant-public-preview-bridge"
    for conversation in ("a", "b"):
        peers.seen({"peer": peer, sync.OPT_IN: True, "session": {"session_id": f"ns:conversation:{conversation}"}})
    assert peers.others("default") == []
    assert peers.others(f"{BRIDGE}|ns:conversation:a") == []
    assert not sync.shareable(None)


def test_at_most_eight_sessions_and_none_older_than_a_day():
    clock = Clock()
    peers = sync.Peers(clock)
    for index in range(10):
        peers.seen(screen(ME, f"screen-{index}"))
    remembered = peers.others(f"client-{ME}")
    assert len(remembered) == sync.MAX_PEERS and label(ME, declared="screen-0") not in remembered
    clock.now += sync.TTL_SECONDS + 1
    assert peers.others(f"client-{ME}") == []


def test_send_tells_each_other_session_alone_and_only_the_meta():
    peers, bus = sync.Peers(), Bus()
    for declared in ("laptop", "home", "kitchen"):
        peers.seen(screen(ME, declared))
    peers.seen(screen(THEM, "their-board"))

    sent = sync.send(bus, peers, f"client-{ME}", exclude=[label(ME, declared="laptop"), None],
                     kind="alarm", meta={"schedule": [{"kind": "alarm", "id": "a1", "state": "scheduled"}]},
                     source="thalovant-skill-alarm.thalovant")

    assert sent == 2
    assert [message.context["destination"] for message in bus.emitted] == [
        [label(ME, declared="home")], [label(ME, declared="kitchen")]]
    assert {message.msg_type for message in bus.emitted} == {sync.TYPE}
    assert bus.emitted[0].data == {"kind": "alarm", "meta": {"schedule": [{"kind": "alarm", "id": "a1", "state": "scheduled"}]}}


def test_send_does_nothing_without_a_bus_news_or_a_shareable_owner():
    peers, bus = sync.Peers(), Bus()
    peers.seen(screen(ME, "home"))
    assert sync.send(None, peers, f"client-{ME}", kind="alarm", meta={"schedule": []}, source="s") == 0
    assert sync.send(bus, peers, f"client-{ME}", kind="alarm", meta={}, source="s") == 0
    assert sync.send(bus, peers, "default", kind="alarm", meta={"schedule": [1]}, source="s") == 0
    assert bus.emitted == []


def test_labels_in_reads_only_hub_labels_from_destination():
    context = {"destination": [label(ME, declared="laptop"), "skills", None]}
    assert sync.labels_in(context) == [label(ME, declared="laptop")]
    assert sync.labels_in({"destination": label(ME)}) == [label(ME)]
    assert sync.labels_in({}) == []
