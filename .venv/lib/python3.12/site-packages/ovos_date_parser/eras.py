"""Re-export of named eras, epochs, and out-of-range date arithmetic.

The reckoning core lives in the :mod:`chronologia` library; this module keeps
the historical ``ovos_date_parser.eras`` import path working, including the
``AstroDate``/``is_leap_year`` names that used to be imported through here.
"""
from chronologia.astrodate import AstroDate, is_leap_year
from chronologia.eras import (ERAS, Era, EraCounting, astro_year_range,
                              julian_day_to_date, resolve_bp, resolve_era,
                              resolve_era_year_span)

__all__ = [
    "AstroDate",
    "is_leap_year",
    "ERAS",
    "Era",
    "EraCounting",
    "astro_year_range",
    "julian_day_to_date",
    "resolve_bp",
    "resolve_era",
    "resolve_era_year_span",
]
