"""Give a sentence back to the other skills, silently, once.

An intent handler cannot decline. A skill whose intent matched "play a quiz" but which must not
answer (the device may not use it, or the sentence turned out not to be its own) has two bad
choices: say something, which tells a stranger the feature is there, or say nothing, which
swallows a sentence another skill would have answered. The third way is to send the sentence
through the pipeline again with this skill left out of it, so the others answer as if this
skill had never matched:

    from thalovant_skillkit.skill import ThalovantSkill

    class MusicSkill(ThalovantSkill):
        def handle_play(self, message):
            if not self.may_use(message):
                return self.pass_on(message)     # nothing is said, nothing is dialled

Three skills had written this, each a little differently, and each remembered that it had already
handed a sentence back by writing a key of its own into the message context
(`thalovant_music_passed_on`). The context is the client's to write: a client that sent the key
itself got silence where another client got an answer, which told it in one message that the skill
is installed. So the memory is kept HERE, in the process: a small, bounded, expiring set keyed by
the speaking device (as the hub's router names it), the session and the sentence. Nothing a client
can send is trusted, and nothing but the session's own `blacklisted_skills` (the framework's way to
leave a skill out of one turn) is written into the message that goes back.

The memory is what stops a loop: should the sentence come back to the same skill anyway (a pipeline
stage that does not read the blacklist), the second request to hand it back is dropped and the
entry is forgotten. It expires after a few seconds, so the same words said again a moment later are
handed back again.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from time import monotonic
from typing import Any

from .device import device_identity
from .message import context_of, message_lang, utterance
from .speech import bus_of
from .text import fold

__all__ = ["UTTERANCE_TOPIC", "HandBackMemory", "hand_back"]

LOG = logging.getLogger(__name__)

#: Where a sentence enters the pipeline.
UTTERANCE_TOPIC = "recognizer_loop:utterance"


class HandBackMemory:
    """The sentences handed back a moment ago: bounded, expiring, in this process only.

    `ttl` is how long an entry stops a second hand-back (seconds); `limit` is how many entries are
    kept at most (the oldest goes first). Thread-safe: handlers run on a pool.
    """

    def __init__(self, ttl: float = 5.0, limit: int = 512, clock: Any = monotonic):
        self.ttl = float(ttl)
        self.limit = max(1, int(limit))
        self._clock = clock
        self._entries: OrderedDict[tuple, float] = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def first_time(self, key: tuple) -> bool:
        """True when `key` was not handed back within `ttl`, and remember it now.

        False means "this is the sentence coming back": the entry is forgotten, so a loop ends
        after one round and the same words are handed back again the next time they are said.
        """
        now = self._clock()
        with self._lock:
            for old in [k for k, at in self._entries.items() if now - at >= self.ttl]:
                del self._entries[old]
            if key in self._entries:
                del self._entries[key]
                return False
            self._entries[key] = now
            while len(self._entries) > self.limit:
                self._entries.popitem(last=False)
            return True


def _key(skill_id: str, context: dict, text: str) -> tuple:
    identity = device_identity(context)
    session = context.get("session")
    session_id = session.get("session_id") if isinstance(session, dict) else None
    return (
        skill_id,
        identity.device_id if identity else "",
        session_id if isinstance(session_id, str) else "",
        fold(text),
    )


def hand_back(skill: Any, message: Any, memory: HandBackMemory | None = None) -> bool:
    """Send `message`'s sentence through the pipeline again without `skill`; True when it was sent.

    The sentence is emitted as a new utterance whose session leaves this skill out
    (`blacklisted_skills`), so the other skills answer it. Nothing is said. A sentence this skill
    handed back a moment ago is not handed back twice (`memory`, kept in the process: no context
    key is written or read, so a client cannot ask for silence). Never raises: a failure here is
    silence, which is the safe way to fail for a skill that was about to refuse.
    """
    try:
        skill_id = getattr(skill, "skill_id", None)
        text = utterance(message)
        bus = bus_of(skill)
        if not skill_id or not text or bus is None:
            return False
        context = dict(context_of(message))
        if memory is None:
            memory = skill.__dict__.setdefault("_hand_back_memory", HandBackMemory())
        if not memory.first_time(_key(skill_id, context, text)):
            LOG.info("a sentence handed back a moment ago came back; it was dropped")
            return False
        session = context.get("session")
        session = dict(session) if isinstance(session, dict) else {}
        listed = session.get("blacklisted_skills")
        listed = [s for s in listed if isinstance(s, str)] if isinstance(listed, list) else []
        session["blacklisted_skills"] = listed if skill_id in listed else [*listed, skill_id]
        context["session"] = session
        from ovos_bus_client.message import Message

        lang = message_lang(message, getattr(skill, "lang", None) or "en-US")
        bus.emit(Message(UTTERANCE_TOPIC, {"utterances": [text], "lang": lang}, context))
        LOG.info("handed a sentence back to the other skills")
        return True
    except Exception:  # noqa: BLE001 - silence is the safe failure
        LOG.warning("could not hand a sentence back", exc_info=True)
        return False
