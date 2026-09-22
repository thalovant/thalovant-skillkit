"""Observable selection behavior, including a speaker returning after another."""
from concurrent.futures import ThreadPoolExecutor
from random import Random

import pytest

from thalovant_skillkit.selection import ShuffleBag, ShuffleBagPool


def test_pool_switches_avoid_last_sound_and_respect_speaker_history():
    pools = ShuffleBagPool[str](rng=Random(2))
    assert pools.draw(["duck"]) == ["duck"]
    assert pools.draw(["duck", "bear"]) == ["bear"]
    assert pools.draw(["duck", "bear"], avoid="duck") == ["bear"]


def test_reloaded_dialog_replaces_old_choices_and_history_stays_bounded():
    pools = ShuffleBagPool[str](max_pools=2)
    assert pools.draw(["old"], key="dialog") == ["old"]
    assert pools.draw(["new"], key="dialog") == ["new"]
    pools.draw(["other"], key="other")
    pools.draw(["third"], key="third")
    assert len(pools._bags) == 2
    assert pools.draw(["new"], key="dialog") == ["new"]


def test_cycles_cover_every_item_without_boundary_repeats():
    bag = ShuffleBag(["duck", "bear", "robot"], rng=Random(4))
    draws = [bag.draw() for _ in range(300)]
    assert all(left != right for left, right in zip(draws, draws[1:], strict=False))
    assert all(set(draws[start:start + 3]) == {"duck", "bear", "robot"}
               for start in range(0, len(draws), 3))


def test_seeded_bags_are_reproducible_and_independent():
    first = ShuffleBag(range(8), rng=Random(17))
    second = ShuffleBag(range(8), rng=Random(17))
    expected = [first.draw() for _ in range(40)]
    assert [second.draw() for _ in range(40)] == expected


def test_explicit_avoid_uses_the_returning_speakers_last_choice():
    bag = ShuffleBag(["duck", "bear"], rng=Random(2))
    alice = bag.draw()
    bob = bag.draw()
    assert alice != bob
    assert bag.draw(avoid=alice) != alice


def test_avoid_can_skip_the_last_remaining_item_and_start_a_new_cycle():
    bag = ShuffleBag(["duck", "bear"], rng=Random(2))
    first = bag.draw()
    remaining = "bear" if first == "duck" else "duck"
    assert bag.draw(avoid=remaining) == first


def test_none_is_a_valid_item_and_an_explicit_avoid_value():
    bag = ShuffleBag([None, "duck"], rng=Random(3))
    assert all(bag.draw(avoid=None) == "duck" for _ in range(5))


def test_equal_items_are_kept_once_and_need_not_be_hashable():
    bag = ShuffleBag([[1], [1], [2]], rng=Random(3))
    first, second = bag.draw(), bag.draw()
    assert sorted([first, second]) == [[1], [2]]


def test_single_item_is_the_only_possible_result():
    bag = ShuffleBag(["duck", "duck"])
    assert bag.draw() == bag.draw(avoid="duck") == "duck"


def test_empty_input_is_rejected():
    with pytest.raises(ValueError, match="at least one"):
        ShuffleBag([])


def test_concurrent_draws_do_not_lose_items_in_a_cycle():
    bag = ShuffleBag(range(100), rng=Random(9))
    with ThreadPoolExecutor(max_workers=8) as executor:
        draws = list(executor.map(lambda _: bag.draw(), range(100)))
    assert sorted(draws) == list(range(100))
