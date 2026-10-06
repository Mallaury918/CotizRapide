from __future__ import annotations

import re
import unicodedata


def normalize(text: str) -> str:
    """Minuscules, sans accents, espaces simples : pour comparer des titres."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text.lower()).strip()


def contains_term(text: str, term: str) -> bool:
    """Le terme apparaît-il comme mot(s) entier(s) ? ("hs" ne matche pas "hsbc")."""
    t = normalize(term)
    if not t:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", normalize(text)) is not None
