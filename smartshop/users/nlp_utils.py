"""Extract profile preferences from free text or a speech transcript.

Handles what speech recognition actually produces: numbers as words ("six feet",
"seventy kilos"), US/UK spellings, feet+inches ("5 feet 8 inches", "5 foot 10",
"5'8\""), Indian-style decimal feet ("5.8 feet" = 5 ft 8 in), and bare numbers
only when the context makes their meaning clear ("I am 22", "weight is 60").
Returned values always match the Profile form's field types and choices.
"""
import logging
import re

logger = logging.getLogger(__name__)

_UNITS = {
    'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7,
    'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11, 'twelve': 12, 'thirteen': 13,
    'fourteen': 14, 'fifteen': 15, 'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19,
}
_TENS = {'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50, 'sixty': 60,
         'seventy': 70, 'eighty': 80, 'ninety': 90}
_NUMBER_WORD = '|'.join(list(_UNITS) + list(_TENS) + ['hundred'])
_NUMBER_PHRASE = re.compile(
    rf'\b(?:{_NUMBER_WORD})(?:[\s-]+(?:and\s+)?(?:{_NUMBER_WORD}))*\b')


def _phrase_to_int(phrase):
    total, current = 0, 0
    for word in re.split(r'[\s-]+', phrase):
        if word == 'and':
            continue
        if word in _UNITS:
            current += _UNITS[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word == 'hundred':
            current = (current or 1) * 100
    return total + current


def words_to_digits(text):
    """'five feet eight inches' -> '5 feet 8 inches'; 'one hundred seventy five' -> '175'."""
    text = _NUMBER_PHRASE.sub(lambda m: str(_phrase_to_int(m.group())), text)
    # "five point eight" -> "5.8"
    return re.sub(r'(\d+)\s+point\s+(\d+)', r'\1.\2', text)


def _normalise(text):
    text = text.lower().replace('’', "'").replace('″', '"').replace('′', "'")
    text = words_to_digits(text)
    return re.sub(r'\s+', ' ', text)


NUM = r'(\d+(?:\.\d+)?)'
FEET = r"(?:feet|foot|ft|')"
INCHES = r'(?:inches|inch|in\b|")'
CM = r'(?:cm|cms|centimet(?:er|re)s?)\b'
METRES = r'(?:m|mtr|mtrs|met(?:er|re)s?)\b'
KG = r'(?:kg|kgs|kilo|kilos|kilogram|kilograms)\b'
LBS = r'(?:lb|lbs|pound|pounds)\b'


def _height_cm(t):
    # 5 feet 8 inches / 5 foot 10 / 5'8" / 5 ft 6 in
    m = re.search(rf"\b(\d)\s*{FEET}\s*(?:and\s*)?(\d{{1,2}})\b(?:\s*{INCHES})?", t)
    if m and int(m.group(2)) < 12:
        return int(m.group(1)) * 30.48 + int(m.group(2)) * 2.54
    # 5.8 feet -> Indian convention: 5 ft 8 in (when the part after the dot is 0-11)
    m = re.search(rf'\b(\d)\.(\d{{1,2}})\s*{FEET}', t)
    if m:
        feet, frac = int(m.group(1)), m.group(2)
        if int(frac) < 12:
            return feet * 30.48 + int(frac) * 2.54
        return float(f'{feet}.{frac}') * 30.48
    m = re.search(rf'\b(\d)\s*{FEET}', t)
    if m:
        return int(m.group(1)) * 30.48
    m = re.search(rf'\b{NUM}\s*{CM}', t)
    if m:
        return float(m.group(1))
    m = re.search(rf'\b(\d(?:\.\d+)?)\s*{METRES}', t)
    if m and 1 <= float(m.group(1)) <= 2.5:
        return float(m.group(1)) * 100
    m = re.search(rf'\b(\d{{2}})\s*{INCHES}', t)
    if m:
        return int(m.group(1)) * 2.54
    # "height is 175" / "175 tall" with no unit: assume cm when plausible
    m = re.search(r'\bheight\s*(?:is|of|=)?\s*(\d{3})\b', t) or re.search(r'\b(\d{3})\s*tall\b', t)
    if m:
        return float(m.group(1))
    return None


def _weight_kg(t):
    m = re.search(rf'\b{NUM}\s*{KG}', t)
    if m:
        return float(m.group(1))
    m = re.search(rf'\b{NUM}\s*{LBS}', t)
    if m:
        return float(m.group(1)) * 0.453592
    m = re.search(r'\bweigh(?:t|ing|s)?\s*(?:is|of|about|around|=)?\s*(\d{2,3})\b(?!\s*(?:cm|years?|yrs?))', t)
    if m:
        return float(m.group(1))
    return None


def _age(t):
    m = (re.search(r'\b(\d{2})\s*(?:years?|yrs?|yo)\b', t)
         or re.search(r'\bage(?:d)?\s*(?:is|of|=)?\s*(\d{2})\b', t)
         # "I am 22" / "I'm 22" but not "I am 5 feet" or "I am 70 kg"
         or re.search(r"\b(?:i am|i'm|im)\s+(\d{2})\b(?!\s*(?:\.\d|feet|foot|ft|'|cm|kg|kgs|kilo|inch|lb|pound))", t))
    if m:
        age = int(m.group(1))
        if 13 <= age <= 110:
            return age
    return None


AGE_GROUPS = [((18, 24), '18-24'), ((25, 34), '25-34'), ((35, 44), '35-44'),
              ((45, 54), '45-54'), ((55, 120), '55+')]

DEPARTMENTS = {
    'Men': r"\b(?:men|men's|mens|man|male|boys?|gents|guys?)\b",
    'Women': r"\b(?:women|women's|womens|woman|female|girls?|ladies|lady)\b",
}

# Only values that exist in Profile.FIT_CHOICES
FITS = {
    'slim': r'\b(?:slim|skinny|tight|fitted|athletic|muscle)\b',
    'regular': r'\b(?:regular|standard|normal|classic)\b',
    'relaxed': r'\b(?:relaxed|comfort|comfortable)\b',
    'loose': r'\b(?:loose|baggy|oversized|over sized)\b',
}


def _earliest(patterns, t):
    """The key whose pattern appears first in the text (handles 'a man shopping for women')."""
    hits = [(m.start(), key) for key, pattern in patterns.items() if (m := re.search(pattern, t))]
    return min(hits)[1] if hits else None


def extract_preferences_from_text(text):
    t = _normalise(text or '')
    data = {}

    department = _earliest(DEPARTMENTS, t)
    if department:
        data['preferred_department'] = department

    height = _height_cm(t)
    if height and 50 <= height <= 250:
        data['height_cm'] = round(height)

    weight = _weight_kg(t)
    if weight and 20 <= weight <= 300:
        data['weight_kg'] = round(weight)

    age = _age(t)
    if age:
        for (low, high), group in AGE_GROUPS:
            if low <= age <= high:
                data['age_group'] = group
                break

    fit = _earliest(FITS, t)
    if fit:
        data['preferred_fit'] = fit

    logger.debug('Preference extraction: %r -> %r', text, data)
    return data
