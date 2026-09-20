"""Kabyle (Taqbaylit, ``kab``) date and time tools.

Weekday names are the Arabic-derived forms in everyday use (letnayen,
ttlata, ...); month names follow the Kabyle calendar spellings (yennayer,
fuṛar, ... dujembeṛ). Time units mix the attested Amazigh neologisms
(tasint "second", asrag "hour", amalas "week") with the Arabic-derived
words that carry daily usage (ddqiqa "minute", ssaɛa "hour").

Spoken clock phrases (e.g. "d lɛecṛa u ṛbeɛ", "d juǧ n uzal") are built
around the presentative particle "d" ("it is"), the additive/subtractive
conjunctions "u"/"ɣiṛ", and a closed set of fraction and day-period
words - see `_extract_spoken_time_kab` below.

Sources:
- https://kab.wikipedia.org/wiki/Yennayer (month names)
- https://apprendrelekabyle.com/les-jours-de-la-semaine-en-kabyle/
- https://glosbe.com/fr/kab (heure, minute, seconde, matin, soir, semaine)
- https://en.wikipedia.org/wiki/Kabyle_language (grammar)
- Boulifa, *Une première année de langue kabyle*, 1910 (roba', nofc,
  r'ir, eddeq'iq'a)
- Dallet, *Dictionnaire kabyle-français*, 1982 (azgen, swaswa/gedged)
- Amazit-Hamidchi & Lounaci, *Le Kabyle de poche*, Assimil, 2005
  (nefs, ɣir, u, ddqayeq, wac)
"""
import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

from ovos_number_parser.numbers_kab import (pronounce_number_kab,
                                            extract_number_kab, _normalize)

WEEKDAYS_KAB = {0: "letnayen", 1: "ttlata", 2: "laṛebɛa", 3: "lexmis",
                4: "lǧemɛa", 5: "ssebt", 6: "lḥedd"}
MONTHS_KAB = {1: "yennayer", 2: "fuṛar", 3: "meɣres", 4: "yebrir",
              5: "mayyu", 6: "yunyu", 7: "yulyu", 8: "ɣuct",
              9: "ctembeṛ", 10: "tubeṛ", 11: "wambeṛ", 12: "dujembeṛ"}

# day-part words: ssbeḥ "morning", tameddit "evening", iḍ "night"
_MORNING = "ssbeḥ"
_EVENING = "tameddit"

# duration units, singular and plural spellings (Amazigh neologisms and
# the Arabic-derived words both extract)
_SECONDS_UNITS = {"tasint", "tisinin"}
_MINUTES_UNITS = {"ddqiqa", "tesdidin", "tisdidin", "dqiqa"}
_HOURS_UNITS = {"ssaɛa", "saɛa", "tsaɛtin", "tisaɛtin", "asrag", "isragen",
                "wesrag", "usrag"}
_DAYS_UNITS = {"ass", "ussan", "wass", "wussan"}
_WEEKS_UNITS = {"amalas", "imalasen", "yimalasen", "ddurt", "dduṛt",
                "umalas"}

_RELATIVE_DAYS = {"azekka": 1, "iḍelli": -1, "idelli": -1,
                  "ass-a": 0, "assa": 0, "ass-agi": 0}

# ---------------------------------------------------------------------------
# Spoken clock-time grammar
# ---------------------------------------------------------------------------

# presentative particle introducing a clock time ("it is")
_PRESENTATIVE = {_normalize(w) for w in ("d",)}

# additive conjunction ("and")
_PLUS = {_normalize(w) for w in ("u",)}

# subtractive conjunction ("minus, except")
_MINUS = {_normalize(w) for w in ("ɣiṛ", "ɣir", "r'ir")}

# exact-hour marker
_EXACT = {_normalize(w) for w in ("swaswa", "gedged")}

# vague-approximation markers ("and a bit" / used bare after ɣiṛ)
_APPROX_PLUS = {_normalize(w) for w in ("wac", "ci")}
_APPROX_MINUTES = 10  # fixed offset used only for the vague forms above

# quarter-hour fraction
_QUARTER = {_normalize(w) for w in ("ṛbeɛ", "roba'")}

# half-hour fraction - amazigh, old borrowing, assimil form, contemporary
_HALF = {_normalize(w) for w in
         ("azgen", "nofc", "nofç", "nefs", "nnefs", "neṣṣ", "nefṣ", "nsaf")}

# genitive linking a clock hour to a day-period ("n uzal" = "of midday")
_GENITIVE = {_normalize(w) for w in ("n",)}

# day-period words -> (start_hour_inclusive, end_hour_exclusive)
# used only to disambiguate 12h/24h, not to change the parsed hour itself.
# "tameddit"/"tmeddit" are both attested (with and without the epenthetic
# vowel); both map to the same band.
_DAY_PERIODS = {
    _normalize("ṣṣbeḥ"): (4, 8),
    _normalize("ssbeḥ"): (8, 12),
    _normalize("uzal"): (12, 15),
    _normalize("tameddit"): (15, 20),
    _normalize("tmeddit"): (15, 20),
    _normalize("iḍ"): (20, 4),
    _normalize("yiḍ"): (20, 4),
}

# regional (Soummam) alternative numeral for "two" used only in time
# expressions, alongside the everyday loanword "juǧ"
_TWO_HOURS_WORDS = {_normalize(w) for w in ("juǧ", "ssaɛtin")}

# Kabyle clock hours take the Arabic-style definite article fused onto
# the numeral. Like Arabic, it surfaces two ways depending on the first
# consonant of the noun:
#   - "moon letters" keep a plain "l-" ("lɛecṛa" = the-ten, "lxemsa" =
#     the-five)
#   - "sun letters" assimilate: "l-" + "tnac" -> "ttnac" (the-twelve),
#     "l-" + "tlata" -> "ttlata" (the-three), i.e. the article surfaces
#     as a doubled copy of the noun's own initial consonant instead of
#     "l". This is the same rule already implicit in WEEKDAYS_KAB
#     (ssebt "the-Saturday" vs lḥedd "the-Sunday").
# extract_number_kab does not know about either surface form, so both
# are stripped here before the lookup.
#
# "One" also takes a feminine form ("weḥda") agreeing with the feminine
# noun "ssaɛa" (hour), which is not part of the general loan-numeral
# vocabulary at all (only the masculine "waḥed" is).
_HOUR_FEMININE_OVERRIDES = {_normalize(w): 1 for w in ("weḥda", "waḥda")}

# midnight set phrases (word-for-word, matched as adjacent-token triples)
_MIDNIGHT_PHRASES = (
    (_normalize("nṣaf"), _normalize("n"), _normalize("yiḍ")),
    (_normalize("ttnaṣfa"), _normalize("n"), _normalize("yiḍ")),
)


def _hour_article_candidates(raw_tok: str, norm_tok: str):
    """Yield (raw, norm) candidate forms with the fused article removed,
    trying the plain "l-" case first, then sun-letter degemination.
    """
    yield raw_tok, norm_tok
    if norm_tok.startswith(_normalize("l")) and len(norm_tok) > 1:
        yield raw_tok[1:], norm_tok[1:]
    if len(norm_tok) > 1 and norm_tok[0] == norm_tok[1]:
        yield raw_tok[1:], norm_tok[1:]


def _extract_hour_number_kab(raw_tok: str, norm_tok: str):
    """Resolve a single clock-hour token to an int 1-12, or False."""
    for raw_c, norm_c in _hour_article_candidates(raw_tok, norm_tok):
        if norm_c in _HOUR_FEMININE_OVERRIDES:
            return _HOUR_FEMININE_OVERRIDES[norm_c]
        val = extract_number_kab(raw_c)
        if val is not False and float(val).is_integer() and 1 <= val <= 12:
            return int(val)
    return False


def _period_to_hour24(hour12: int, period_tok: str) -> int:
    """Resolve a 1-12 spoken hour to 24h using a day-period word.

    Only called when a day-period token is actually present in the
    utterance; per the source grammar, an utterance with no period word
    (e.g. bare "D juǧ") stays ambiguous and must default to the 12h
    reading rather than being guessed here.
    """
    start, end = _DAY_PERIODS[period_tok]
    if period_tok in (_normalize("iḍ"), _normalize("yiḍ")):
        # night wraps midnight: 20h-4h. 12 o'clock at night is 00:00.
        return 0 if hour12 == 12 else hour12
    if start >= 12:
        return hour12 if hour12 == 12 else hour12 + 12
    # morning/midday bands (ssbeḥ, ṣṣbeḥ, uzal early edge)
    return 0 if hour12 == 12 and start < 8 else hour12


def _extract_spoken_time_kab(tokens, norm) -> Optional[Tuple[int, int, set]]:
    """Extract (hour24, minute, consumed_token_indices) from spoken Kabyle
    clock-time grammar, or None if no such expression is found.

    `tokens` are the original (lower-cased, punctuation-stripped) words;
    `norm` is their _normalize()'d form, index-aligned with `tokens`.
    """
    n = len(norm)

    # --- midnight set phrases: check first, they don't need "D" ---
    for phrase in _MIDNIGHT_PHRASES:
        plen = len(phrase)
        for i in range(n - plen + 1):
            if tuple(norm[i:i + plen]) == phrase:
                return 0, 0, set(range(i, i + plen))

    for i, tok in enumerate(norm):
        if tok not in _PRESENTATIVE:
            continue

        # the presentative "d" is also the number-connector "d"
        # (see _CONNECTORS in numbers_kab.py) - only treat it as
        # presentative when followed by a recognizable hour word.
        j = i + 1
        if j >= n:
            continue

        consumed = {i}

        # regional "two" words are not ordinary cardinals, check first
        if norm[j] in _TWO_HOURS_WORDS:
            hour_val = 2
            consumed.add(j)
            j += 1
        else:
            val = _extract_hour_number_kab(tokens[j], norm[j])
            if val is False:
                continue
            hour_val = val
            consumed.add(j)
            j += 1

        minute_val = 0
        # walk any trailing modifiers: swaswa | u <frac> | ɣiṛ [<num>] | n <period>
        while j < n:
            tok2 = norm[j]

            if tok2 in _EXACT:
                consumed.add(j)
                j += 1
                continue

            if tok2 in _PLUS and j + 1 < n:
                nxt = norm[j + 1]
                if nxt in _QUARTER:
                    minute_val = 15
                    consumed.update({j, j + 1})
                    j += 2
                    continue
                if nxt in _HALF:
                    minute_val = 30
                    consumed.update({j, j + 1})
                    j += 2
                    continue
                if nxt in _APPROX_PLUS:
                    minute_val = _APPROX_MINUTES
                    consumed.update({j, j + 1})
                    j += 2
                    continue
                # "u <number>" additive minutes is not attested in the
                # source grammar; stop rather than guess.
                break

            if tok2 in _MINUS:
                consumed.add(j)
                j += 1
                if j >= n:
                    # bare ɣiṛ = vague "almost <hour>"
                    hour_val -= 1
                    minute_val = 60 - _APPROX_MINUTES
                    break
                nxt = norm[j]
                if nxt in _QUARTER:
                    hour_val -= 1
                    minute_val = 45
                    consumed.add(j)
                    j += 1
                    break
                mins = extract_number_kab(tokens[j])
                if mins is not False and float(mins).is_integer() and 1 <= mins <= 59:
                    hour_val -= 1
                    minute_val = 60 - int(mins)
                    consumed.add(j)
                    j += 1
                    # optional trailing unit word, e.g. "n ddqayeq"/"n tesdidin"
                    if j < n and norm[j] in _GENITIVE and j + 1 < n:
                        consumed.update({j, j + 1})
                        j += 2
                    break
                # "ɣiṛ" with nothing parseable after it = vague
                hour_val -= 1
                minute_val = 60 - _APPROX_MINUTES
                break

            if tok2 in _GENITIVE and j + 1 < n and norm[j + 1] in _DAY_PERIODS:
                period_tok = norm[j + 1]
                hour_val = _period_to_hour24(hour_val, period_tok)
                consumed.update({j, j + 1})
                j += 2
                continue

            break

        if hour_val < 0:
            hour_val += 12

        hour24 = hour_val % 24
        return hour24, minute_val, consumed

    return None


def nice_time_kab(dt, speech=True, use_24hour=False, use_ampm=False):
    """Format a time to a human-readable string in Kabyle.
    Conforms to native speaker specifications (Mokraoui 2026).
    """
    if not speech:
        return dt.strftime("%H:%M")

    # Spoken Kabyle naturally uses a 12-hour cycle
    hour_12 = dt.hour % 12
    if hour_12 == 0:
        hour_12 = 12

    # Canonical hour words with article assimilation (sun/moon letters)
    hour_words = {
        1: "lweḥda",
        2: "ssaɛtin",    # Regional/Preferred form for 2 o'clock
        3: "ttlata",
        4: "ṛabɛa",
        5: "lxemsa",
        6: "setta",
        7: "ssebɛa",
        8: "ttmanya",
        9: "tesɛa",
        10: "lɛecṛa",
        11: "leḥdac",
        12: "ttnac"
    }

    # Section 3.1: Mandatory presentative "d"
    time_str = f"d {hour_words.get(hour_12, str(hour_12))}"
    minute = dt.minute

    # Section 4.1, 4.5: Handle minutes and fractions
    if minute == 0:
        pass  # Exact hour, no suffix needed (e.g., "d ttmanya")
    elif minute == 15:
        time_str += " u ṛbeɛ"
    elif minute == 30:
        time_str += " u neṣṣ"          # Canonical "neṣṣ"
    elif minute == 45:
        time_str += " ɣiṛ ṛbeɛ"
    else:
        # Section 4.5: Explicit minutes require "u [minute] n ddqayeq"
        # Note: Uses FEMININE numeral forms to agree with "ddqiqa" (minute)
        min_words = {
            1: "yiwet", 2: "snat", 3: "tlata", 4: "ṛebɛa", 5: "xemsa",
            6: "setta", 7: "sebɛa", 8: "tmanya", 9: "tesɛa", 10: "ɛecṛa",
            11: "hḍac", 12: "tnac",
            13: "tleṭṭac", 14: "ṛebɛaṭac", 15: "xemseṭṭac",
            16: "seṭṭac", 17: "sbeɛṭac", 18: "tmenṭac", 19: "tseɛṭac",
            20: "ɛecrin",
            21: "waḥed u ɛecrin", 22: "tnayn u ɛecrin", 23: "tlata u ɛecrin",
            24: "ṛebɛa u ɛecrin", 25: "xemsa u ɛecrin", 26: "setta u ɛecrin",
            27: "sebɛa u ɛecrin", 28: "tmanya u ɛecrin", 29: "tesɛa u ɛecrin",
            30: "tlatin",
            31: "waḥed u tlatin", 32: "tnayn u tlatin", 33: "tlata u tlatin",
            34: "ṛebɛa u tlatin", 35: "xemsa u tlatin", 36: "setta u tlatin",
            37: "sebɛa u tlatin", 38: "tmanya u tlatin", 39: "tesɛa u tlatin",
            40: "rebɛin",
            41: "waḥed u rebɛin", 42: "tnayn u rebɛin", 43: "tlata u rebɛin",
            44: "ṛebɛa u rebɛin", 45: "xemsa u rebɛin", 46: "setta u rebɛin",
            47: "sebɛa u rebɛin", 48: "tmanya u rebɛin", 49: "tesɛa u rebɛin",
            50: "xemsin",
            51: "waḥed u xemsin", 52: "tnayn u xemsin", 53: "tlata u xemsin",
            54: "ṛebɛa u xemsin", 55: "xemsa u xemsin", 56: "setta u xemsin",
            57: "sebɛa u xemsin", 58: "tmanya u xemsin", 59: "tesɛa u xemsin"
        }
        min_word = min_words.get(minute, str(minute))
        time_str += f" u {min_word} n ddqayeq"

    # Section 5: Handle AM/PM or day period context
    if use_ampm:
        if 4 <= dt.hour < 8:
            time_str += " n ṣṣbeḥ"
        elif 8 <= dt.hour < 12:
            time_str += " n ssbeḥ"
        elif 12 <= dt.hour < 15:
            time_str += " n uzal"
        elif 15 <= dt.hour < 20:
            time_str += " n tmeddit"
        else:
            time_str += " n yiḍ"

    return time_str


def extract_duration_kab(text: str) -> Tuple[Optional[timedelta], str]:
    """Extract a duration from Kabyle text.

    Understands digit and spoken quantities followed by an optional "n"
    genitive particle and a time unit ("10 n ddqayeq", "sin wussan").
    """
    if not text:
        return None, text

    unit_seconds = {}
    for w in _SECONDS_UNITS:
        unit_seconds[_normalize(w)] = 1
    for w in _MINUTES_UNITS:
        unit_seconds[_normalize(w)] = 60
    for w in _HOURS_UNITS:
        unit_seconds[_normalize(w)] = 3600
    for w in _DAYS_UNITS:
        unit_seconds[_normalize(w)] = 86400
    for w in _WEEKS_UNITS:
        unit_seconds[_normalize(w)] = 604800

    tokens = text.split()
    total = 0.0
    found = False
    consumed = set()
    i = 0
    while i < len(tokens):
        tok = _normalize(tokens[i].strip(".,!?;:"))
        if tok in unit_seconds:
            # find the quantity immediately before (skipping genitive "n")
            j = i - 1
            if j >= 0 and _normalize(tokens[j].strip(".,!?;:")) == "n":
                j -= 1
            # allow multiword spoken numbers before the unit
            start = j
            value = None
            while start >= 0:
                if start in consumed:
                    break
                candidate = " ".join(tokens[start:j + 1])
                val = extract_number_kab(candidate)
                if val is False:
                    break
                value = val
                start -= 1
            if value is None:
                value = 1
                start = j
            total += value * unit_seconds[tok]
            found = True
            consumed.update(range(start + 1, i + 1))
        i += 1

    if not found:
        return None, text

    remainder = " ".join(t for idx, t in enumerate(tokens)
                         if idx not in consumed)
    return timedelta(seconds=total), remainder.strip()


def extract_datetime_kab(text: str, anchorDate: Optional[datetime] = None,
                         default_time=None):
    """Extract a datetime from Kabyle text.

    Understands the relative day words (azekka "tomorrow", iḍelli
    "yesterday", ass-a "today"), weekday and month names, day-of-month
    numbers, digit clock times ("13:04"), and spoken clock-time
    expressions built on the presentative "d" ("d lɛecṛa u ṛbeɛ",
    "d juǧ n uzal", "d lɛecṛa ɣiṛ xemsa", "nṣaf n yiḍ", ...).
    """
    if not text:
        return None
    anchor = anchorDate or datetime.now()
    tokens = [t.strip(".,!?;:") for t in text.lower().split()]
    norm = [_normalize(t) for t in tokens]

    date_found = False
    result = anchor
    consumed = set()

    rel_days = {_normalize(k): v for k, v in _RELATIVE_DAYS.items()}
    weekdays = {_normalize(v): k for k, v in WEEKDAYS_KAB.items()}
    months = {_normalize(v): k for k, v in MONTHS_KAB.items()}

    for i, tok in enumerate(norm):
        if tok in rel_days:
            result = anchor + timedelta(days=rel_days[tok])
            date_found = True
            consumed.add(i)
        elif tok in weekdays:
            target = weekdays[tok]
            diff = (target - anchor.weekday()) % 7 or 7
            result = anchor + timedelta(days=diff)
            date_found = True
            consumed.add(i)
        elif tok in months:
            month = months[tok]
            day = None
            for j in (i - 1, i + 1):
                if 0 <= j < len(tokens):
                    if j == i + 1 and norm[j] == "n" and j + 1 < len(tokens):
                        j += 1
                    val = extract_number_kab(tokens[j])
                    if val and float(val).is_integer() and 1 <= val <= 31:
                        day = int(val)
                        consumed.add(j)
                        break
            year = anchor.year
            if datetime(year, month, day or 1) < anchor.replace(
                    hour=0, minute=0, second=0, microsecond=0):
                year += 1
            result = result.replace(year=year, month=month, day=day or 1)
            date_found = True
            consumed.add(i)

    time_found = False
    spoken = _extract_spoken_time_kab(tokens, norm)
    if spoken:
        hour, minute, spoken_consumed = spoken
        result = result.replace(hour=hour, minute=minute, second=0,
                                microsecond=0)
        time_found = True
        consumed.update(spoken_consumed)
    else:
        for i, tok in enumerate(tokens):
            m = re.fullmatch(r"(\d{1,2}):(\d{2})", tok)
            if m:
                hour, minute = int(m.group(1)), int(m.group(2))
                if hour < 24 and minute < 60:
                    result = result.replace(hour=hour, minute=minute,
                                            second=0, microsecond=0)
                    time_found = True
                    consumed.add(i)
                    break

    if not date_found and not time_found:
        return None
    if not time_found:
        if default_time:
            result = result.replace(hour=default_time.hour,
                                    minute=default_time.minute,
                                    second=default_time.second,
                                    microsecond=0)
        else:
            result = result.replace(hour=0, minute=0, second=0,
                                    microsecond=0)
    remainder = " ".join(t for idx, t in enumerate(tokens)
                         if idx not in consumed)
    return [result, remainder.strip()]
