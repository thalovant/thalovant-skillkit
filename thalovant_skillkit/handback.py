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
entry is forgotten. What tells "the sentence coming back" from "the same words said again" is that
the copy this module sent leaves the skill out of its session, and a sentence somebody says again
does not: said again, it is handed back again (the other skill answered the first one, so nothing
ever spent the entry, and dropping the second would be silence for a sentence another skill
answers). That sign only narrows what the memory already decided: without an entry in the memory
it buys nothing, and a pipeline that reads the blacklist never brings such a message here at all.
A loop whose messages lose their session is ended by a count instead: the same sentence is handed
back `rounds` times at most while its entry lives. The entry expires after a few seconds.
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

    `ttl` is how long an entry lives (seconds, counted from the first hand-back); `limit` is how
    many entries are kept at most (the oldest goes first); `rounds` is how many times the same
    sentence is handed back while its entry lives when nothing shows it is the same turn coming
    round (somebody saying the same words again). Thread-safe: handlers run on a pool.
    """

    def __init__(
        self, ttl: float = 5.0, limit: int = 512, clock: Any = monotonic, rounds: int = 3
    ):
        self.ttl = float(ttl)
        self.limit = max(1, int(limit))
        self.rounds = max(1, int(rounds))
        self._clock = clock
        #: key -> (when it was first handed back, how many times since)
        self._entries: OrderedDict[tuple, tuple[float, int]] = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def admit(self, key: tuple, returning: bool = False) -> bool:
        """Whether the sentence `key` names may be handed back now; a yes is remembered.

        The first time: yes. With an entry already there, `returning` decides. True (the message
        already leaves the skill out of its session) means this is the copy that was handed back
        coming round again: no, and the entry is forgotten, so a loop ends after one round. False
        means the same words said again: yes, `rounds` times at most while the entry lives, then
        no until it expires (the bound for a loop whose messages lose their session).
        """
        now = self._clock()
        with self._lock:
            for old in [k for k, (at, _) in self._entries.items() if now - at >= self.ttl]:
                del self._entries[old]
            entry = self._entries.get(key)
            if entry is None:
                self._entries[key] = (now, 1)
                while len(self._entries) > self.limit:
                    self._entries.popitem(last=False)
                return True
            if returning:
                del self._entries[key]
                return False
            if entry[1] >= self.rounds:
                return False
            self._entries[key] = (entry[0], entry[1] + 1)
            return True

    def first_time(self, key: tuple) -> bool:
        """`admit(key, returning=True)`, for a caller with no message to read: yes the first time,
        no the second (which forgets the entry), yes again after that."""
        return self.admit(key, returning=True)

    def release(self, key: tuple) -> None:
        """Take back one `admit` whose sentence was never sent (the bus refused it), so the next
        try is not mistaken for that sentence coming back."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            if entry[1] <= 1:
                del self._entries[key]
            else:
                self._entries[key] = (entry[0], entry[1] - 1)


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
    (`blacklisted_skills`), so the other skills answer it. Nothing is said. The copy this skill
    handed back a moment ago is not handed back twice when it comes round again (`memory`, kept in
    the process: no marker is written into the message, and no key a client sends buys silence),
    while the same words said again are handed back again. Never raises: a failure here is
    silence, which is the safe way to fail for a skill that was about to refuse; a sentence the
    bus refused is not remembered as handed back.
    """
    try:
        skill_id = getattr(skill, "skill_id", None)
        text = utterance(message)
        bus = bus_of(skill)
        if not skill_id or not text or bus is None:
            return False
        context = dict(context_of(message))
        session = context.get("session")
        session = dict(session) if isinstance(session, dict) else {}
        listed = session.get("blacklisted_skills")
        listed = [s for s in listed if isinstance(s, str)] if isinstance(listed, list) else []
        if memory is None:
            memory = skill.__dict__.setdefault("_hand_back_memory", HandBackMemory())
        key = _key(skill_id, context, text)
        if not memory.admit(key, returning=skill_id in listed):
            LOG.info("a sentence handed back a moment ago came back; it was dropped")
            return False
    except Exception:  # noqa: BLE001 - silence is the safe failure
        LOG.warning("could not hand a sentence back", exc_info=True)
        return False
    try:
        session["blacklisted_skills"] = listed if skill_id in listed else [*listed, skill_id]
        context["session"] = session
        from ovos_bus_client.message import Message

        lang = message_lang(message, getattr(skill, "lang", None) or "en-US")
        bus.emit(Message(UTTERANCE_TOPIC, {"utterances": [text], "lang": lang}, context))
        LOG.info("handed a sentence back to the other skills")
        return True
    except Exception:  # noqa: BLE001 - silence is the safe failure
        memory.release(key)  # nothing was sent: the next try is not that sentence coming back
        LOG.warning("could not hand a sentence back", exc_info=True)
        return False
