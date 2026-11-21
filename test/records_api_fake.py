"""thalovant-api's records store (`/v1/runtime/records`), as a `requests.Session` stand-in.

It answers as the API does (app/routes/runtime_records.py in thalovant-api): GET
returns the store's records, oldest first, for one owner or every served owner and
`_unowned`; POST makes the puts, then the deletes, `only_new` puts only where there
is none, and a change for an owner the runtime does not serve is skipped. It also
records every request, so a test can read what the kit sent (and never a token in a
URL).
"""

from __future__ import annotations

import json
import threading
from urllib.parse import unquote, urlsplit

TOKEN = "tsi_" + "t" * 43
URL = "http://thalovant-api.thalovant.svc.cluster.local/v1/runtime/records"


class Response:
    def __init__(self, status_code: int, payload=None, headers=None, text: str | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self._text = text

    def json(self):
        if self._text is not None:
            raise ValueError("not JSON")
        return self._payload


class FakeRecordsApi:
    """One API, shared by every store (pod) given a session from `session()`."""

    def __init__(self, *, served: set[str] | None = None, token: str = TOKEN):
        self.stores: dict[tuple[str, str], dict[tuple[str, str], str]] = {}
        self.served = served  # None: every owner key is served
        self.token = token
        self.requests: list[dict] = []
        self.answer: Response | None = None  # set to answer every request with this
        self.fail: Exception | None = None  # set to raise this instead of answering
        self._lock = threading.Lock()

    def session(self) -> FakeSession:
        return FakeSession(self)

    def _serves(self, owner: str) -> bool:
        return owner == "_unowned" or self.served is None or owner in self.served

    def handle(self, method, url, *, params=None, json=None, headers=None, timeout=None,
               allow_redirects=True):
        with self._lock:
            self.requests.append({"method": method, "url": url, "params": params, "json": json,
                                  "headers": dict(headers or {}), "timeout": timeout,
                                  "allow_redirects": allow_redirects})
            if self.fail is not None:
                raise self.fail
            if self.answer is not None:
                return self.answer
            if (headers or {}).get("Authorization") != f"Bearer {self.token}":
                return Response(401, {"detail": "A runtime token is required."})
            path = urlsplit(url).path
            prefix = urlsplit(URL).path + "/"
            if not path.startswith(prefix):
                return Response(404, {"detail": "Not found"})
            scope, key = (unquote(part) for part in path[len(prefix):].split("/"))
            store = self.stores.setdefault((scope, key), {})
            if method == "GET":
                owner = (params or {}).get("owner")
                wanted = (lambda ok: ok == owner and self._serves(ok)) if owner else self._serves
                return Response(200, {"skill_id": key, "records": [
                    {"owner": ok, "id": rid, "body": body}
                    for (ok, rid), body in store.items() if wanted(ok)
                ]})
            body = json or {}
            put = deleted = skipped = 0
            for item in body.get("puts", []):
                slot = (item["owner"], item["id"])
                if not self._serves(slot[0]):
                    skipped += 1
                    continue
                if body.get("only_new") and slot in store:
                    continue
                store[slot] = item["body"]
                put += 1
            for item in body.get("deletes", []):
                slot = (item["owner"], item["id"])
                if not self._serves(slot[0]):
                    skipped += 1
                    continue
                if store.pop(slot, None) is not None:
                    deleted += 1
            return Response(200, {"put": put, "deleted": deleted, "skipped": skipped})


class FakeSession:
    def __init__(self, api: FakeRecordsApi):
        self.api = api

    def request(self, method, url, **kwargs):
        return self.api.handle(method, url, **kwargs)


def records_sent(api: FakeRecordsApi) -> str:
    """Everything the kit sent, as one text, to look for what must not be there."""
    return json.dumps(api.requests, default=str)
