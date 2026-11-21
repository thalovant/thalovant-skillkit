# Frequently asked questions

## Where does `RecordStore` keep a person's records on a private skill set?

On a tenant's runtime (a private skill set, where Skill Studio skills run), the platform gives no login to the hub Redis that every hub shares: that runtime runs code the tenant chose. thalovant-api renders `THALOVANT_RECORDS_API_URL` for it, and from 0.39.0 the store keeps its records through the API (`ApiBackend` in [records.py](thalovant_skillkit/records.py)) with the runtime's token from its netrc, when the settings and the environment name no Redis and no PostgreSQL. The API decides who may touch what from the token: its own workspace, the Skill Studio skills attached to its own skill set, the connections its hubs serve and everyone's bucket. A read that fails answers None and the skill keeps its settings, as before. The contract is in [docs/records.md](docs/records.md#tenant-runtimes-the-records-api); the tests are [test_records_api.py](test/test_records_api.py), and the whole record suite of [test_records.py](test/test_records.py) also runs on the API backend against a stand-in of the API.

## Why can a declined play request finish without an answer?

A broad music intent may decline a request that belongs to another skill. `ThalovantSkill.pass_on` calls `handback.hand_back` to replay the request with the music skill excluded for that turn. The receiver must listen on the topic being emitted. The 0.38.1 compatibility fix in [handback.py](thalovant_skillkit/handback.py) uses the loaded core's topic instead of relying on legacy bus translation. The 0.38.2 correction also reverses the matched intent’s reply envelope into a new request envelope, so the next dispatch’s reply targets the original caller. Request IDs and the explicit copied session remain intact. [Regression tests](test/test_handback.py) cover modern and old cores and standalone skill processes.

## Does this disable the music skill or change routing priority?

No. The existing access check and the copied session's per-turn blacklist remain the same. No global skill setting or intent order changes.
