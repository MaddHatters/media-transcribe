"""Deterministic post-processing corrections for transcripts.

Whisper transcribes prose well but mangles a handful of recurring symbols
(tickers, coined acronyms) the *same way every time*. A small per-course
find/replace dictionary fixes them reliably — far more robust than fighting the
model with prompts.

Rule file format (see corrections.txt), one rule per line:
    wrong phrase => CORRECT     # literal, case-insensitive, whole-word
    re:PATTERN => REPLACEMENT   # raw regex (case-insensitive)
    # full-line and trailing "# ..." comments are ignored
"""
from __future__ import annotations

import re
from pathlib import Path


def load_rules(path: str | Path) -> list[tuple[re.Pattern, str]]:
    """Parse a rules file into (compiled_pattern, replacement) pairs."""
    rules: list[tuple[re.Pattern, str]] = []
    p = Path(path)
    if not p.exists():
        return rules
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.split("#", 1)[0].strip()        # drop inline comment
        if "=>" not in line:
            continue
        left, right = (s.strip() for s in line.split("=>", 1))
        if left.startswith("re:"):
            pat = re.compile(left[3:].strip(), re.IGNORECASE)
        else:
            pat = re.compile(rf"\b{re.escape(left)}\b", re.IGNORECASE)
        rules.append((pat, right))
    return rules


def apply_rules(text: str, rules: list[tuple[re.Pattern, str]]) -> tuple[str, dict[str, int]]:
    """Apply all rules to text. Returns (corrected_text, {replacement: count})."""
    counts: dict[str, int] = {}
    for pat, repl in rules:
        text, n = pat.subn(repl, text)
        if n:
            counts[repl] = counts.get(repl, 0) + n
    return text, counts
