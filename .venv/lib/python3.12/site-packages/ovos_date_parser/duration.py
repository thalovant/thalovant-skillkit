"""Shared duration-extraction engine.

Each language contributes a :class:`DurationLexicon` — a table of unit
regex fragments covering the declined/suffixed forms that follow a
numeral — and the generic matcher does the rest: the text is normalized
(numerals spelled in words become digits), every ``<number> <unit>``
occurrence is consumed, and the accumulated values are converted to the
requested :class:`DurationResolution`.
"""
import re
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from math import modf
from typing import Callable, Dict, List, Optional, Tuple, Union

from dateutil.relativedelta import relativedelta
from ovos_number_parser import numbers_to_digits
from ovos_utils.time import DAYS_IN_1_MONTH, DAYS_IN_1_YEAR


class DurationResolution(Enum):
    TIMEDELTA = 0
    RELATIVEDELTA = 1
    RELATIVEDELTA_STRICT = 1
    RELATIVEDELTA_FALLBACK = 2
    RELATIVEDELTA_APPROXIMATE = 3
    TOTAL_SECONDS = 4
    TOTAL_MICROSECONDS = 5
    TOTAL_MILLISECONDS = 6
    TOTAL_MINUTES = 7
    TOTAL_HOURS = 8
    TOTAL_DAYS = 9
    TOTAL_WEEKS = 10
    TOTAL_MONTHS = 11
    TOTAL_YEARS = 12
    TOTAL_DECADES = 13
    TOTAL_CENTURIES = 14
    TOTAL_MILLENNIUMS = 15


# canonical unit names, in the order they are matched (smallest first, so
# e.g. "milliseconds" never loses its prefix to a bare "seconds" fragment)
_UNITS = ("microseconds", "milliseconds", "seconds", "minutes", "hours",
          "days", "weeks", "months", "years", "decades", "centuries",
          "millenniums")

# canonical unit -> microseconds
_US = {
    "microseconds": 1,
    "milliseconds": 1000,
    "seconds": 1000 * 1000,
    "minutes": 1000 * 1000 * 60,
    "hours": 1000 * 1000 * 60 * 60,
    "days": 1000 * 1000 * 60 * 60 * 24,
    "weeks": 1000 * 1000 * 60 * 60 * 24 * 7,
    "months": 1000 * 1000 * 60 * 60 * 24 * DAYS_IN_1_MONTH,
    "years": 1000 * 1000 * 60 * 60 * 24 * DAYS_IN_1_YEAR,
    "decades": 1000 * 1000 * 60 * 60 * 24 * DAYS_IN_1_YEAR * 10,
    "centuries": 1000 * 1000 * 60 * 60 * 24 * DAYS_IN_1_YEAR * 100,
    "millenniums": 1000 * 1000 * 60 * 60 * 24 * DAYS_IN_1_YEAR * 1000,
}

_TOTALS = {
    DurationResolution.TOTAL_MICROSECONDS: "microseconds",
    DurationResolution.TOTAL_MILLISECONDS: "milliseconds",
    DurationResolution.TOTAL_SECONDS: "seconds",
    DurationResolution.TOTAL_MINUTES: "minutes",
    DurationResolution.TOTAL_HOURS: "hours",
    DurationResolution.TOTAL_DAYS: "days",
    DurationResolution.TOTAL_WEEKS: "weeks",
    DurationResolution.TOTAL_MONTHS: "months",
    DurationResolution.TOTAL_YEARS: "years",
    DurationResolution.TOTAL_DECADES: "decades",
    DurationResolution.TOTAL_CENTURIES: "centuries",
    DurationResolution.TOTAL_MILLENNIUMS: "millenniums",
}


@dataclass
class DurationLexicon:
    """Per-language duration unit table.

    Attributes:
        lang: BCP-47 code passed to the number parser.
        units: mapping of canonical unit name -> regex fragment matching
            every declined/suffixed surface form of that unit when it
            follows a numeral. Units are matched in _UNITS order.
        value_pattern: regex for the numeric value (named group ``value``).
        joiner: regex between the value and the unit word.
        pattern_template: optional full pattern override with a ``{unit}``
            placeholder; must define a ``value`` group and may define a
            ``half`` group adding 0.5 to the value when present.
        normalize: optional override for text normalization; receives the
            raw text and returns text with numerals as digits. Defaults
            to ``numbers_to_digits(text.lower(), lang)``.
        connectors: regex fragments (no capturing groups) matching the
            conjunction word(s) used to join two duration chunks (e.g.
            ``"and"`` in English, ``"y"`` in Spanish). When a connector
            (optionally surrounded by commas) is left sandwiched between
            two consumed ``<number> <unit>`` matches it is stripped from
            the remainder along with the matches themselves; a connector
            touching unconsumed text on either side is left untouched.
    """
    lang: str
    units: Dict[str, str]
    value_pattern: str = r"(?P<value>\d+(?:[.,]\d+)?)"
    joiner: str = r"(?:\s+|-)"
    pattern_template: Optional[str] = None
    normalize: Optional[Callable[[str], str]] = None
    connectors: Tuple[str, ...] = ()

    def _normalize(self, text: str) -> str:
        if self.normalize:
            return self.normalize(text)
        return numbers_to_digits(text.lower(), self.lang)

    def _pattern(self, fragment: str) -> str:
        if self.pattern_template:
            return self.pattern_template.format(unit=fragment)
        return self.value_pattern + self.joiner + "(?:" + fragment + r")\b"


def extract_duration_generic(
        text: str, lexicon: DurationLexicon,
        resolution: DurationResolution = DurationResolution.TIMEDELTA,
        replace_token: str = ""
) -> Optional[Tuple[Optional[Union[timedelta, relativedelta, float]], str]]:
    """Extract a duration from ``text`` using ``lexicon``.

    Consumes every ``<number> <unit>`` occurrence and returns the duration
    in the requested resolution plus the remaining text. Returns ``None``
    for empty input; the duration is ``None`` when nothing matched.
    """
    if not text:
        return None

    text = lexicon._normalize(text)

    # when the caller wants consumed chunks erased (the default), matches
    # are replaced with a private-use sentinel instead of "" so that, once
    # every unit has been consumed, connective tokens ("and", ",", ...)
    # left stranded *between two sentinels* can be told apart from ones
    # still joining real, unconsumed text and cleaned up accordingly.
    marker = ""
    token = marker if not replace_token else replace_token

    values: Dict[str, float] = {}
    for unit in _UNITS:
        frag = lexicon.units.get(unit)
        if not frag:
            continue
        pattern = lexicon._pattern(frag)

        def repl(match, _unit=unit):
            val = float(match.group("value").replace(",", "."))
            if "half" in match.groupdict() and match.group("half"):
                val += 0.5
            values[_unit] = values.get(_unit, 0) + val
            return token

        text = re.sub(pattern, repl, text)

    if not replace_token:
        if lexicon.connectors:
            conn_alt = "|".join(lexicon.connectors)
            sep = (r"\s*,\s*|\s+(?:" + conn_alt + r")\s+|"
                   r"\s*,\s*(?:" + conn_alt + r")\s*")
            collapse = re.compile(marker + r"(?:" + sep + r")" + marker)
            while True:
                new_text = collapse.sub(marker + marker, text)
                if new_text == text:
                    break
                text = new_text
        text = text.replace(marker, "")
        text = re.sub(r"\s+", " ", text).strip(" ,;.!")

    return _resolve(values, resolution), text


def _resolve(values: Dict[str, float],
             resolution: DurationResolution
             ) -> Optional[Union[timedelta, relativedelta, float]]:
    """Convert accumulated per-unit values to the requested resolution."""
    if not values:
        return None

    if resolution == DurationResolution.TIMEDELTA:
        td = {k: v for k, v in values.items()
              if k in ("microseconds", "milliseconds", "seconds",
                       "minutes", "hours", "weeks")}
        days = values.get("days", 0) \
            + values.get("months", 0) * DAYS_IN_1_MONTH \
            + values.get("years", 0) * DAYS_IN_1_YEAR \
            + values.get("decades", 0) * 10 * DAYS_IN_1_YEAR \
            + values.get("centuries", 0) * 100 * DAYS_IN_1_YEAR \
            + values.get("millenniums", 0) * 1000 * DAYS_IN_1_YEAR
        if days:
            td["days"] = days
        try:
            return timedelta(**td)
        except OverflowError:
            # values too large for timedelta to represent; treat as no
            # duration found rather than crashing the caller
            return None

    if resolution in (DurationResolution.RELATIVEDELTA,
                      DurationResolution.RELATIVEDELTA_STRICT,
                      DurationResolution.RELATIVEDELTA_FALLBACK,
                      DurationResolution.RELATIVEDELTA_APPROXIMATE):
        rd = {k: values.get(k, 0)
              for k in ("seconds", "minutes", "hours", "days", "weeks")}
        # relativedelta has no milliseconds field
        rd["microseconds"] = int(values.get("microseconds", 0) +
                                 values.get("milliseconds", 0) * 1000)
        rd["months"] = values.get("months", 0)
        # relativedelta has no decade/century/millennium fields
        rd["years"] = values.get("years", 0) \
            + values.get("decades", 0) * 10 \
            + values.get("centuries", 0) * 100 \
            + values.get("millenniums", 0) * 1000
        if resolution == DurationResolution.RELATIVEDELTA_APPROXIMATE:
            _frac, years = modf(rd["years"])
            rd["months"] += 12 * _frac
            rd["years"] = int(years)
            _frac, months = modf(rd["months"])
            rd["days"] += DAYS_IN_1_MONTH * _frac
            rd["months"] = int(months)
        else:
            for unit in ("months", "years"):
                _frac, whole = modf(rd[unit])
                if _frac != 0:
                    if resolution == DurationResolution.RELATIVEDELTA_FALLBACK:
                        return _resolve(values, DurationResolution.TIMEDELTA)
                    raise ValueError(
                        f"relativedelta requires {unit} to be an integer")
                rd[unit] = int(whole)
        return relativedelta(**rd)

    if resolution in _TOTALS:
        microseconds = sum(v * _US[k] for k, v in values.items())
        return microseconds / _US[_TOTALS[resolution]]

    raise ValueError(f"invalid resolution: {resolution}")


def _suffixed(stem: str, suffixes: str) -> str:
    """Regex fragment for ``stem`` with optional suffix alternatives."""
    return stem + "(?:" + suffixes + ")?"


DURATION_LEXICONS: Dict[str, DurationLexicon] = {}


def register_duration_lexicon(lexicon: DurationLexicon) -> None:
    DURATION_LEXICONS[lexicon.lang.split("-")[0]] = lexicon


# ---------------------------------------------------------------------------
# language tables
# ---------------------------------------------------------------------------

register_duration_lexicon(DurationLexicon(
    lang="fr",
    units={
        "microseconds": r"microsecondes?",
        "milliseconds": r"millisecondes?",
        "seconds": r"secondes?",
        "minutes": r"minutes?",
        "hours": r"heures?",
        "days": r"jours?",
        "weeks": r"semaines?",
        "months": r"mois",
        "years": r"an(?:née)?s?",
        "decades": r"décennies?",
        "centuries": r"siècles?",
        "millenniums": r"millénaires?",
    }))

register_duration_lexicon(DurationLexicon(
    lang="it",
    units={
        "microseconds": r"microsecond[oi]",
        "milliseconds": r"millisecond[oi]",
        "seconds": r"second[oi]",
        "minutes": r"minut[oi]",
        "hours": r"or[ae]",
        "days": r"giorn[oi]",
        "weeks": r"settiman[ae]",
        "months": r"mes[ei]",
        "years": r"ann[oi]",
        "decades": r"decenni[o]?",
        "centuries": r"secol[oi]",
        "millenniums": r"millenni[o]?",
    }))

# Basque nouns stay singular after numerals; the absolutive/case suffixes
# (-a, -ak, -ko, -tako, -z, -tan, -etan) are accepted.
_EU_SUFFIX = "ak|a|ko|tako|z|tan|etan"
register_duration_lexicon(DurationLexicon(
    lang="eu",
    units={
        "microseconds": _suffixed("mikrosegundo", _EU_SUFFIX),
        "milliseconds": _suffixed("milisegundo", _EU_SUFFIX),
        "seconds": _suffixed("segundo", _EU_SUFFIX),
        "minutes": _suffixed("minutu", _EU_SUFFIX),
        "hours": _suffixed("ordu", _EU_SUFFIX),
        "days": _suffixed("egun", _EU_SUFFIX),
        "weeks": _suffixed("aste", _EU_SUFFIX),
        "months": _suffixed("hilabete", _EU_SUFFIX),
        "years": _suffixed("urte", _EU_SUFFIX),
        "decades": _suffixed("hamarkada", "k|ko|tan"),
        "centuries": _suffixed("mende", _EU_SUFFIX),
        "millenniums": _suffixed("milurteko", _EU_SUFFIX),
    }))


def _normalize_hu(text: str) -> str:
    # "hét" is both "seven" and "week": read it as the unit when a number
    # precedes it and as the numeral otherwise
    from ovos_number_parser.numbers_hu import extract_number_hu
    tokens = text.lower().split()
    protected = []
    for i, tok in enumerate(tokens):
        if tok == "hét" and i > 0 and \
                extract_number_hu(tokens[i - 1]) is not False:
            protected.append("\x00hét\x00")
        else:
            protected.append(tok)
    text = numbers_to_digits(" ".join(protected), "hu")
    return text.replace("\x00hét\x00", "hét")


register_duration_lexicon(DurationLexicon(
    lang="hu",
    normalize=_normalize_hu,
    units={
        "microseconds": r"mikroszekundum(?:ot)?",
        "milliseconds": r"(?:milliszekundum(?:ot)?|ezredmásodperc(?:et)?)",
        "seconds": r"másodperc(?:et|re|ig)?",
        "minutes": r"perc(?:et|re|ig)?",
        "hours": r"(?:óra|órát|órára|óráig)",
        "days": r"nap(?:ot|ra|ig)?",
        "weeks": r"h[eé]t(?:et|re|ig)?",
        "months": r"hónap(?:ot|ra|ig)?",
        "years": r"év(?:et|re|ig)?",
        "decades": r"évtized(?:et)?",
        "centuries": r"évszázad(?:ot)?",
        "millenniums": r"évezred(?:et)?",
    }))

register_duration_lexicon(DurationLexicon(
    lang="sl",
    units={
        "microseconds": r"mikrosekund(?:a|e|i|o)?",
        "milliseconds": r"milisekund(?:a|e|i|o)?",
        "seconds": r"sekund(?:a|e|i|o)?",
        "minutes": r"minut(?:a|e|i|o)?",
        "hours": r"ur(?:a|e|i|o)?",
        "days": r"(?:dan|dni|dnev(?:a|e|i|ov)?)",
        "weeks": r"(?:teden|tedn(?:a|e|i|ov)?)",
        "months": r"mesec(?:a|e|i|ev)?",
        "years": r"let(?:o|a|i|ih)?",
        "decades": r"desetletj(?:e|a|i|ih)?|desetletij",
        "centuries": r"stoletj(?:e|a|i|ih)?|stoletij",
        "millenniums": r"tisočletj(?:e|a|i|ih)?|tisočletij",
    }))


def _normalize_en(text: str) -> str:
    # the English-specific normalizer folds "X and a half" into X.5
    from ovos_number_parser.numbers_en import numbers_to_digits_en
    text = numbers_to_digits_en(text)
    text = text.replace("centuries", "century").replace(
        "millenia", "millennium")
    for word in ("day", "month", "year", "decade", "century", "millennium"):
        text = text.replace(f"a {word}", f"1 {word}")
    return text


register_duration_lexicon(DurationLexicon(
    lang="en",
    normalize=_normalize_en,
    connectors=("and",),
    units={
        "microseconds": r"microseconds?",
        "milliseconds": r"milliseconds?",
        "seconds": r"seconds?",
        "minutes": r"minutes?",
        "hours": r"hours?",
        "days": r"days?",
        "weeks": r"weeks?",
        "months": r"months?",
        "years": r"years?",
        "decades": r"decades?",
        "centuries": r"centurys?",
        "millenniums": r"millenniums?",
    }))


def _fold_iberian(text: str) -> str:
    return text.lower().replace("í", "i").replace("é", "e").replace("ñ", "n")


register_duration_lexicon(DurationLexicon(
    lang="ca",
    normalize=lambda text: numbers_to_digits(_fold_iberian(text), "ca"),
    units={
        "microseconds": r"microsegons?",
        "milliseconds": r"mil·lisegons?|milisegons?",
        "seconds": r"segons?",
        "minutes": r"minuts?",
        "hours": r"hor(?:a|es)",
        "days": r"di(?:a|es)",
        "weeks": r"setman(?:a|es)",
        "months": r"mes(?:os)?",
        "years": r"anys?",
        "decades": r"dècad(?:a|es)|decad(?:a|es)",
        "centuries": r"segles?",
        "millenniums": r"mil·lenis?|milenis?",
    }))

register_duration_lexicon(DurationLexicon(
    lang="es",
    normalize=lambda text: numbers_to_digits(_fold_iberian(text), "es"),
    connectors=("y",),
    units={
        "microseconds": r"microsegundos?",
        "milliseconds": r"milisegundos?",
        "seconds": r"segundos?",
        "minutes": r"minutos?",
        "hours": r"horas?",
        "days": r"dias?",
        "weeks": r"semanas?",
        "months": r"mes(?:es)?",
        "years": r"anos?",
        "decades": r"decadas?",
        "centuries": r"siglos?",
        "millenniums": r"milenios?",
    }))

register_duration_lexicon(DurationLexicon(
    lang="gl",
    normalize=lambda text: numbers_to_digits(_fold_iberian(text), "gl"),
    units={
        "microseconds": r"microsegundos?",
        "milliseconds": r"milisegundos?",
        "seconds": r"segundos?",
        "minutes": r"minutos?",
        "hours": r"horas?",
        "days": r"dias?",
        "weeks": r"semanas?",
        "months": r"mes(?:es)?",
        "years": r"anos?",
        "decades": r"decadas?",
        "centuries": r"seculos?",
        "millenniums": r"milenios?",
    }))


def _fold_occitan(text: str) -> str:
    return (text.lower().replace("è", "e").replace("ò", "o")
            .replace("í", "i").replace("é", "e").replace("ó", "o"))


register_duration_lexicon(DurationLexicon(
    lang="oc",
    normalize=_fold_occitan,
    units={
        "microseconds": r"microsegondas?",
        "milliseconds": r"millisegondas?|milisegondas?",
        "seconds": r"segondas?",
        "minutes": r"minutas?",
        "hours": r"oras?",
        "days": r"jorns?",
        "weeks": r"setmanas?",
        "months": r"mes(?:es)?",
        "years": r"ans?",
        "decades": r"decadas?",
        "centuries": r"segles?",
        "millenniums": r"millenaris?|milenaris?",
    }))


def _normalize_pt(text: str) -> str:
    text = text.lower().replace("mês", "meses").replace("é", "e")
    # "segundo" (second) is also the ordinal "second"; shield it from the
    # number normalizer
    text = text.replace("segundo", "_s_")
    text = numbers_to_digits(text, "pt")
    return text.replace("_s_", "segundo")


register_duration_lexicon(DurationLexicon(
    lang="pt",
    normalize=_normalize_pt,
    units={
        "microseconds": r"microsegundos?",
        "milliseconds": r"milisegundos?",
        "seconds": r"segundos?",
        "minutes": r"minutos?",
        "hours": r"horas?",
        "days": r"dias?",
        "weeks": r"semanas?",
        "months": r"meses",
        "years": r"anos?",
        "decades": r"decadas?",
        "centuries": r"seculos?",
        "millenniums": r"milenios?",
    }))

register_duration_lexicon(DurationLexicon(
    lang="de",
    pattern_template=r"(?:^|\s)(?P<value>\d+(?:[.,]?\d+)?\b)(?:\s+|\-)"
                     r"(?:{unit})\b",
    units={
        "microseconds": r"mikrosekunde[nes]?[sn]?",
        "milliseconds": r"millisekunde[nes]?[sn]?",
        "seconds": r"sekunde[nes]?[sn]?",
        "minutes": r"minute[nes]?[sn]?",
        "hours": r"stunde[nes]?[sn]?",
        "days": r"tag[nes]?[sn]?",
        "weeks": r"woche[nes]?[sn]?",
    }))

register_duration_lexicon(DurationLexicon(
    lang="nl",
    units={
        "microseconds": r"microsecond(?:jes|je|en|e)?",
        "milliseconds": r"millisecond(?:jes|je|en|e)?",
        "seconds": r"second(?:jes|je|en|e)?",
        "minutes": r"minu(?:ut(?:jes|je)?|ten)",
        "hours": r"u(?:ur(?:tjes|tje)?|ren)",
        "days": r"dag(?:jes|je|en)?",
        "weeks": r"we(?:ek(?:jes|je)?|ken)",
    }))

register_duration_lexicon(DurationLexicon(
    lang="fy",
    units={
        "microseconds": r"mikrosekonde[n]?",
        "milliseconds": r"millisekonde[n]?",
        "seconds": r"sekonde[n]?",
        "minutes": r"minút(?:en)?|minut(?:en)?",
        "hours": r"oere[n]?",
        "days": r"dagen|dei",
        "weeks": r"wike[n]?",
        "months": r"moanne[n]?",
        "years": r"jier(?:ren)?",
        "decades": r"desennium[s]?",
        "centuries": r"ieu(?:wen|w)?",
        "millenniums": r"millennium[s]?",
    }))

# Aragonese: numbers_to_digits leaves the text unchanged (the Aragonese
# number engine exposes no word->digit normaliser), which matches the
# digit-only surface forms this lexicon targets.
register_duration_lexicon(DurationLexicon(
    lang="an",
    normalize=lambda text: numbers_to_digits(_fold_iberian(text), "an"),
    units={
        "microseconds": r"microsegundos?",
        "milliseconds": r"milisegundos?",
        "seconds": r"segundos?",
        "minutes": r"minutos?",
        "hours": r"horas?",
        "days": r"(?:días?|diyas?)",
        "weeks": r"semanas?",
        "months": r"mes(?:es)?",
        "years": r"anyos?",
        "decades": r"decadas?",
        "centuries": r"sieglos?",
        "millenniums": r"milenios?",
    }))


def _normalize_da(text: str) -> str:
    # the Danish-specific normalizer keeps the article "en" intact
    from ovos_number_parser.numbers_da import numbers_to_digits_da
    return numbers_to_digits_da(text.lower())


register_duration_lexicon(DurationLexicon(
    lang="da",
    normalize=_normalize_da,
    units={
        "microseconds": r"mikrosekund(?:ers|er|s)?",
        "milliseconds": r"millisekund(?:er|s)?",
        "seconds": r"sekund(?:ers|er|s)?",
        "minutes": r"minut(?:ters|ter|s)?",
        "hours": r"time(?:rs|r|s)?",
        "days": r"dag(?:es|e|s)?",
        "weeks": r"uge(?:rs|r|s)?",
        "months": r"måned(?:ers|er|s)?",
        "years": r"års?",
        "decades": r"årti(?:er|s)?",
        "centuries": r"århundrede(?:r|s)?",
        "millenniums": r"årtusinde(?:r|s)?",
    }))


def _normalize_nb(text: str) -> str:
    from ovos_number_parser.numbers_nb import numbers_to_digits_nb
    return numbers_to_digits_nb(text.lower())


register_duration_lexicon(DurationLexicon(
    lang="nb",
    normalize=_normalize_nb,
    units={
        "microseconds": r"mikrosekund(?:ene|er|et)?",
        "milliseconds": r"millisekund(?:ene|er|et)?",
        "seconds": r"sekund(?:ene|er|et)?",
        "minutes": r"minutt(?:ene|er|et)?",
        "hours": r"time(?:ne|r|n)?",
        "days": r"dag(?:ene|er|en)?",
        "weeks": r"uke(?:ne|r|n)?",
        "months": r"måned(?:ene|er|en)?",
        "years": r"år(?:ene|et)?",
        "decades": r"(?:tiår(?:ene|et)?|årti(?:ene|er|et)?)",
        "centuries": r"(?:århundre(?:ne|r|t)?|hundreår(?:ene|et)?)",
        "millenniums": r"årtusen(?:ene|er|et)?",
    }))


def _normalize_nn(text: str) -> str:
    from ovos_number_parser.numbers_nn import numbers_to_digits_nn
    return numbers_to_digits_nn(text.lower())


register_duration_lexicon(DurationLexicon(
    lang="nn",
    normalize=_normalize_nn,
    units={
        "microseconds": r"mikrosekund(?:a|er|et)?",
        "milliseconds": r"millisekund(?:a|er|et)?",
        "seconds": r"sekund(?:a|er|et)?",
        "minutes": r"minutt(?:a|er|et)?",
        "hours": r"tim(?:ane|ar|en|e|r)?",
        "days": r"dag(?:ane|ar|er|en)?",
        "weeks": r"veke(?:ne|r|a)?",
        "months": r"månad(?:ene|er|en)?",
        "years": r"år(?:a|et)?",
        "decades": r"(?:tiår(?:a|et)?|årti(?:a|er|et)?)",
        "centuries": r"(?:hundreår(?:a|et)?|århundre(?:a|r|t)?)",
        "millenniums": r"årtusen(?:a|er|et)?",
    }))


register_duration_lexicon(DurationLexicon(
    lang="cs",
    units={
        "microseconds": r"mikrosekund[ay]?",
        "milliseconds": r"milisekund[ay]?",
        "seconds": r"sekund(?:u|y|a)?",
        "minutes": r"minut(?:u|y|a)?",
        "hours": r"hodin[ay]?",
        "days": r"(?:den|dny|dnů|dní|dne)",
        "weeks": r"(?:týden|týdny|týdnů)",
    }))

register_duration_lexicon(DurationLexicon(
    lang="pl",
    units={
        "microseconds": r"mikrosekund(?:y|a|ę)?",
        "milliseconds": r"milisekund(?:y|a|ę)?",
        "seconds": r"sekund(?:y|a|ę)?",
        "minutes": r"minut(?:y|a|ę)?",
        "hours": r"godzin(?:y|a|ę)?",
        "days": r"(?:dzień|dni[aeę]?)",
        "weeks": r"(?:tydzień|tygodni(?:e|u|a)?)",
    }))

register_duration_lexicon(DurationLexicon(
    lang="ru",
    units={
        "microseconds": r"микросекунд(?:а|ы|у)?",
        "milliseconds": r"мил(?:л)?исекунд(?:а|ы|у)?",
        "seconds": r"секунд(?:а|ы|у)?",
        "minutes": r"минут(?:а|ы|у)?",
        "hours": r"(?:час(?:а|ов|у)?|годин(?:а|ы|ой|ами|е|у)?)",
        "days": r"(?:день|дня|дней|дню)",
        "weeks": r"недел(?:я|и|ь|ю|ей)?",
    }))

register_duration_lexicon(DurationLexicon(
    lang="uk",
    units={
        "microseconds": r"мікросекунд(?:а|и|у)?",
        "milliseconds": r"мілісекунд(?:а|и|у)?",
        "seconds": r"секунд(?:а|и|у)?",
        "minutes": r"хвилин(?:а|и|у)?",
        "hours": r"годин(?:а|и|у|ами|ою)?",
        "days": r"(?:днів|день|дні|дня|дню)",
        "weeks": r"(?:тиждень|тижн(?:я|і|ів|ю))",
    }))

register_duration_lexicon(DurationLexicon(
    lang="sk",
    units={
        "microseconds": r"mikrosek[úu]nd(?:a|y|u)?",
        "milliseconds": r"milisek[úu]nd(?:a|y|u)?",
        "seconds": r"sek[úu]nd(?:a|y|u)?",
        "minutes": r"min[úu]t(?:a|y|u)?",
        "hours": r"hod[íi]n(?:a|y|u)?",
        "days": r"(?:deň|dni|dní|dňa)",
        "weeks": r"(?:týždeň|týždne|týždňov|týždňa)",
        "months": r"mesiac(?:e|ov|a)?",
        "years": r"(?:rok(?:y|ov|a)?)",
        "decades": r"(?:desaťroč(?:ie|ia|í)|dekád(?:a|y)?)",
        "centuries": r"storoč(?:ie|ia|í)",
        "millenniums": r"tisícroč(?:ie|ia|í)",
    }))

register_duration_lexicon(DurationLexicon(
    lang="hr",
    units={
        "microseconds": r"mikrosekund(?:a|e|i|u)?",
        "milliseconds": r"milisekund(?:a|e|i|u)?",
        "seconds": r"sekund(?:a|e|i|u)?",
        "minutes": r"minut(?:a|e|i|u)?",
        "hours": r"sat(?:a|i|u)?",
        "days": r"dan(?:a|i|u)?",
        "weeks": r"(?:tjedan|tjedn(?:a|i|u))",
        "months": r"mjesec(?:a|i|u)?",
        "years": r"godin(?:a|e|i|u)?",
        "decades": r"(?:desetljeć(?:e|a|i)?|desetljeća)",
        "centuries": r"stoljeć(?:e|a|i)?",
        "millenniums": r"tisućljeć(?:e|a|i)?",
    }))

register_duration_lexicon(DurationLexicon(
    lang="bg",
    units={
        "microseconds": r"микросекунд(?:а|и)?",
        "milliseconds": r"милисекунд(?:а|и)?",
        "seconds": r"секунд(?:а|и)?",
        "minutes": r"минут(?:а|и)?",
        "hours": r"час(?:а|ове)?",
        "days": r"(?:ден|дни|дена)",
        "weeks": r"седмиц(?:а|и)?",
        "months": r"месец(?:а|и)?",
        "years": r"годин(?:а|и)?",
        "decades": r"десетилети(?:е|я)",
        "centuries": r"(?:век(?:а|ове)?|столети(?:е|я))",
        "millenniums": r"хилядолети(?:е|я)",
    }))

register_duration_lexicon(DurationLexicon(
    lang="az",
    pattern_template=r"(?P<value>\d+(?:\.?\d+)?)(?:\s+|\-)(?:{unit})"
                     r"(?:yə|a|ə)?(?:(?:\s|,)+)?(?P<half>yarım|0\.5)?(?:a)?",
    units={
        "microseconds": r"mikrosaniyə",
        "milliseconds": r"milisaniyə",
        "seconds": r"saniyə",
        "minutes": r"dəqiqə",
        "hours": r"saat",
        "days": r"gün",
        "weeks": r"həftə",
    }))


def _normalize_ro(text: str) -> str:
    # articled "one <unit>" forms and idiomatic fractions of an hour
    text = text.lower().replace("ş", "ș").replace("ţ", "ț")
    for phrase, repl in (("o secundă", "1 secundă"), ("un minut", "1 minut"),
                         ("o oră", "1 oră"), ("un ceas", "1 oră"),
                         ("o zi", "1 zi"), ("o săptămână", "1 săptămână"),
                         ("o lună", "1 lună"), ("un an", "1 an"),
                         ("un deceniu", "1 deceniu"),
                         ("un secol", "1 secol"), ("un veac", "1 secol"),
                         ("un mileniu", "1 mileniu"),
                         ("jumătate de oră", "30 minute"),
                         ("un sfert de oră", "15 minute"),
                         ("trei sferturi de oră", "45 minute")):
        text = re.sub(rf"\b{phrase}\b", repl, text)
    return numbers_to_digits(text, "ro")


# "luni" is both Monday and the plural of "lună" (month); the value
# pattern only matches it after a numeral, so the weekday is never
# consumed. Numbers link to counted nouns with "de" ("49 de secunde"),
# which the joiner accepts.
register_duration_lexicon(DurationLexicon(
    lang="ro",
    normalize=_normalize_ro,
    joiner=r"(?:\s+de\s+|\s+|-)",
    units={
        "microseconds": r"microsecund[ăe]",
        "milliseconds": r"milisecund[ăe]",
        "seconds": r"secund[ăe](?:le)?",
        "minutes": r"minut(?:e(?:le)?|ul)?",
        "hours": r"or[ăe](?:le)?|ceas(?:uri)?",
        "days": r"zi(?:le(?:le)?|ua)?",
        "weeks": r"săptămân[ăi](?:le)?",
        "months": r"lun[ăi](?:le)?",
        "years": r"an(?:i(?:i)?|ul)?",
        "decades": r"deceni[iu](?:le)?",
        "centuries": r"secol(?:e(?:le)?|ul)?|veac(?:uri)?",
        "millenniums": r"mileni[iu](?:le)?",
    }))


def _normalize_fi(text):
    # numbers_to_digits already folds "puoli" -> 0.5 and "puolitoista" ->
    # 1.5; collapse "N ja 0.5" ("kolme ja puoli") into "N.5" so the whole
    # quantity is read as a single fractional value
    text = numbers_to_digits(text.lower(), "fi")
    return re.sub(r"(\d+)\s+ja\s+0[.,]5", r"\1.5", text)


# Finnish nouns follow a numeral in the partitive singular ("kaksi tuntia");
# the nominative ("tunti") and genitive ("tunnin", in "kahden tunnin") forms
# also occur, so each unit accepts its common declined surface forms.
# Fractional numerals ("puoli tuntia" = 0.5 h, "puolitoista tuntia" = 1.5 h,
# "kolme ja puoli tuntia" = 3.5 h) are handled by the numeral normalizer.
register_duration_lexicon(DurationLexicon(
    lang="fi",
    normalize=_normalize_fi,
    units={
        "microseconds": r"mikrosekunt(?:ia|i)|mikrosekunnin",
        "milliseconds": r"millisekunt(?:ia|i)|millisekunnin",
        "seconds": r"sekunt(?:ia|i)|sekunnin",
        "minutes": r"minuut(?:tia|ti)|minuutin",
        "hours": r"(?:tunti|tuntia|tunnin)",
        "days": r"(?:päivää|päivän|päivä|vuorokausi|vuorokautta)",
        "weeks": r"(?:viikko|viikkoa|viikon)",
        "months": r"(?:kuukausi|kuukautta|kuukauden)",
        "years": r"(?:vuosi|vuotta|vuoden)",
        "decades": r"(?:vuosikymmen|vuosikymmentä|vuosikymmenen)",
        "centuries": r"(?:vuosisata|vuosisataa|vuosisadan)",
        "millenniums": r"(?:vuosituhat|vuosituhatta|vuosituhannen)",
    }))


def _normalize_et(text):
    # numbers_to_digits already folds "pool" -> 0.5 and "poolteist" -> 1.5;
    # collapse "N ja 0.5" ("kolm ja pool") into "N.5" so the whole quantity
    # is read as a single fractional value
    text = numbers_to_digits(text.lower(), "et")
    return re.sub(r"(\d+)\s+ja\s+0[.,]5", r"\1.5", text)


# Estonian nouns follow a numeral in the partitive singular ("kaks tundi");
# the nominative ("tund") and partitive/genitive variants also occur.
# Fractional numerals ("pool tundi" = 0.5 h, "poolteist tundi" = 1.5 h,
# "kolm ja pool tundi" = 3.5 h) are handled by the numeral normalizer.
register_duration_lexicon(DurationLexicon(
    lang="et",
    normalize=_normalize_et,
    units={
        "microseconds": r"mikrosekund(?:it|i)?",
        "milliseconds": r"millisekund(?:it|i)?",
        "seconds": r"sekund(?:it|i)?",
        "minutes": r"minut(?:it|i)?",
        "hours": r"(?:tundi|tunni|tund)",
        "days": r"(?:päeva|päev|ööpäev(?:a)?)",
        "weeks": r"(?:nädalat|nädala|nädal)",
        "months": r"(?:kuud|kuu)",
        "years": r"(?:aastat|aasta)",
        "decades": r"(?:aastakümmet|aastakümne|aastakümmend)",
        "centuries": r"(?:aastasada|aastasaja|sajand(?:it|i)?)",
        "millenniums": r"(?:aastatuhat|aastatuhande|aastatuhat)",
    }))
