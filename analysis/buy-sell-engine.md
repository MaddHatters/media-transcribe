# Buy/Sell Point Engine (hybrid deterministic + LLM)

> **Status: deterministic core IMPLEMENTED** in finance-suite (branch
> `feat/buy-sell-engine-primitives`): `stock_analyzer/tools/engine.py`
> (`build_buy_plan`/`build_sell_plan`/`analyze_ticker`) over `Fractals.get_levels`,
> `indicators` (MA/RSI/Fibonacci/`air_pocket`), and `house_shares_to_sell`. 24 tests.
> Pending: LLM judgment layer, air-pocket threshold calibration (chart-day videos).

Identifies entries and exits that fit the FUW methodology for a given ticker. It is a
**composition**, not a new data source: it orchestrates the **Deterministic TA Engine**
([ta-determinism.md](ta-determinism.md)) for levels, the **DCA Planner** (FUWTALAS lot
allocation), and the **Sell-Discipline expert** (profit-taking → house shares). Gated by
**DD** — never buy/sell on price alone ("is the business broken or the stock broken?").

Deliberately **hybrid**: deterministic math computes the levels and the lot/profit
arithmetic; an **LLM judgment layer** handles the fuzzy calls the course leaves visual.

## Deterministic layer (compute exactly)
- 50/100/200-day MAs; RSI on the 1-day chart; volatility/ATR.
- Fibonacci retracement & extension levels from a defined swing.
- Support/resistance candidates (prior pivots / consolidation zones / volume nodes).
- **FUWTALAS lot math:** 20–25% per lot → bull 2–3 lots, bear 10–30 lots; per-lot $ and the
  trigger price for each lot (at the 200-day, then 100/50-day or Fib/support steps).
- **House-shares math:** shares to sell to recover the *initial cost basis*; remaining
  "house" (free-rider) shares. Deterministic given cost basis + current price.

## LLM / judgment layer (the Layer-3 formalization targets)
- **Air-pocket detection** — is there real support *beneath* the entry, or a void (gap /
  thin zone / no prior pivot) it can fall through? Don't add into a pocket.
- **Support quality** — which candidate levels are real vs noise.
- **Story intact?** — route to DD; conviction gates everything.
- **Conviction → which MA to buy at** (200-day default; 50/100-day if high conviction).
- **"Parabolic / frothy"** trim judgment beyond the RSI≥90 flag.

## Reuse from finance-suite (don't rebuild)
The data-bound primitives already exist in the **finance-suite** repo:
- **Support/resistance:** `data-analysis/stock_analyzer` → `tools/levels/fractals.py` (`Fractals`).
  Fractal pivots clustered into levels with a **conviction** score (# touches) + estimated
  volatility, off Alpaca bars. *Improve:* it currently only plots/prints — expose
  `get_levels(ticker, days) -> List[Level]` so it returns data. Conviction powers air-pocket
  detection (no conviction-scored support within X% beneath entry).
- **House shares:** `portfolio-api/.../services/cost_basis.py::shares_to_house_shares(
  cost_invested, proceeds, open_shares, current_price)` → shares to sell to reach house shares
  (0 if already there, capped at holding). Reuse as-is. Plus `PositionCostBasis.is_house_shares`,
  `.cost_recovered_pct`, `.net_invested`.
- **Market data + cost basis:** Alpaca via `stock_analyzer` data providers; positions/cost basis
  via `portfolio-db`/`portfolio-api`.
- **To add (not present):** 50/100/200-day MAs, RSI, Fibonacci — trivial with pandas on the
  same bars.

## Buy logic (entries that fit the methodology)
1. **Gate:** fits the blueprint bucket + story intact (DD)? If not → no buy.
2. **Prefer at/below the 200-day MA** (primary support); 50/100-day for high conviction.
3. **Scale in via FUWTALAS lots** at support/Fib levels — never all at once (bull 2–3 @
   20–25%; bear 10–30, nibble down).
4. **Avoid air pockets** — only add where support exists beneath the entry (a prior pivot/
   consolidation/MA). If the level sits above a void, wait for the next real support.
5. **Add on a confirmed 200-day break + retest** (the Dollar General pattern) if conviction holds.
- **Output:** a buy zone, the lot ladder (price + $ per lot), and air-pocket warnings.

## Sell logic (exits + house shares)
1. **Never sell on price alone** — run the Sell-Discipline 12 reasons first.
2. **Trim into strength:** at resistance / Fibonacci extension / RSI 70–90 / parabolic.
3. **House shares:** once a position has run, sell shares equal to the **initial cost basis**
   (e.g. $5k → $20k, sell $5k), let the rest ride risk-free. The *quantity* is deterministic;
   the *when* is judgment (overbought / overvalued / target hit).
4. Optionally **exit via cash-covered calls** at a target strike (Options-Income expert).
- **Output:** trim/sell levels, the house-shares sell quantity, the resulting free-rider position.

## Provenance flags (course-grounded vs added)
- 🟢 200-day/RSI/Fibonacci/support, FUWTALAS lots, house shares — **course-grounded**.
- 🆕 **"Avoid air pockets"** — *not in the masterclass (0 hits in transcripts/slides);* from the
  chart-day videos / general TA. **Candidate deterministic definition:** a *parabolic rip way
  above the 200-day MA* — operationalized as **extended ≥30% above the 200-day AND ripped ≥15%
  above the 50-day** (a steady riser hugs the 50-day; a parabolic rip detaches from it — this
  avoids the false-positive that RSI-alone gives). Implemented (provisional) in finance-suite
  `stock_analyzer/tools/indicators.py::air_pocket()`. ⚠ **Thresholds need calibration against the
  chart-day videos** (the authoritative source) — and the classic TA "air pocket" is the sharp
  *drop* itself; ours is the *setup* that precedes it (the actionable framing for "don't buy in").
