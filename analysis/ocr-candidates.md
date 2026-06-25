# OCR Candidates Register (Phase 3 input)

Spots where a slide/chart/table/image is referenced but its content is **not fully
spoken** — so the transcript is missing data without seeing the screen. Phase 3 extracts
the frame at each timestamp and OCRs it (tesseract for text, a vision model for
charts/tables), then merges the recovered context back into the mental model.

Timestamps are from each episode's `.srt`. **P1** = high value (numeric tables /
financial statements / allocation charts / "pause your screen" content); **P2** =
medium (definition/criteria slides, lists); **P3** = low (decorative images, quote
slides mostly read aloud).

## Priority summary — do these first (P1)
- **MC7** — Tesla 2019/2020 balance sheet (full statement, ~22:57→33:13): nearly every dollar value is on-screen-only.
- **MC9** — NVIDIA income statement (02:06+) and Wingstop cash-flow statement (32:36+): full multi-column tables, few values spoken.
- **MC13** — hand-drawn $5M end-game pie (10:14–13:03) + 50-stock sector dividend table with per-name yields (13:30–17:15).
- **MC15** — semiconductor 4-pillar megatrend flowchart (32:31–35:30, "not going to read all this") + Microsoft $52.75B segment-revenue breakdown (49:16) + Y Charts/Fidelity 5-metric panel (52:01).
- **MC10** — entire candlestick/chart-pattern slide library + annotated raw-vs-marked yearly chart (39:30–41:00).
- **MC2** — Fidelity GICS sector-allocation chart (23:43) + GICS pyramid (25:47).
- **MC14** — NVIDIA options chain (24:24), tax-loss-harvest infographic (29:09), loss-recovery % table (35:50).
- **MC16** — Tom Brady stat block (20:14, "other stats bottom-right"), missing-best-days S&P table (08:42), Finviz/TradingView screenshots.
- **MC17** — Mistake-8 cluster (SEC stat, Yahoo Finance article, headline montage "pause your screen," Oxford GameStop study).
- **MC18** — Discord "F arts" screenshot ("hard to read", ~20:00) + investor.gov calculator result (with filled fields).

---

## Per-episode register

### MC1 — History & Intro
- 03:20 (P3) Dutch East India trade-network map + legend
- 08:13 / 09:01 (P2) Twilio & DraftKings offering screenshots ($247, $52)
- 26:57 (P1) investor.gov compound calculator ($10k+$500/mo, 30yr, 10% → $1,161,000)
- 29:25 (P1) S&P 500 chart 1928–2020; 30:39 (P1) 60-yr compounding curve
- 33:45 (P2) inflation calculator + Vespa $7,749 image
- 35:02 / 36:03 (P1) asset-class return charts 1926–2017 & Visual Capitalist 2010–2019 (returns + std-dev table)

### MC2 — Basics 101
- 02:44 / 05:08 / 06:03 (P2) index lists; Yahoo/investing.com world-indices tables
- 11:13 / 18:15 / 21:23 (P1) S&P/Dow/NASDAQ historical charts (incl. NASDAQ 4,000 breakeven line)
- **23:43 (P1) Fidelity GICS sector-allocation chart** (per-sector % vs recommended 18–36% band; he's 54% tech)
- **25:47 (P1) MSCI GICS pyramid** (11 sectors/24 groups/69 industries/158 sub)
- 28:59 (P1) Wikipedia exchange table (market-cap column); 34:31 (P2) ETF-examples slide; 38:05 (P2) brokerage list/logos

### MC3 — Basics 102
- **23:34 (P1) hand-drawn 8/10 pie** (25/20/40/10/5); 45:36 (P1) 6/10 & 4/10 hand-drawn pies
- 26:23 (P2) ETF table w/ expense ratios; 31:20 (P1) "ETF ideas" master list
- **36:25 (P1) DGIF sector table** (tickers per sector, starred = not true DGIF)
- 41:42 / 43:31 (P2) growth + spec ticker/logo slides
- **56:15 (P1) Top-100 ETFs by AUM table** (AUM + volume cols); 59:31 (P2) dividend tax-rate table
- 01:06:41 (P1) ARK distributions table; 01:11:33 (P2) live WCLD limit-order ticket

### MC4 — Basics 103 (fundamentals)
- **08:54–13:47 (P1) Tesla balance sheet (live)**; 17:44 (P1) sample income statement
- 28:14 (P1) NVIDIA quick-glance + quarterly rev/margin (56.8% / 28.27%)
- 30:46 / 36:46 (P2) P/S, P/E, PEG, P/B formula slides

### MC5 — Peter Lynch
- 05:46–07:41 (P2) investor icon/photo deck (Buffett, Munger, Bogle, Kiyosaki, Wood, Lee, Cramer, Najarians) — names/book titles
- 21:50 (P2) 6-categories slide; 25:37 (P2) Magellan/holdings chart
- 36:49 / 39:08 (P2) book pages 18 & 23 ($341,722 vs $153,792 market-timing figures)

### MC6 — Intro to Technical Analysis (chart-heavy)
- 10:10 (P1) Fidelity ATP full indicator menu; 18:53 (P1) Dow investor-psychology cycle chart
- 26:43 / 37:00 (P1) TradingView Cloudflare trend lines + technical-summary (RSI by timeframe 92/73/68; MA values)
- 32:43 (P2) SMA/EMA illustration slides; 43:57 (P1) Dollar General 200-day chart w/ retest $192.44; 46:03 (P1) JFrog channel

### MC7 — Balance Sheet Deep Dive
- 06:23 (P2) Enron chart ($90.75 → $0.26); 16:01 (P2) Enron broadband diagram; 19:52 (P2) news headlines
- **22:57→33:13 (P1) Tesla 2019/2020 consolidated balance sheet** — full statement, both years; only cash ($6,268M→$19,384M) & goodwill ($198M→$207M) spoken. Top OCR target.
- 40:14 (P1) current-ratio tier chart (3 numeric tiers shown, never stated)

### MC9 — Income Statement & Cash Flow
- **02:06 (P1) NVIDIA income statement** (3 cols, all line items); 12:02 confirms GP $10,396M / rev $16,675M
- 24:58 (P1) net-income series 4,141/2,796/4,332; 26:44 (P1) EPS rows
- **32:36 (P1) Wingstop cash-flow statement** (3 cols, all sections); 37:08 ending cash "59,xxx"; 57:47 special-dividend article ($5/share)

### MC11 — Intro to Options
- 08:52 (P1) Fidelity CRM covered-call ticket (premium not spoken)
- 14:31 (P2) Buffett/Coke case-study slide; **17:32 (P1) ATP SNOW option chain** (strikes/bid/ask/probabilities)
- 24:33 / 27:46 (P1) SNOW covered-call ($300/$510) & cash-secured-put ($200/$430/$20k) tickets; 32:02 (P2) married-put slide

### MC8 — Psychology & Discipline
- 10:09 (P1) market-emotion cycle curve (stage labels/positions)
- 20:59 (P2) anchoring mug infographic; 21:48 (P2) self-attribution infographic
- **29:50 (P1) Barber–O'Dean returns/turnover table** (18.5/11.4/7.1%, 21% turnover)
- 31:39 (P2) Kahneman–Tversky PDF gamble ratios; 35:50 (P2) loss-aversion "napkin" value function
- 37:10 (P2) MPT 4-asset table; 40:56 (P1) Credit Suisse loss-aversion-by-country bar chart; 01:06:48 (P2) SEC 300-vs-3-4 PDF

### MC10 — Technical Analysis II (richest visual target — OCR all)
- 03:22 / 04:09 (P1) candlestick anatomy diagram + hand-drawn candles
- 06:39 (P1) Fidelity QQQ multi-duration/candle-type demo + menus
- 11:52–21:00 (P1) pattern library slides: hammer family, doji+marubozu, spinning tops, engulfing/harami/tweezers, triple-candle (4 examples each)
- 21:00–25:35 (P1) upside/downside reversal master grids + side-by-side comparison (~12 mini-charts each)
- 25:35 (P2) his buy/sell signal slide; 27:03 / 28:01 (P1) continuation + chart-pattern taxonomy slides
- 29:33 (P1) bilateral-triangle slide + live annotation (apex candle difference); **39:30 (P1) raw-vs-annotated yearly chart**

### MC12 — Personal Finance (lightest)
- 09:01 (P2) SEC goal-setting worksheet; 10:02 (P2) net-worth assets/liabilities table; 11:21 (P2) budget category worksheet
- 15:01 (P1) compound-interest calculator ($1,825 + $150/mo, 5yr, 10% → $13,928.36) + Motley Fool article
- 25:04–33:00 (P2) two numbered account-priority "waterfall" slides (his order vs standard)

### MC13 — Passive Income Portfolios
- 00:36 / 01:12 / 09:58 (P2) 8/10 blueprint slide/table w/ ticker examples
- 05:50 (P2) growth-category spreadsheet (color-coded holdings)
- **10:14–13:03 (P1) hand-drawn $5M end-game pie** (40/30/25/5 + sub-splits + $ amounts)
- 13:03 (P2) 8/10-vs-end-game transformation slide
- **13:30–17:15 (P1) 50-stock sector dividend table** (per-name yields: O 4.3%, XEL 2.8%, NWE 4.3%, SPG 6.8%, CVX 3.85%…) — heaviest target
- 17:15 (P1) final income-summary table ($58K/$63K/$121K/2.5%/$10,083/mo)

### MC14 — When to Sell Stocks
- 03:20 (P3) Philip Fisher quote slide; 07:15 (P2) "story changed" trigger list
- 10:56 (P1) KnowBe4 deal chart/news ($24.90, dates); 12:44 (P1) Teladoc/Livongo terms (0.5920 + $11.33, 58/42)
- 15:11 (P2) NVDA analyst price-target chart; **24:24 (P1) NVDA options chain** ($950/$3,000)
- 29:09 (P1) tax-loss-harvest infographic; 30:24 (P2) wash-sale 61-day timeline; **35:50 (P1) loss-recovery % table**

### MC15 — Portfolio Plans & Purchasing Steps
- 01:40 (P2) investor.gov compounding ($10k+$1k/mo, 20yr, 12.5% → $1M+)
- 17:03 (P2) megatrends slide; 21:09 / 21:46 (P2) 8/10 pie + DGIF criteria slides; 28:46 / 29:05 (P2) 6/10 & 4/10 slides
- 31:01 (P1) $5M end-game slide (re-shown); **32:31 (P1) semiconductor 4-pillar flowchart** ("not going to read all this")
- 36:00 (P2) "Should I buy MSFT?" decision flowchart; 40:00 (P2) valuation-metrics master list; 42:12 (P2) PE/PEG/PS/PB explainer cards
- **49:16 (P1) Microsoft $52.75B segment-revenue breakdown**; **52:01 (P1) Y Charts vs Fidelity 5-metric panel** (PEG 63.07 vs 2.27, PS 11.13/11.18, PE history to 2012)

### MC16 — Tips & Tools
- **08:42 (P1) missing-best-days S&P table** (2003–2022: 9.8/5.6/2.9/−4.2%)
- 10:23 (P1) Finviz screenshots (heat map, screener filters, futures, crypto); 13:45 (P1) Upstart chart ($11.93 low / anomalous $7,258 high)
- 15:57 (P2) TSM vs NVDA P/E Discord screenshot; 18:38 (P2) Buffett/Lynch stat slides
- **20:14 (P1) Tom Brady stat block** ("other stats bottom-right"); 29:06 (P1) TradingView QQQ indicators
- (late) (P1) DCA-outcomes infographic ($175k/$162,410/$141,371/$64,386); (late) (P2) analyst-rating ladder table

### MC17 — 12 Common Mistakes
- (M1) (P2) investing-vs-gambling comparison table; (M2) 11:58 (P1) NVDA 1,300% chart; 13:41 (P2) six-SaaS Twitter screenshot
- (M6) (P1) S&P annual-returns table 2000–2021 (9% avg, −36.5% in 2008)
- **(M8 cluster, P1):** SEC "70% lose / 100% within 12 mo" stat; Yahoo Finance "$40k by 19 / $200k unrealized" article; headline montage ("pause your screen"); Oxford GameStop study ("+145% in one day")
- (M11) (P2) time/money/returns 3-pillar graphic

### MC18 — Playing to Win, DCA & Goals
- 04:27 (P2) penalty-shootout stats slide (93/73/44%); 06:40 (P2) house-shares / $1.7M figures
- 09:33 (P3) DCA definition slide (reused from MC16)
- **~20:00 (P1) Discord "F arts" screenshot** (instructor says "hard to read" — verbatim Q&A only partly narrated)
- (P2) goal-tracking spreadsheet + SMART-goals slide
- **(P1) investor.gov calculator** ($5,000 + $1,000/mo, 30yr, 12% → $3,045,791.82, filled fields + breakdown)
- (P2) 8/10 blueprint allocation pie ("or so" percentages); daughter UTMA NVDA +1200% screenshot

---

## Notes for Phase 3
- Frames extract cleanly from the `.mkv` at the listed timestamps via ffmpeg; dedupe
  near-identical frames per slide before OCR.
- Use **tesseract** for text-dense slides (statements, tables, headlines) and a **vision
  model** for charts/diagrams/flowcharts (candlestick library, semiconductor flowchart,
  emotion cycle) where layout/shape carries meaning.
- Reconcile known anomalies during OCR (e.g. MC16 Upstart "$7,258 52-week high" is almost
  certainly a split-adjusted/label artifact).
