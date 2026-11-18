# Frequently asked questions

## Why can a declined play request finish without an answer?

A broad music intent may decline a request that belongs to another skill. `ThalovantSkill.pass_on` calls `handback.hand_back` to replay the request with the music skill excluded for that turn. The receiver must listen on the topic being emitted. The 0.38.1 compatibility fix in [handback.py](thalovant_skillkit/handback.py) uses the loaded core's topic instead of relying on legacy bus translation. The 0.38.2 correction also reverses the matched intent’s reply envelope into a new request envelope, so the next dispatch’s reply targets the original caller. Request IDs and the explicit copied session remain intact. [Regression tests](test/test_handback.py) cover modern and old cores and standalone skill processes.

## Does this disable the music skill or change routing priority?

No. The existing access check and the copied session's per-turn blacklist remain the same. No global skill setting or intent order changes.
