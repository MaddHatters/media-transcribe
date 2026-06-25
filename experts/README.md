# experts — Phase 4

Specialized, single-focus experts grounded in `analysis/`. Architecture:
**deterministic core + LLM/agent wrapper.** Anything the course defines with rules/
thresholds lives in *tested Python* (exact, unit-testable, Phase-5 validatable); the LLM
layer gathers inputs, handles judgment calls, and explains — it never re-derives the math.

This keeps the experts "very accurate" (the project goal): a DGIF classification or a
buy-level calculation is computed, not guessed.

## Built
- **`dividend_classifier.py`** — DGIF / DGI / Income / Growth bucket classifier. Implements
  the DGIF 5 criteria + the Income rule (`yield > 4% + high payout, OR any REIT`; avoid
  `>= 6%`) + the NVDA/Disney edge cases. `classify(DividendProfile) -> Classification`
  (bucket + reasons + flags + per-criterion pass/fail). Tested in
  `tests/test_dividend_classifier.py`.

## Next (in priority order)
- **Buy/Sell Point Engine** (`analysis/buy-sell-engine.md`) — deterministic levels (200-day,
  Fibonacci, FUWTALAS lots, house-shares math) + LLM judgment (air pockets, support quality).
- **Financial-Statement Analyst** — the ratio/threshold scorecard (uses OCR'd statements).
- **Bull / Bear / Judge** synthesis personas over the DD evidence sub-experts.
- Then the agent/router layer (format TBD: Claude Code subagents vs expertise.yaml).

Run: `uv run pytest -q`
