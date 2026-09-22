from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier

import pytest

from thalovant_skillkit.network import JsonServiceClient, RequestBudget


def test_nested_budgets_restore_on_exception_and_cannot_extend_a_turn():
    budget = RequestBudget(clock=lambda: 10)
    with budget.limit(2):
        with pytest.raises(RuntimeError), budget.limit(20):
            assert budget.deadline == 12
            raise RuntimeError()
        assert budget.deadline == 12
    assert budget.deadline is None


def test_two_speakers_do_not_share_deadlines():
    budget = RequestBudget(clock=lambda: 100)
    barrier = Barrier(2)

    def turn(seconds):
        with budget.limit(seconds):
            barrier.wait(timeout=5)
            assert budget.remaining() == seconds
        assert budget.deadline is None

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(turn, (2, 10)))


def test_size_limit_accepts_exact_body_and_rejects_truncation():
    budget = RequestBudget()
    assert budget.read(BytesIO(b"1234"), max_bytes=4, chunk_bytes=3) == b"1234"
    with pytest.raises(ValueError, match="byte limit"):
        budget.read(BytesIO(b"12345"), max_bytes=4, chunk_bytes=3)


def test_trickling_body_is_stopped_after_the_budget():
    now = [0]
    budget = RequestBudget(clock=lambda: now[0])

    class Trickle:
        def read(self, size):
            now[0] += 1
            return b"x"

    with budget.limit(2), pytest.raises(TimeoutError):
        budget.read(Trickle())


def test_exhausted_budget_does_not_call_or_disable_the_service():
    budget = RequestBudget(clock=lambda: 10)
    client = JsonServiceClient("demo", "1", budget=budget)
    budget.deadline = 9

    def unexpected(*args, **kwargs):
        pytest.fail("transport called after deadline")

    assert client.post("https://example.test", {}, opener=unexpected) is None
    budget.deadline = None
    assert client.post("https://example.test", {}, opener=lambda *a, **kw: BytesIO(b'{}')) == {}


def test_failure_cooldown_expires_and_does_not_disable_another_endpoint():
    now = [0]
    client = JsonServiceClient("demo", "1", clock=lambda: now[0], cooldown=5)
    calls = []

    def malformed(request, **kwargs):
        calls.append(request.full_url)
        return BytesIO(b'[]')

    assert client.post("https://example.test/a", {}, opener=malformed) is None
    assert client.post("https://example.test/a", {}, opener=malformed) is None
    assert len(calls) == 1
    assert client.post("https://example.test/b", {}, opener=lambda *a, **kw: BytesIO(b'{}')) == {}
    now[0] = 5
    assert client.post("https://example.test/a", {}, opener=lambda *a, **kw: BytesIO(b'{}')) == {}


def test_requests_have_identity_unique_ids_and_close_responses():
    client = JsonServiceClient("demo", "1")
    ids, bodies = [], []

    def answer(request, timeout):
        headers = {k.lower(): v for k, v in request.headers.items()}
        assert headers["x-thalovant-skill"] == "demo"
        assert headers["x-thalovant-skill-version"] == "1"
        assert 0 < timeout <= 2.4
        ids.append(headers["x-request-id"])
        body = BytesIO(b'{"answer":"yes"}')
        bodies.append(body)
        return body

    for _ in range(2):
        assert client.post("https://example.test", {}, opener=answer) == {"answer": "yes"}
    assert len(set(ids)) == 2
    assert all(body.closed for body in bodies)


def test_oversized_service_response_is_closed_and_cooldown_stays_bounded():
    client = JsonServiceClient("demo", "1", max_bytes=4)
    bodies = []

    def oversized(*args, **kwargs):
        body = BytesIO(b'{"too":"large"}')
        bodies.append(body)
        return body

    for index in range(140):
        assert client.post(f"https://example.test/{index}", {}, opener=oversized) is None
    assert all(body.closed for body in bodies)
    assert len(client._failures) == 128
