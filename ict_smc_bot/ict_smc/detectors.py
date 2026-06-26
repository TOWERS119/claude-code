"""Numeric detectors for the ICT/SMC primitives.

These turn the discretionary vocabulary into deterministic functions:
ATR, swing pivots, displacement, fair value gaps, and order blocks. Each is
written to be reproducible and (where it matters for the strategy) carries the
information needed to avoid look-ahead — most importantly ``Swing.confirmed_at``.
"""

from __future__ import annotations

from typing import List, Optional

from .types import Candle, Swing, FVG, Params


def compute_atr(candles: List[Candle], period: int) -> List[Optional[float]]:
    """Simple-moving-average ATR. ``atr[i]`` uses true ranges up to and
    including bar ``i``; the first ``period-1`` entries are ``None``."""
    n = len(candles)
    tr: List[float] = [0.0] * n
    atr: List[Optional[float]] = [None] * n
    for i in range(n):
        if i == 0:
            tr[i] = candles[i].high - candles[i].low
        else:
            pc = candles[i - 1].close
            tr[i] = max(
                candles[i].high - candles[i].low,
                abs(candles[i].high - pc),
                abs(candles[i].low - pc),
            )
    run = 0.0
    for i in range(n):
        run += tr[i]
        if i >= period:
            run -= tr[i - period]
        if i >= period - 1:
            atr[i] = run / period
    return atr


def find_swings(candles: List[Candle], k: int) -> List[Swing]:
    """Fractal swing pivots with half-width ``k``.

    A swing high needs ``high[i]`` to be the max of the ``2k+1`` window and
    strictly greater than the bars ``k`` away on each side (to reject flats).
    Each pivot is stamped with ``confirmed_at = i + k`` — the first bar at which
    the pivot is knowable in real time.
    """
    n = len(candles)
    out: List[Swing] = []
    for i in range(k, n - k):
        hi, lo = candles[i].high, candles[i].low
        is_h = is_l = True
        for d in range(1, k + 1):
            if not (hi >= candles[i - d].high and hi >= candles[i + d].high):
                is_h = False
            if not (lo <= candles[i - d].low and lo <= candles[i + d].low):
                is_l = False
        if is_h and not (hi > candles[i - k].high and hi > candles[i + k].high):
            is_h = False
        if is_l and not (lo < candles[i - k].low and lo < candles[i + k].low):
            is_l = False
        if is_h:
            out.append(Swing(i, hi, "high", i + k))
        if is_l:
            out.append(Swing(i, lo, "low", i + k))
    out.sort(key=lambda s: (s.index, 0 if s.kind == "high" else 1))
    return out


def is_displacement(
    candle: Candle, atr_val: Optional[float], params: Params, direction: str
) -> bool:
    """A displacement candle: range exceeds ``mult * ATR``, body dominates the
    range, and the close is in the requested direction."""
    if atr_val is None or atr_val <= 0:
        return False
    if candle.range <= 0:
        return False
    if candle.range < atr_val * params.displacement_atr_mult:
        return False
    if candle.body < params.displacement_body_ratio * candle.range:
        return False
    return candle.bullish if direction == "bull" else candle.bearish


def detect_fvgs(
    candles: List[Candle], atr: List[Optional[float]], params: Params
) -> List[FVG]:
    """3-candle fair value gaps. The middle candle (``i-1``) must be a
    displacement candle when ``require_displacement_fvg`` is set (FVG secret #1:
    no displacement, no tradable FVG)."""
    out: List[FVG] = []
    for i in range(2, len(candles)):
        mid = candles[i - 1]
        a = atr[i - 1]
        # Bullish FVG: gap between candle i-2 high and candle i low.
        if candles[i].low > candles[i - 2].high:
            if not params.require_displacement_fvg or is_displacement(mid, a, params, "bull"):
                out.append(FVG("bull", i, candles[i].low, candles[i - 2].high))
        # Bearish FVG: gap between candle i-2 low and candle i high.
        if candles[i].high < candles[i - 2].low:
            if not params.require_displacement_fvg or is_displacement(mid, a, params, "bear"):
                out.append(FVG("bear", i, candles[i - 2].low, candles[i].high))
    return out


def find_order_block(
    candles: List[Candle], disp_idx: int, long: bool, max_back: int = 10
) -> Optional[int]:
    """The order block feeding a displacement leg: the last opposite-color
    candle before ``disp_idx``. Bullish OB = last bearish candle before an up
    displacement (and mirror for shorts)."""
    lo = max(-1, disp_idx - 1 - max_back)
    for j in range(disp_idx - 1, lo, -1):
        c = candles[j]
        if long and c.bearish:
            return j
        if not long and c.bullish:
            return j
    return None
