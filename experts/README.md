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

- **`financial_statement_analyst.py`** — DD evidence sub-expert. Computes the course's
  ratios/thresholds across balance sheet / income statement / cash flow into a health
  Scorecard (current/quick ratio, debt-to-equity >100% red flag, net tangible assets,
  retained-earnings deficit, revenue-trend decline, FCF, payout >90%). Validated against the
  OCR'd NVIDIA/Tesla/Wingstop statements. Tested in `tests/test_financial_statement_analyst.py`.

## Next (in priority order)
- **Buy/Sell Point Engine** — deterministic core DONE in finance-suite; pending the LLM judgment layer.
- **Bull / Bear / Judge** + perspective personas (Retail / Institutional / Value: Lynch/Buffett/Munger)
  over the DD evidence sub-experts.
- Then the agent/router layer (format TBD: Claude Code subagents vs expertise.yaml).

Run: `uv run pytest -q`
