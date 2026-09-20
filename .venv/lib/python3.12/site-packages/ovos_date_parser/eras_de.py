"""German era/epoch extraction: "44 v. Chr.", "500 Jahre vor heute".

The surface forms live in ``ovos_date_parser/locale/de/*.voc`` (loaded
through ovos-spec-tools by :func:`ovos_date_parser.eras_scan.
load_era_patterns`): v. Chr./vor Christi Geburt/vor unserer Zeitrechnung,
n. Chr./nach Christi Geburt/unserer Zeitrechnung (the Duden
``v. Chr.``/``n. Chr.`` convention plus its secular ``Zeitrechnung``
forms), B.P./Jahre vor heute, Unixzeit, julianischer Tag, Holozän-Ära/
Menschheitsära, Anno Mundi, "im Jahr 12000", and BC-axis Jahrhundert/
Jahrtausend ordinals.

This module contributes only the German spelled-number normaliser.
``ordinal_suffixes.voc`` carries a single line, a literal dot, so
German's ordinal-by-punctuation convention ("3. Jahrhundert") composes
with the shared scanner's ``NUM (?:suffix)?`` grammar unchanged.

``era_year_ref.voc`` includes "im Jahr", which also feeds the deep-
future bare-year fallback ("im Jahr 12000"); representable years such
as "im Jahr 1996" still fall through to the ordinary scanner because
:func:`ovos_date_parser.eras_scan.extract_era_date` only claims
``__bare_year__`` matches outside the ``datetime`` range — verified in
``test/test_eras_de.py``.
"""
from ovos_number_parser.numbers_de import numbers_to_digits_de

from ovos_date_parser.eras_scan import (EraPatterns, extract_era_date,
                                        load_era_patterns)

ERA_PATTERNS_DE: EraPatterns = load_era_patterns("de")


def extract_era_date_de(text: str):
    """Extract an era-qualified date from German text.

    Thin wrapper binding :data:`ERA_PATTERNS_DE` and the German
    spelled-number normaliser to the shared scanner — see
    :func:`ovos_date_parser.eras_scan.extract_era_date` for the contract.

    German has no non-deprecated ``RomanceNumberExtractor``-style class
    (unlike pt/es/fr/it); :func:`numbers_to_digits_de
    <ovos_number_parser.numbers_de.numbers_to_digits_de>` is the public,
    non-deprecated entry point used instead.
    """
    return extract_era_date(text, ERA_PATTERNS_DE,
                            normalize=numbers_to_digits_de)
