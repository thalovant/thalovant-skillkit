"""Spanish era/epoch extraction: "44 a. C.", "500 años antes del presente".

The surface forms live in ``ovos_date_parser/locale/es/*.voc`` (loaded
through ovos-spec-tools by :func:`ovos_date_parser.eras_scan.
load_era_patterns`): a.C./a. de C./a.e.c./antes de Cristo/antes de
nuestra era, d.C./d. de C./e.c./después de Cristo/de nuestra era (the
RAE/DPD ``a. C.``/``d. C.`` convention, also accepting the unspaced
abbreviations in everyday use), AP/años antes del presente (the
radiocarbon *antes del presente*), tiempo unix, día juliano, era
holocena/humana, anno mundi, "en el año 12000", and BC-axis
siglo/milenio ordinals.

This module contributes only the Spanish spelled-number normaliser;
Spanish needs no extra guard patterns — the ambiguous short forms
("ac", "dc") already only match adjacent to a number via the shared
scanner.
"""
from ovos_number_parser.numbers_es import ES

from ovos_date_parser.eras_scan import (EraPatterns, extract_era_date,
                                        load_era_patterns)

ERA_PATTERNS_ES: EraPatterns = load_era_patterns("es")


def extract_era_date_es(text: str):
    """Extract an era-qualified date from Spanish text.

    Thin wrapper binding :data:`ERA_PATTERNS_ES` and the Spanish
    spelled-number normaliser to the shared scanner — see
    :func:`ovos_date_parser.eras_scan.extract_era_date` for the contract.
    """
    return extract_era_date(text, ERA_PATTERNS_ES,
                            normalize=ES.numbers_to_digits)
