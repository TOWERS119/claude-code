# Findings: does this ICT/SMC strategy have a tradeable edge?

**Short answer: no.** Under honest out-of-sample testing, the strategy's results
on real BTC data are statistically indistinguishable from — and partly worse
than — what the *same* strategy produces on pure random noise. This document
shows the evidence and the method, and is careful about what is *proven* versus
what is *empirically shown*.

> Everything here is reproducible: `python3 findings/reproduce.py` (frozen data
> snapshot in `findings/data/`), and `python3 -m unittest discover -s tests` for
> the engineering claims.

## What is provable vs. what is empirical

- **Provable (engineering).** The backtest is look-ahead-safe, fills are
  conservative (same-bar stop-and-target counts as a stop), costs are applied,
  and the live path is fail-closed. These are deterministic properties of the
  code, verified by **52 passing tests**, including an explicit no-look-ahead
  test and a "no edge on random data" guard.
- **Empirical (the strategy).** "No edge" is *not* a mathematical proof that no
  edge can ever exist on any instrument/timeframe. It is the result of testing:
  the measured performance does not exceed the noise floor established by a
  negative control. An edge on other markets/parameters we didn't test remains
  possible — the honest claim is bounded by what was measured.

## Method

1. Encode the discretionary ICT/SMC rules as numeric, testable logic (sweep →
   market-structure shift with displacement → FVG/order-block entry in
   discount/premium → stop beyond the sweep, target opposing liquidity).
2. Validate with **walk-forward**: optimize parameters on each in-sample fold,
   score the *next* (unseen) fold, aggregate the out-of-sample trades.
3. Establish a **negative control**: run the identical pipeline on random-walk
   data. A trustworthy harness must show ~no edge here. This calibrates the
   noise floor — the range of results attributable to luck on small samples.
4. **Robustness check**: report the median trade and recompute expectancy with
   the single best trade removed. A real edge does not depend on one outlier.

## The evidence

Parameters: `require_fvg=False`, walk-forward grid `min_rr ∈ {1.5,2,2.5,3}`,
`displacement_atr_mult ∈ {0.8,1,1.2}`, 4 folds. Expectancy is in R-multiples
(profit per trade in units of risk).

### Negative control — random data (n=6000)

| Seed | Full-sample E | WF OOS trades | WF OOS E | PF | Median | E without best trade |
|---|---|---|---|---|---|---|
| 7  | +0.018R | 48 | −0.157R | 0.82 | −1.05R | −0.249R |
| 42 | +0.348R | 48 | **+0.227R** | 1.36 | −1.02R | +0.161R |
| 99 | +0.020R | 44 | **+0.224R** | 1.32 | −1.04R | −0.008R |

Pure noise produces walk-forward "edges" of **+0.22R** (seeds 42, 99) on ~50
trades. This *is the noise floor.* Note also how wildly the same harness swings
(−0.16R to +0.23R) just by changing the random seed — proof that a ~50-trade
sample tells you almost nothing.

### Real data — Coinbase BTC-USD (n=5000)

| Dataset | Full-sample E | WF OOS trades | WF OOS E | PF | Median | E without best trade |
|---|---|---|---|---|---|---|
| 15m (~52d) | −0.340R | 55 | **−0.350R** | 0.63 | −1.15R | −0.524R |
| 1h (~208d) | −0.067R | 48 | **+0.146R** | 1.22 | −1.07R | −0.004R |

## Why this means "no edge"

1. **Real results sit inside/below the noise floor.** The best real reading
   (1h, +0.146R OOS) is *lower* than two of three random controls (+0.227R,
   +0.224R). The 15m result (−0.350R) is worse than every random control. If a
   strategy can't beat its own performance on random data, it has no edge.
2. **The median trade loses everywhere** (−1.0 to −1.15R), real and random
   alike. All apparent profit comes from rare large winners.
3. **Every positive reading is one trade deep.** Remove the single best trade and
   the real 1h "edge" goes to −0.004R; the random "edges" collapse too. An edge
   that lives or dies on one outlier in 48 trades is not an edge.
4. **The largest, most trustworthy sample is negative.** Full-sample (no
   per-fold optimization) is −0.34R and −0.067R on real data.

## Honest limitations

- One asset (BTC), two timeframes, one ~52d/~208d window. Not a survey of
  markets or regimes.
- Small samples throughout (20–75 trades) — by design we treat these as
  inconclusive, which is *why* the negative control matters more than any single
  number.
- Costs are modeled (1bp slippage + 2bp/side commission) but real microstructure
  could be worse, which would only push results *more* negative.
- This tests one defensible encoding of ICT/SMC. A different interpretation could
  differ — but the burden of proof is on any positive claim to survive this same
  pipeline.

## Bottom line

The valuable artifact here is not a profitable strategy — it's a pipeline that
can **tell a real edge from noise** and a negative control that proves the
measurement is honest. Applied to this strategy, the verdict is no edge. That is
the result, stated without dressing it up.
