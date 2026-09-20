"""English calendar-scoped ordinal and season extraction.

The surface forms live in ``ovos_date_parser/locale/en/*.voc`` (unit
names, month names, season names, markers) and are composed by the
shared grammar in :mod:`ovos_date_parser.scoped_scan`; this module only
binds the English spelled-number normaliser.

Recognised phrasing: "the 21st century", "the 3rd millennium", "the 3rd
week of june", "the last day of february 2024", "the 100th day of the
year", "the first decade of the 21st century", "summer of 1969",
"next winter", "last spring", "this autumn"/"this fall".
"""
from ovos_number_parser.numbers_en import numbers_to_digits_en

from ovos_date_parser.ranges import Hemisphere
from ovos_date_parser.scoped_scan import (ScopedVocabulary,
                                          extract_scoped_date,
                                          load_scoped_vocabulary)

SCOPED_VOCAB_EN: ScopedVocabulary = load_scoped_vocabulary("en")


def extract_scoped_date_en(text: str, ref_date=None,
                           hemisphere: Hemisphere = Hemisphere.NORTH):
    """Extract a scoped ordinal or season from English text.

    Thin wrapper binding :data:`SCOPED_VOCAB_EN` and the English
    spelled-number normaliser to the shared scanner — see
    :func:`ovos_date_parser.scoped_scan.extract_scoped_date`.
    """
    return extract_scoped_date(
        numbers_to_digits_en(text, ordinals=True), SCOPED_VOCAB_EN,
        ref_date=ref_date, hemisphere=hemisphere)
