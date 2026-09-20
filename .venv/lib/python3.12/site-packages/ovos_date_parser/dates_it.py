import re
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from ovos_number_parser.numbers_it import extract_number_it, pronounce_number_it
from ovos_utils.time import now_local, DAYS_IN_1_MONTH, DAYS_IN_1_YEAR
from ovos_number_parser import numbers_to_digits
from ovos_date_parser.duration import (
    DurationResolution, DURATION_LEXICONS, extract_duration_generic
)


def nice_time_it(dt, speech=True, use_24hour=False, use_ampm=False):
    """
    Format a time to a comfortable human format
    adapted to italian fron en version

    For example, generate 'cinque e trenta' for speech or '5:30' for
    text display.

    Args:
        dt (datetime): date to format (assumes already in local timezone)
        speech (bool): format for speech (default/True) or display (False)=Fal
        use_24hour (bool): output in 24-hour/military or 12-hour format
        use_ampm (bool): include the am/pm for 12-hour format
    Returns:
        (str): The formatted time string
    """
    if use_24hour:
        # e.g. "03:01" or "14:22"
        string = dt.strftime("%H:%M")
    else:
        if use_ampm:
            # e.g. "3:01 AM" or "2:22 PM"
            string = dt.strftime("%I:%M %p")
        else:
            # e.g. "3:01" or "2:22"
            string = dt.strftime("%I:%M")
        if string[0] == '0':
            string = string[1:]  # strip leading zeros

    if not speech:
        return string

    # Generate a speakable version of the time
    if use_24hour:
        speak = ""
        # Either "zero 8 zerozero" o "13 zerozero"
        if string[0:2] == '00':
            speak += "zerozero"
        elif string[0] == '0':
            speak += pronounce_number_it(int(string[0])) + " "
            if int(string[1]) == 1:
                speak = "una"
            else:
                speak += pronounce_number_it(int(string[1]))
        else:
            speak = pronounce_number_it(int(string[0:2]))

        # in italian  "13 e 25"
        speak += " e "

        if string[3:5] == '00':
            speak += "zerozero"
        else:
            if string[3] == '0':
                speak += pronounce_number_it(0) + " "
                speak += pronounce_number_it(int(string[4]))
            else:
                speak += pronounce_number_it(int(string[3:5]))
        return speak
    else:
        if dt.hour == 0 and dt.minute == 0:
            return "mezzanotte"
        if dt.hour == 12 and dt.minute == 0:
            return "mezzogiorno"
        # TODO: "10 e un quarto", "4 e tre quarti" and ot her idiomatic times

        if dt.hour == 0:
            speak = "mezzanotte"
        elif dt.hour == 1 or dt.hour == 13:
            speak = "una"
        elif dt.hour > 13:  # era minore
            speak = pronounce_number_it(dt.hour - 12)
        else:
            speak = pronounce_number_it(dt.hour)

        speak += " e"
        if dt.minute == 0:
            speak = speak[:-2]
            if not use_ampm:
                speak += " in punto"
        elif dt.minute == 15:
            speak += " un quarto"
        elif dt.minute == 45:
            speak += " tre quarti"
        else:
            if dt.minute < 10:
                speak += " zero"
            speak += " " + pronounce_number_it(dt.minute)

        if use_ampm:

            if dt.hour < 4:
                speak.strip()
            elif dt.hour > 20:
                speak += " della notte"
            elif dt.hour > 17:
                speak += " della sera"
            elif dt.hour > 12:
                speak += " del pomeriggio"
            else:
                speak += " della mattina"

        return speak


def extract_datetime_it(text, anchorDate=None, default_time=None):
    def clean_string(s):
        """
            cleans the input string of unneeded punctuation and capitalization
            among other things.
            Normalize italian plurals
        """
        symbols = ['.', ',', ';', '?', '!', 'º', 'ª', '°', 'l\'']

        for word in symbols:
            s = s.replace(word, '')

        s = s.lower().replace('á', 'a').replace('à', 'a').replace('è', "e'") \
            .replace('é', "e'").replace('ì', 'i').replace('ù', 'u') \
            .replace('ò', 'o').replace('-', ' ').replace('_', '')

        # normalizza plurali per semplificare analisi
        s = s.replace('secondi', 'secondo').replace('minuti', 'minuto') \
            .replace('ore', 'ora').replace('giorni', 'giorno') \
            .replace('settimane', 'settimana').replace('mesi', 'mese') \
            .replace('anni', 'anno').replace('mattino', 'mattina') \
            .replace('prossima', 'prossimo').replace('questa', 'questo') \
            .replace('quarti', 'quarto').replace('in punto', 'in_punto') \
            .replace('decennio', 'decenni').replace('secoli', 'secolo') \
            .replace('millennio', 'millenni').replace(' un ', ' uno ') \
            .replace('scorsa', 'scorso').replace('passata', 'passato') \
            .replace('uno paio', 'due')

        noise_words = ['dello', 'la', 'del', 'al', 'il', 'di', 'tra', 'lo',
                       'le', 'alle', 'alla', 'dai', 'delle', 'della',
                       'a', 'e\'', 'era', 'questa', 'questo', 'e', 'nel',
                       'nello', 'dallo', '  ']

        word_list = s.split()
        word_list = [x for x in word_list if x not in noise_words]
        # normalizza alcuni formati orari
        for idx in range(0, len(word_list) - 1):
            if word_list[idx][0].isdigit() and word_list[idx + 1][0].isdigit():
                num0 = int(word_list[idx])
                num1 = int(word_list[idx + 1])
                if 0 <= num0 <= 23 and 10 <= num1 <= 59:
                    word_list[idx] = str(num0) + ':' + str(num1)
                    word_list[idx + 1] = ''

        word_list = [x for x in word_list if x]

        return word_list

    def date_found():
        return found or \
            (datestr != '' or time_str != '' or year_offset != 0 or
             month_offset != 0 or day_offset is True or hr_offset != 0 or
             hr_abs or min_offset != 0 or min_abs or sec_offset != 0)

    if text == '':
        return None
    anchorDate = anchorDate or now_local()
    found = False
    day_specified = False
    day_offset = False
    month_offset = 0
    year_offset = 0
    today = anchorDate.strftime('%w')
    current_year = anchorDate.strftime('%Y')
    from_flag = False
    datestr = ''
    has_year = False
    time_qualifier = ''
    time_qualifiers_am = ['mattina', 'stamani', 'stamane']
    time_qualifiers_pm = ['pomeriggio', 'sera', 'stasera', 'stanotte']
    time_qualifiers_list = set(time_qualifiers_am + time_qualifiers_pm)
    markers = ['alle', 'in', 'questo', 'per', 'di', 'tra', 'fra', 'entro']
    days = ['lunedi', 'martedi', 'mercoledi',
            'giovedi', 'venerdi', 'sabato', 'domenica']
    months = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno',
              'luglio', 'agosto', 'settembre', 'ottobre', 'novembre',
              'dicembre']
    months_short = ['gen', 'feb', 'mar', 'apr', 'mag', 'giu', 'lug', 'ago',
                    'set', 'ott', 'nov', 'dic']
    year_multiples = ['decenni', 'secolo', 'millenni']  # decennio <- decenni
    time_multiples = ['ora', 'minuto', 'secondo']
    day_multiples = ['settimana', 'mese', 'anno']
    noise_words_2 = ['tra', 'di', 'per', 'fra', 'un ', 'uno', 'lo', 'del',
                     'l', 'in_punto', ' ', 'nella', 'dell']

    words = clean_string(text)

    for idx, word in enumerate(words):
        if word == '':
            continue
        word_prev_prev = words[idx - 2] if idx > 1 else ''
        word_prev = words[idx - 1] if idx > 0 else ''
        word_next = words[idx + 1] if idx + 1 < len(words) else ''
        word_next_next = words[idx + 2] if idx + 2 < len(words) else ''
        start = idx
        used = 0
        # save timequalifier for later
        if word == 'adesso' and not datestr:
            # word == 'ora' va in conflitto con 'tra un ora'
            words = [x for x in words if x != 'adesso']
            words = [x for x in words if x]
            result_str = ' '.join(words)
            extracted_date = anchorDate.replace(microsecond=0)
            return [extracted_date, result_str]

        # un paio di  o  tra tre settimane --> secoli
        elif extract_number_it(word) and (word_next in year_multiples or
                                          word_next in day_multiples):
            multiplier = int(extract_number_it(word))
            used += 2
            # "N <periodo> fa" = N periods in the past (Treccani)
            if word_next_next == 'fa':
                multiplier = -multiplier
                used += 1
            if word_next == 'decenni':
                year_offset = multiplier * 10
            elif word_next == 'secolo':
                year_offset = multiplier * 100
            elif word_next == 'millenni':
                year_offset = multiplier * 1000
            elif word_next == 'anno':
                year_offset = multiplier
            elif word_next == 'mese':
                month_offset = multiplier
            elif word_next == 'settimana':
                day_offset = multiplier * 7
        elif word in time_qualifiers_list:
            time_qualifier = word
        # parse today, tomorrow, day after tomorrow
        elif word == 'oggi' and not from_flag:
            day_offset = 0
            used += 1
        elif word == 'domani' and not from_flag:
            day_offset = 1
            used += 1
        elif word == 'ieri' and not from_flag:
            day_offset -= 1
            used += 1
        elif word == 'dopodomani' and not from_flag:  # after tomorrow
            day_offset += 2
            used += 1
        elif word == 'dopo' and word_next == 'domani' and not from_flag:
            day_offset += 1
            used += 2
        elif word == 'giorno':
            if word_prev and word_prev[0].isdigit():
                # "N giorni fa" = N days in the past (Treccani)
                if word_next == 'fa':
                    day_offset -= int(word_prev)
                    used += 1
                else:
                    day_offset += int(word_prev)
                start -= 1
                used += 2
                if word_next == 'dopo' and word_next_next == 'domani':
                    day_offset += 1
                    used += 2
        elif word == 'settimana' and not from_flag:
            if word_prev == 'prossimo':
                day_offset = 7
                start -= 1
                used = 2
            elif word_prev == 'passato' or word_prev == 'scorso':
                day_offset = -7
                start -= 1
                used = 2
            elif word_next == 'prossimo':
                day_offset = 7
                used += 2
            elif word_next == 'passato' or word_next == 'scorso':
                day_offset = -7
                used += 2
        # parse next month, last month
        elif word == 'mese' and not from_flag:
            if word_prev == 'prossimo':
                month_offset = 1
                start -= 1
                used = 2
            elif word_prev == 'passato' or word_prev == 'scorso':
                month_offset = -1
                start -= 1
                used = 2
            elif word_next == 'prossimo':
                month_offset = 1
                used += 2
            elif word_next == 'passato' or word_next == 'scorso':
                month_offset = -1
                used += 2
        # parse next year, last year
        elif word == 'anno' and not from_flag:
            if word_prev == 'prossimo':  # prossimo anno
                year_offset = 1
                start -= 1
                used = 2
            elif word_next == 'prossimo':  # anno prossimo
                year_offset = 1
                used = 2
            elif word_prev == 'passato' or word_prev == 'scorso':
                year_offset = -1
                start -= 1
                used = 2
            elif word_next == 'passato' or word_next == 'scorso':
                year_offset = -1
                used = 2
        elif word == 'decenni' and not from_flag:
            if word_prev == 'prossimo':  # prossimo mese
                year_offset = 10
                start -= 1
                used = 2
            elif word_next == 'prossimo':  # mese prossimo
                year_offset = 10
                used = 2
            elif word_prev == 'passato' or word_prev == 'scorso':
                year_offset = -10
                start -= 1
                used = 2
            elif word_next == 'passato' or word_next == 'scorso':
                year_offset = -10
                used = 2
        # parse Monday, Tuesday, etc., and next Monday,
        # last Tuesday, etc.
        elif word in days and not from_flag:
            ddd = days.index(word)
            day_offset = (ddd + 1) - int(today)
            used = 1
            if day_offset < 0:
                day_offset += 7
            if word_prev == 'prossimo':
                day_offset += 7
                start -= 1
                used += 1
            elif word_prev == 'passato' or word_prev == 'scorso':
                day_offset -= 7
                start -= 1
                used += 1
            if word_next == 'prossimo':
                day_offset += 7
                used += 1
            elif word_next == 'passato' or word_next == 'scorso':
                day_offset -= 7
                used += 1
        # parse 15 of July, June 20th, Feb 18, 19 of February
        elif word in months or word in months_short and not from_flag:
            try:
                mmm = months.index(word)
            except ValueError:
                mmm = months_short.index(word)
            used += 1
            datestr = months[mmm]
            if word_prev and extract_number_it(word_prev):
                datestr += ' ' + str(int(extract_number_it(word_prev)))
                start -= 1
                used += 1
                # only a value large enough to be a year (never a clock
                # hour or a day-of-month) may follow the day as the year
                _yr = extract_number_it(word_next) if word_next else False
                if _yr and int(_yr) >= 100:
                    datestr += ' ' + str(int(_yr))
                    used += 1
                    has_year = True
                else:
                    has_year = False
            elif word_next and word_next[0].isdigit():
                datestr += ' ' + word_next
                used += 1
                if word_next_next and word_next_next[0].isdigit() \
                        and int(word_next_next) >= 100:
                    datestr += ' ' + word_next_next
                    used += 1
                    has_year = True
                else:
                    has_year = False
        # parse 5 days from tomorrow, 10 weeks from next thursday,
        # 2 months from July
        validFollowups = days + months + months_short
        validFollowups.append('oggi')
        validFollowups.append('domani')
        validFollowups.append('prossimo')
        validFollowups.append('passato')
        validFollowups.append('adesso')

        if (word == 'da' or word == 'dopo') and word_next in validFollowups:
            used = 0
            from_flag = True
            if word_next == 'domani':
                day_offset += 1
                used += 2
            elif word_next == 'oggi' or word_next == 'adesso':
                used += 2
            elif word_next in days:
                ddd = days.index(word_next)
                tmp_offset = (ddd + 1) - int(today)
                used += 2
                if tmp_offset < 0:
                    tmp_offset += 7
                if word_next_next == 'prossimo':
                    tmp_offset += 7
                    used += 1
                elif word_next_next == 'passato' or word_next_next == 'scorso':
                    tmp_offset = (ddd + 1) - int(today)
                    used += 1
                day_offset += tmp_offset
            elif word_next_next and word_next_next in days:
                ddd = days.index(word_next_next)
                tmp_offset = (ddd + 1) - int(today)
                if word_next == 'prossimo':
                    tmp_offset += 7
                # elif word_next == 'passato' or word_next == 'scorso':
                #    tmp_offset -= 7
                day_offset += tmp_offset
                used += 3

        if used > 0:
            if start - 1 > 0 and words[start - 1] == 'questo':
                start -= 1
                used += 1

            for i in range(0, used):
                words[i + start] = ''

            if start - 1 >= 0 and words[start - 1] in markers:
                words[start - 1] = ''
            found = True
            day_specified = True

    # spoken clock hours ("alle tre", "domani alle otto") must reach the
    # digit-based time parser just like "alle 3" does; the indefinite
    # article and the fraction words keep their own meaning and are left
    # untouched
    # the duration-unit words must survive: "secondo" is also the ordinal
    # "second", so converting it to a digit would turn "15 secondo" into
    # "15 2" and lose the seconds offset
    _keep_words = {'un', 'uno', 'una', "un'", 'mezzo', 'mezza', 'mezzora',
                   'quarto', 'quarti', 'paio', 'secondo', 'minuto', 'ora'}
    for _i, _w in enumerate(words):
        if not _w or _w[0].isdigit() or _w in _keep_words:
            continue
        _n = extract_number_it(_w)
        if _n is not False and _n is not None and float(_n) == int(_n) \
                and 1 <= int(_n) <= 24:
            words[_i] = str(int(_n))

    # parse time
    time_str = ''
    hr_offset = 0
    min_offset = 0
    sec_offset = 0
    hr_abs = None
    min_abs = None
    military = False

    for idx, word in enumerate(words):
        if word == '':
            continue
        word_prev_prev = words[idx - 2] if idx > 1 else ''
        word_prev = words[idx - 1] if idx > 0 else ''
        word_next = words[idx + 1] if idx + 1 < len(words) else ''
        word_next_next = words[idx + 2] if idx + 2 < len(words) else ''
        # parse noon, midnight, morning, afternoon, evening
        used = 0
        if word == 'mezzogiorno':
            hr_abs = 12
            used += 1
        elif word == 'mezzanotte':
            hr_abs = 24
            used += 1
        if word == 'mezzo' and word_next == 'giorno':
            hr_abs = 12
            used += 2
        elif word == 'mezza' and word_next == 'notte':
            hr_abs = 24
            used += 2
        elif word == 'mattina':
            if not hr_abs:
                hr_abs = 8
            used += 1
            if word_next and word_next[0].isdigit():  # mattina alle 5
                hr_abs = int(word_next)
                used += 1
        elif word == 'pomeriggio':
            if not hr_abs:
                hr_abs = 15
            used += 1
            if word_next and word_next[0].isdigit():  # pomeriggio alle 5
                hr_abs = int(word_next)
                used += 1
                if (hr_abs or 0) < 12:
                    hr_abs = (hr_abs or 0) + 12
        elif word == 'sera':
            if not hr_abs:
                hr_abs = 19
            used += 1
            if word_next and word_next[0].isdigit() \
                    and ':' not in word_next:
                hr_abs = int(word_next)
                used += 1
                if (hr_abs or 0) < 12:
                    hr_abs = (hr_abs or 0) + 12
        # da verificare più a fondo
        elif word == 'presto':
            hr_abs -= 1
            used += 1
        elif word == 'tardi':
            hr_abs += 1
            used += 1
        # un paio di minuti  tra cinque minuti tra 5 ore
        elif extract_number_it(word) and (word_next in time_multiples):
            d_time = int(extract_number_it(word))
            used += 2
            if word_next == 'ora':
                hr_offset = d_time
                isTime = False
                hr_abs = -1
                min_abs = -1
            elif word_next == 'minuto':
                min_offset = d_time
                isTime = False
                hr_abs = -1
                min_abs = -1
            elif word_next == 'secondo':
                sec_offset = d_time
                isTime = False
                hr_abs = -1
                min_abs = -1
        elif word == 'mezzora':
            min_offset = 30
            used = 1
            isTime = False
            hr_abs = -1
            min_abs = -1
            # if word_prev == 'uno' or word_prev == 'una':
            #    start -= 1
            #    used += 1
        elif extract_number_it(word) and word_next and \
                word_next == 'quarto' and word_next_next == 'ora':
            if int(extract_number_it(word)) == 1 \
                    or int(extract_number_it(word)) == 3:
                min_offset = 15 * int(extract_number_it(word))
            else:  # elimina eventuali errori
                min_offset = 15
            used = 3
            start -= 1
            isTime = False
            hr_abs = -1
            min_abs = -1
        elif word and word[0].isdigit():
            isTime = True
            str_hh = ''
            str_mm = ''
            remainder = ''
            # digits-only prefix, so tokens like "20h" or "21h30" that glue a
            # letter suffix onto a number do not crash int() below
            str_num = ''
            for ch in word:
                if ch.isdigit():
                    str_num += ch
                else:
                    break
            if ':' in word:
                # parse colons
                # '3:00 in the morning'
                components = word.split(':')
                if len(components) == 2:
                    num0 = int(extract_number_it(components[0]))
                    num1 = int(extract_number_it(components[1]))
                    if num0 is not False and num1 is not False \
                            and 0 <= num0 <= 23 and 0 <= num1 <= 59:
                        str_hh = str(num0)
                        str_mm = str(num1)
            elif str_num and 0 < int(str_num) < 24 \
                    and word_next != 'quarto':
                str_hh = str(int(str_num))
                str_mm = '00'
            elif str_num and 100 <= int(str_num) <= 2400:
                str_hh = int(str_num) / 100
                str_mm = int(str_num) - str_hh * 100
                military = True
                isTime = False
            if extract_number_it(word) and word_next \
                    and word_next == 'quarto' and word_next_next != 'ora':
                if int(extract_number_it(word)) == 1 \
                        or int(extract_number_it(word)) == 3:
                    str_mm = str(15 * int(extract_number_it(word)))
                else:  # elimina eventuali errori
                    str_mm = '0'
                str_hh = str(hr_abs)
                used = 2
                words[idx + 1] = ''
                isTime = False
            if extract_number_it(word) and word_next \
                    and word_next == 'in_punto':
                str_hh = str(int(extract_number_it(word)))
                used = 2
            if str_hh == '':
                # a bare number that is not a valid clock value
                # (e.g. "99", "25:99", "24:00", out-of-range hours/minutes)
                # is not a time - ignore it rather than crashing on int('')
                isTime = False
                used = 0
            elif word_next == 'pm':
                remainder = 'pm'
                hr_abs = int(str_hh)
                min_abs = int(str_mm)
                if hr_abs <= 12:
                    hr_abs = hr_abs + 12
                used = 2
            elif word_next == 'am':
                remainder = 'am'
                hr_abs = int(str_hh)
                min_abs = int(str_mm)
                used = 2
            elif word_next == 'mattina':
                # ' 11 del mattina'
                hh = int(str_hh)
                mm = int(str_mm)
                used = 2
                remainder = 'am'
                isTime = False
                hr_abs = hh
                min_abs = mm
            elif word_next == 'pomeriggio':
                # ' 2 del pomeriggio'
                hh = int(str_hh)
                mm = int(str_mm)
                if hh < 12:
                    hh += 12
                used = 2
                remainder = 'pm'
                isTime = False
                hr_abs = hh
                min_abs = mm
            elif word_next == 'sera':
                # 'alle 8 di sera'
                hh = int(str_hh)
                mm = int(str_mm)
                if hh < 12:
                    hh += 12
                used = 2
                remainder = 'pm'
                isTime = False
                hr_abs = hh
                min_abs = mm
            elif word_next == 'notte':
                hh = int(str_hh)
                mm = int(str_mm)
                if hh > 5:
                    remainder = 'pm'
                else:
                    remainder = 'am'
                used = 2
                isTime = False
                hr_abs = hh
                min_abs = mm
            # parse half an hour : undici e mezza
            elif word_next and word_next == 'mezza':
                hr_abs = int(str_hh)
                min_abs = 30
                used = 2
                isTime = False
            elif word_next and word_next == 'in_punto':
                hr_abs = int(str_hh)
                min_abs = 0
                str_mm = '0'
                used = 2
                isTime = False
            else:
                # 17:30
                remainder = ''
                hr_abs = int(str_hh)
                min_abs = int(str_mm)
                used = 1
                isTime = False
                if word_prev == 'ora':
                    words[idx - 1] = ''

            if time_qualifier != '':
                # military = True
                if str_hh and int(str_hh) <= 12 and \
                        (time_qualifier in time_qualifiers_pm):
                    str_hh = str(int(str_hh) + 12)
            else:
                isTime = False

            str_hh = int(str_hh) if str_hh else 0
            str_mm = int(str_mm) if str_mm else 0

            str_hh = str_hh + 12 if remainder == 'pm' \
                                    and str_hh < 12 else str_hh
            str_hh = str_hh - 12 if remainder == 'am' \
                                    and str_hh >= 12 else str_hh

            if (not military and
                    remainder not in ['am', 'pm'] and
                    ((not day_specified) or day_offset < 1)):
                # ambiguous time, detect whether they mean this evening or
                # the next morning based on whether it has already passed
                hr_abs = str_hh
                if anchorDate.hour < str_hh:
                    pass  # No modification needed
                elif anchorDate.hour < str_hh + 12:
                    str_hh += 12
                    hr_abs = str_hh
                else:
                    # has passed, assume the next morning
                    day_offset += 1

            if time_qualifier in time_qualifiers_pm and str_hh < 12:
                str_hh += 12

            if str_hh > 24 or str_mm > 59:
                isTime = False
                used = 0
            if isTime:
                hr_abs = str_hh * 1
                min_abs = str_mm * 1
                used += 1

            if (hr_abs or 0) <= 12 and (time_qualifier == 'sera' or
                                        time_qualifier == 'pomeriggio'):
                hr_abs = (hr_abs or 0) + 12

        if used > 0:
            # removed parsed words from the sentence
            for i in range(used):
                words[idx + i] = ''

            if word_prev == 'o' or word_prev == 'oh':
                words[words.index(word_prev)] = ''

            if idx > 0 and word_prev in markers:
                words[idx - 1] = ''
            if idx > 1 and word_prev_prev in markers:
                words[idx - 2] = ''

            idx += used - 1
            found = True

    # check that we found a date
    if not date_found():
        return None

    if day_offset is False:
        day_offset = 0

    # perform date manipulation

    extracted_date = anchorDate.replace(microsecond=0)

    if datestr != '':
        en_months = ['january', 'february', 'march', 'april', 'may', 'june',
                     'july', 'august', 'september', 'october', 'november',
                     'december']
        en_months_short = ['jan', 'feb', 'mar', 'apr', 'may', 'june', 'july',
                           'aug', 'sept', 'oct', 'nov', 'dec']

        for idx, en_month in enumerate(en_months):
            datestr = re.sub(r"\b" + re.escape(months[idx]) + r"\b", en_month, datestr)

        for idx, en_month in enumerate(en_months_short):
            datestr = datestr.replace(months_short[idx], en_month)

        temp = None
        for _fmt in ('%B %d', '%B %d %Y', '%B'):
            try:
                temp = datetime.strptime(datestr, _fmt)
                # a bare month with no day ("a giugno"): first of the month
                has_year = has_year and _fmt == '%B %d %Y'
                break
            except ValueError:
                continue
        extracted_date = extracted_date.replace(hour=0, minute=0, second=0)
        if temp is None:
            # unparseable day/month ("il 99 dicembre"): leave the date alone
            pass
        elif not has_year:
            temp = temp.replace(year=extracted_date.year,
                                tzinfo=extracted_date.tzinfo)
            if extracted_date < temp:
                extracted_date = extracted_date.replace(
                    year=int(current_year),
                    month=int(temp.strftime('%m')),
                    day=int(temp.strftime('%d')),
                    tzinfo=extracted_date.tzinfo)
            else:
                extracted_date = extracted_date.replace(
                    year=int(current_year) + 1,
                    month=int(temp.strftime('%m')),
                    day=int(temp.strftime('%d')),
                    tzinfo=extracted_date.tzinfo)
        else:
            extracted_date = extracted_date.replace(
                year=int(temp.strftime('%Y')),
                month=int(temp.strftime('%m')),
                day=int(temp.strftime('%d')),
                tzinfo=extracted_date.tzinfo)
    else:
        # ignore the current HH:MM:SS if relative using days or greater
        if hr_offset == 0 and min_offset == 0 and sec_offset == 0:
            extracted_date = extracted_date.replace(hour=0, minute=0, second=0)

    if year_offset != 0:
        extracted_date = extracted_date + relativedelta(years=year_offset)
    if month_offset != 0:
        extracted_date = extracted_date + relativedelta(months=month_offset)
    if day_offset != 0:
        extracted_date = extracted_date + relativedelta(days=day_offset)
    if hr_abs != -1 and min_abs != -1:
        # If no time was supplied in the string set the time to default
        # time if it's available
        if hr_abs is None and min_abs is None and default_time is not None:
            hr_abs, min_abs = default_time.hour, default_time.minute
        else:
            hr_abs = hr_abs or 0
            min_abs = min_abs or 0

        extracted_date = extracted_date + relativedelta(hours=hr_abs,
                                                        minutes=min_abs)
        if (hr_abs != 0 or min_abs != 0) and datestr == '':
            if not day_specified and anchorDate > extracted_date:
                extracted_date = extracted_date + relativedelta(days=1)
    if hr_offset != 0:
        extracted_date = extracted_date + relativedelta(hours=hr_offset)
    if min_offset != 0:
        extracted_date = extracted_date + relativedelta(minutes=min_offset)
    if sec_offset != 0:
        extracted_date = extracted_date + relativedelta(seconds=sec_offset)

    words = [x for x in words if x not in noise_words_2]
    words = [x for x in words if x]
    result_str = ' '.join(words)

    return [extracted_date, result_str]


def extract_duration_it(text, resolution=DurationResolution.TIMEDELTA,
                        replace_token=""):
    """
    Convert a phrase into a duration and return the remainder text.

    The words used in the duration are consumed, the remainder of the
    text is returned. Returns None for empty input; the duration is
    None if no duration was found.

    Args:
        text (str): string containing a duration.
        resolution (DurationResolution): format to return the duration in.
        replace_token (str): string each consumed duration is replaced with.
    Returns:
        (duration, str): the duration (timedelta, relativedelta or float
                         depending on resolution) and the remaining
                         unconsumed text.
    """
    return extract_duration_generic(text, DURATION_LEXICONS["it"],
                                    resolution, replace_token)
