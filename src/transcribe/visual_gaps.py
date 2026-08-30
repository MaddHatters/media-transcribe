"""Visual-context gap detection in SRT transcripts.

Scans for phrases indicating on-screen content that audio alone misses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Gap:
    file: str
    subtitle_index: int
    timestamp: str
    pattern: str
    text: str
    context_before: list[dict] = field(default_factory=list)
    context_after: list[dict] = field(default_factory=list)


DEFAULT_PATTERNS = [
    "as you can see", "you can see", "we can see", "i can see",
    "you'll see", "what you see", "if we look", "take a look",
    "look at", "let me show you", "i'll show you", "shown here",
    "displayed", "right here", "over here", "down here", "up here",
    "on screen", "on the screen", "on this slide",
    "this chart", "this graph", "the table", "this table",
    "the figure", "this figure", "on the blueprint",
    "in the portfolio", "on fidelity", "on seeking alpha",
    "the ticker", "this number", "these numbers",
    "this spreadsheet", "the spreadsheet", "on morningstar",
    "this formula", "the formula",
]


def parse_srt(filepath: Path) -> list[dict]:
    """Parse an SRT file into a list of subtitle entries."""
    content = filepath.read_text(encoding="utf-8")
    entries = []
    blocks = re.split(r"\n\n+", content.strip())
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue
        timestamp = lines[1].strip()
        text = " ".join(lines[2:]).strip()
        entries.append({"index": index, "timestamp": timestamp, "text": text})
    return entries


def find_gaps(
    srt_path: Path,
    patterns: list[str] | None = None,
) -> list[Gap]:
    """Find visual-context gaps in an SRT file."""
    pats = patterns or DEFAULT_PATTERNS
    compiled = [(re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE), p) for p in pats]
    entries = parse_srt(srt_path)
    gaps = []

    for i, entry in enumerate(entries):
        for pat_re, pat_name in compiled:
            if pat_re.search(entry["text"]):
                context_before = [
                    {"timestamp": entries[j]["timestamp"], "text": entries[j]["text"]}
                    for j in range(max(0, i - 2), i)
                ]
                context_after = [
                    {"timestamp": entries[j]["timestamp"], "text": entries[j]["text"]}
                    for j in range(i + 1, min(len(entries), i + 3))
                ]
                gaps.append(Gap(
                    file=srt_path.name,
                    subtitle_index=entry["index"],
                    timestamp=entry["timestamp"],
                    pattern=pat_name,
                    text=entry["text"],
                    context_before=context_before,
                    context_after=context_after,
                ))
                break

    return gaps


def find_gaps_in_folder(
    transcripts_dir: Path,
    patterns: list[str] | None = None,
) -> dict[str, list[Gap]]:
    """Find visual gaps across all SRT files in a folder."""
    result: dict[str, list[Gap]] = {}
    srt_files = sorted(transcripts_dir.glob("*.srt"))
    for srt_file in srt_files:
        gaps = find_gaps(srt_file, patterns=patterns)
        if gaps:
            result[srt_file.stem] = gaps
    return result
