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
DEBT_TO_EQUITY_RED = 1.0        # > 100% = red flag (debt-to-equity = total liabilities / equity)
PAYOUT_RED = 0.90               # dividends / net income > 90% = red flag (REITs exempt)
DECLINING_YEARS_RED = 3         # >= 3 consecutive declining revenue years = avoid


class Status(Enum):
    STRONG = "strong"
    PASS = "pass"
    CONCERN = "concern"
    RED_FLAG = "red_flag"


@dataclass
class BalanceSheet:
    current_assets: float | None = None
    current_liabilities: float | None = None
    inventory: float | None = None
    total_liabilities: float | None = None
    shareholders_equity: float | None = None
    goodwill: float | None = None
    long_term_debt: float | None = None
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
    def summary(self) -> str:
        if self.red_flags:
            return f"weak — {self.red_flags} red flag(s), {self.concerns} concern(s)"
        if self.concerns:
            return f"mixed — {self.concerns} concern(s), {self.strengths} strength(s)"
        return f"strong — {self.strengths} strength(s), no red flags"

    def __str__(self) -> str:
        lines = [f"Scorecard: {self.summary}"]
        for c in self.checks:
            lines.append(f"  [{c.status.value:8}] {c.name}: {c.detail}")
        return "\n".join(lines)


def _ratio(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def analyze_balance_sheet(bs: BalanceSheet, sc: Scorecard) -> None:
    current_ratio = _ratio(bs.current_assets, bs.current_liabilities)
    if current_ratio is not None:
        sc.ratios["current_ratio"] = round(current_ratio, 2)
        if current_ratio < CURRENT_RATIO_CONCERN:
            note = " (< 1.0 — though giants with credit access can run lower)" if current_ratio < 1.0 else ""
            sc.checks.append(Check("current_ratio", Status.CONCERN, f"{current_ratio:.2f} < 1.5{note}"))
        else:
            sc.checks.append(Check("current_ratio", Status.PASS, f"{current_ratio:.2f}"))

    if bs.current_assets is not None and bs.inventory is not None:
        quick = _ratio(bs.current_assets - bs.inventory, bs.current_liabilities)
        if quick is not None:
            sc.ratios["quick_ratio"] = round(quick, 2)
            status = Status.CONCERN if quick < QUICK_RATIO_CONCERN else Status.PASS
            sc.checks.append(Check("quick_ratio", status, f"{quick:.2f}"))

    if bs.shareholders_equity is not None and bs.shareholders_equity <= 0:
        sc.checks.append(Check("equity", Status.RED_FLAG, "negative shareholders' equity"))
    else:
        dte = _ratio(bs.total_liabilities, bs.shareholders_equity)
        if dte is not None:
            sc.ratios["debt_to_equity"] = round(dte, 2)
            if dte > DEBT_TO_EQUITY_RED:
                sc.checks.append(Check("debt_to_equity", Status.RED_FLAG, f"{dte:.2f} > 1.0 (>100%)"))
            else:
                sc.checks.append(Check("debt_to_equity", Status.PASS, f"{dte:.2f}"))

    if bs.shareholders_equity is not None and bs.goodwill is not None:
        nta = bs.shareholders_equity - bs.goodwill
        sc.ratios["net_tangible_assets"] = round(nta, 2)
        if nta < 0:
            sc.checks.append(Check("net_tangible_assets", Status.CONCERN, "negative (excess goodwill)"))

    if bs.retained_earnings is not None and bs.retained_earnings < 0:
        sc.checks.append(Check("retained_earnings", Status.CONCERN,
                               "deficit (accumulated losses) — weak-balance-sheet signal"))

    if bs.long_term_debt is not None and bs.long_term_debt == 0:
        sc.checks.append(Check("long_term_debt", Status.STRONG, "zero long-term debt"))


def analyze_income_statement(inc: IncomeStatement, sc: Scorecard) -> None:
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


def analyze_cash_flow(cf: CashFlow, sc: Scorecard) -> None:
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
            sc.checks.append(Check("payout_ratio", Status.RED_FLAG,
                                   f"{payout * 100:.0f}% > 90% (REITs exempt; or a special dividend — investigate)"))


def analyze(balance_sheet: BalanceSheet | None = None,
            income_statement: IncomeStatement | None = None,
            cash_flow: CashFlow | None = None) -> Scorecard:
    """Score whichever statements are provided into one health scorecard."""
    sc = Scorecard()
    if balance_sheet is not None:
        analyze_balance_sheet(balance_sheet, sc)
    if income_statement is not None:
        analyze_income_statement(income_statement, sc)
    if cash_flow is not None:
        analyze_cash_flow(cash_flow, sc)
    return sc
