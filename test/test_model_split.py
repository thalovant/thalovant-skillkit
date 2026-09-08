"""The training split: every label with two or more sentences is judged on
held-out ones, a single-sentence label is never held out, and the split is
the same on every run."""
from thalovant_skillkit.model import Row, split


def test_split_holds_out_a_share_per_label_and_is_deterministic():
    rows = [Row(f"a{i}", "s:a", "en-US") for i in range(10)]
    rows += [Row(f"b{i}", "s:b", "en-US") for i in range(5)]
    rows += [Row("only", "s:c", "en-US")]
    train, test = split(rows, test_size=0.2)
    assert len(test) == 2 + 1  # 20% of ten, 20% of five (rounded), none of one
    assert all(r.label != "s:c" for r in test)
    assert next(r for r in train if r.label == "s:c").text == "only"
    assert {r.text for r in train} | {r.text for r in test} == {r.text for r in rows}
    assert split(rows, test_size=0.2) == (train, test)
