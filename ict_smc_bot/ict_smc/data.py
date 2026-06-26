"""Data loading: a dependency-free CSV reader and a synthetic OHLC generator.

The synthetic generator is deliberately a (near) random walk with shifting drift
and occasional liquidity-sweep spikes. It exists so the harness runs end-to-end
with zero external data, *and* so it doubles as a sanity check: a strategy with
no real edge should be ~break-even-minus-costs on random data. If the backtest
shows a big edge here, suspect look-ahead bias or a bug — not alpha.

Real data is intentionally optional (see ``from_ccxt``/``from_yfinance`` notes in
the README) to keep the core import-clean.
"""

from __future__ import annotations

import csv
import random
from typing import List, Optional

from .types import Candle


def from_csv(path: str, ts_col: str = "timestamp") -> List[Candle]:
    """Read OHLCV from a CSV with a header. Column names are matched
    case-insensitively; ``open/high/low/close`` are required, ``volume`` and a
    timestamp column are optional (a running index is used if absent)."""
    candles: List[Candle] = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        cols = {c.lower(): c for c in (reader.fieldnames or [])}

        def col(name: str) -> Optional[str]:
            return cols.get(name.lower())

        for need in ("open", "high", "low", "close"):
            if col(need) is None:
                raise ValueError(f"CSV missing required column: {need}")

        ts_key = col(ts_col) or col("time") or col("date")
        vol_key = col("volume")
        for i, row in enumerate(reader):
            ts = i
            if ts_key:
                raw = row[ts_key]
                try:
                    ts = int(float(raw))
                except ValueError:
                    ts = i
            candles.append(Candle(
                ts=ts,
                open=float(row[col("open")]),
                high=float(row[col("high")]),
                low=float(row[col("low")]),
                close=float(row[col("close")]),
                volume=float(row[vol_key]) if vol_key and row.get(vol_key) else 0.0,
            ))
    return candles


def to_csv(path: str, candles: List[Candle]) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for c in candles:
            w.writerow([c.ts, c.open, c.high, c.low, c.close, c.volume])


def synthetic(
    n: int = 3000,
    seed: int = 7,
    start: float = 100.0,
    vol: float = 0.5,
    drift_period: int = 200,
    sweep_prob: float = 0.05,
) -> List[Candle]:
    """A reproducible pseudo-market: random walk + regime drift + sweep spikes."""
    rnd = random.Random(seed)
    candles: List[Candle] = []
    price = start
    drift = 0.0
    for i in range(n):
        if i % drift_period == 0:
            drift = rnd.uniform(-0.04, 0.04)
        op = price
        cl = max(0.5, op + rnd.gauss(drift, vol))
        hi = max(op, cl) + abs(rnd.gauss(0.0, vol * 0.7))
        lo = min(op, cl) - abs(rnd.gauss(0.0, vol * 0.7))
        if rnd.random() < sweep_prob:  # an exaggerated wick = a liquidity raid
            if rnd.random() < 0.5:
                lo -= abs(rnd.gauss(0.0, vol * 2.0))
            else:
                hi += abs(rnd.gauss(0.0, vol * 2.0))
        lo = max(0.1, lo)
        candles.append(Candle(i, op, hi, lo, cl, abs(rnd.gauss(1000, 200))))
        price = cl
    return candles
