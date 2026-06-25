# Due-Diligence Playbook — the DD super-domain

DD is not one expert; it's a **cluster of sub-experts** behind a **DD Lead** that runs them
and composes a per-ticker scorecard. The course frames DD as **two phases**: *Phase 1 idea
generation* → *Phase 2 the 10-step deep dive*. Each sub-expert below is tagged by how well
the course grounds it — which determines whether we can encode it from the transcripts or
must **augment** with outside methodology.

**Grounding legend:** 🟢 deterministic (course gives rules/thresholds) · 🟡 signal-only
(course gives signals, no scoring — build a checklist) · 🔴 needs-augmentation (course is
thin/absent — bring an external framework).

## DD Lead (orchestrator)
Runs Phase 1 (is this even a candidate / which bucket gap does it fill?) → Phase 2 sub-experts
in parallel (evidence gathering) → hands the shared evidence to the **Bull/Bear/Judge synthesis
layer** → emits a scorecard + balanced recommendation. Enforces the course's governance rules:
**devil's advocate / stay neutral** (don't pre-decide), **"paralysis analysis" stop**
(conviction ends DD), **no single metric decides** ("tool in the toolbox"), **always read the
footnotes**.

## Synthesis layer — Bull, Bear & Judge
The sub-experts (1–9) produce *evidence*, not a verdict. Three personas turn evidence into a
well-rounded recommendation:
- **Bull persona** — builds the strongest good-faith BUY case from the same evidence: growth
  thesis, moat, TAM/runway, valuation upside, positive catalysts, where it fits a blueprint
  bucket. Must cite sub-expert findings (no hand-waving).
- **Bear persona** — builds the strongest good-faith AVOID/SELL case: red flags (weak balance
  sheet, dilution, declining revenue, debt), valuation risk, competitive/secular threats,
  governance/management concerns, the bear macro/sentiment read. Must cite findings.
- **Judge / Synthesizer** — neither advocate; weighs both arguments against the evidence and the
  course's rules, then issues a **balanced verdict + conviction level** (and which bucket / what
  size / what entry per the TA + DCA experts). Surfaces the key disagreements rather than burying
  them. This is the adversarial check that enforces "stay neutral / is the business broken or the
  stock broken?"

Design notes: Bull and Bear see *identical* evidence (fairness); each is instructed to argue its
side as strongly as honestly possible, then concede its weakest point. The Judge's conviction
feeds position sizing (high conviction → buy at 50/100-day per the TA engine; low → smaller lot
or pass). This pattern also makes Phase-5 validation natural: score Bull vs Bear vs realized
outcome to tune the experts.

---

## 1. Financial-Statement Analyst 🟢
Strongest-grounded sub-expert; real numeric thresholds.
- **Balance sheet:** Assets = Liab + Equity; current ratio = CA/CL (≥1, <1.5 concern, but
  <1 not always bad — industry-dependent), quick = (CA−inv)/CL (<1 concern), working capital,
  net tangible assets = equity − goodwill. **Weak flags:** neg retained earnings / neg equity /
  neg NTA / low current ratio. **Strong signals:** cash+ST-investments / low-zero LT debt /
  undervalued assets. Cash-jump diagnostic; AR↑ or inventory↑ vs sales = red flag.
- **Income statement:** Rev−Exp=Profit; gross & net margins (**moat detector** vs peers);
  R&D scale (moat) / low-R&D (less obsolescence risk); SG&A vs revenue; revenue quality
  (recurring>discretionary); ROE = NI/equity; EBITDA criticized; value-trap (low trailing PE
  that worsens). **Red flags:** ≥3 yrs declining revenue, falling margins, dilution.
- **Cash flow:** OCF>CFI>CFF renewability; FCF = OCF − replacement CapEx; neg-OCF+pos-CFI = bad;
  payout >90% red flag (REIT-exempt). Anomaly-dig method (Wingstop special dividend).
- **Read order:** income (trend) → balance (debt/intangibles) → cash flow (sustainability) →
  adjust non-recurring → valuation ratios → liquidity ratios → peer comparison.
- ⚠ interest-coverage threshold as taught is inverted — see mental-model.md, verify before encoding.

## 2. Valuation 🟢
P/E (trailing vs forward), PEG (≤1 attractive; 0.5 = investigate; fast growers 2–5), P/S
(unprofitable), P/B (<1 = margin of safety), EV/NTM-rev (SaaS), EV/EBITDA, FCF yield, DCF,
DDM, sum-of-parts. **Never one metric; cross-check ≥3 sources** (Y Charts vs Fidelity vs your
own math — Y Charts showed PEG 63.07 vs Fidelity's correct 2.27). Qualified-dividend tax
tiers 0/15/18.8/23.8% (+3.8% NII).

## 3. Dividend Classifier (DGF / DGI / Income) 🟢
- **DGF** (total growth) — all 5: yield ≤3% (best ~1–1.5%), payout ≤50% (pref ≤35%), ≥5 yr
  div growth, ≥10% 5-yr div growth, ≥10% 10-yr annualized growth.
- **DGI** (grow the dividend ≥ inflation, paid from profits not debt; for income/retirement).
- **Income** — **yield >4% + high payout, OR any REIT**; avoid ≥6% yield.
- **Overlap resolution:** investor classifies subjectively; "99% fit one bucket." Edge cases:
  NVDA (~0.15% yield → DGF-vs-Growth), Disney (suspended → no longer DGF), AbbVie (borderline).
- Growth sub-tiers: hyper (80–100% YoY) / growth / mature ("maturity = less risk/reward").

## 4. Management & Governance Rater 🟡
**Course gives signals only — NO scoring rubric (it says so: "subjective").** Build as a
checklist, not a scorer: insider ownership (want high, no threshold given), founder
involvement (skin in the game), insider selling (context — a "tool," not auto-bearish),
exec/board turnover (CFO+CIO leaving same day = big risk), backgrounds (SEC filings/LinkedIn),
voting/share structure, capital-allocation quality, **diworsification** (M&A outside core).
*Augment:* if you want a CEO/board *rating*, design the rubric — the course won't supply it.

## 5. Moat / Competitive-Position 🟡
Qualitative ("best-of-breed, differentiators, barriers to entry") **plus** semi-quantitative
proxies that are the closest thing to a test: **gross/net margin consistently > peers**, **R&D
scale**, **low SG&A vs peers**, Lynch's ">50% growth attracts competition → moat critical" and
"fast grower in a slow industry." No composite moat score — margin-vs-peers is the one
measurable handle.

## 6. Market-Sizing — TAM / SAM / SOM 🔴
**Course covers TAM only, qualitatively** ("how much room left? is the niche big within a big
industry?"); **SAM and SOM are never mentioned.** TAM is used directionally to judge runway for
fast growers and to value new-product/patent expansion. *Augment:* bring a standard TAM→SAM→SOM
funnel (top-down + bottoms-up) — essentially un-resourced by the course beyond the TAM concept.

## 7. Risk Assessor 🟡
Category checklist (MC4 step 10), **no rubric/weighting/severity scale**: macro/geopolitical,
industry-wide, company-specific (patent cliffs — AbbVie), legal/regulatory (J&J talc/opioid),
management, ESG/sustainability (funds use "sentiment/sustainability scores" — not taught how),
demographic shift; plus market-cap/volatility, dilution, options-backdating, weak-balance-sheet-
in-rising-rates. *Augment:* build the scoring/severity layer.

## 8. Market-Sentiment & Analyst-Ratings 🔴/🟡
**Sentiment is NARRATIVE only — no quantified method in the course** (the one numeric proxy is
RSI from the TA engine). What exists:
- **Analyst rating ladder** (the one concrete artifact) — Strong Buy → Buy → Moderate
  Buy/Overweight (*Outperform, Accumulate, Add*) → Hold/Neutral → Moderate Sell/Underweight
  (*Underperform, Weak hold, Reduce*) → Sell → Strong Sell. Caveat taught: **"underperform ≠
  sell."** Price targets = "darts"; *"never a reason to buy."*
- **Buy-side vs sell-side:** sell-side = marketing to route institutional trades; institutions
  front-run their own public calls. **"Media has an agenda; info is already factored in."**
- *Augment:* if you want quantified sentiment (put/call, social, Fear&Greed value), bring it —
  the course only teaches "discount the noise."

## 9. Idea Generation / Screening 🟡
Phase-1 funnel: **portfolio-gap analysis** (which bucket/sector am I light in?) → secular trend →
"use what you know" → best-of-breed-few-own → news catalyst. One concrete screen (MC7): **high
current ratio + high cash + low debt**. Tools (idea-generation only, then DD): **Finviz** (free;
filters e.g. "PE < 40", "10% below 200-day SMA", then RSI/gap), **Fidelity** (better, ad-free),
**TradingView** (Chart Day). Lynch **innings** framework (buy 2nd–3rd inning).

---

## Standalone lists to preserve (distinct from the Top-15 Rules)

**MC16 — 20 Tips & Tools:** 1) don't stare at the portfolio; 2) timing doesn't work (78% of
best days in bear/early-bull; miss-best-days table); 3) Finviz; 4) a stock can always go lower
(bottom is zero); 5) don't overemphasize P/E (trailing = lagging); 6) realistic expectations
(Buffett ~22%, Lynch 29.2% vs S&P 15.8%); 7) don't sweat pennies; 8) you won't be right every
time; 9) psychology is #1; 10) TradingView; 11) plan & stick (switching = market timing);
12) let winners ride; 13) own 25–30 (20–35) names + ETF core; 14) DCA works (periodic + FUWTALAS);
15) don't chase yield (>5–6% off-limits); 16) beware tax fears; 17) diversify (buckets+sectors+
vehicles; SCHD offsets tech; ARKG = spec via ETF); 18) media has an agenda + analyst ladder;
19) understanding analysts (folded into 18); 20) don't delay.

**MC17 — 12 Common Mistakes:** 1) not investing at all; 2) buying without understanding;
3) lack of diversification; 4) overconfidence (Enron = "Microsoft of its era"; ≤5%/name);
5) investing money you can't afford to lose; 6) impatience/get-rich-quick; 7) bad info/opinions
(Ackman "hell is coming" while short); 8) herd mentality / copying portfolios (SEC: 70% of
traders lose; GameStop +145% in a day); 9) averaging down / sunk-cost ("call a dog a dog");
10) not doing your own homework; 11) unclear goals (**time + money + returns** triangle —
"getting on base is fine"); 12) watching too closely (info already factored in).

**Foundations (MC1):** common vs preferred stock; **bankruptcy priority: bondholders →
preferred → common**; penny stock = <$5 (or <$3), esp. OTC; suitability = **willingness AND
ability**.
