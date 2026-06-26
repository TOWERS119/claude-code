#!/usr/bin/env python3
"""Stateless "run once" entry point for the paper-trading agent.

Each call wakes up, restores state from ``--state-dir``, advances over the bars
that arrived since the last run, and persists. Call it on a schedule (cron /
Claude Code routine) and it behaves like a live agent. Repeated calls here over
the same synthetic series demonstrate the incremental, resumable behavior.

Examples
--------
    # one stateless run over synthetic data, persisting to ./.bot_state
    python run_bot.py --synthetic --bars 4000 --state-dir ./.bot_state

    # advance only 500 bars per call (run several times to see it resume)
    python run_bot.py --synthetic --bars 4000 --max-bars 500
    python run_bot.py --synthetic --bars 4000 --max-bars 500

    # start fresh, then trade your own data
    python run_bot.py --csv data/BTCUSDT_15m.csv --symbol BTCUSDT --reset

This runner only ever uses the PaperBroker. Live trading is intentionally not
wired here (see ict_smc/broker.py::LiveBroker).
"""

from __future__ import annotations

import argparse
import logging
import sys

from ict_smc import data
from ict_smc.config import BotConfig
from ict_smc.risk import RiskManager
from ict_smc.memory import Memory
from ict_smc.engine import run_once, build_broker


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="ICT/SMC paper-trading agent (run once)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--synthetic", action="store_true")
    src.add_argument("--csv", type=str)

    ap.add_argument("--bars", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--symbol", type=str, default="SYNTH")
    ap.add_argument("--state-dir", type=str, default="./.bot_state")
    ap.add_argument("--max-bars", type=int, default=None,
                    help="process at most N new bars this run (default: all)")
    ap.add_argument("--reset", action="store_true", help="wipe memory first")
    ap.add_argument("--risk-pct", type=float, default=0.01)
    ap.add_argument("--max-drawdown", type=float, default=0.15)
    ap.add_argument("--max-daily-loss", type=float, default=0.03)
    ap.add_argument("--max-trades-per-day", type=int, default=3)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logger = logging.getLogger("bot")

    config = BotConfig(symbol=args.symbol, state_dir=args.state_dir)
    config.limits.risk_pct = args.risk_pct
    config.limits.max_drawdown_pct = args.max_drawdown
    config.limits.max_daily_loss_pct = args.max_daily_loss
    config.limits.max_new_trades_per_day = args.max_trades_per_day

    if args.synthetic:
        candles = data.synthetic(n=args.bars, seed=args.seed)
        config.symbol = args.symbol
    else:
        candles = data.from_csv(args.csv)

    memory = Memory(config.state_dir)
    if args.reset:
        memory.reset()
        logger.info("memory reset")

    broker = build_broker(config, memory)
    risk = RiskManager(config.limits)

    report = run_once(config, broker, risk, memory, candles,
                      max_bars=args.max_bars, logger=logger)

    print("== run report ==")
    print(report.summary())
    trades = memory.read_trades()
    if trades:
        wins = sum(1 for t in trades if t["pnl"] > 0)
        total_r = sum(t["r_multiple"] for t in trades)
        print(f"cumulative trades logged: {len(trades)}  "
              f"win%={wins / len(trades) * 100:.1f}  "
              f"sum={total_r:+.2f}R  realized equity={broker.get_equity():.2f}")
    print(f"state dir: {config.state_dir}  (run again to resume from the cursor)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
