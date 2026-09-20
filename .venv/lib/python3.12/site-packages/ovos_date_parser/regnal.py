"""Re-export of regnal (reign-numbered) date sequences.

The reckoning core lives in the :mod:`chronologia` library; this module keeps
the historical ``ovos_date_parser.regnal`` import path working.
"""
from chronologia.regnal import REGNAL_SEQUENCES, RegnalSequence

__all__ = ["REGNAL_SEQUENCES", "RegnalSequence"]
