"""Tests for the ingestion -> FSA adapter.

Statements are built as ``SimpleNamespace`` mirroring finance-suite's canonical
``FinancialStatements`` shape — this proves the adapter is duck-typed and needs no
cross-repo import. Numbers reuse the OCR'd statements (analysis/ocr-reconciliation.md),
so the end-to-end path must agree with the direct-FSA tests.
"""
from types import SimpleNamespace

from financial_statement_analyst import Status
from statement_adapter import analyze_financials, to_fsa_inputs


def _statements(*, balance=None, income=None, cash=None, fiscal_year=2021):
    """A FinancialStatements-shaped object (finance-suite canonical fields)."""
    income_fields = {"revenue": None, "gross_profit": None, "operating_income": None,
                     "net_income": None, **(income or {})}
    cash_fields = {"operating_cash_flow": None, "capital_expenditures": None,
                   "dividends_paid": None, **(cash or {})}
    return SimpleNamespace(
        ticker="TEST", fiscal_year=fiscal_year, source="test",
        balance_sheet=SimpleNamespace(**(balance or {})),
        income_statement=SimpleNamespace(**income_fields),
        cash_flow=SimpleNamespace(**cash_fields),
    )


def _names(scorecard, status):
    return {c.name for c in scorecard.checks if c.status is status}


# --- the mapping bridges the two shape gaps --------------------------------- #
def test_revenue_history_assembled_across_years_flags_decline():
    # Three FinancialStatements (no revenue_history field anywhere) -> adapter builds the trend.
    y1 = _statements(income={"revenue": 100, "gross_profit": 30, "net_income": 10}, fiscal_year=2019)
    y2 = _statements(income={"revenue": 90, "gross_profit": 25, "net_income": 8}, fiscal_year=2020)
    y3 = _statements(income={"revenue": 80, "gross_profit": 20, "net_income": 5}, fiscal_year=2021)
    _, inc, _ = to_fsa_inputs(y3, history=[y1, y2])
    assert inc.revenue_history == [100, 90, 80]                  # oldest -> newest, latest included
    sc = analyze_financials(y3, history=[y1, y2])
    assert "revenue_trend" in _names(sc, Status.RED_FLAG)


def test_net_income_spliced_into_cash_flow_for_payout():
    # finance-suite CashFlow has no net_income; the adapter splices it from the income statement.
    st = _statements(
        income={"revenue": 100, "net_income": 23306},
        cash={"operating_cash_flow": 65530, "capital_expenditures": 6052, "dividends_paid": 163792},
    )
    _, _, cf = to_fsa_inputs(st)
    assert cf.net_income == 23306
    sc = analyze_financials(st)
    assert sc.ratios["payout_ratio"] > 90                        # Wingstop special-dividend anomaly resolves
    assert "payout_ratio" in _names(sc, Status.RED_FLAG)


# --- end-to-end agreement with the direct-FSA results ----------------------- #
def test_tesla_balance_sheet_matches_direct_fsa():
    st = _statements(balance={
        "current_assets": 26717, "current_liabilities": 14248, "inventory": 4101,
        "total_assets": 52148, "total_liabilities": 28418, "shareholders_equity": 22225,
        "goodwill": 207, "long_term_debt": 9556, "retained_earnings": -5399,
    })
    sc = analyze_financials(st)
    assert sc.ratios["current_ratio"] == 1.88
    assert sc.ratios["debt_to_equity"] == 1.28
    assert "debt_to_equity" in _names(sc, Status.RED_FLAG)
    assert "retained_earnings" in _names(sc, Status.CONCERN)


# --- profile flows through (gics_to_profile -> profile_spec contract) -------- #
def test_financial_profile_suppresses_bank_debt():
    bank = _statements(balance={
        "current_assets": 100, "current_liabilities": 200, "inventory": 0,
        "total_liabilities": 900, "shareholders_equity": 100,
    })
    spec = {"suppress": {"debt_to_equity", "current_ratio", "quick_ratio"}, "payout_exempt": False}
    sc = analyze_financials(bank, profile_name="financial", profile_spec=spec)
    names = {c.name for c in sc.checks}
    assert "debt_to_equity" not in names and "current_ratio" not in names
    assert sc.profile == "financial" and "debt_to_equity" in sc.suppressed

    # without the profile the same bank red-flags
    general = analyze_financials(bank)
    assert "debt_to_equity" in _names(general, Status.RED_FLAG)


def test_reit_payout_exempt_through_adapter():
    st = _statements(
        income={"revenue": 100, "net_income": 50},
        cash={"operating_cash_flow": 100, "dividends_paid": 95},
    )
    spec = {"suppress": {"debt_to_equity"}, "payout_exempt": True}
    payout = next(c for c in analyze_financials(st, profile_name="reit", profile_spec=spec).checks
                  if c.name == "payout_ratio")
    assert payout.status is Status.PASS


def test_missing_statements_degrade_to_clean():
    # all-None statements -> no checks, no crashes (honest empty scorecard)
    sc = analyze_financials(_statements())
    assert sc.summary.startswith("strong") and sc.red_flags == 0
