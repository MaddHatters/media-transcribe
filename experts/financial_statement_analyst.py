"""Financial-Statement Analyst — DD evidence sub-expert (deterministic).

Computes the ratios and applies the thresholds the FIRE Investing Masterclass teaches
(see analysis/dd-playbook.md, analysis/mental-model.md) to score a company's three
statements. Pure logic — feed it line items, get a health scorecard. An LLM/DD-Lead
layer fetches statements (or uses OCR'd ones) and narrates; THIS module scores.

Line items are in the statement's own units (e.g. $millions); ratios are unit-free.
This is a health scorecard, NOT a buy/sell call (that's other experts).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Thresholds as taught.
CURRENT_RATIO_CONCERN = 1.5     # < 1.5 = concern (and < 1.0 is weaker still, though not always bad)
QUICK_RATIO_CONCERN = 1.0       # < 1.0 = concern
DEBT_TO_EQUITY_RED = 1.0        # > 100% = red flag. Debt-to-equity here = interest-bearing DEBT /
                                # equity (MC9 red flag #1: "absorbing more debt than it can handle").
                                # NOT total liabilities/equity — that conflates it with red flag #8
                                # ("liabilities > assets"), false-flagging deferred-revenue/lease-heavy
                                # but debt-light businesses (ABNB, CELH). See analysis/ocr-reconciliation.md.
PAYOUT_RED = 0.90               # dividends / net income > 90% = red flag (REITs exempt)
DECLINING_YEARS_RED = 3         # >= 3 consecutive declining revenue years = avoid


class Status(Enum):
    STRONG = "strong"
    PASS = "pass"
    CONCERN = "concern"
    RED_FLAG = "red_flag"


@dataclass(frozen=True)
class Profile:
    """Sector metric profile — which checks to suppress and whether payout is exempt.

    Built from finance-suite's ``financials.profile_spec`` (the caller passes the spec,
    keeping this module free of any cross-repo import). E.g. banks suppress debt-to-equity
    and the liquidity ratios; REITs are exempt from the >90% payout red flag.
    """
    name: str = "general"
    suppress: frozenset[str] = frozenset()
    payout_exempt: bool = False

    @classmethod
    def from_spec(cls, name: str, spec: dict) -> "Profile":
        return cls(name=name, suppress=frozenset(spec.get("suppress", ())),
                   payout_exempt=bool(spec.get("payout_exempt", False)))


GENERAL_PROFILE = Profile()


@dataclass
class BalanceSheet:
    current_assets: float | None = None
    current_liabilities: float | None = None
    inventory: float | None = None
    total_liabilities: float | None = None
    shareholders_equity: float | None = None
    goodwill: float | None = None
    long_term_debt: float | None = None       # interest-bearing, noncurrent
    short_term_debt: float | None = None      # current portion of debt / short-term borrowings
    retained_earnings: float | None = None
    cash_and_st_investments: float | None = None


@dataclass
class IncomeStatement:
    revenue: float | None = None
    gross_profit: float | None = None
    net_income: float | None = None
    revenue_history: list[float] = field(default_factory=list)  # oldest -> newest


@dataclass
class CashFlow:
    operating_cash_flow: float | None = None
    capital_expenditures: float | None = None   # positive magnitude
    dividends_paid: float | None = None          # positive magnitude
    net_income: float | None = None


@dataclass
class Check:
    name: str
    status: Status
    detail: str


@dataclass
class Scorecard:
    ratios: dict[str, float] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    profile: str = "general"
    suppressed: list[str] = field(default_factory=list)   # checks skipped for this sector

    def _count(self, status: Status) -> int:
        return sum(1 for c in self.checks if c.status is status)

    @property
    def red_flags(self) -> int:
        return self._count(Status.RED_FLAG)

    @property
    def concerns(self) -> int:
        return self._count(Status.CONCERN)

    @property
    def strengths(self) -> int:
        return self._count(Status.STRONG)

    @property
    def passed(self) -> int:
        """Checks that cleared their threshold (PASS or STRONG) — what a clean run earned."""
        return self._count(Status.PASS) + self._count(Status.STRONG)

    @property
    def summary(self) -> str:
        # Count *passed* checks, not only STRONG ones — otherwise a fortress balance sheet
        # with every ratio clean reads as "strong — 0 strengths", which is self-contradictory.
        if self.red_flags:
            return f"weak — {self.red_flags} red flag(s), {self.concerns} concern(s)"
        if self.concerns:
            return f"mixed — {self.concerns} concern(s), {self.passed} check(s) passed"
        return f"strong — {self.passed} check(s) passed, no red flags"

    def __str__(self) -> str:
        lines = [f"Scorecard [{self.profile}]: {self.summary}"]
        for c in self.checks:
            lines.append(f"  [{c.status.value:8}] {c.name}: {c.detail}")
        if self.suppressed:
            lines.append(f"  (suppressed for {self.profile}: {', '.join(self.suppressed)})")
        return "\n".join(lines)


def _ratio(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def analyze_balance_sheet(bs: BalanceSheet, sc: Scorecard, profile: Profile = GENERAL_PROFILE) -> None:
    if "current_ratio" not in profile.suppress:
        current_ratio = _ratio(bs.current_assets, bs.current_liabilities)
        if current_ratio is not None:
            sc.ratios["current_ratio"] = round(current_ratio, 2)
            if current_ratio < CURRENT_RATIO_CONCERN:
                note = " (< 1.0 — though giants with credit access can run lower)" if current_ratio < 1.0 else ""
                sc.checks.append(Check("current_ratio", Status.CONCERN, f"{current_ratio:.2f} < 1.5{note}"))
            else:
                sc.checks.append(Check("current_ratio", Status.PASS, f"{current_ratio:.2f}"))

    if "quick_ratio" not in profile.suppress and bs.current_assets is not None and bs.inventory is not None:
        quick = _ratio(bs.current_assets - bs.inventory, bs.current_liabilities)
        if quick is not None:
            sc.ratios["quick_ratio"] = round(quick, 2)
            status = Status.CONCERN if quick < QUICK_RATIO_CONCERN else Status.PASS
            sc.checks.append(Check("quick_ratio", status, f"{quick:.2f}"))

    # Red flag #2/#8: negative equity (= total liabilities exceed total assets, "over-leveraged").
    if bs.shareholders_equity is not None and bs.shareholders_equity <= 0:
        sc.checks.append(Check("equity", Status.RED_FLAG, "negative shareholders' equity"))
    # Red flag #1: debt-to-equity from interest-bearing DEBT (not total liabilities). Computed only
    # when at least one debt component resolves; absent debt tags -> can't compute (honest), no flag.
    elif "debt_to_equity" not in profile.suppress:
        debt_parts = [d for d in (bs.long_term_debt, bs.short_term_debt) if d is not None]
        if debt_parts:
            total_debt = sum(debt_parts)
            dte = _ratio(total_debt, bs.shareholders_equity)
            if dte is not None:
                sc.ratios["debt_to_equity"] = round(dte, 2)
                if dte > DEBT_TO_EQUITY_RED:
                    sc.checks.append(Check("debt_to_equity", Status.RED_FLAG,
                                           f"{dte:.2f} > 1.0 (>100%) — interest-bearing debt/equity"))
                else:
                    sc.checks.append(Check("debt_to_equity", Status.PASS,
                                           f"{dte:.2f} (interest-bearing debt/equity)"))

    if bs.shareholders_equity is not None and bs.goodwill is not None:
        nta = bs.shareholders_equity - bs.goodwill
        sc.ratios["net_tangible_assets"] = round(nta, 2)
        if nta < 0:
            sc.checks.append(Check("net_tangible_assets", Status.CONCERN, "negative (excess goodwill)"))

    if bs.retained_earnings is not None and bs.retained_earnings < 0:
        sc.checks.append(Check("retained_earnings", Status.CONCERN,
                               "negative — accumulated deficit, or capital returned via buybacks/"
                               "dividends (e.g. AAPL); weak-balance-sheet signal, verify the cause"))

    if bs.long_term_debt is not None and bs.long_term_debt == 0:
        sc.checks.append(Check("long_term_debt", Status.STRONG, "zero long-term debt"))


def analyze_income_statement(inc: IncomeStatement, sc: Scorecard, profile: Profile = GENERAL_PROFILE) -> None:
    gross_margin = _ratio(inc.gross_profit, inc.revenue)
    if gross_margin is not None:
        sc.ratios["gross_margin"] = round(gross_margin * 100, 1)
    net_margin = _ratio(inc.net_income, inc.revenue)
    if net_margin is not None:
        sc.ratios["net_margin"] = round(net_margin * 100, 1)
        if net_margin < 0:
            sc.checks.append(Check("net_margin", Status.CONCERN, "unprofitable (negative net margin)"))

    history = inc.revenue_history
    if len(history) >= DECLINING_YEARS_RED:
        recent = history[-DECLINING_YEARS_RED:]
        if all(recent[i] < recent[i - 1] for i in range(1, len(recent))):
            sc.checks.append(Check("revenue_trend", Status.RED_FLAG,
                                   f">= {DECLINING_YEARS_RED} years of declining revenue"))
        else:
            sc.checks.append(Check("revenue_trend", Status.PASS, "no sustained revenue decline"))


def analyze_cash_flow(cf: CashFlow, sc: Scorecard, profile: Profile = GENERAL_PROFILE) -> None:
    if cf.operating_cash_flow is not None:
        if cf.operating_cash_flow < 0:
            sc.checks.append(Check("operating_cash_flow", Status.CONCERN, "negative operating cash flow"))
        if cf.capital_expenditures is not None:
            fcf = cf.operating_cash_flow - cf.capital_expenditures
            sc.ratios["free_cash_flow"] = round(fcf, 2)
            if fcf < 0:
                sc.checks.append(Check("free_cash_flow", Status.CONCERN,
                                       "negative (note: growth capex can explain this — verify)"))

    payout = _ratio(cf.dividends_paid, cf.net_income)
    if payout is not None and payout > 0:
        sc.ratios["payout_ratio"] = round(payout * 100, 1)
        if payout > PAYOUT_RED:
            if profile.payout_exempt:
                sc.checks.append(Check("payout_ratio", Status.PASS,
                                       f"{payout * 100:.0f}% — REIT, payout exempt from the >90% flag"))
            else:
                sc.checks.append(Check("payout_ratio", Status.RED_FLAG,
                                       f"{payout * 100:.0f}% > 90% (or a special dividend — investigate)"))


def analyze(balance_sheet: BalanceSheet | None = None,
            income_statement: IncomeStatement | None = None,
            cash_flow: CashFlow | None = None,
            profile: Profile = GENERAL_PROFILE) -> Scorecard:
    """Score whichever statements are provided into one health scorecard.

    Pass a sector ``profile`` (built from finance-suite's profile_spec) to suppress
    checks that don't apply to the company type (e.g. a bank's debt-to-equity) and to
    exempt REIT payout from the >90% flag.
    """
    sc = Scorecard(profile=profile.name, suppressed=sorted(profile.suppress))
    if balance_sheet is not None:
        analyze_balance_sheet(balance_sheet, sc, profile)
    if income_statement is not None:
        analyze_income_statement(income_statement, sc, profile)
    if cash_flow is not None:
        analyze_cash_flow(cash_flow, sc, profile)
    return sc
