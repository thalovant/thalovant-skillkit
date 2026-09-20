"""French era/epoch extraction: "44 av. J.-C.", "500 ans avant le présent".

The surface forms live in ``ovos_date_parser/locale/fr/*.voc`` (loaded
through ovos-spec-tools by :func:`ovos_date_parser.eras_scan.
load_era_patterns`): av. J.-C./avant Jésus-Christ/avant notre ère,
ap. J.-C./après Jésus-Christ/de notre ère (the conventional French
``av.``/``ap. J.-C.`` abbreviations plus their spelled-out and secular
forms), B.P./ans avant le présent (the radiocarbon *avant le présent*),
temps unix, jour julien, ère holocène/humaine, anno mundi, "en l'an
12000", and BC-axis siècle/millénaire ordinals.

This module contributes only the French spelled-number normaliser.  One
genuinely non-translatable guard is needed: :func:`FR.numbers_to_digits
<ovos_number_parser.numbers_fr.FR.numbers_to_digits>` unconditionally
splits every hyphen in the input into ``" - "`` while tokenising for
compound numbers (a library quirk unrelated to era phrasing — it fires
even when no number word is present), so "Jésus-Christ" becomes
"Jésus - Christ" after normalisation.  Rather than special-case the
scanner, ``era_bc_suffix.voc``/``era_ad_suffix.voc`` simply carry both
the natural and post-split spellings as translatable alternates.
"""
from ovos_number_parser.numbers_fr import FR

from ovos_date_parser.eras_scan import (EraPatterns, extract_era_date,
                                        load_era_patterns)

ERA_PATTERNS_FR: EraPatterns = load_era_patterns("fr")


def extract_era_date_fr(text: str):
    """Extract an era-qualified date from French text.

    Thin wrapper binding :data:`ERA_PATTERNS_FR` and the French
    spelled-number normaliser to the shared scanner — see
    :func:`ovos_date_parser.eras_scan.extract_era_date` for the contract.
    """
    return extract_era_date(text, ERA_PATTERNS_FR,
                            normalize=FR.numbers_to_digits)
