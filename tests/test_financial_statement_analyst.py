"""Tests for the Financial-Statement Analyst.

Real cases use the statements OCR recovered in Phase 3 (analysis/ocr-reconciliation.md):
NVIDIA income statement, Tesla 2020 balance sheet, Wingstop 2020 cash flow.
"""
from financial_statement_analyst import (
    BalanceSheet, CashFlow, IncomeStatement, Profile, Status, analyze,
)


def _names(scorecard, status):
    return {c.name for c in scorecard.checks if c.status is status}


# --- NVIDIA income statement (FY21/20/19), from the OCR'd statement ---------- #
def test_nvidia_income_statement_strong_margins_no_decline():
    inc = IncomeStatement(revenue=16675, gross_profit=10396, net_income=4332,
                          revenue_history=[11716, 10918, 16675])  # 2019, 2020, 2021
    sc = analyze(income_statement=inc)
    assert sc.ratios["gross_margin"] == 62.3
    assert sc.ratios["net_margin"] == 26.0
    assert "revenue_trend" not in _names(sc, Status.RED_FLAG)  # dipped then rose, not 3-yr decline


# --- Tesla 2020 balance sheet (the OCR'd 10-K) ------------------------------- #
def test_tesla_2020_balance_sheet_mixed():
    bs = BalanceSheet(current_assets=26717, current_liabilities=14248, inventory=4101,
                      total_liabilities=28418, shareholders_equity=22225, goodwill=207,
                      long_term_debt=9556, retained_earnings=-5399)
    sc = analyze(balance_sheet=bs)
    assert sc.ratios["current_ratio"] == 1.88           # healthy liquidity
    assert sc.ratios["quick_ratio"] == 1.59
    # debt-to-equity is interest-bearing DEBT / equity (9556/22225 = 0.43), NOT total
    # liabilities / equity (1.28). Tesla 2020 was lease/payable-heavy but not debt-heavy,
    # so it must NOT trip the leverage red flag — the accumulated deficit is the real concern.
    assert sc.ratios["debt_to_equity"] == 0.43
    assert "debt_to_equity" not in _names(sc, Status.RED_FLAG)
    assert "debt_to_equity" in _names(sc, Status.PASS)
    assert "retained_earnings" in _names(sc, Status.CONCERN)
    assert sc.ratios["net_tangible_assets"] == 22018     # positive (equity - goodwill)


# --- Wingstop 2020 cash flow (the OCR'd statement; special dividend) --------- #
def test_wingstop_2020_special_dividend_blows_payout():
    cf = CashFlow(operating_cash_flow=65530, capital_expenditures=6052,
                  dividends_paid=163792, net_income=23306)
    sc = analyze(cash_flow=cf)
    assert sc.ratios["free_cash_flow"] == 59478          # positive FCF
    assert sc.ratios["payout_ratio"] > 90                # 700%+ — the special-dividend anomaly
    assert "payout_ratio" in _names(sc, Status.RED_FLAG)


# --- synthetic weak / strong cases ------------------------------------------ #
def test_weak_balance_sheet_negative_equity_red_flag():
    bs = BalanceSheet(current_assets=50, current_liabilities=100, inventory=10,
                      total_liabilities=200, shareholders_equity=-30, retained_earnings=-80)
    sc = analyze(balance_sheet=bs)
    assert "equity" in _names(sc, Status.RED_FLAG)
    assert "current_ratio" in _names(sc, Status.CONCERN)   # 0.5 < 1.5
    assert sc.red_flags >= 1
    assert sc.summary.startswith("weak")


def test_strong_balance_sheet_zero_debt():
    bs = BalanceSheet(current_assets=300, current_liabilities=100, inventory=20,
                      total_liabilities=120, shareholders_equity=500, goodwill=0,
                      long_term_debt=0, retained_earnings=200)
    sc = analyze(balance_sheet=bs)
    assert "long_term_debt" in _names(sc, Status.STRONG)
    assert "current_ratio" in _names(sc, Status.PASS)
    assert sc.red_flags == 0


def test_clean_company_summary_counts_passed_checks_not_just_strengths():
    # NVDA-like: every ratio clean but no STRONG check -> must not read "0 strength(s)".
    bs = BalanceSheet(current_assets=417, current_liabilities=100, inventory=50,
                      total_liabilities=53, shareholders_equity=100, goodwill=0,
                      long_term_debt=0, retained_earnings=200)
    sc = analyze(balance_sheet=bs)
    assert sc.red_flags == 0 and sc.concerns == 0
    assert sc.passed >= 3
    assert sc.summary.startswith("strong") and "0 strength" not in sc.summary
    assert f"{sc.passed} check(s) passed" in sc.summary


def test_three_year_revenue_decline_red_flag():
    inc = IncomeStatement(revenue=80, gross_profit=20, net_income=5,
                          revenue_history=[100, 90, 80])
    sc = analyze(income_statement=inc)
    assert "revenue_trend" in _names(sc, Status.RED_FLAG)


def test_empty_profile_is_clean():
    sc = analyze()
    assert sc.checks == [] and sc.summary.startswith("strong")


# --- sector profiles ---------------------------------------------------------- #
def test_financial_profile_suppresses_debt_and_liquidity():
    # bank-like: debt/equity = 9, current ratio 0.5 — would red-flag/concern under the general profile
    bank = BalanceSheet(current_assets=100, current_liabilities=200, inventory=0,
                        total_liabilities=900, shareholders_equity=100, long_term_debt=900)
    fin = Profile.from_spec("financial", {"suppress": {"debt_to_equity", "current_ratio", "quick_ratio"}})
    sc = analyze(balance_sheet=bank, profile=fin)
    names = {c.name for c in sc.checks}
    assert "debt_to_equity" not in names and "current_ratio" not in names
    assert "debt_to_equity" in sc.suppressed and sc.profile == "financial"

    # general profile still flags it
    general = analyze(balance_sheet=bank)
    assert any(c.name == "debt_to_equity" and c.status is Status.RED_FLAG for c in general.checks)


def test_reit_payout_exempt():
    cf = CashFlow(operating_cash_flow=100, dividends_paid=95, net_income=50)   # payout 190%
    reit = Profile.from_spec("reit", {"payout_exempt": True})
    payout = next(c for c in analyze(cash_flow=cf, profile=reit).checks if c.name == "payout_ratio")
    assert payout.status is Status.PASS                       # exempt, not a red flag

    general = next(c for c in analyze(cash_flow=cf).checks if c.name == "payout_ratio")
    assert general.status is Status.RED_FLAG                  # flagged under general profile
