"""Dividend-bucket classifier: DGIF / DGI / Income / Growth (deterministic).

Implements the FIRE Investing Masterclass rules (see analysis/dd-playbook.md,
analysis/mental-model.md). Pure logic — no LLM, no network — so it is exact and
unit-testable. An agent layer gathers the inputs (dividend metrics) and explains the
verdict; THIS module decides.

Rules:
- DGIF ("Dividend Growth Investing for FIRE", total-return bucket) — ALL 5:
  yield <= 3%, payout <= 50%, >= 5 yrs dividend growth, >= 10% dividend growth over that
  5-yr window, >= 10% 10-yr annualized return.
- Income — yield > 4% with a high payout, OR any REIT. Guardrail: avoid yield >= 6%.
- DGI — a consistent dividend grower (>= 5 yrs) that misses the DGIF total-return bar.
- Growth — pays little/no dividend (or suspended) => not a dividend bucket.
Edge cases the course calls out: a tiny/new dividend (NVDA) is a DGIF-vs-Growth judgment;
a suspended dividend (Disney) no longer fits DGIF.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Thresholds (percent), as taught.
YIELD_MAX_DGIF = 3.0
PAYOUT_MAX_DGIF = 50.0
MIN_YEARS_GROWTH = 5
MIN_DIV_GROWTH_5YR = 10.0
MIN_ANN_10YR_RETURN = 10.0
INCOME_YIELD_MIN = 4.0      # > this + high payout => Income
HIGH_PAYOUT = 50.0
AVOID_YIELD = 6.0           # >= this => avoid (guardrail flag)


@dataclass
class DividendProfile:
    ticker: str
    pays_dividend: bool = True
    dividend_yield: float = 0.0                 # %
    payout_ratio: float | None = None           # %
    years_dividend_growth: int = 0
    div_growth_5yr_pct: float | None = None      # dividend growth over the 5-yr window, %
    annualized_10yr_return: float | None = None  # %
    is_reit: bool = False


@dataclass
class Classification:
    ticker: str
    bucket: str                                  # DGIF | DGI | Income | Growth
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    dgif_criteria: dict[str, bool] = field(default_factory=dict)

    def __str__(self) -> str:
        passed = sum(self.dgif_criteria.values())
        out = [f"{self.ticker}: {self.bucket}  (DGIF criteria {passed}/5)"]
        out += [f"  - {r}" for r in self.reasons]
        out += [f"  ! {f}" for f in self.flags]
        return "\n".join(out)


def _dgif_criteria(p: DividendProfile) -> dict[str, bool]:
    return {
        "yield<=3%": p.dividend_yield <= YIELD_MAX_DGIF,
        "payout<=50%": p.payout_ratio is not None and p.payout_ratio <= PAYOUT_MAX_DGIF,
        "div_growth_years>=5": p.years_dividend_growth >= MIN_YEARS_GROWTH,
        "div_growth_5yr>=10%": p.div_growth_5yr_pct is not None and p.div_growth_5yr_pct >= MIN_DIV_GROWTH_5YR,
        "ann_10yr_return>=10%": p.annualized_10yr_return is not None and p.annualized_10yr_return >= MIN_ANN_10YR_RETURN,
    }


def classify(p: DividendProfile) -> Classification:
    crit = _dgif_criteria(p)
    flags: list[str] = []

    if not p.pays_dividend:
        return Classification(p.ticker, "Growth",
                              ["pays no dividend (or suspended) -> not a dividend bucket"],
                              ["suspended_or_none"], crit)

    if p.dividend_yield >= AVOID_YIELD:
        flags.append(f"avoid: yield {p.dividend_yield:g}% >= 6% (chasing yield)")

    if p.is_reit:
        return Classification(p.ticker, "Income", ["REIT -> Income by rule"], flags, crit)

    high_payout = p.payout_ratio is not None and p.payout_ratio > HIGH_PAYOUT
    if p.dividend_yield > INCOME_YIELD_MIN and (high_payout or p.payout_ratio is None):
        why = "high payout" if high_payout else "payout unknown"
        return Classification(p.ticker, "Income",
                              [f"yield {p.dividend_yield:g}% > 4% with {why} -> Income"], flags, crit)

    if all(crit.values()):
        return Classification(p.ticker, "DGIF", ["meets all 5 DGIF criteria"], flags, crit)

    # tiny/new dividend (e.g. NVDA): course treats as a DGIF-vs-Growth judgment call
    if p.dividend_yield < 1.0 and p.years_dividend_growth < MIN_YEARS_GROWTH:
        flags.append("DGIF-vs-Growth judgment: tiny/new dividend")
        return Classification(p.ticker, "Growth",
                              ["fractional, <5 yrs dividend growth -> Growth (not yet DGIF)"], flags, crit)

    failed = [k for k, v in crit.items() if not v]
    if p.years_dividend_growth >= MIN_YEARS_GROWTH:
        return Classification(p.ticker, "DGI",
                              [f"consistent dividend grower but misses DGIF on: {', '.join(failed)} -> DGI"],
                              flags, crit)

    return Classification(p.ticker, "Growth",
                          [f"not a consistent grower; misses DGIF on: {', '.join(failed)}"], flags, crit)
