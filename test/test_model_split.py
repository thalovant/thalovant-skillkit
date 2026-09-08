"""The training split: every label with two or more sentences is judged on
held-out ones, a single-sentence label is never held out, and the split is
the same on every run."""
import pytest

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


def test_every_label_keeps_a_training_row_and_gives_one_up():
    rows = [Row("a1", "s:a", "en-US"), Row("a2", "s:a", "en-US")]
    train, test = split(rows, test_size=0.2)
    assert len(train) == 1 and len(test) == 1
    train, test = split(rows * 5, test_size=0.99)
    assert len(train) == 1 and len(test) == 9
    assert split(rows, test_size=0)[1] == []


def test_split_rejects_a_share_outside_the_unit_interval():
    for bad in (1, 1.5, -0.1):
        with pytest.raises(ValueError, match="test_size"):
            split([Row("a", "s:a", "en-US")], test_size=bad)
