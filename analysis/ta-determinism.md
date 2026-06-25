# Deterministic Technical-Analysis Engine — Spec

The goal: a **deterministic** TA engine that outputs concrete numbers and buy/sell
targets. The course's TA (MC6, MC10) is mostly *discretionary/visual*, so this splits
into three layers: **(1) codeable rules** the course states precisely, **(2) priced
test cases** to validate against, and **(3) formalization targets** — judgment calls the
course leaves visual that we must turn into explicit rules ourselves.

> The instructor's own disclaimer (MC10): *"put 10 chart masters on one chart and you'll
> get slightly different answers."* TA is not fully deterministic in the source; layer 3
> is where we add determinism the course never provides.

## Layer 1 — Codeable rules (implement directly)

| ID | Rule | Action |
|---|---|---|
| D1 | Long-term MA set = 50/100/200-day, computed on the **1-day** chart | compute MAs |
| D2 | 200-day SMA = primary support / best buy level | default buy target = 200-day |
| D3 | High conviction → buy at 50 or 100-day instead of waiting for 200 | conviction raises buy MA |
| D4 | Price closes **below** 200-day + conviction → "load up" (larger lot) | add aggressively |
| D5 | 20-day SMA = short-term uptrend support (Bollinger) | optional short-term level |
| D6 | RSI bounds 0–100; **>70 overbought, <30 oversold** | standard zones |
| D7 | RSI **≥ 90** → expect ~20% correction → flag "don't buy / consider trim" | trim/avoid flag |
| D8 | SMA for support/resistance; EMA for growth-stock trend | indicator selection by bucket |
| D9 | EMA needs >10 days of data to be valid | data-sufficiency guard |
| D10 | Read RSI/MAs on **1-day** candles (RSI is timeframe-dependent) | default timeframe |
| D11 | Fibonacci breakdown target ≈ erase **~2/3** of the prior move | downside target |

Bucket coupling: TA is the **"last 1%"** — only refines entry/exit after fundamentals pass.
Lot plan integrates with DCA (see [dd-playbook.md] DCA section): bull 2–3 lots, bear 10–30.

## Layer 2 — Priced test cases (regression fixtures)

- **Dollar General (DG)** — DGIF, yield 0.73%, ~$50B cap. **SMA200 = 200.38 / EMA200 = 197.91**;
  bought ~**$194** with drawn support **$192.44 / $193.03**; RSI(14) 49.84; price 203.41 (+2.5%).
  Exercises D2+D4+retest. (Note: ~$194 was the buy price, near — not equal to — the 200-day.)
- **Cloudflare (NET)** — growth. ~**$93**, parabolic at ATH, earnings in 2 days. EMA10 85.33 /
  SMA200 50.50. RSI(14) **92.08** ("Sell") and **~68** ("Neutral") across timeframes (exact
  1mo/1wk/1day split narration-only). Exercises D8+D10.
- **JFrog** — trading channel, support **$59** / resistance **$70** (recent IPO, limited data).
- **Salesforce** — touched 200-day with bad sentiment, took 1–2 yrs to recover (slow-mean-reversion case).
- **MindMed** — sold on extreme RSI, kept rising (RSI can stay >90 for days/weeks; overbought ≠ immediate sell).

## Layer 3 — Formalization targets (the course is discretionary; WE define the rule)

These are the judgment calls that block determinism. Each needs an explicit, testable rule
we invent (then validate against Layer 2 + new cases):

1. **Triangle-apex breakout direction** (biggest gap) — identical ascending/descending/
   symmetrical triangles break opposite ways; the course says "read the candles at the apex"
   with no rule. *Define:* apex window size + a candle-classifier → breakout-direction signal.
2. **Candlestick recognition** — hammer/engulfing/doji/marubozu/star defined only visually.
   *Define:* body/wick ratio thresholds (e.g. lower-wick ≥ 2× body = hammer; full overlap =
   engulfing).
3. **Trend-line drawing** — "click the lows," manual. *Define:* pivot-selection + touch tolerance.
4. **Support/resistance & channel levels** — eyeballed. *Define:* algorithmic level detection.
5. **"Parabolic / frothy" trim trigger** — loosely RSI≥90 and "30–50% over the 200-day."
   *Define:* a concrete %-over-MA and/or RSI threshold.
6. **RSI divergences & failure swings** — named, never defined.
7. **"Which MA it bottoms at"** / "EMA until it doesn't" — demand-dependent, qualitative.
8. **Whether a 200-day break has a fundamental reason** — requires fundamental input (route to DD).
9. **Air pockets** (🆕 not in the course — 0 hits; from chart-day videos / general TA) — now
   given a **provisional deterministic** definition: *parabolic rip way above the 200-day* =
   extended ≥30% above the 200-day MA AND ripped ≥15% above the 50-day MA. Implemented in
   finance-suite `indicators.py::air_pocket()`. ⚠ thresholds pending chart-day-video calibration;
   the "air" is the gap from the overextended price down to the 200-day. See
   [buy-sell-engine.md](buy-sell-engine.md).

## Recommended build
A pure-function engine: inputs = OHLCV history + bucket + conviction flag; outputs = MA
levels, RSI(1-day), support/resistance, a **buy zone** (around the applicable MA + retest
band), a **trim/sell flag** (D7 + formalized #5), and a **lot plan** (DCA coupling).
Layer-1 rules ship first (fully testable against Layer 2). Layer-3 items ship behind a
"confidence: low" tag until validated. Keep it deterministic and unit-tested — same inputs,
same numbers — so it can be a reliable tool the other experts call.
