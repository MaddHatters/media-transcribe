"""Adapter: ingested financial statements -> Financial-Statement Analyst inputs.

The ingestion layer (finance-suite ``portfolio_db.financials``) produces a canonical
``FinancialStatements`` per fiscal year. This module maps that shape onto the FSA's
input dataclasses and runs the scorecard — the missing glue between *fetching* the
data and *scoring* it.

It is deliberately **duck-typed**: it reads the canonical fields by attribute and never
imports finance-suite, keeping the dependency one-way (methodology here; data there —
the Phase 8 boundary). Anything exposing ``.balance_sheet`` / ``.income_statement`` /
``.cash_flow`` with the canonical field names works.

Two shape differences the ingestion model has from the FSA inputs, bridged here:
  * income statements carry no ``revenue_history`` — we assemble it across years;
  * the cash-flow statement carries no ``net_income`` — we splice it from the income
    statement so the payout ratio resolves.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from financial_statement_analyst import (
    GENERAL_PROFILE, BalanceSheet, CashFlow, IncomeStatement, Profile, Scorecard, analyze,
)


def _get(obj: Any, *path: str):
    """Read a nested attribute path, tolerating missing intermediate objects."""
    for name in path:
        if obj is None:
            return None
        obj = getattr(obj, name, None)
    return obj


def _balance_sheet(statements: Any) -> BalanceSheet:
    bs = _get(statements, "balance_sheet")
    return BalanceSheet(
        current_assets=_get(bs, "current_assets"),
        current_liabilities=_get(bs, "current_liabilities"),
        inventory=_get(bs, "inventory"),
        total_liabilities=_get(bs, "total_liabilities"),
        shareholders_equity=_get(bs, "shareholders_equity"),
        goodwill=_get(bs, "goodwill"),
        long_term_debt=_get(bs, "long_term_debt"),
        short_term_debt=_get(bs, "short_term_debt"),
        retained_earnings=_get(bs, "retained_earnings"),
        cash_and_st_investments=_get(bs, "cash_and_st_investments"),
    )


def _income_statement(latest: Any, history: Sequence[Any]) -> IncomeStatement:
    inc = _get(latest, "income_statement")
    # revenue_history: oldest -> newest, latest included, gaps dropped.
    ordered = [*history, latest]
    revenue_history = [r for r in (_get(s, "income_statement", "revenue") for s in ordered) if r is not None]
    return IncomeStatement(
        revenue=_get(inc, "revenue"),
        gross_profit=_get(inc, "gross_profit"),
        net_income=_get(inc, "net_income"),
        revenue_history=revenue_history,
    )


def _cash_flow(statements: Any) -> CashFlow:
    cf = _get(statements, "cash_flow")
    return CashFlow(
        operating_cash_flow=_get(cf, "operating_cash_flow"),
        capital_expenditures=_get(cf, "capital_expenditures"),
        dividends_paid=_get(cf, "dividends_paid"),
        net_income=_get(statements, "income_statement", "net_income"),  # spliced from income statement
    )


def to_fsa_inputs(
    latest: Any, history: Sequence[Any] = (),
) -> tuple[BalanceSheet, IncomeStatement, CashFlow]:
    """Map an ingested ``FinancialStatements`` (+ optional prior years, oldest->newest)
    onto the three FSA input dataclasses."""
    return _balance_sheet(latest), _income_statement(latest, history), _cash_flow(latest)


def profile_for(name: str | None, spec: dict | None) -> Profile:
    """Build an FSA ``Profile`` from finance-suite's profile name + ``profile_spec`` dict.

    Pass ``gics_to_profile(...)`` as ``name`` and ``profile_spec(name)`` as ``spec``.
    With no profile given, falls back to the general profile (all checks active).
    """
    if not name or spec is None:
        return GENERAL_PROFILE
    return Profile.from_spec(name, spec)


def analyze_financials(
    latest: Any,
    history: Sequence[Any] = (),
    profile_name: str | None = None,
    profile_spec: dict | None = None,
) -> Scorecard:
    """Score an ingested ``FinancialStatements`` end-to-end.

    ``latest`` is the most recent fiscal year; ``history`` is prior years (oldest->newest)
    used only to build the revenue trend. ``profile_name`` / ``profile_spec`` come from
    finance-suite's ``gics_to_profile`` / ``profile_spec`` — omit for the general profile.
    """
    balance_sheet, income_statement, cash_flow = to_fsa_inputs(latest, history)
    return analyze(
        balance_sheet=balance_sheet,
        income_statement=income_statement,
        cash_flow=cash_flow,
        profile=profile_for(profile_name, profile_spec),
    )
