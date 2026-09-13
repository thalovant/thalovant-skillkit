"""Wait for one caller's reply on a shared OVOS message topic."""
from __future__ import annotations

import math
from collections.abc import Callable
from threading import Event, Lock
from time import monotonic
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ovos_bus_client.message import Message


def wait_for_response(
    bus,
    message: Message,
    reply_type: str,
    *,
    matches: Callable[[Message], bool],
    timeout: float = 5.0,
) -> Message | None:
    """Emit a request and accept only a matching reply within ``timeout``.

    Unlike the bus's topic-only waiter, concurrent callers cannot consume each
    other's reply when ``matches`` checks a unique identifier echoed by the
    provider. Subscribe before emitting, so a synchronous reply is not lost.
    The listener is removed after success, timeout, or failure. Exceptions from
    the predicate are re-raised in the calling thread.

    ``timeout`` must be positive and finite. It includes time spent emitting,
    though this helper cannot interrupt a bus whose ``emit`` itself blocks.
    ``matches`` must be cheap and must not perform I/O. The provider must echo
    the correlation field: inventing an ID only on the request is insufficient.
    The caller owns context propagation and response payload validation.
    """
    timeout = float(timeout)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")

    done = Event()
    lock = Lock()
    deadline = monotonic() + timeout
    result = None
    failure = None

    def receive(response):
        nonlocal result, failure
        with lock:
            if done.is_set() or monotonic() >= deadline:
                return
            try:
                if not matches(response):
                    return
                result = response
            except Exception as error:
                failure = error
            done.set()

    bus.on(reply_type, receive)
    try:
        bus.emit(message)
        done.wait(max(0.0, deadline - monotonic()))
        with lock:
            if failure is not None:
                raise failure
            return result
    finally:
        bus.remove(reply_type, receive)
