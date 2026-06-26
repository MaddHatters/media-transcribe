# Metric Catalogue & Sector Applicability

The metrics the experts compute, their formulas, and **which company types each applies to**.
"Course" = taught in the masterclass (see mental-model.md); others are standard finance we add.
The Financial-Statement Analyst runs the *universal* metrics always, then layers the *sector
profile* (and suppresses metrics that don't apply, e.g. a bank's debt-to-equity).

## Catalogue (metric — formula — needs — source)

**Profitability / quality**
- Gross margin — GrossProfit / Revenue — IS — *course* (moat detector vs peers)
- Operating margin — OperatingIncome / Revenue — IS
- Net margin — NetIncome / Revenue — IS — *course*
- ROE — NetIncome / ShareholdersEquity — IS+BS — *course*
- ROIC — NOPAT / InvestedCapital — IS+BS
- **Rule of 40** — revenue_growth% + FCF-margin% (or EBITDA-margin%) ≥ 40 — IS+CF — *course (SaaS)*

**Liquidity / solvency**
- Current ratio — CurrentAssets / CurrentLiabilities — BS — *course* (<1.5 concern)
- Quick ratio — (CurrentAssets − Inventory) / CurrentLiabilities — BS — *course* (<1 concern)
- Debt-to-equity — TotalLiabilities / Equity — BS — *course* (>100% red flag; **suppress for banks**)
- Interest coverage — OperatingIncome / InterestExpense — IS — *course* (⚠ taught inverted — verify)
- Net tangible assets — Equity − Goodwill — BS — *course* (<0 = concern)

**Cash flow**
- FCF — OperatingCashFlow − CapEx — CF — *course* (replacement vs growth capex caveat)
- FCF margin — FCF / Revenue — CF+IS
- FCF yield — FCF / MarketCap — CF+price — *course (MC15)*
- Payout ratio — DividendsPaid / NetIncome — CF — *course* (>90% red flag; **REIT-exempt**)

**Valuation**
- P/E (trailing & forward) — Price / EPS — *course*
- PEG — P/E / earnings_growth — *course* (≤1 attractive)
- P/S — MarketCap / Revenue — *course* (use when unprofitable — SaaS)
- P/B — Price / BookValuePerShare — *course* (<1 = margin of safety; key for banks)
- EV/EBITDA — EnterpriseValue / EBITDA — *course (MC15)*
- **EV/NTM revenue** — EV / next-12-mo revenue — *course (MC15, SaaS)*
- EBITDA — EBIT + D&A — IS+CF — *course* (⚠ instructor calls it "flawed" — flag, don't lean on it)
- DCF / DDM / sum-of-parts — *course (listed)*

**Growth / dilution**
- Revenue growth (YoY) & ≥3-yr decline flag — IS — *course*
- Dilution — share-count growth YoY — IS — *course* (red flag)
- Net revenue retention — (SaaS-specific; rarely in filings) — non-course

**Dividend** (handled by the dividend classifier) — yield, payout, 5-yr div growth — *course (DGIF)*

## Type → applicable-metric matrix
Legend: ✅ key · 🟡 used · — n/a / suppressed

| Metric | SaaS / Software | Mature / Consumer / Industrial | Bank / Financial | REIT |
|---|---|---|---|---|
| Rule of 40 | ✅ | — | — | — |
| EV/NTM revenue | ✅ | — | — | — |
| P/S | ✅ (pre-profit) | 🟡 | — | — |
| Gross margin (moat) | ✅ | ✅ | n/a | — |
| EV/EBITDA | 🟡 | ✅ | — | — |
| P/E, PEG | once profitable | ✅ | ✅ | — (use P/FFO) |
| ROE | 🟡 | ✅ | ✅ | 🟡 |
| Net interest margin | — | — | ✅ | — |
| Current / quick ratio | ✅ | ✅ | — | 🟡 |
| Debt-to-equity >100% flag | ✅ | ✅ | **suppress** | 🟡 (leverage-aware) |
| P/B / book value | 🟡 | 🟡 | ✅ | — (use NAV) |
| FFO / AFFO, FFO payout | — | — | — | ✅ |
| Payout ratio >90% flag | rare | ✅ | ✅ | **REIT-exempt** |
| FCF / FCF margin / yield | ✅ | ✅ | — | 🟡 |
| Dividend (DGIF/DGI/Income) | rare | ✅ | ✅ | ✅ (income) |

## Sector profiles (the registry)
- **SaaS / software:** Rule of 40, revenue growth, gross margin (high), P/S, EV/NTM-rev, FCF margin,
  dilution, EV/EBITDA once profitable. (Pre-profit → no P/E.)
- **Mature / consumer / industrial:** universal ratios + P/E/PEG, EV/EBITDA, FCF, dividend metrics.
- **Bank / financial:** ROE, net interest margin, efficiency ratio, P/B / book value; **suppress
  D/E and current/quick ratios** (don't apply to balance-sheet structure of a bank).
- **REIT:** FFO/AFFO, P/FFO, NAV, leverage; payout **exempt** from the >90% flag (REITs must distribute).
- Classify type via SEC SIC code + GICS sector (the course's framework).
