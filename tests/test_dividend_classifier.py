"""Tests for the DGIF/DGI/Income/Growth dividend classifier.

Inputs use representative figures for the course's named examples — the point is the
classification logic, not live market data.
"""
from dividend_classifier import DividendProfile, classify


def test_dgif_apple_like():
    # AAPL-like: low yield, low payout, long growth, strong total return
    c = classify(DividendProfile("AAPL", dividend_yield=0.6, payout_ratio=15,
                                 years_dividend_growth=11, div_growth_5yr_pct=45,
                                 annualized_10yr_return=25))
    assert c.bucket == "DGIF"
    assert all(c.dgif_criteria.values())


def test_dgif_visa_like():
    c = classify(DividendProfile("V", dividend_yield=0.8, payout_ratio=22,
                                 years_dividend_growth=14, div_growth_5yr_pct=80,
                                 annualized_10yr_return=18))
    assert c.bucket == "DGIF"


def test_reit_is_income():
    c = classify(DividendProfile("O", dividend_yield=4.3, payout_ratio=75,
                                 years_dividend_growth=27, is_reit=True))
    assert c.bucket == "Income"
    assert "REIT" in c.reasons[0]


def test_high_yield_high_payout_is_income_with_avoid_flag():
    c = classify(DividendProfile("T", dividend_yield=6.5, payout_ratio=70,
                                 years_dividend_growth=0))
    assert c.bucket == "Income"
    assert any("avoid" in f for f in c.flags)        # >= 6% yield guardrail


def test_nvda_fractional_new_dividend_is_growth_judgment():
    c = classify(DividendProfile("NVDA", dividend_yield=0.15, payout_ratio=8,
                                 years_dividend_growth=2, div_growth_5yr_pct=0,
                                 annualized_10yr_return=60))
    assert c.bucket == "Growth"
    assert any("judgment" in f for f in c.flags)


def test_suspended_dividend_is_growth():
    c = classify(DividendProfile("DIS", pays_dividend=False))
    assert c.bucket == "Growth"
    assert "suspended_or_none" in c.flags


def test_mature_grower_misses_total_return_is_dgi():
    # consistent 20-yr grower but low total return + 3.5% yield => DGI, not DGIF
    c = classify(DividendProfile("KO", dividend_yield=3.2, payout_ratio=70,
                                 years_dividend_growth=20, div_growth_5yr_pct=18,
                                 annualized_10yr_return=8))
    assert c.bucket == "DGI"
    assert not all(c.dgif_criteria.values())


def test_abbvie_borderline_high_payout_yield_just_over_4():
    # ABBV-like: ~4.1% yield + high payout => Income (course flags it borderline DGI/Income)
    c = classify(DividendProfile("ABBV", dividend_yield=4.1, payout_ratio=80,
                                 years_dividend_growth=10, div_growth_5yr_pct=40,
                                 annualized_10yr_return=12))
    assert c.bucket == "Income"


def test_dgif_requires_all_five():
    # passes 4/5 (10-yr return only 7%) => not DGIF
    c = classify(DividendProfile("X", dividend_yield=2.0, payout_ratio=30,
                                 years_dividend_growth=8, div_growth_5yr_pct=15,
                                 annualized_10yr_return=7))
    assert c.bucket != "DGIF"
    assert c.dgif_criteria["ann_10yr_return>=10%"] is False
