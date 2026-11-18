# Suggestions

## Exercise handback against a live core before release

Problem: an emitted-message unit test does not prove that the actual core consumed the replay. The strict-core regression now checks delivery, but a deployed bus can add protocol translation or filtering.

Next step: validate a denied generic music request followed by the News reply on the intended runtime, then repeat a valid music request to verify its route remains intact. Keep the shared library change scoped to that runtime until verified. Expected impact: catches compatibility failures without changing global intent priority. See [handback.py](thalovant_skillkit/handback.py) and [test_handback.py](test/test_handback.py).
