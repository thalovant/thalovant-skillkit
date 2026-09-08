"""Folding, in the four shapes the skills actually needed."""
from __future__ import annotations

from thalovant_skillkit import fold, fold_spaces, fold_tight, fold_words, strip_accents


def test_the_default_fold_is_case_and_accent_free():
    assert fold("Café") == "cafe"
    assert fold("ÉTÉ") == "ete"
    assert fold("") == ""
    assert fold(None) == ""


def test_hyphens_and_typographic_apostrophes_become_the_spoken_form():
    """The showroom types French with hyphens ("Donne-moi") and voice never
    sends them, so one vocabulary line has to match both."""
    assert fold_spaces("Donne-moi") == "donne moi"
    assert fold_spaces("s’il te plaît") == "s'il te plait"
    assert fold_spaces("a   b") == "a b"


def test_punctuation_can_be_dropped_entirely():
    assert fold_words("What's up!") == "what s up"


def test_identifiers_fold_to_letters_and_digits():
    """For comparing a typed city against its accented spelling, not for
    matching what someone said."""
    assert fold_tight("Test-Value") == "testvalue"
    assert fold_tight("Montréal") == "montreal"


def test_accents_can_be_stripped_without_touching_case():
    assert strip_accents("Café") == "Cafe"
