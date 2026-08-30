#!/usr/bin/env python3
"""Scan SRT transcripts for phrases indicating on-screen content
that audio alone misses (visual-context gaps).

Modeled after the TAC knowledge-base version, adapted for FIRE
Investing Masterclass content.

Outputs visual_gaps.yaml with lesson number, timestamp, pattern matched,
and surrounding subtitle context (2 entries before + 2 entries after).

Usage:
    uv run transcribe/find_visual_gaps.py "/mnt/secondary/media/patreon/FIRE Investing Masterclass/transcripts"
    uv run transcribe/find_visual_gaps.py /path/to/transcripts --output gaps.yaml
    uv run transcribe/find_visual_gaps.py /path/to/transcripts  # prints to stdout
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml


# Patterns that indicate visual-only content.
# Each tuple is (compiled_regex_pattern, human-readable label).
# Sorted roughly by confidence / frequency.
VISUAL_PATTERNS = [
    # --- Generic visual references ---
    (r"\bas you can see\b", "as you can see"),
    (r"\byou can see\b", "you can see"),
    (r"\bwe can see\b", "we can see"),
    (r"\bi can see\b", "I can see"),
    (r"\byou'll see\b", "you'll see"),
    (r"\bwhat you see\b", "what you see"),
    (r"\bif we look\b", "if we look"),
    (r"\btake a look\b", "take a look"),
    (r"\blook at\b", "look at"),
    (r"\blet me show you\b", "let me show you"),
    (r"\bi'll show you\b", "I'll show you"),
    (r"\bshown here\b", "shown here"),
    (r"\bdisplayed\b", "displayed"),

    # --- Spatial references (pointing at screen) ---
    (r"\bright here\b", "right here"),
    (r"\bover here\b", "over here"),
    (r"\bdown here\b", "down here"),
    (r"\bup here\b", "up here"),
    (r"\bon screen\b|\bon the screen\b", "on screen"),
    (r"\bon this slide\b", "on this slide"),

    # --- Charts / tables / figures ---
    (r"\bthis chart\b", "this chart"),
    (r"\bthis graph\b", "this graph"),
    (r"\bthe table\b", "the table"),
    (r"\bthis table\b", "this table"),
    (r"\bthe figure\b", "the figure"),
    (r"\bthis figure\b", "this figure"),

    # --- FUW / finance-specific visual references ---
    (r"\bon the blueprint\b", "on the blueprint"),
    (r"\bin the portfolio\b", "in the portfolio"),
    (r"\bon fidelity\b", "on Fidelity"),
    (r"\bon seeking alpha\b", "on Seeking Alpha"),
    (r"\bthe ticker\b", "the ticker"),
    (r"\bthis number\b", "this number"),
    (r"\bthese numbers\b", "these numbers"),
    (r"\bthis spreadsheet\b", "this spreadsheet"),
    (r"\bthe spreadsheet\b", "the spreadsheet"),
    (r"\bon morningstar\b", "on Morningstar"),
    (r"\bthis formula\b", "this formula"),
    (r"\bthe formula\b", "the formula"),
]

# Pre-compile all patterns for performance
COMPILED_PATTERNS = [
    (re.compile(pat, re.IGNORECASE), label)
    for pat, label in VISUAL_PATTERNS
]


def parse_srt(filepath: Path) -> list[dict]:
    """Parse an SRT file into a list of subtitle entries."""
    content = filepath.read_text(encoding="utf-8")
    entries = []

    # SRT format: index\ntimestamp\ntext\n\n
    blocks = re.split(r"\n\n+", content.strip())

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue

        # First line is the index number
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue

        # Second line is the timestamp
        timestamp = lines[1].strip()

        # Remaining lines are the subtitle text
        text = " ".join(lines[2:]).strip()

        entries.append({
            "index": index,
            "timestamp": timestamp,
            "text": text,
        })

    return entries


def extract_lesson_number(filename: str) -> str:
    """Extract lesson number from filename.

    Handles patterns like:
        '19 - Title.srt'
        'Masterclass 19 - Title.srt'
        'MC 19 - Title.srt'
    """
    match = re.search(r"(\d+)", filename)
    return match.group(1) if match else "??"


def find_visual_gaps(entries: list[dict], lesson_num: str) -> list[dict]:
    """Find visual-context gaps in a list of SRT entries."""
    gaps = []

    for i, entry in enumerate(entries):
        text_lower = entry["text"].lower()

        for pattern_re, pattern_name in COMPILED_PATTERNS:
            if pattern_re.search(text_lower):
                # Gather context: 2 before + current + 2 after
                context_before = []
                for j in range(max(0, i - 2), i):
                    context_before.append({
                        "timestamp": entries[j]["timestamp"],
                        "text": entries[j]["text"],
                    })

                context_after = []
                for j in range(i + 1, min(len(entries), i + 3)):
                    context_after.append({
                        "timestamp": entries[j]["timestamp"],
                        "text": entries[j]["text"],
                    })

                gaps.append({
                    "lesson": int(lesson_num) if lesson_num.isdigit() else lesson_num,
                    "subtitle_index": entry["index"],
                    "timestamp": entry["timestamp"],
                    "pattern_matched": pattern_name,
                    "text": entry["text"],
                    "context_before": context_before,
                    "context_after": context_after,
                })
                break  # Only report first matching pattern per subtitle entry

    return gaps


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "transcripts_dir",
        help="Directory containing .srt transcript files",
    )
    ap.add_argument(
        "--output", "-o",
        help="Output YAML file path (default: stdout)",
    )
    args = ap.parse_args()

    transcripts_dir = Path(args.transcripts_dir)
    if not transcripts_dir.exists():
        print(f"ERROR: Directory not found: {transcripts_dir}", file=sys.stderr)
        return 1

    srt_files = sorted(transcripts_dir.glob("*.srt"))
    if not srt_files:
        print(f"ERROR: No .srt files found in {transcripts_dir}", file=sys.stderr)
        return 1

    print(f"Scanning {len(srt_files)} SRT files for visual-context gaps...",
          file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    all_gaps = []

    for srt_file in srt_files:
        lesson_num = extract_lesson_number(srt_file.name)
        entries = parse_srt(srt_file)
        gaps = find_visual_gaps(entries, lesson_num)
        all_gaps.extend(gaps)
        print(
            f"  Lesson {lesson_num:>2s}: {len(gaps):3d} visual gaps "
            f"({len(entries)} subtitles)",
            file=sys.stderr,
        )

    print("=" * 70, file=sys.stderr)
    print(
        f"TOTAL: {len(all_gaps)} visual-context gaps across "
        f"{len(srt_files)} lessons",
        file=sys.stderr,
    )

    # Summary by pattern
    pattern_counts: dict[str, int] = {}
    for gap in all_gaps:
        p = gap["pattern_matched"]
        pattern_counts[p] = pattern_counts.get(p, 0) + 1

    print("\nBy pattern:", file=sys.stderr)
    for pattern, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
        print(f"  '{pattern}': {count}", file=sys.stderr)

    # Build output data
    by_lesson: dict[int | str, int] = {}
    for gap in all_gaps:
        lesson = gap["lesson"]
        by_lesson[lesson] = by_lesson.get(lesson, 0) + 1

    output_data = {
        "total_gaps": len(all_gaps),
        "by_lesson": by_lesson,
        "gaps": all_gaps,
    }

    # Write output
    yaml_str = yaml.dump(
        output_data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(yaml_str, encoding="utf-8")
        print(f"\nSaved to: {output_path}", file=sys.stderr)
    else:
        sys.stdout.write(yaml_str)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
