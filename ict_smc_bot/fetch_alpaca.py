#!/usr/bin/env python3
"""Fetch equity OHLCV bars from Alpaca's market-data API into a standard CSV.

Needs Alpaca keys in the environment (the same paper keys used for trading):
``ALPACA_API_KEY_ID`` / ``ALPACA_API_SECRET_KEY``. Writes
``timestamp,open,high,low,close,volume`` (epoch seconds), oldest-first, ready for
``run_live_dryrun.py --alpaca`` and ``run_backtest.py``.

Usage:
    export ALPACA_API_KEY_ID=...  ALPACA_API_SECRET_KEY=...
    python3 fetch_alpaca.py --symbol AAPL --timeframe 15Min --days 60 \
        --out data/AAPL_15m.csv

Free accounts use the IEX feed (``--feed iex``, the default); SIP needs a
subscription. Timeframe is passed through to Alpaca (e.g. 1Min, 5Min, 15Min,
1Hour, 1Day).
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from ict_smc.config import get_secret
from ict_smc.live import urllib_http, HttpFn

DATA_BASE = "https://data.alpaca.markets"


def _ts_to_epoch(t: str) -> int:
    return int(datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp())


def bars_to_rows(payload: dict) -> List[Tuple[int, float, float, float, float, float]]:
    """Convert an Alpaca bars payload into OHLCV rows (pure, unit-testable)."""
    rows = []
    for b in payload.get("bars") or []:
        rows.append((_ts_to_epoch(b["t"]), float(b["o"]), float(b["h"]),
                     float(b["l"]), float(b["c"]), float(b.get("v", 0.0))))
    return rows


def fetch(symbol: str, timeframe: str, start_iso: str, feed: str,
          http: HttpFn = urllib_http, headers: Optional[dict] = None
          ) -> List[Tuple[int, float, float, float, float, float]]:
    headers = headers or {
        "APCA-API-KEY-ID": get_secret("ALPACA_API_KEY_ID"),
        "APCA-API-SECRET-KEY": get_secret("ALPACA_API_SECRET_KEY"),
    }
    out: List[tuple] = []
    page_token = None
    while True:
        q = (f"/v2/stocks/{symbol}/bars?timeframe={timeframe}&start={start_iso}"
             f"&limit=10000&feed={feed}&adjustment=raw")
        if page_token:
            q += f"&page_token={page_token}"
        status, raw = http("GET", DATA_BASE + q, headers, None)
        if not 200 <= status < 300:
            raise RuntimeError(f"Alpaca data {status}: {raw[:300]!r}")
        import json
        payload = json.loads(raw)
        out.extend(bars_to_rows(payload))
        page_token = payload.get("next_page_token")
        if not page_token:
            break
    out.sort(key=lambda r: r[0])
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="AAPL")
    ap.add_argument("--timeframe", default="15Min")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--feed", default="iex")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    start = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"fetching {args.symbol} {args.timeframe} since {start} (feed={args.feed}) ...")
    rows = fetch(args.symbol, args.timeframe, start, args.feed)
    if not rows:
        print("no bars returned (check symbol/feed/market hours)", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
