import unicodedata
import re

# Character substitution map — keeps special letters readable in ASCII
_CHAR_MAP = str.maketrans({
    # Polish / Czech stroke
    "ł": "l",  "Ł": "L",
    # German sharp-s
    "ß": "ss",
    # Scandinavian
    "ø": "o",  "Ø": "O",
    "æ": "ae", "Æ": "AE",
    "å": "a",  "Å": "A",
    # Ligatures
    "œ": "oe", "Œ": "OE",
    # Icelandic / Old English
    "ð": "d",  "Ð": "D",
    "þ": "th", "Þ": "TH",
    # Typographic punctuation common in CSV exports
    "\u2019": "'", "\u2018": "'",
    "\u2013": "-", "\u2014": "-",
})


def normalize_name(text: str) -> str:
    """Convert a name string to a plain ASCII representation for FAISS key building."""
    if not isinstance(text, str):
        return str(text)
    text = text.translate(_CHAR_MAP)                          # 1 substitute known chars
    text = unicodedata.normalize("NFD", text)                 # 2 decompose accents
    text = "".join(c for c in text                            # 3 drop combining marks
                   if unicodedata.category(c) != "Mn")
    text = text.encode("ascii", errors="ignore").decode()     # 4 drop any remaining non-ASCII
    text = re.sub(r"\s+", " ", text).strip()                  # 5 normalise whitespace
    return text
