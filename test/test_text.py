"""Folding, in the four shapes the skills actually needed."""
from __future__ import annotations

import unicodedata

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


# -- marks that spell a letter ------------------------------------------------
#
# Folding used to drop every combining mark. In Hindi and Thai the mark is the
# spelling, and `fold_words` then cut each Hindi word at its vowel signs, so no
# Hindi topic, vocabulary word or literal intent line ever matched as a word.


def test_hindi_keeps_its_vowel_signs_and_virama():
    assert fold("खेल समाचार") == "खेल समाचार"
    assert fold("क्रिकेट") == "क्रिकेट"  # was "करिकेट": the virama is a letter here
    assert fold_words("खेल समाचार") == "खेल समाचार"  # was "ख ल सम च र"
    assert fold_words("तकनीक की खबरें") == "तकनीक की खबरें"  # was "तकन क क खबर"
    assert fold_words("विज्ञान") == "विज्ञान"  # was "व जञ न"


def test_hindi_words_stay_words():
    """One Hindi word folds to one word, so splitting on spaces finds it."""
    for word in ("खेल", "समाचार", "विज्ञान", "प्रौद्योगिकी", "कृत्रिम", "बुद्धिमत्ता"):
        assert fold_words(word).split() == [fold_words(word)], word


def test_the_nukta_still_folds_because_hindi_writes_it_both_ways():
    """The fleet lists "दरवाज़ा" and "दरवाजा" side by side: one word."""
    assert fold("दरवाज़ा") == fold("दरवाजा")
    assert fold("तेज़") == fold("तेज")
    assert fold_words("क़ानून") == fold_words("कानून")  # precomposed U+0958 too


def test_thai_tone_marks_tell_words_apart():
    assert fold("ข่าวกีฬา") == "ข่าวกีฬา"
    assert fold("โป้") != fold("โป๊")  # two words the old fold made one
    assert fold_words("ข่าวกีฬา") == "ข่าวกีฬา"  # was "ขาวก ฬา"


def test_kana_voicing_is_part_of_the_letter():
    assert fold("何かある") != fold("何がある")
    assert fold("が") != fold("か")


def test_bengali_tamil_and_other_brahmic_scripts_keep_their_marks():
    for text in ("খেলার খবর", "விளையாட்டு", "ਖੇਡ", "ರಾಜಕೀಯ", "ကစား", "កីឡា"):
        # Unchanged but for canonical decomposition (Kannada "ೀ" is "ಿ" + "ೕ").
        assert fold_words(text) == unicodedata.normalize("NFD", text), text


def test_accents_still_fold_where_they_are_accents():
    """Latin, Greek and Cyrillic diacritics, Arabic harakat and Hebrew niqqud
    go exactly as before."""
    assert fold("Tiếng Việt") == "tieng viet"
    assert fold("Ελληνικά") == "ελληνικα"
    assert fold("йод") == "иод"
    assert fold("مَرْحَبًا") == "مرحبا"
    assert fold("שָׁלוֹם") == "שלום"
    assert fold_words("Ça va, l’été ?") == "ca va l ete"


def test_a_word_character_includes_a_kept_mark():
    import re

    from thalovant_skillkit.text import WORD_CHAR

    assert re.fullmatch(rf"{WORD_CHAR}+", "समाचार")
    assert re.fullmatch(rf"{WORD_CHAR}+", "ข่าว")
    assert not re.fullmatch(WORD_CHAR, "।")  # the danda is punctuation
    assert not re.fullmatch(WORD_CHAR, "́")  # an accent is not a letter
