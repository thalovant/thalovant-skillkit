"""Portuguese era/epoch extraction: "44 a.C.", "2000 anos antes do presente".

The surface forms live in ``ovos_date_parser/locale/pt/*.voc`` (loaded
through ovos-spec-tools by :func:`ovos_date_parser.eras_scan.
load_era_patterns`): a.C./aC/a.e.c./antes de Cristo/antes da era comum,
d.C./e.c./depois de Cristo/da era comum, AP/anos antes do presente (the
radiocarbon *antes do presente*), tempo unix, dia juliano, era
holocena/humana, anno mundi, "no ano 12000", and BC-axis
século/milénio (also milênio, the Brazilian orthography) ordinals.

This module contributes only the Portuguese spelled-number normaliser;
Portuguese needs no extra guard patterns — the ambiguous short forms
("ap", "dc") already only match adjacent to a number via the shared
scanner.
"""
from ovos_number_parser.numbers_pt import PT_PT

from ovos_date_parser.eras_scan import (EraPatterns, extract_era_date,
                                        load_era_patterns)

ERA_PATTERNS_PT: EraPatterns = load_era_patterns("pt")


def extract_era_date_pt(text: str):
    """Extract an era-qualified date from Portuguese text.

    Thin wrapper binding :data:`ERA_PATTERNS_PT` and the Portuguese
    spelled-number normaliser to the shared scanner — see
    :func:`ovos_date_parser.eras_scan.extract_era_date` for the contract.
    """
    return extract_era_date(text, ERA_PATTERNS_PT,
                            normalize=PT_PT.numbers_to_digits)
