#!/usr/bin/env python3
"""Apply the correction dictionary to *existing* .txt/.srt transcripts.

Lets you tune corrections.txt and re-fix transcripts without re-transcribing.

    uv run transcribe/apply_corrections.py "/mnt/secondary/FIRE Investing Masterclass/transcripts"
    uv run transcribe/apply_corrections.py "<folder>" --dry-run   # preview counts only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corrections import apply_rules, load_rules


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", help="Transcripts folder (recurses) or a single file")
    ap.add_argument("--corrections", default=str(Path(__file__).parent / "corrections.txt"))
    ap.add_argument("--dry-run", action="store_true", help="Report changes, write nothing")
    args = ap.parse_args()

    rules = load_rules(args.corrections)
    if not rules:
        print(f"No rules loaded from {args.corrections}", file=sys.stderr)
        return 1

    root = Path(args.path).expanduser()
    if root.is_file():
        files = [root]
    else:
        files = sorted(p for p in root.rglob("*") if p.suffix.lower() in {".txt", ".srt"})
    if not files:
        print(f"No .txt/.srt files under {root}")
        return 1

    totals: dict[str, int] = {}
    changed = 0
    for f in files:
        text = f.read_text(encoding="utf-8")
        new, counts = apply_rules(text, rules)
        if not counts:
            continue
        changed += 1
        for k, v in counts.items():
            totals[k] = totals.get(k, 0) + v
        summary = ", ".join(f"{k}×{v}" for k, v in sorted(counts.items()))
        print(f"{'(dry) ' if args.dry_run else ''}{f.name}: {summary}")
        if not args.dry_run:
            f.write_text(new, encoding="utf-8")

    print(f"\n{'Would change' if args.dry_run else 'Changed'} {changed}/{len(files)} files.")
    if totals:
        print("Totals: " + ", ".join(f"{k}×{v}" for k, v in sorted(totals.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
