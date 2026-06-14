"""The ICT/SMC entry gate as a deterministic, look-ahead-safe scanner.

For each direction it searches for the canonical sequence:

    1. Liquidity sweep  - price takes a confirmed swing's liquidity and closes
       back (sell-side sweep for longs, buy-side for shorts).
    2. Market-structure shift (MSS/CHoCH) - a body close back through the
       protected swing that formed *before* the sweep, with displacement in the
       breaking leg (leaving a fair value gap).
    3. PD-array entry - a pending limit into the bullish/bearish FVG (or order
       block) left by that displacement, required to sit in discount (long) or
       premium (short) of the dealing range.
    4. Risk geometry - stop just beyond the sweep wick; target the next opposing
       liquidity (prior swing), discarding anything below ``min_rr``.

Every value on a returned ``Setup`` is derived from candles at or before
``armed_at`` (the MSS bar). The simulator only fills *after* ``armed_at``.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .types import Candle, Swing, FVG, Setup, Params
from .detectors import (
    compute_atr,
    find_swings,
    detect_fvgs,
    is_displacement,
    find_order_block,
)


def _entry_from_zone(top: float, bottom: float, level: str, long: bool) -> float:
    """Pick the entry price within a PD-array zone (``top`` >= ``bottom``).

    ``edge`` = earliest fill (shallowest retrace), ``deep`` = best price
    (deepest retrace), ``mid`` = the 50% / consequent-encroachment level.
    """
    if level == "mid":
        return (top + bottom) / 2.0
    if long:
        return top if level == "edge" else bottom
    return bottom if level == "edge" else top


def _find_target(
    swings: List[Swing],
    ref_price: float,
    entry: float,
    stop: float,
    params: Params,
    long: bool,
    m: int,
) -> Optional[float]:
    """Target the nearest opposing liquidity (a prior confirmed swing) beyond
    the current price that still yields at least ``min_rr``. Falls back to a
    synthetic ``min_rr`` target only if enabled."""
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    if long:
        highs = sorted(
            (s for s in swings if s.kind == "high" and s.index < m
             and s.confirmed_at <= m and s.price > ref_price),
            key=lambda s: s.price,
        )
        for s in highs:
            if (s.price - entry) / risk >= params.min_rr - 1e-9:
                return s.price
    else:
        lows = sorted(
            (s for s in swings if s.kind == "low" and s.index < m
             and s.confirmed_at <= m and s.price < ref_price),
            key=lambda s: -s.price,
        )
        for s in lows:
            if (entry - s.price) / risk >= params.min_rr - 1e-9:
                return s.price
    if params.target_synthetic_fallback:
        return entry + (1 if long else -1) * params.min_rr * risk
    return None


def _scan(
    candles: List[Candle],
    atr: List[Optional[float]],
    swings: List[Swing],
    fvgs: List[FVG],
    params: Params,
    long: bool,
) -> List[Setup]:
    n = len(candles)
    out: List[Setup] = []
    pivots = [s for s in swings if s.kind == ("low" if long else "high")]
    opp = [s for s in swings if s.kind == ("high" if long else "low")]
    inf = float("inf")

    for L in pivots:
        level = L.price
        # --- 1. sweep of L's liquidity, after L is confirmed ---
        s_from = max(L.confirmed_at, L.index + 1)
        sweep_index: Optional[int] = None
        for s in range(s_from, min(n, L.index + 1 + params.sweep_max_age)):
            c = candles[s]
            if atr[s] is None:
                continue
            took = (c.low < level and c.close >= level) if long else (
                c.high > level and c.close <= level
            )
            if took:
                sweep_index = s
                break
        if sweep_index is None:
            continue
        s = sweep_index
        sweep_extreme = candles[s].low if long else candles[s].high

        # --- protected swing (opposite kind) formed before the sweep ---
        prot: Optional[Swing] = None
        for sw in reversed(opp):
            if sw.index < s:
                prot = sw
                break
        if prot is None:
            continue

        # --- 2. MSS: close back through the protected swing ---
        mss_index: Optional[int] = None
        for mm in range(s + 1, min(n, s + 1 + params.mss_max_age)):
            c = candles[mm]
            broke = c.close > prot.price if long else c.close < prot.price
            if broke:
                mss_index = mm
                break
        if mss_index is None:
            continue
        m = mss_index
        if prot.confirmed_at > m:  # protected swing must be known by the MSS bar
            continue

        # --- displacement in the breaking leg (s, m] ---
        disp_idx: Optional[int] = None
        for t in range(s + 1, m + 1):
            if is_displacement(candles[t], atr[t], params, "bull" if long else "bear"):
                disp_idx = t
                break
        if disp_idx is None:
            continue

        # --- dealing range + equilibrium ---
        seg = candles[s : m + 1]
        rng_low = min(c.low for c in seg)
        rng_high = max(c.high for c in seg)
        equilibrium = (rng_low + rng_high) / 2.0
        close_m = candles[m].close

        # --- 3. entry array: FVG first, order block fallback ---
        want = "bull" if long else "bear"
        cand = [f for f in fvgs if f.direction == want and s < f.start_index <= m]
        entry: Optional[float] = None
        entry_source = "fvg"
        if long:
            valid = [
                f for f in cand
                if (f.mid <= equilibrium if params.equilibrium_filter else True)
                and f.top <= close_m
            ]
            if valid:
                chosen = max(valid, key=lambda f: f.mid)  # deepest still-in-discount
                entry = _entry_from_zone(chosen.top, chosen.bottom, params.entry_level, True)
        else:
            valid = [
                f for f in cand
                if (f.mid >= equilibrium if params.equilibrium_filter else True)
                and f.bottom >= close_m
            ]
            if valid:
                chosen = min(valid, key=lambda f: f.mid)
                entry = _entry_from_zone(chosen.top, chosen.bottom, params.entry_level, False)

        if entry is None and not params.require_fvg and params.use_ob_fallback:
            ob = find_order_block(candles, disp_idx, long)
            if ob is not None:
                top, bot = candles[ob].high, candles[ob].low
                mid = (top + bot) / 2.0
                ok = (
                    (mid <= equilibrium or not params.equilibrium_filter) and top <= close_m
                    if long
                    else (mid >= equilibrium or not params.equilibrium_filter) and bot >= close_m
                )
                if ok:
                    entry = _entry_from_zone(top, bot, params.entry_level, long)
                    entry_source = "order_block"
        if entry is None:
            continue

        # --- 4. stop beyond the sweep, target opposing liquidity ---
        buf = params.stop_buffer_atr * (atr[s] or 0.0)
        stop = sweep_extreme - buf if long else sweep_extreme + buf
        if long and not stop < entry:
            continue
        if not long and not stop > entry:
            continue

        target = _find_target(swings, close_m, entry, stop, params, long, m)
        if target is None:
            continue
        risk = abs(entry - stop)
        if abs(target - entry) / risk < params.min_rr - 1e-9:
            continue

        out.append(
            Setup(
                direction="long" if long else "short",
                sweep_index=s,
                sweep_price=sweep_extreme,
                mss_index=m,
                entry=entry,
                stop=stop,
                target=target,
                equilibrium=equilibrium,
                range_low=rng_low,
                range_high=rng_high,
                armed_at=m,
                entry_source=entry_source,
            )
        )
    return out


def generate_setups(
    candles: List[Candle], params: Params
) -> Tuple[List[Setup], Dict[str, object]]:
    """Run the gate over ``candles`` and return ``(setups, context)`` where
    ``setups`` is time-ordered by ``armed_at`` and ``context`` carries the raw
    detector outputs (atr/swings/fvgs) for inspection or plotting."""
    atr = compute_atr(candles, params.atr_period)
    swings = find_swings(candles, params.swing_lookback)
    fvgs = detect_fvgs(candles, atr, params)

    setups: List[Setup] = []
    if params.allow_long:
        setups += _scan(candles, atr, swings, fvgs, params, True)
    if params.allow_short:
        setups += _scan(candles, atr, swings, fvgs, params, False)
    setups.sort(key=lambda s: (s.armed_at, 0 if s.direction == "long" else 1))

    return setups, {"atr": atr, "swings": swings, "fvgs": fvgs}
