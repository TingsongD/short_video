"""M5 voice text: TTS-clean version of the script — numbers spelled out,
contractions expanded, markdown/emoji stripped."""
import re

_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]

_ORD_ONES = [
    "zeroth", "first", "second", "third", "fourth", "fifth", "sixth",
    "seventh", "eighth", "ninth", "tenth", "eleventh", "twelfth",
    "thirteenth", "fourteenth", "fifteenth", "sixteenth", "seventeenth",
    "eighteenth", "nineteenth",
]
_ORD_TENS = ["", "", "twentieth", "thirtieth", "fortieth", "fiftieth",
             "sixtieth", "seventieth", "eightieth", "ninetieth"]

_CONTRACTIONS = {
    "you're": "you are", "i've": "I have", "we've": "we have",
    "they've": "they have", "don't": "do not", "doesn't": "does not",
    "didn't": "did not", "can't": "cannot", "cannot": "cannot",
    "won't": "will not", "it's": "it is", "that's": "that is",
    "there's": "there is", "isn't": "is not", "aren't": "are not",
    "wasn't": "was not", "weren't": "were not", "couldn't": "could not",
    "shouldn't": "should not", "wouldn't": "would not", "i'm": "I am",
    "we'll": "we will", "you'll": "you will", "they'll": "they will",
    "i'll": "I will", "he's": "he is", "she's": "she is", "let's": "let us",
    "haven't": "have not", "hasn't": "has not", "hadn't": "had not",
    "you've": "you have", "we're": "we are", "they're": "they are",
    "what's": "what is", "here's": "here is",
}


def _num_words(n):
    n = int(n)
    if n < 0:
        return "minus " + _num_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return _TENS[t] + (" " + _ONES[o] if o else "")
    if n < 1000:
        h, r = divmod(n, 100)
        return _ONES[h] + " hundred" + (" " + _num_words(r) if r else "")
    return " ".join(_num_words(int(d)) for d in str(n))


def _ord_words(n):
    n = int(n)
    if n < 20:
        return _ORD_ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return _ORD_TENS[t] if not o else f"{_TENS[t]} {_ORD_ONES[o]}"
    if n % 100 == 0:
        return _num_words(n // 100) + " hundredth"
    return _num_words(n) + "th"


def _expand_contractions(text):
    def repl(m):
        w = m.group(0)
        rep = _CONTRACTIONS.get(w.lower())
        if rep is None:
            return w
        return rep.capitalize() if w[0].isupper() else rep
    return re.sub(r"[A-Za-z]+'[a-z]+", repl, text)


def clean(script):
    t = re.sub(r"[*_`#>\[\]~|]", " ", script)
    t = re.sub(
        r"[\U0001F300-\U0001FAFF\U00002702-\U000027B0\U0001F000-\U0001F02F]+",
        " ", t,
    )
    t = _expand_contractions(t)
    t = re.sub(r"\b(\d+)(st|nd|rd|th)\b",
               lambda m: _ord_words(m.group(1)), t, flags=re.IGNORECASE)
    t = re.sub(r"\b(\d+)\b", lambda m: _num_words(m.group(1)), t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s+([.,!?;:])", r"\1", t)
    return t.strip()
