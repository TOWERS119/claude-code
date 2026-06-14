#!/usr/bin/env python3
"""Fetch real OHLCV history from Coinbase's public API (no key required).

Coinbase returns at most 300 candles per request, newest-first, each row shaped
``[time, low, high, open, close, volume]`` (note the non-standard column order).
We paginate backwards and write a standard ``timestamp,open,high,low,close,volume``
CSV sorted oldest-first, ready for ``run_backtest.py --csv``.

Usage:
    python3 fetch_coinbase.py --product BTC-USD --granularity 900 --bars 5000 \
        --out data/BTC-USD_15m.csv
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
import urllib.request
import json
from typing import List, Tuple

API = "https://api.exchange.coinbase.com"


def fetch(product: str, granularity: int, bars: int) -> List[Tuple[int, float, float, float, float, float]]:
    rows: dict[int, tuple] = {}
    end = int(time.time())
    page = 300
    while len(rows) < bars:
        start = end - page * granularity
        url = (f"{API}/products/{product}/candles"
               f"?granularity={granularity}&start={start}&end={end}")
        req = urllib.request.Request(url, headers={"User-Agent": "mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r)
        except Exception as e:  # noqa: BLE001
            print(f"  request failed ({e}); retrying once after 2s", file=sys.stderr)
            time.sleep(2)
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r)
        if not data:
            break
        for t, low, high, op, close, vol in data:
            rows[int(t)] = (int(t), float(op), float(high), float(low), float(close), float(vol))
        oldest = min(int(c[0]) for c in data)
        if oldest >= end:  # no progress
            break
        end = oldest
        print(f"  fetched {len(rows)} bars (back to {time.strftime('%Y-%m-%d', time.gmtime(oldest))})")
        time.sleep(0.34)  # be polite to the public endpoint
    out = sorted(rows.values(), key=lambda x: x[0])
    return out[-bars:]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product", default="BTC-USD")
    ap.add_argument("--granularity", type=int, default=900, help="seconds (900=15m, 3600=1h)")
    ap.add_argument("--bars", type=int, default=5000)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    print(f"fetching {args.bars} x {args.granularity}s candles for {args.product} ...")
    rows = fetch(args.product, args.granularity, args.bars)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        w.writerows(rows)
    span_days = (rows[-1][0] - rows[0][0]) / 86400 if len(rows) > 1 else 0
    print(f"wrote {len(rows)} rows to {args.out} (~{span_days:.0f} days)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
