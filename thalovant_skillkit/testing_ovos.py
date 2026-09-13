"""Optional integration helpers using the real OVOS testing components.

Install ``thalovant-skillkit[testing]`` for the supported OVOScope stack. This
module imports no OVOS components until a helper needs them: enter
``isolated_xdg()`` before importing skills, normally in ``pytest_configure``.
The existing ``testing.FakeBus`` remains a lightweight recording double.

These context managers own only the resources they create. They can be used
with pytest's ``yield`` fixtures or unittest's ``enterClassContext``/ExitStack;
they do not register a pytest plugin or replace upstream bus/scheduler logic.
"""
from __future__ import annotations

import gc
import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import PropertyMock, patch

XDG_VARIABLES = ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME")


@contextmanager
def isolated_xdg(root: str | Path | None = None) -> Iterator[Path]:
    """Give a test process private XDG paths and restore every original value.

    Enter before importing OVOS: some upstream modules cache XDG locations at
    import time. Each xdist worker gets its own temporary tree by default.
    An explicit root belongs to the caller and is retained after exit. Like
    other environment patches, scopes must not overlap across threads.
    """
    with ExitStack() as cleanup:
        if root is None:
            root = cleanup.enter_context(TemporaryDirectory(prefix="skillkit-ovos-"))
        directory = Path(root).resolve()
        previous = {name: os.environ.get(name) for name in XDG_VARIABLES}
        try:
            for name in XDG_VARIABLES:
                path = directory / name.lower()
                path.mkdir(parents=True, exist_ok=True)
                os.environ[name] = str(path)
            yield directory
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


@dataclass
class SkillHarness:
    """A live skill, upstream dispatching FakeBus, and optional SCHEDULER-1 service."""

    skill: Any
    bus: Any
    scheduler: Any | None


@contextmanager
def skill_harness(
    skill_type: type,
    *,
    skill_id: str,
    settings: dict | None = None,
    scheduler: bool = True,
    scheduler_autostart: bool = False,
    bus_options: dict | None = None,
    **skill_options: Any,
) -> Iterator[SkillHarness]:
    """Initialize a skill with isolated settings and deterministic scheduler ticks.

    Uses ``ovos_utils.fakebus.FakeBus`` and the bus client's public
    ``ScheduledEventService``. The default service answers scheduler requests
    without starting a timer thread; tests can drive its public ``tick()``.
    Shut down the skill before the scheduler so its cancellation requests can
    finish. The temporary settings-path override is scoped to this context;
    tests constructing the same class concurrently should use separate workers.
    """
    with ExitStack() as cleanup:
        directory = cleanup.enter_context(isolated_xdg())
        from ovos_utils.fakebus import FakeBus

        cleanup.enter_context(patch.object(
            skill_type, "settings_path", new_callable=PropertyMock,
            return_value=str(directory / "settings.json"),
        ))
        bus = FakeBus(**(bus_options or {}))
        cleanup.callback(bus.close)
        service = None
        if scheduler:
            from ovos_bus_client.util.scheduled_events.service import ScheduledEventService

            service = ScheduledEventService(
                bus, store_path=str(directory / "schedule.json"),
                autostart=scheduler_autostart,
            )
            cleanup.callback(service.shutdown)
        skill = skill_type(bus=bus, skill_id=skill_id, settings=settings, **skill_options)
        cleanup.callback(skill.default_shutdown)
        yield SkillHarness(skill, bus, service)


@contextmanager
def managed_minicroft(skill_ids: list[str] | str, **options: Any) -> Iterator[Any]:
    """Start upstream MiniCroft and stop it even when a test raises.

    Pipeline selection, configuration isolation, training, and readiness remain
    upstream behavior. Enter ``isolated_xdg`` before importing the tested skill.
    """
    from ovoscope import get_minicroft

    croft = get_minicroft(skill_ids, **options)
    try:
        yield croft
    finally:
        croft.stop()


@dataclass(frozen=True)
class CapturedAudio:
    """One queued or immediate sound, decoded without opening or playing its URI."""

    message: Any
    uri: str | None
    binary: bytes | None
    extension: str | None


def _session_carrier(message: Any) -> dict:
    context = getattr(message, "context", None)
    carrier = context.get("session") if isinstance(context, dict) else None
    return carrier if isinstance(carrier, dict) else {}


def _audio_messages(messages: list[Any], canonical: str, legacy: str) -> list[Any]:
    """Prefer a canonical topic over its legacy mirror, as ``spoken`` does."""
    selected = canonical if any(m.msg_type == canonical for m in messages) else legacy
    return [m for m in messages if m.msg_type == selected]


@dataclass
class CapturedTurn:
    """Completed bus traffic and the originating session's newest state."""

    messages: list[Any]
    session: Any | None

    def of_type(self, topic: str) -> list[Any]:
        return [message for message in self.messages if message.msg_type == topic]

    @property
    def spoken(self) -> list[str]:
        """Canonical speech, falling back to legacy-only stacks without doubling twins."""
        messages = self.of_type("ovos.utterance.speak") or self.of_type("speak")
        return [str(message.data.get("utterance", "")) for message in messages]

    def for_session(self, session_id: str) -> CapturedTurn:
        """Select only messages carrying this explicit session ID.

        Unscoped or malformed carriers are excluded, never assigned to a room.
        The returned view has its own list but shares the original messages.
        Existing full-capture ``spoken`` and ``of_type`` behavior is unchanged.
        """
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a nonempty string")
        messages = [m for m in self.messages
                    if _session_carrier(m).get("session_id") == session_id]
        session = self.session if getattr(self.session, "session_id", None) == session_id else None
        if messages:
            from ovos_bus_client.session import Session

            session = Session.deserialize(_session_carrier(messages[-1]))
        return CapturedTurn(messages, session)

    @property
    def audio(self) -> list[CapturedAudio]:
        """Queued and immediate sound requests, in captured order.

        Canonical topics take precedence over their legacy mirrors per operation.
        Remote ``binary_data`` is decoded from hex and keeps its declared
        ``audio_ext``. URI requests are reported without reading a file or URL.
        Malformed or ambiguous payloads raise ``AssertionError`` for the test.
        """
        selected = _audio_messages(self.messages, "ovos.audio.queue", "mycroft.audio.queue")
        selected += _audio_messages(
            self.messages, "ovos.audio.play_sound", "mycroft.audio.play_sound",
        )
        selected_ids = {id(message) for message in selected}
        result = []
        for message in self.messages:
            if id(message) not in selected_ids:
                continue
            data = getattr(message, "data", None)
            if not isinstance(data, dict):
                raise AssertionError(f"{message.msg_type}: audio data must be a dictionary")
            if ("uri" in data) == ("binary_data" in data):
                raise AssertionError(f"{message.msg_type}: expected either uri or binary_data")
            if "uri" in data:
                if not isinstance(data["uri"], str) or not data["uri"]:
                    raise AssertionError(f"{message.msg_type}: uri must be a nonempty string")
                result.append(CapturedAudio(message, data["uri"], None, None))
                continue
            binary, extension = data["binary_data"], data.get("audio_ext")
            if not isinstance(binary, str) or not binary:
                raise AssertionError(f"{message.msg_type}: binary_data must be nonempty hex text")
            if not isinstance(extension, str) or not extension:
                raise AssertionError(f"{message.msg_type}: audio_ext must be a nonempty string")
            try:
                decoded = bytes.fromhex(binary)
            except ValueError as error:
                raise AssertionError(
                    f"{message.msg_type}: invalid hexadecimal binary_data",
                ) from error
            if not decoded:
                raise AssertionError(f"{message.msg_type}: binary_data contains no audio bytes")
            result.append(CapturedAudio(message, None, decoded, extension))
        return result

    @property
    def audio_stops(self) -> list[Any]:
        """Audio Stop requests, preferring the canonical topic over legacy mirrors."""
        return _audio_messages(self.messages, "ovos.audio.stop", "mycroft.audio.speech.stop")


def capture_turn(
    croft: Any, source: Any, *, timeout: float = 30, **capture_options: Any,
) -> CapturedTurn:
    """Capture one upstream lifecycle, fail on timeout, and always detach listeners.

    ``capture_options`` go directly to OVOScope's ``CaptureSession`` (for example
    ``eof_msgs`` or ``terminal_signals``). This checks completion, not whether
    the right intent or reply occurred; callers retain those assertions.
    Session updates from other concurrent speakers are never propagated into
    the originating speaker's next turn.
    """
    from ovos_bus_client.session import Session
    from ovoscope import CaptureSession

    capture = CaptureSession(minicroft=croft, **capture_options)
    try:
        completed = capture.capture(source, timeout=timeout)
    finally:
        messages = capture.finish()
    if not completed:
        topics = [message.msg_type for message in messages]
        raise AssertionError(
            f"OVOS capture timed out after {timeout}s for {source.msg_type}: {topics}"
        )
    carrier = (source.context or {}).get("session")
    session_id = carrier.get("session_id") if isinstance(carrier, dict) else None
    if session_id:
        for received in reversed(messages):
            candidate = (received.context or {}).get("session")
            if isinstance(candidate, dict) and candidate.get("session_id") == session_id:
                carrier = candidate
                break
        session = Session.deserialize(carrier)
    else:
        session = None
    return CapturedTurn(messages, session)


@contextmanager
def deferred_capture_gc() -> Iterator[None]:
    """Scope the known OVOScope 1.8.5a1/pyee 12.1.1 finalizer workaround.

    On that tested combination, cyclic GC can finalize CaptureSession while
    pyee holds its non-reentrant listener lock. The finalizer removes listeners
    and deadlocks. Collect between tests, outside bus callbacks, and after all
    MiniCroft owners have stopped. Other versions retain their normal GC policy;
    remove this workaround when upstream capture finalization is fixed.
    """
    try:
        affected = version("ovoscope") == "1.8.5a1" and version("pyee") == "12.1.1"
    except PackageNotFoundError:
        affected = False
    if not affected:
        yield
        return
    enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        try:
            gc.collect()
        finally:
            if enabled:
                gc.enable()
