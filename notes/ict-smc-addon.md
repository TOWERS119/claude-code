# ICT / Smart Money Concepts — Strategy Addon

> Deep analysis of "the ultimate ICT and smart money concepts trading course"
> transcript, structured as a **strategy-layer addon** for the trading agent
> described in `trading-knowledge-base.md` (§1 strategy layer). This file is the
> *vocabulary and rule set*; it is not a profitability claim. The course is solid
> TA terminology wrapped in a paid-mentorship funnel ("Edge School") with
> unverifiable results — see the caveat at the end. Everything here should be
> encoded as explicit, testable rules and **validated out-of-sample before any
> capital** (see `trading-knowledge-base.md` §2 and §6).

ICT (Inner Circle Trader) / SMC reframes classic support-resistance and
supply-demand into a "smart money vs. retail liquidity" narrative. The core bet:
price is engineered to take liquidity (stops) and rebalance inefficiencies, so
you trade *with* the entity hunting those stops rather than getting hunted.

---

## 1. The Three Core Concepts

Everything in the method reduces to these three primitives.

1. **Liquidity** — clusters of resting orders (stop losses + pending orders),
   mostly above equal/old highs (**buy-side liquidity, BSL**) and below
   equal/old lows (**sell-side liquidity, SSL**). Price "needs" liquidity to
   move; a **liquidity sweep / raid** is a wick that takes out a high/low to
   trigger those stops, then reverses. Trendline liquidity and equal highs/lows
   are the highest-quality pools.
2. **Fair Value Gap (FVG)** — a 3-candle imbalance: a gap between candle 1's
   wick and candle 3's wick where candle 2 displaced so fast it left an
   un-traded price range. Markets tend to return to "rebalance" this
   inefficiency. Bullish FVG = support on the way up; bearish FVG = resistance
   on the way down.
3. **Market structure** — same as the manual course (`trading-course-summary.md`
   §5) but with a vocabulary split that matters:
   - **BOS (Break of Structure)** = continuation; body close beyond the last
     HH/LL *in the trend direction*.
   - **MSS / CHoCH (Market Structure Shift / Change of Character)** = potential
     reversal; the *first* break against the prevailing trend (breaks the most
     recent protected HL/LH). MSS after a liquidity sweep is the key reversal
     tell.

**Combined entry skeleton:** liquidity sweep → MSS/CHoCH → return to a PD array
(usually an FVG or order block) inside discount/premium → entry.

## 2. PD Arrays (Premium/Discount Arrays)

The menu of zones price reacts to. All are "where smart money left a footprint."

| PD array | What it is | Use |
|---|---|---|
| **Order block (OB)** | Last opposite-color candle before a displacement move | Entry zone; bullish OB = last down candle before an up impulse |
| **Breaker block** | An OB that *failed* (price broke through it), then is retested from the other side | Continuation entry after a sweep + structure break |
| **Mitigation block** | OB-like zone where price returns to "mitigate" an earlier unfilled position | Re-entry in trend direction |
| **Rejection block** | Cluster of long wicks (bodies ignored) — a wick-based zone | Reversal entry where wicks dominate |
| **Volume imbalance** | Gap between candle bodies (opens/closes) but wicks overlap — smaller than an FVG | Minor draw on price |
| **Inverse FVG (IFVG)** | An FVG that price closes *through*; it flips polarity (support→resistance) | Strong continuation signal once flipped |

Priority of reaction generally: FVG / order block > breaker/mitigation > volume
imbalance. The strongest setups **stack** arrays (e.g., FVG sitting inside an
order block inside a discount zone).

## 3. Premium / Discount & Equilibrium

- Draw a Fibonacci on the current dealing range (swing low → swing high).
- **Equilibrium = the 50% level.** Above it = **premium** (expensive — look to
  sell); below it = **discount** (cheap — look to buy).
- The discipline rule: **only buy in discount, only sell in premium.** A bullish
  setup whose entry array sits in premium is lower quality.
- "Optimal Trade Entry" (OTE) zone ≈ the 62%–79% retracement into
  discount/premium — the preferred entry pocket.

## 4. The Six FVG "Secrets" (the course's signature section)

The presenter's value-add over generic ICT — treat as refinements, not gospel:

1. **Quality filter** — a tradable FVG should come from *displacement* (a
   strong, often structure-breaking candle), not slow drift. No displacement,
   no FVG worth trading.
2. **FVG + liquidity confluence** — FVGs that form right after / on a liquidity
   sweep are highest probability; an FVG with no liquidity logic behind it is
   noise.
3. **Internal FVG analysis** — zoom *inside* the FVG on a lower timeframe; there
   is usually a smaller structure/OB within it for a tighter entry and stop.
4. **The "MFVG" (self-coined "Mulham's Fair Value Gap)** — the presenter's
   branded variant: an FVG defined/refined by his specific candle-body criteria
   (the branding is a funnel hook; the underlying idea is just a stricter FVG
   definition).
5. **Higher-TF vs lower-TF FVG relationship** — a lower-TF FVG is only worth
   taking when it aligns with a higher-TF FVG / draw on liquidity; the HTF FVG
   is the *target/context*, the LTF FVG is the *entry*.
6. **Consumed/inverse FVG** — once price trades fully through an FVG it is
   "consumed"; if it then closes beyond it, it inverts (see IFVG, §2) and
   becomes a continuation level.

## 5. Market Makers Model (MMXM)

The macro template the setups live inside — a buy model (mirror for sell):

1. **Original consolidation** — accumulation range; liquidity builds on both
   sides.
2. **Smart money reversal** — sweep of one side's liquidity + MSS; the turn.
3. **Accumulation / re-accumulation** — pullbacks into FVGs/OBs as price steps
   toward the opposing liquidity.
4. **Distribution / draw on liquidity** — price runs to the targeted external
   liquidity pool (the "draw").

MMXM is essentially the AMD cycle (Accumulation → Manipulation → Distribution)
with named structure points. The "draw on liquidity" (where price is *most
likely headed next*) is the single most important read for daily bias.

## 6. SMT Divergence (Smart Money Technique)

Correlated-asset divergence as a reversal confirmation:

- Watch correlated pairs (e.g., **EUR/USD vs GBP/USD**, both inverse to
  **DXY**). When one makes a higher high but the correlated one fails to (or
  DXY fails to make the matching lower low), that **non-confirmation** flags a
  likely reversal / failed liquidity run.
- Strongest when the divergence coincides with a liquidity sweep + FVG at a
  premium/discount extreme.

## 7. Five Daily-Bias Methods

How the course decides direction for the day (use as a confluence vote, not
five independent signals):

1. **Rejection** — strong rejection (long wick / engulf) off a HTF PD array
   sets the day's lean.
2. **External vs internal liquidity** — if external liquidity (old high/low) was
   just taken, bias shifts toward the *internal* range (FVGs); if internal was
   filled, bias targets the next *external* pool.
3. **CISD (Change In State of Delivery)** — a 3-candle pattern: a run in one
   direction, then a candle that closes back through the opens of the prior
   delivery, signalling delivery has flipped. (Course's lower-TF trigger.)
4. **Asian range sweep** — mark the Asian session high/low; a sweep of one side
   during London/NY often sets the day's reversal direction (fade the sweep).
5. **EMA 9 / EMA 18** — simple dynamic-trend filter; 9>18 = bullish lean, 9<18 =
   bearish lean. Lowest-priority "cherry on top," like the 50 EMA in the manual
   course.

## 8. Candle Continuity Theory

Read the *opens/closes relationship* of consecutive candles (esp. on HTF):
bullish continuity = each candle opening near the prior's low and closing near
its high (and vice versa). A break in continuity warns the move is maturing /
about to rebalance. Used as a coarse trend-health gauge.

## 9. The "Two Lines" Strategy (17:00 + midnight open)

A concrete intraday model:

- **Two reference lines:** the **17:00 (5 PM EST) open** (the new daily/CME open)
  and the **midnight (00:00 EST) open**.
- Price **above both lines = strength** (favor longs); **below both = weakness**
  (favor shorts); between them = neutral/choppy.
- Combine with session timing and a sweep + FVG entry.

**Sessions (EST) used by the model:**

| Session | Window (EST) | Role |
|---|---|---|
| Asia | 20:00 – 00:00 | Builds the range to be swept |
| London | 02:00 – 05:00 | First manipulation / sweep of Asia |
| New York | 07:00 – 10:00 | Main move / continuation or reversal |

## 10. Time-Frame Alignment

A fixed HTF-context → LTF-entry pairing:

- **4H → 15M:** 4H sets bias/draw and the HTF PD array; drop to 15M for the
  sweep + MSS + FVG entry.
- **15M → 1M:** for finer entries, 15M context with a 1M trigger.

Rule: the lower TF must *agree* with the higher TF's draw on liquidity; never
take an LTF entry against the HTF bias.

## 11. Strong vs Weak Highs/Lows

- **Strong high/low** = a swing point that (a) **swept liquidity** and (b) was
  followed by a **break of structure / breaker** in the opposite direction —
  i.e., it is unlikely to be revisited; it becomes a protected reference.
- **Weak high/low** = a swing point that has *not* been respected that way; it is
  a likely **target** (its liquidity will probably be taken).
- Trade *from* strong points *toward* weak points.

## 12. High-Probability Range Criteria

The course's checklist for a range/setup worth trading — needs all three:

1. **Anchored** — the range is tied to a clear HTF reference (a HTF PD array /
   liquidity level), not drawn arbitrarily.
2. **Displacement** — the move creating/leaving the range was a strong
   displacement candle (left an FVG), proving intent.
3. **Range fill** — there is unfilled inefficiency (FVG) inside the range for
   price to return to and for you to enter against.

---

## How this plugs into the agent (addon wiring)

Maps directly onto the layered architecture in `trading-knowledge-base.md` §4:

- **Strategy file (encode as explicit rules):**
  - Bias: compute the day's *draw on liquidity* (§5/§7) from the 4H — which
    external pool is price most likely targeting?
  - Setup gate: require **liquidity sweep → MSS/CHoCH → PD array in
    discount/premium** (§1) before any entry; reject setups missing
    displacement (§4.1) or sitting on the wrong side of equilibrium (§3).
  - Entry: FVG/OB inside the OTE pocket (§3/§4), optionally refined by internal
    FVG (§4.3); stop beyond the sweep wick; target the next weak high/low (§11)
    / opposing liquidity, giving a measurable R:R (reuse the manual course's
    1:2 minimum).
  - Filters/confluence votes: SMT divergence (§6), EMA 9/18 (§7.5), candle
    continuity (§8), two-lines regime (§9), session timing (§9).
- **Validation layer:** every rule above is a parameter — backtest the *whole
  gate*, not cherry-picked wins, with out-of-sample/walk-forward checks
  (`trading-knowledge-base.md` §2, §6). ICT's discretionary labels (what counts
  as "displacement," which sweep is "the" sweep) are exactly where curve-fitting
  and hindsight creep in, so define them numerically (e.g., displacement =
  candle range > N×ATR) and test.
- **Execution layer:** unchanged — paper-first, position caps, broker-side hard
  limits, watched runs.

---

## Caveat

The terminology in §§1–12 is internally consistent and is genuinely useful as a
precise vocabulary for liquidity, imbalance, and structure — it's a stricter
relabeling of the support/resistance and supply/demand ideas in
`trading-course-summary.md`. But:

- **No edge is demonstrated.** ICT/SMC is heavily discretionary; "it works in
  hindsight" because there is always *some* FVG, OB, or sweep to point at after
  the fact. Published, audited, out-of-sample results for the full method are
  effectively nonexistent. Treat every rule as a hypothesis to test, not a fact.
- **Self-branded concepts ("MFVG", proprietary names) are funnel markers**, not
  new market mechanics — they exist to differentiate a paid product.
- **"Edge School" / mentorship promotion is the business model.** As with the
  other three videos (`trading-knowledge-base.md` §5), the teaching doubles as
  marketing; performance/lifestyle claims are unverifiable.
- **Over-fitting risk is acute** precisely because the method is so flexible:
  many parameters, many optional confluences, lots of discretionary labels. The
  more confluences you can "find," the easier it is to fool yourself. Encode it
  numerically and validate before risking anything beyond paper.

Bottom line: a good *vocabulary and rule scaffold* to feed the strategy layer —
worth encoding and backtesting honestly, worthless as an unexamined promise of
profit.
