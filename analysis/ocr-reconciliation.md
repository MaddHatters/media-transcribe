# OCR Reconciliation (Phase 3) — findings validated + corrections + recovered data

Result of OCR'ing all 18 episodes (2,900+ slides, local/free) and diffing the recovered
slide text against the transcript-based mental model. **Outcome: findings overwhelmingly
confirmed; a handful of corrections; large amounts of skipped numeric data recovered.**
The full per-episode slide text lives at `/mnt/secondary/media/patreon/FIRE Investing
Masterclass/ocr/<stem>/slides.{md,json}` (gitignored). This doc captures the corrections
and the highest-value recovered tables; bulk statements stay in `slides.md`.

## Corrections applied to the knowledge base
1. **DGF → DGIF.** The slides label the bucket **"D.G.I.F." = Dividend Growth Investing for
   FIRE(D)** (MC1 17:42, MC9 52:50, MC13 01:44, MC15 21:44). The instructor says four letters;
   our transcript correction had collapsed it to "DGF." DGIF is canonical. (DGI — the
   income-growth *strategy* — is still distinct.) Note: the transcripts still read "DGF" from
   the earlier correction dictionary; optionally re-map DGF→DGIF there too.
2. **NVDA margins (MC4 quick-glance, 28:49):** "56.80%" = *year-over-year revenue growth*,
   **not** gross margin; 28.27% = net profit margin (correct). No gross-margin line is on that
   slide. The real 62.3% gross margin comes from **MC9's income statement** (10,396/16,675),
   which OCR confirms — so the mental model's 62.3% is right, just sourced from MC9 not MC4.
3. **Dollar General (MC6):** 200-day SMA was **200.38** (EMA200 197.91); the ~$194 figure was
   the *buy/close price*, and $192.44/$193.03/$194.00 were drawn support lines. RSI(14) 49.84.
4. **MC14 NVDA option:** **DEC-20-2024 $900 call** (not $950), limit $30, **$3,000 credit**,
   8% prob above strike; position 283.7 sh @ $38 cost basis ("house shares").
5. **Barber–O'Dean (MC8):** turnover is *mean monthly* — least-active 0.19%/mo (18.5%/yr),
   most-active **21.49%/mo** (11.4%/yr). The "21%" is monthly, most-active only.
6. **Cloudflare RSI (MC6):** OCR shows **92.08** and **~68** only (no "73"); the 1mo/1wk/1day
   timeframe attribution is narration-only (unverifiable from slides).
7. **MSFT metrics (MC15):** Fidelity panel = P/S **11.13**, **P/B 11.42** (our "11.18" was a
   mis-read of P/B), PEG **2.27** vs YCharts' wrong **63.07**; P/E TTM 32.7 / fwd 29.1 / next-yr 25.3.
8. **Spec sizing (MC3 slide 29:14):** "10–20 stocks, **1–2% per holding**" (a %, like DGIF);
   the "$500–$1,000 / 10x-or-zero" framing is narration, not on the slide.

## Not recovered (still narration-only or need the vision pass)
- The investor/influencer photo deck (MC5), the MPT/Markowitz "300-stock vs 3–4" slide (MC8),
  and the book-page market-timing figures ($341,722 vs $153,792, MC5) did not OCR (image/PDF).
- **Chart *shapes/diagrams*** — candlestick diagrams, the semiconductor flowchart hierarchy
  (arrows), the emotion-cycle curve, hand-drawn pies — yield labels but not gestalt. These are
  the **Phase-3 tail / Mac-mini vision POC** targets.

---

## Recovered reference data (highest-value)

### Candlestick & chart-pattern library (MC10) — full list for the TA engine
**Single:** Hammer, Inverted Hammer, Hanging Man, Shooting Star · Doji, Doji Star, Long-Legged
Doji, Four-Price Doji, Gravestone Doji, Dragonfly Doji · Bullish/Bearish Marubozu · Bullish/
Bearish Spinning Top. **Double:** Bullish/Bearish Engulfing · Bullish/Bearish Harami · Tweezer
Top/Bottom. **Triple:** Morning Star, Evening Star, Three White Soldiers, Three Black Crows.
**Upside-reversal grid:** + Morning Doji Star, Dragonfly Doji, Long-Legged Doji, Tweezers
Bottom, Belt Hold, Piercing Line, Counterattack Line. **Downside-reversal grid:** + Evening
Doji Star, Gravestone Doji, Tweezers Top, Belt Hold, Dark Cloud Cover, Counterattack Line.
**His buy signals:** Bullish Engulfing, Morning Doji Star, Hammer, Rising Sun. **Sell:** Bearish
Engulfing, Dark Cloud Cover, Shooting Star, Hanging Man. **Continuation:** Tasuki gaps, side-by-
side white lines, rising/falling three methods, mat hold, three-line strike, on/in neck line,
thrusting, separating lines. **Chart patterns:** Double Top/Bottom, H&S, Inverse H&S, Rising/
Falling Wedge, Bullish/Bearish Rectangle, Bullish/Bearish Pennant, Ascending/Descending/
Symmetrical Triangle (each with a Target projection).

### Analyst rating ladder (MC16, Investopedia) — 1 (bullish) → 5 (bearish)
| Tier | Synonyms |
|---|---|
| Strong Buy (1) | Strong Buy |
| Moderate Buy / Outperform (2) | Moderate Buy, Accumulate, Add, Overweight |
| Hold (3) | Hold, Neutral |
| Moderate Sell / Underperform (4) | Moderate Sell, Weak Hold, Reduce, Underweight |
| Strong Sell (5) | Sell, Strong Sell |
*"Underperform ≠ Sell" — it's mid-bearish.*

### Loss-recovery table (MC14) — gain needed to break even
5%→5.26 · 10%→11.11 · 20%→25 · 30%→42.86 · 40%→66.67 · 50%→100 · 60%→150 · 70%→233.33 ·
80%→400 · 90%→900 · **95%→1,900%**.

### Missing-best-days (MC16, $10k S&P 2003–2022, J.P. Morgan)
Fully invested $64,844 (9.8%) · miss 10 → $29,708 (5.6%) · 20 → $17,826 (2.9%) · 30 → $11,701
(0.8%) · 40 → $8,048 (−1.1%) · 50 → $5,746 (−2.7%) · 60 → $4,205 (−4.2%).

### DCA outcomes (MC16, $2k/yr × 20yr)
Perfect timing **$175,126** · invest immediately **$162,410** · bad timing **$141,371** · cash
**$64,386**. ("Even bad timing beats staying in cash.")

### MSFT segment revenue (MC15, Q2 FY23, total $52.75B)
Server+Cloud $19.59B · Office+Cloud $11.84B · Windows $4.81B · LinkedIn $4.76B · Gaming $3.88B
· Search/News Ads $3.22B · Enterprise Svcs $1.86B · Devices $1.43B · Other $1.36B.

### Semiconductor megatrend — 4 pillars (MC15)
(1) SaaS/Cloud/Cybersecurity/Data/AI/Quantum · (2) EV/Clean Energy/E-commerce/Web2.0/IoT ·
(3) Rare Earth/Future Materials/Space · (4) Semiconductors (mining→materials→equipment→
foundries→fabless→production). "Semis are the new oil — they fuel everything." (Node→pillar
arrows lost to OCR — vision-pass target.)

### Financial statements (recovered in full — see slides.md)
- **Tesla balance sheet:** MC4 has the **Q3 10-Q (Sep-30-2020)** version (total assets 45,691,
  cash 14,531); MC7 has the **annual 10-K (Dec-31-2020)** version (total assets 52,148, cash
  19,384). Different periods — both correct; not a contradiction.
- **NVIDIA income statement (MC9):** FY21/20/19 — revenue 16,675/10,918/11,716; gross profit
  10,396/6,768/7,171; net income 4,332/2,796/4,141; diluted EPS 6.90/4.52/6.63.
- **Wingstop cash flow (MC9):** OCF 65,530; the $163,792K 2020 dividend drives the special-
  dividend ($5.00/sh) investigation; ending cash 59,270.
- **Top-100 ETFs by AUM (MC3):** SPY $325.5B, IVV $238B, VTI $192B, VOO $172B, QQQ $147.7B …
- **Asset-class returns (MC1):** Ibbotson 1926–2017 — small 12.1%, large 10.2%, govt bonds 5.5%,
  T-bills 3.4%, inflation 2.9%; Visual Capitalist 2010–19 table (US small cap 11.87% top).

### Methodology correction — debt-to-equity means DEBT, not total liabilities (MC7/MC9)
Verified from the MC9 "Top 10 Red Flags" slide + transcript (and MC7's green flags):
- **#1 Rising debt-to-equity** — "a company is absorbing more **debt** than it can handle.
  If the debt-to-equity ratio is over 100%, it's a red flag." → numerator is **interest-bearing
  debt**, not total liabilities.
- **#8 Consistently higher liabilities than assets** ("over-leveraged") and **#2 Negative
  equity** are *separate* flags — that is the total-liabilities-vs-assets concept.
- MC7 green flag: **"Low or Zero Long-Term Debt."**

The FSA originally computed D/E as total liabilities ÷ equity, conflating #1 with #8 and
false-flagging deferred-revenue/lease-heavy but debt-light businesses. Fixed to interest-bearing
debt (long-term + short-term/current debt) ÷ equity. Live-portfolio validation (FY2023):
ABNB total-liab/eq 1.53 → debt/eq **0.24** (false flag removed); CELH ~0 debt (removed);
AVGO **1.63** and AAPL **1.69** still flag on real debt (true positives); Tesla 2020 **0.43**.
Ingestion gained a `short_term_debt` field; `long_term_debt` tag list broadened to include
`LongTermDebtAndCapitalLeaseObligations` (AVGO) to fix fragmented EDGAR debt tags.
