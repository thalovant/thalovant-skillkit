"""Italian era/epoch extraction: "44 a.C.", "500 anni prima del presente".

The surface forms live in ``ovos_date_parser/locale/it/*.voc`` (loaded
through ovos-spec-tools by :func:`ovos_date_parser.eras_scan.
load_era_patterns`): a.C./avanti Cristo/avanti l'era volgare/a.e.v.,
d.C./dopo Cristo/era volgare/e.v. (the Treccani ``a.C.``/``d.C.``
convention plus its secular ``era volgare`` forms), B.P./anni prima del
presente, tempo unix, giorno giuliano, era olocenica/umana, anno mundi,
"nell'anno 12000", and BC-axis secolo/millennio ordinals.

This module contributes only the Italian spelled-number normaliser;
Italian needs no extra guard patterns.  ``era_year_ref.voc``
deliberately only carries "nell'anno"/"l'anno" (and their apostrophe-
stripped "nell anno"/"l anno" variants) rather than bare "nel", since a
bare "nel" would falsely claim ordinary phrasing like "nel 1996".
"""
from ovos_number_parser.numbers_it import IT

from ovos_date_parser.eras_scan import (EraPatterns, extract_era_date,
                                        load_era_patterns)

ERA_PATTERNS_IT: EraPatterns = load_era_patterns("it")


def extract_era_date_it(text: str):
    """Extract an era-qualified date from Italian text.

    Thin wrapper binding :data:`ERA_PATTERNS_IT` and the Italian
    spelled-number normaliser to the shared scanner — see
    :func:`ovos_date_parser.eras_scan.extract_era_date` for the contract.
    """
    return extract_era_date(text, ERA_PATTERNS_IT,
                            normalize=IT.numbers_to_digits)
