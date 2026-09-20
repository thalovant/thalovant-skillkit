"""English era/epoch extraction: "44 BC", "2000 years before present".

The surface forms live in ``ovos_date_parser/locale/en/*.voc`` (loaded
through ovos-spec-tools by :func:`ovos_date_parser.eras_scan.
load_era_patterns`); this module contributes only the English
spelled-number normaliser and the one guard that is not a translation:

* bare ``HE`` (Holocene/Human Era, as in "12025 HE") collides with the
  English pronoun, so it only counts with a 5+ digit year — every
  Holocene year for a CE date is >= 10001.  Smaller counts need the era
  spelled out ("holocene era 1"), which the ``.voc`` forms cover.

Other era words that double as ordinary English ("ad", "ce", "am") are
safe without special guards because the shared scanner only matches era
forms immediately adjacent to a number, mirroring the permissive-parse-
then-validate stance used across the parser libs.
"""
import re

from ovos_number_parser.numbers_en import numbers_to_digits_en

from ovos_date_parser.eras_scan import (EraPatterns, extract_era_date,
                                        load_era_patterns)

ERA_PATTERNS_EN: EraPatterns = load_era_patterns("en") + [
    ("holocene",
     re.compile(r"(?<![\w.])(\d{5,})\s+he(?=\W|$)", re.IGNORECASE)),
]


def extract_era_date_en(text: str):
    """Extract an era-qualified date from English text.

    Thin wrapper binding :data:`ERA_PATTERNS_EN` and the English
    spelled-number normaliser to the shared scanner — see
    :func:`ovos_date_parser.eras_scan.extract_era_date` for the contract.
    """
    return extract_era_date(
        text, ERA_PATTERNS_EN,
        normalize=lambda s: numbers_to_digits_en(s, ordinals=True))
