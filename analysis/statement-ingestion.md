# Statement Ingestion & Sector Metrics — design

Reliably pull the three financial statements for owned + DD-candidate companies, normalize
formats that vary across companies and change over time, and apply the *right* metrics for
the company type. Feeds the Financial-Statement Analyst and the DD experts; enables Phase-5
validation against the real portfolio.

## Layers
1. **Acquire** (ranked by reliability)
   - **SEC EDGAR `companyfacts` (XBRL)** — primary. Free, authoritative (the actual 10-K/10-Q
     the course says to read on sec.gov), GAAP-tagged, full multi-year history per concept.
   - **yfinance** — fast fallback (income_stmt / balance_sheet / cashflow); scraped, flakier.
   - Non-US / no-XBRL → yfinance or manual. (Paid APIs — FMP/Polygon/AlphaVantage — only if needed.)
2. **Normalize** — map source line items → the canonical `BalanceSheet`/`IncomeStatement`/`CashFlow`
   the FSA consumes. **Canonical-mapping-first, per-company override second:** each canonical
   field maps from a *priority list* of candidate GAAP tags (e.g. revenue ←
   `[RevenueFromContractWithCustomerExcludingAssessedTax, Revenues, SalesRevenueNet]`); a small
   per-company override table handles the messy reporters. **Log every fallback / unresolved
   field — no silent gaps.** (XBRL's standardization makes shared-first less work than per-company;
   per-company is only forced for scraped/non-XBRL sources, which EDGAR-first avoids.)
3. **Classify type/sector** — SEC SIC code + GICS (the course's framework) → business-model type
   (SaaS/software, hardware, financials/bank, REIT, consumer/industrial, energy…).
4. **Apply metric profile** — universal checks always run; the sector profile adds/overrides:
   - **SaaS/software:** revenue growth, gross margin, **Rule of 40** (course), P/S & EV/NTM-rev
     (course), FCF margin, net retention (if available), dilution.
   - **Banks/financials:** ROE, net interest margin, book value / P/B (D/E is meaningless → suppress).
   - **REITs:** FFO/AFFO, payout (REIT-exempt from the >90% red flag), leverage.
   - **Mature/consumer/industrial:** the universal ratios + the dividend (DGIF/DGI/Income) metrics.

## Where it lives
- **Acquire + Normalize + Classify** are data-bound → **finance-suite** (alongside Alpaca/holdings;
  EDGAR fetcher there). Emits canonical statement objects.
- **Metric profiles + FSA scoring** are methodology → media-transcribe today (`experts/`), likely
  consolidating into finance-suite with the other data-bound experts (same cross-repo tension as
  the Buy/Sell engine). Keep the canonical statement schema as the contract between them.

## Validation hook
We have OCR'd ground-truth statements (NVDA FY21 income, Tesla 2020 balance sheet, Wingstop 2020
cash flow). **Milestone 1:** pull those filings from EDGAR, normalize, assert the numbers match the
OCR'd values → end-to-end validation of acquire+normalize against known-good data.

## Proposed sequence
1. EDGAR `companyfacts` fetcher + shared GAAP-tag normalizer → canonical statements; validate vs the 3 OCR'd statements.
2. Per-company override mechanism + fallback logging.
3. Wire to portfolio-db holdings (pull statements for everything we own).
4. Sector classifier + the first metric profile (SaaS — the portfolio is software-heavy), then add profiles as needed.
5. Feed the FSA scorer the sector profile; extend the scorecard with sector metrics.
