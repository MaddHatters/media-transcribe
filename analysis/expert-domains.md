# Proposed Expert Architecture (Phase 4 input)

Updated after the completeness pass. Experts are deliberately narrow so each is accurate at
one thing. **Grounding legend:** 🟢 deterministic (course gives rules/thresholds) · 🟡
signal-only (build a checklist) · 🔴 needs-augmentation (course thin/absent). Detail for the
DD cluster lives in [dd-playbook.md](dd-playbook.md); the TA engine in
[ta-determinism.md](ta-determinism.md); all rules in [mental-model.md](mental-model.md).

Experts are educational, ground in the instructor's rules, and must say they are **not
financial advice**.

## Router
Classifies a ticker/portfolio/question and dispatches. Most questions ("should I buy NVDA?")
fan out per the course's buy methodology: DD Lead → Valuation → TA Engine → Portfolio-fit →
Psychology check.

## Due-Diligence super-domain → see [dd-playbook.md](dd-playbook.md)
A **DD Lead** orchestrates 9 evidence sub-experts, then a **Bull / Bear / Judge synthesis
layer** turns the shared evidence into a well-rounded recommendation (Bull argues the buy case,
Bear argues avoid/sell from the *same* evidence, Judge weighs both → balanced verdict +
conviction that feeds position sizing). Evidence sub-experts:
1. Financial-Statement Analyst 🟢
2. Valuation 🟢
3. Dividend Classifier (DGIF/DGI/Income) 🟢
4. Management & Governance Rater 🟡 (signals only — no scoring rubric in the course)
5. Moat / Competitive-Position 🟡 (margin/R&D/SG&A-vs-peers proxies)
6. Market-Sizing TAM/SAM/SOM 🔴 (only TAM, qualitative; SAM/SOM not taught)
7. Risk Assessor 🟡 (category checklist, no severity scale)
8. Market-Sentiment & Analyst-Ratings 🔴/🟡 (rating ladder exists; sentiment is narrative-only)
9. Idea Generation / Screening 🟡 (portfolio-gap funnel + one balance-sheet screen + Finviz)

## Standalone experts

**Portfolio Architect** 🟢 — blueprint design, bucket allocation, risk-tier selection (8/10,
6/10, 4/10, $5M end-game), ≤5%/stock, lifecycle rotation. Grounds: MC3/13/15/18.

**Deterministic TA Engine** 🟢/🔴 → see [ta-determinism.md](ta-determinism.md). 11 codeable
rules + 5 priced test cases now; the ~8 discretionary judgment calls (triangle-apex direction,
candlestick thresholds, trend-line drawing) are formalization targets we define ourselves.

**Buy/Sell Point Engine** 🟢/🔴 → see [buy-sell-engine.md](buy-sell-engine.md). Hybrid
composition of the TA Engine + DCA Planner + Sell-Discipline: buy at/below the 200-day via
FUWTALAS lots at Fib/support (avoiding air pockets), sell at levels and take profits to
"house shares." Deterministic levels/lot/profit math; LLM judgment for air pockets & support quality.

**DCA Planner** 🟢 — periodic vs FUWTALAS lot-allocation; mode→bucket mapping; 20–25%/lot
(bull 2–3 / bear 10–30); DRIP-as-DCA; accumulation vs preservation; goal pipeline (≤12% return
assumption). Grounds: MC3/13/15/18.

**Sell-Discipline Expert** 🟢 — the 12 sell reasons; never sell on price alone; rebalance to
≤5%; tax-loss harvest ($3k/yr, 61-day wash-sale); loss-recovery math. Grounds: MC14.

**Options-Income Expert** 🟢 — covered calls, cash-secured puts, protective puts; 1 contract =
100 shares; effective put cost = strike − premium; cash-secured/covered only, never naked.
Grounds: MC11.

**Psychology & Discipline Coach** 🟡 — behavioral guardrail over every other expert: catch
FOMO/FOLE, bias, yield-chasing, market-timing, overconcentration; the Top-15 Rules, MC16
20-tips, MC17 12-mistakes. Grounds: MC8/12/16/17.

## What the course can't give us (augmentation backlog)
- **CEO/C-suite/board rating rubric** — only signals exist; design the scorer.
- **TAM/SAM/SOM** — bring a standard funnel; course has TAM concept only.
- **Quantified market sentiment** — course says "discount the noise"; add put/call, social, etc.
- **Deterministic chart reading** — the 8 formalization targets in ta-determinism.md.
- **Risk severity/weighting** — course has the categories, not the scoring.

## Open design questions (resolve at start of Phase 4)
1. Format: Claude Code subagents vs an `expertise.yaml` system vs standalone prompts.
2. Composition: router + visible specialist panel (leaning this — narrow & testable) vs one
   composite analyst.
3. Grounding: embed mental-model sections in prompts vs RAG over transcripts + OCR.
4. Validation (Phase 5): test each expert against held tickers + the instructor's own example
   calls (NVDA, DG, Fastly→Cloudflare) to tune thresholds.
