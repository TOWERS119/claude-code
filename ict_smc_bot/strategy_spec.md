# ICT/SMC Strategy Spec — numeric, testable rules

This is the machine-readable rule set behind `ict_smc/`. It turns the
discretionary ICT/SMC concepts from `notes/ict-smc-addon.md` into explicit
numbers so the whole gate is backtestable. Every threshold here is a **parameter
to validate**, not a fact (see `notes/ict-smc-addon.md` caveat and §"How this
plugs into the agent"). Defaults live in `ict_smc/types.py::Params`.

## 0. Primitives (numeric definitions)

| Concept | Numeric definition | Param |
|---|---|---|
| **ATR** | SMA of true range | `atr_period=14` |
| **Swing high/low** | fractal: extreme of a `2k+1` window, strictly beyond the bars `k` away; *knowable* only at `index+k` | `swing_lookback=2` |
| **Displacement** | candle `range ≥ mult·ATR` **and** `body ≥ ratio·range`, closing in-direction | `displacement_atr_mult=1.0`, `displacement_body_ratio=0.5` |
| **Fair value gap (FVG)** | 3-candle gap (`low[i] > high[i-2]` bull / `high[i] < low[i-2]` bear); middle candle must be displacement | `require_displacement_fvg=True` |
| **Order block** | last opposite-color candle before a displacement leg | (fallback only) |
| **Dealing range / equilibrium** | `[min low, max high]` over the sweep→MSS segment; equilibrium = midpoint | — |
| **Discount / premium** | below / above equilibrium | `equilibrium_filter=True` |

## 1. The entry gate (long; short is the mirror)

A setup is emitted only when **all** of these fire in order:

1. **Liquidity sweep.** A bar takes a confirmed swing low's liquidity and closes
   back above it: `low[s] < level` **and** `close[s] ≥ level`. Must occur within
   `sweep_max_age=30` bars of the swept pivot. The sweep wick (`low[s]`) anchors
   the stop.
2. **Market-structure shift (MSS/CHoCH).** Within `mss_max_age=20` bars after the
   sweep, a bar **closes above the protected swing high** that formed *before*
   the sweep. The breaking leg must contain a **bullish displacement** candle
   (which is what leaves the FVG).
3. **PD-array entry.** Place a pending **buy limit** into the bullish FVG left by
   the displacement (order block as fallback only if `require_fvg=False`). The
   zone must:
   - be **complete by the MSS bar** (no look-ahead), and
   - sit in **discount** (`zone.mid ≤ equilibrium`) when `equilibrium_filter`, and
   - be **below** the MSS close (a real pullback, not a chase).
   Entry price within the zone: `entry_level ∈ {edge, mid, deep}` (default `mid`
   = consequent encroachment).
4. **Risk geometry.**
   - **Stop** = `sweep_wick − stop_buffer_atr·ATR` (default `0.25·ATR` beyond the
     sweep).
   - **Target** = nearest opposing liquidity (a prior confirmed swing high above
     price) that yields ≥ `min_rr` (default `2.0`); else a synthetic `min_rr`
     target if `target_synthetic_fallback`.
   - Discard the setup if no target reaches `min_rr`.

The setup is **armed at the MSS bar**; the pending order is live for
`entry_valid_bars=15` bars, then cancelled. Once filled, the trade lives at most
`trade_max_bars=60` bars before a forced exit.

## 2. Execution & accounting rules

- **One position at a time** (no pyramiding / no overlap).
- **Conservative intrabar:** if a bar trades through both stop and target, the
  **stop** is counted.
- **Costs always applied:** adverse `slippage_bps=1.0` per fill +
  `commission_bps=2.0` per side.
- **Sizing:** risk `risk_pct=1%` of current equity per trade; results are also
  reported in sizing-neutral **R-multiples**.

## 3. Validation protocol (non-negotiable)

This is the part that answers the over-fitting warning in the notes.

1. **Full-sample numbers are not evidence.** Report them, never trust them.
2. **Train/test 70/30:** out-of-sample only.
3. **Walk-forward:** optimize parameters on each in-sample fold, score the *next*
   fold. Aggregate OOS expectancy is the headline number.
4. **Random-data sanity check:** run the whole thing on `data.synthetic(...)`.
   A method with no real edge should land near **−costs** (it does: ~−0.2 to
   −0.3R, PF < 1). **A positive edge on random data means a bug or look-ahead
   leak, not alpha.** This is wired as a test (`test_no_edge_on_random_data`).

## 4. Parameter grid (for walk-forward, not for cherry-picking)

Default search in `run_backtest.py`:

```
min_rr                  ∈ {1.5, 2.0, 2.5, 3.0}
displacement_atr_mult   ∈ {0.8, 1.0, 1.2}
```

Keep the grid small. Every extra knob is another way to fool yourself — the more
combinations you scan, the more the in-sample winner is luck. The walk-forward's
job is to *expose* that, not reward it.

## 5. Mapping back to the addon

| Spec rule | `notes/ict-smc-addon.md` |
|---|---|
| sweep → MSS → PD array in discount/premium | §1 "Combined entry skeleton", §"agent wiring" |
| displacement-gated FVG | §4.1 (FVG secret #1) |
| FVG + liquidity confluence | §4.2 |
| discount/premium + OTE | §3 |
| stop beyond sweep, target weak high/low | §11, §12 |
| numeric displacement (`range > mult·ATR`) | §"agent wiring" (define labels numerically) |

## 6. What this is *not*

It is a **strategy scaffold**, not a money printer. It deliberately omits the
softer confluences from the addon (SMT divergence §6, two-lines regime §9,
session timing, candle continuity §8, EMA bias §7.5). Those are the next
parameters to add **one at a time, each validated out-of-sample** — adding them
all at once is exactly the over-fitting trap. Paper-trade before any capital;
enforce hard limits broker-side, not just in the prompt (knowledge-base §6).
