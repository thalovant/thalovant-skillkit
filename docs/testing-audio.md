# Assert per-speaker speech and audio

SkillKit 0.12.0 adds optional inspection helpers to `CapturedTurn`, the result of
`testing_ovos.capture_turn()`. They inspect recorded messages without playing
audio, opening media files, or fetching URLs. Install the `[testing]` extra for
native OVOS integration tests and enter XDG isolation before importing OVOS.

Call `turn.for_session(session_id)` before checking a particular speaker's output.
The selection uses the exact `context.session.session_id` carried by each message.
Messages with no matching dictionary carrier are excluded. A missing session is
never assigned to the originating speaker or the default room. Empty or non-string
session IDs raise `ValueError`.

The returned `CapturedTurn` has its own message list and the latest matching OVOS
session state. It shares message objects with the original capture; inspecting it
does not change the full capture. If no message matches, the view is empty and
retains the original session only when its ID matches the requested ID.

## Check speech and the actual sound bytes

This assertion helper can be used after capturing a skill's response:

```python
from pathlib import Path

from thalovant_skillkit.testing_ovos import CapturedTurn


def assert_spoken_cue(
    turn: CapturedTurn, session_id: str, text: str, expected_sound: Path,
) -> None:
    room = turn.for_session(session_id)
    assert room.spoken == [text]
    cue, = room.audio
    assert cue.binary == expected_sound.read_bytes()
    assert cue.extension == expected_sound.suffix.removeprefix(".")
    assert cue.uri is None
    assert cue.message.context["session"]["session_id"] == session_id
```

Native OVOS `play_audio()` sends file bytes for named remote sessions. `audio`
returns frozen `CapturedAudio` records with these fields:

| Field | Meaning |
| --- | --- |
| `message` | Original captured message, including its routing and session context. |
| `binary` | Decoded `binary_data` bytes, or `None` for a URI request. |
| `extension` | The declared `audio_ext`, or `None` for a URI request. |
| `uri` | The supplied URI or filename, or `None` for a binary request. |

Both queued sounds (`ovos.audio.queue` / `mycroft.audio.queue`) and immediate
sounds (`ovos.audio.play_sound` / `mycroft.audio.play_sound`) are included in
capture order. A canonical topic takes precedence over its legacy spelling for
each operation within the selected view. This follows the existing `spoken`
convention and avoids counting compatibility mirrors twice; repeated messages in
the selected namespace remain separate. Keep `messages` or `of_type(topic)` for
an exact inspection of every wire message, including both namespaces.

Binary requests require nonempty valid hexadecimal text and a nonempty string
extension. URI requests require a nonempty string URI. Missing payloads, combined
URI/binary payloads, invalid hex, and missing or invalid extensions raise
`AssertionError`. The helper does not decode the audio format or verify that the
declared extension matches it; compare bytes against the expected packaged file.

## Check Stop stays with its speaker

For a capture containing interleaved activity from Alice and Bob:

```python
alice = turn.for_session("alice")
bob = turn.for_session("bob")
stop, = alice.audio_stops
assert stop.context["session"]["session_id"] == "alice"
assert not bob.audio_stops
assert bob.audio  # Bob's own queued sound is still present in this capture.
```

`audio_stops` returns original `ovos.audio.stop` messages, falling back to
`mycroft.audio.speech.stop` when the view contains no canonical Stop. Inspect the
original context to check additional routing fields used by your integration.
These assertions establish emitted requests; they do not prove that a physical
speaker played a sound or completed a Stop. Assert the skill's remaining state
and subsequent turns separately.

The [native integration tests](../test/test_testing_ovos.py) demonstrate real
`OVOSSkill.play_audio()`, two sessions, and native skill Stop dispatch through
OVOScope and the upstream bus without starting an audio player.
