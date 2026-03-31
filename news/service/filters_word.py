from __future__ import annotations

import re


NOISE_PATTERNS = [
    re.compile(r"^read more here\.?$", re.I),
    re.compile(r"^read the full report here\.?$", re.I),
    re.compile(r"^read more about .*?$", re.I),
    re.compile(r"^read the latest financial and business news from yahoo finance\.?$", re.I),
    re.compile(r"^follow along here\.?$", re.I),
    re.compile(r"^see more here\.?$", re.I),
    re.compile(r"^click here\.?$", re.I),
    re.compile(r"^click here for .*?$", re.I),
]

TAIL_CUTOFF_PATTERNS = [
    "was originally created and published by",
    "this article was originally published",
    "the information on this site has been included in good faith",
    "for general informational purposes only",
    "we give no representation, warranty or guarantee",
    "you must obtain professional or specialist advice",
]


def is_noise_paragraph(text: str) -> bool:
    if not text:
        return True

    for pattern in NOISE_PATTERNS:
        if pattern.search(text):
            return True

    lower = text.lower()
    if len(text) <= 80 and ("read more" in lower or "full report" in lower):
        return True

    return False


def is_tail_cutoff(text: str) -> bool:
    lower = text.lower()
    return any(pattern in lower for pattern in TAIL_CUTOFF_PATTERNS)
