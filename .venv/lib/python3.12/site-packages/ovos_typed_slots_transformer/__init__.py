"""Typed-slots transformer over the OVOS parsers (OVOS-TRANSFORM-1 §3.7)."""
from datetime import datetime, tzinfo
from functools import partial
from typing import Any, Callable, Dict, FrozenSet, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ovos_config import Configuration
from ovos_plugin_manager.templates.transformers import TypedSlotsTransformer as _TypedSlotsTransformer
from ovos_spec_tools import MalformedTypedSlots, standardize_lang, validate_typed_slots
from ovos_utils.log import LOG

#: parsers and timezones already reported broken, so a misconfigured
#: deployment is not a warning on every utterance
_warned = set()


def _entry(start: int, end: int, surface: str, value: Any) -> Dict[str, Any]:
    return {"span": [start, end], "surface": surface, "value": value}


def _numbers(utterance: str, lang: str) -> List[Dict[str, Any]]:
    from ovos_number_parser import extract_number_spans
    return [_entry(s.start, s.end, s.surface, s.value)
            for s in extract_number_spans(utterance, lang)]


def _dates(utterance: str, lang: str, anchor: datetime) -> List[Dict[str, Any]]:
    from ovos_date_parser import extract_datetime_spans
    return [_entry(s.start, s.end, s.surface, s.value.isoformat())
            for s in extract_datetime_spans(utterance, lang, anchor_date=anchor)]


def _durations(utterance: str, lang: str) -> List[Dict[str, Any]]:
    from ovos_date_parser import extract_duration_spans
    return [_entry(s.start, s.end, s.surface, s.value.total_seconds())
            for s in extract_duration_spans(utterance, lang)]


def _colors(utterance: str, lang: str) -> List[Dict[str, Any]]:
    from ovos_color_parser import extract_color_spans
    return [_entry(s.start, s.end, s.surface, {"hex": s.hex, "name": s.name})
            for s in extract_color_spans(utterance, lang)]


def _languages(utterance: str, lang: str) -> List[Dict[str, Any]]:
    from ovos_lang_parser import extract_language
    return [_entry(e["span"][0], e["span"][1], e["surface"], e["value"])
            for e in extract_language(utterance, lang)]


#: parser call per supported type; `date` is bound to the anchor per transform
_EXTRACTORS = {"number": _numbers, "date": _dates, "duration": _durations,
               "color": _colors, "language": _languages}


def _warn_once(key: str, message: str):
    if key not in _warned:
        _warned.add(key)
        LOG.warning(message)


class TypedSlotsTransformer(_TypedSlotsTransformer):
    """Computes `number`, `date`, `duration`, `color` and `language` slots
    with the OVOS parsers, over every candidate utterance it is handed.

    The spans of an entry index the candidate it was read from; a consumer
    identifies that candidate by the `utterance[start:end] == surface`
    invariant.

    The map carries only types with at least one entry. A type is absent
    whenever it produced nothing, whether its parser found no such expression,
    is not installed, does not support the session language, or raised.

    `location` and `timezone` (OVOS-INTENT-1 §5.6) are not computed here yet:
    `location` needs an offline gazetteer of capital cities, countries and
    regions, matched with `ahocorasick-ner` rather than a regex alternation;
    `timezone` needs a per-language zone-name/abbreviation table honouring the
    spec's one-surface-one-zone rule. Both need a data source decided before
    landing (T-2126); `supported_types` grows to include them once that data
    ships.
    """

    supported_types: FrozenSet[str] = frozenset(
        {"number", "date", "duration", "color", "language"})

    def __init__(self, name: str = "ovos-typed-slots-transformer",
                 priority: int = 50, config: Optional[Dict[str, Any]] = None):
        super().__init__(name, priority, config)
        # OPM instantiates plugins as ``plug(config=...)``, so priority only
        # ever reaches the plugin through its own config section
        self.priority = self.config.get("priority", priority)

    def transform(self, utterances: List[str], declared_types: FrozenSet[str],
                  session) -> Dict[str, List[dict]]:
        lang = standardize_lang(session.lang)
        anchor = datetime.now(self._timezone(session))
        if self.config.get("all_types"):
            types = self.supported_types
        else:
            types = self.supported_types & set(declared_types)

        extractors = dict(_EXTRACTORS, date=partial(_EXTRACTORS["date"], anchor=anchor))
        typed_slots = {}
        for slot_type in sorted(types):
            entries = self._extract(slot_type, extractors[slot_type], utterances, lang)
            if entries:
                typed_slots[slot_type] = entries
        return self._validated(typed_slots)

    @staticmethod
    def _timezone(session) -> tzinfo:
        """The session's zone (OVOS-SESSION-1 §3.5 ``location.tz``), falling
        back to the deployment zone when the session names none or names one
        this host cannot resolve."""
        tz = (session.location or {}).get("tz")
        if tz:
            try:
                return ZoneInfo(tz)
            except (ZoneInfoNotFoundError, ValueError):
                _warn_once(f"tz:{tz}", f"session location.tz '{tz}' is not a known "
                                       f"timezone, using the deployment zone")
        code = Configuration().get("location", {}).get("timezone", {}).get("code")
        if code:
            try:
                return ZoneInfo(code)
            except (ZoneInfoNotFoundError, ValueError):
                _warn_once(f"tz:{code}", f"configured location.timezone.code '{code}' "
                                         f"is not a known timezone, using local time")
        return datetime.now().astimezone().tzinfo

    @staticmethod
    def _extract(slot_type: str, extract: Callable, utterances: List[str],
                 lang: str) -> List[Dict[str, Any]]:
        entries = []
        for utterance in utterances:
            try:
                entries += extract(utterance, lang)
            except ImportError:
                _warn_once(f"parser:{slot_type}", f"no parser installed for "
                                                  f"'{slot_type}' slots, the type "
                                                  f"will not be computed")
                return []
            except (NotImplementedError, ValueError):
                # ovos_lang_parser raises ValueError, not NotImplementedError,
                # for a language with no bundled wordlist
                _warn_once(f"lang:{slot_type}:{lang}", f"'{slot_type}' slots are not "
                                                       f"supported in '{lang}', the "
                                                       f"type will not be computed")
                return []
            except Exception:
                LOG.exception(f"'{slot_type}' extraction failed, dropping the type")
                return []
        return entries

    @staticmethod
    def _validated(typed_slots: Dict[str, List[dict]]) -> Dict[str, List[dict]]:
        try:
            validate_typed_slots(typed_slots)
            return typed_slots
        except MalformedTypedSlots:
            pass
        valid = {}
        for slot_type, entries in typed_slots.items():
            try:
                validate_typed_slots({slot_type: entries})
                valid[slot_type] = entries
            except MalformedTypedSlots as err:
                LOG.error(f"dropping malformed '{slot_type}' slots: {err}")
        return valid
