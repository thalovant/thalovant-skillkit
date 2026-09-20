"""Re-export of the Julian-Day-Number calendar registry.

The reckoning core lives in the :mod:`chronologia` library; this module keeps
the historical ``ovos_date_parser.calendars`` import path working.
"""
from chronologia.calendars import (CALENDARS, Calendar, CalendarRangeError,
                                   TabulatedCalendar, gregorian_to_jdn,
                                   jdn_to_gregorian, jdn_to_julian,
                                   julian_to_jdn, register_event_provider)

__all__ = [
    "CALENDARS",
    "Calendar",
    "CalendarRangeError",
    "TabulatedCalendar",
    "gregorian_to_jdn",
    "jdn_to_gregorian",
    "jdn_to_julian",
    "julian_to_jdn",
    "register_event_provider",
]
