"""Independent regression for the captured CBC continuation routing failure.

Uses the actual Message.reply/forward methods. Their ASTs were compared with
the installed spec-tools 1.16.2a1 source and match the local test environment.
Only FakeBus is used; this test cannot emit into a running runtime.
"""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from ovos_bus_client.message import Message

from thalovant_skillkit import handback
from thalovant_skillkit.testing import FakeBus


def peers(value):
    return set(value if isinstance(value, list) else [value]) if value else set()


def request(destination):
    return Message(
        "ovos.utterance.handle",
        {"utterances": ["play cbc montreal news"], "lang": "en-US"},
        {
            "source": "test-satellite",
            "destination": destination,
            "peer": "test-satellite",
            "request_id": "cbc-request",
            "thalovant_request_id": "cbc-request",
            "session": {
                "session_id": "cbc-session",
                "lang": "en-US",
                "blacklisted_skills": ["preexisting-denial"],
                "extension": {"must_survive": True},
            },
        },
    )


def dispatch(utterance, skill_id):
    """Same routing derivation used by installed IntentService._dispatch_match."""
    data = dict(utterance.data)
    data["utterance"] = data["utterances"][0]
    result = utterance.reply(skill_id + ":intent", data)
    result.context["skill_id"] = skill_id
    return result


def decline(intent, skill_id):
    skill = SimpleNamespace(skill_id=skill_id, lang="en-US", _bus=FakeBus())
    assert handback.hand_back(skill, intent)
    assert len(skill._bus.emitted) == 1
    return skill._bus.emitted[0]


@pytest.mark.parametrize("destination", ["skills", ["skills"]])
def test_handback_news_reply_reaches_the_original_satellite(monkeypatch, destination):
    monkeypatch.setattr(handback, "_utterance_topic", lambda: "ovos.utterance.handle")
    initial = request(destination)
    original = deepcopy(initial.context)
    music = dispatch(initial, "music")
    music_before = deepcopy(music.context)
    again = decline(music, "music")
    news = dispatch(again, "news")
    speech = news.forward("ovos.utterance.speak", {"utterance": "Playing CBC Montreal"})

    assert peers(speech.context.get("destination")) == {"test-satellite"}, (
        "Continuation speech was addressed to the runtime, not the asking device"
    )
    assert peers(again.context.get("source")) == {"test-satellite"}
    assert peers(again.context.get("destination")) == {"skills"}
    assert speech.context["request_id"] == "cbc-request"
    assert speech.context["thalovant_request_id"] == "cbc-request"
    assert speech.context["peer"] == "test-satellite"
    assert speech.context["session"]["session_id"] == "cbc-session"
    assert speech.context["session"]["blacklisted_skills"] == ["preexisting-denial", "music"]
    assert speech.context["session"]["extension"] == {"must_survive": True}
    assert initial.context == original
    assert music.context == music_before


def test_two_declining_skills_each_restore_request_direction(monkeypatch):
    monkeypatch.setattr(handback, "_utterance_topic", lambda: "ovos.utterance.handle")
    initial = request("skills")
    again = initial
    for skill_id in ("music", "media"):
        again = decline(dispatch(again, skill_id), skill_id)
        assert peers(again.context.get("source")) == {"test-satellite"}
        assert peers(again.context.get("destination")) == {"skills"}
    speech = dispatch(again, "news").forward("ovos.utterance.speak", {"utterance": "CBC"})
    assert peers(speech.context.get("destination")) == {"test-satellite"}
    assert speech.context["session"]["blacklisted_skills"] == [
        "preexisting-denial", "music", "media"
    ]


def test_unaddressed_local_request_stays_unaddressed(monkeypatch):
    monkeypatch.setattr(handback, "_utterance_topic", lambda: "ovos.utterance.handle")
    initial = request("skills")
    initial.context.pop("source")
    initial.context.pop("destination")
    again = decline(dispatch(initial, "music"), "music")
    assert "source" not in again.context
    assert "destination" not in again.context
    assert again.context["session"]["blacklisted_skills"] == ["preexisting-denial", "music"]


@pytest.mark.parametrize("session_id", ["cbc-session", "default"])
def test_explicit_exclusion_survives_bound_live_session_stamping(monkeypatch, session_id):
    from ovos_spec_tools.session import SessionManager

    monkeypatch.setattr(handback, "_utterance_topic", lambda: "ovos.utterance.handle")
    # Isolate the real registry, rather than mocking the stamping implementation.
    monkeypatch.setattr(SessionManager, "sessions", {})
    monkeypatch.setattr(SessionManager, "default_session", None)
    monkeypatch.setattr(SessionManager, "_extras", {})
    initial = request("skills")
    initial.context["session"]["session_id"] = session_id
    if session_id == "default":
        live = SessionManager.get_default_session()
        live.blacklisted_skills = ["preexisting-denial"]
    else:
        live = SessionManager.get(initial)
    SessionManager.bind(initial, live)
    music = dispatch(initial, "music")
    SessionManager.bind(music, live)
    assert "music" not in live.blacklisted_skills

    # Explicit session edits must survive both old and current stamping behavior.
    again = decline(music, "music")
    assert again.context["session"]["session_id"] == session_id
    assert again.context["session"]["blacklisted_skills"] == ["preexisting-denial", "music"]
    assert "music" not in live.blacklisted_skills
    assert peers(again.context.get("source")) == {"test-satellite"}
    assert peers(again.context.get("destination")) == {"skills"}
