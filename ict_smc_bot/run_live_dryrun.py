#!/usr/bin/env python3
"""End-to-end test harness for the LIVE path.

This runs the real production code path — data -> generate_setups -> RiskManager
-> LiveBroker -> run_live_once -> notify — not a mock of it. Two modes:

  (default)   --sim     simulate a *schedule*: replay growing windows over recent
                        bars, calling run_live_once once per "tick" against a
                        SimVenueClient. Runs now, no keys. Proves the whole live
                        pipeline submits orders, gates risk, and resumes state.

  --alpaca              one real scheduled tick against the Alpaca PAPER sandbox.
                        Requires ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY in the
                        environment and BOT_ALLOW_LIVE=1 (both safety switches).

Examples
--------
    python3 run_live_dryrun.py --sim --csv findings/data/BTC-USD_1h.csv --ticks 300
    BOT_ALLOW_LIVE=1 python3 run_live_dryrun.py --alpaca --symbol AAPL \
        --csv data/AAPL_15m.csv
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile

from ict_smc import data
from ict_smc.types import Params
from ict_smc.config import BotConfig
from ict_smc.risk import RiskManager
from ict_smc.memory import Memory
from ict_smc.notify import ConsoleNotifier
from ict_smc.live import SimVenueClient, AlpacaClient, LiveBroker, run_live_once
from ict_smc import providers
from ict_smc.advisor import TradeAdvisor


def _config(args) -> BotConfig:
    cfg = BotConfig(symbol=args.symbol, state_dir=args.state_dir)
    cfg.params = Params(require_fvg=False, min_rr=args.min_rr)
    cfg.limits.risk_pct = args.risk_pct
    cfg.limits.max_new_trades_per_day = args.max_trades_per_day
    return cfg


def _build_advisor(args, cfg):
    """Optional LLM trade advisor (capability 4). Needs the provider's key in env."""
    if not args.glm_advisor:
        return None
    client = providers.make_client(args.provider, model=args.glm_model,
                                   timeout=cfg.glm_timeout)
    return TradeAdvisor(client, enabled=True, fail_mode=args.glm_fail_mode,
                        min_size_factor=cfg.glm_min_size_factor)


def run_sim(args, cfg, candles) -> int:
    """Replay a schedule: each tick is one run_live_once on a growing window."""
    warmup, ticks = args.warmup, args.ticks
    sub = candles[-(warmup + ticks):] if len(candles) > warmup + ticks else candles
    sim = SimVenueClient(equity=cfg.starting_equity)
    broker = LiveBroker(sim, symbol=cfg.symbol, allow_live=True)
    risk = RiskManager(cfg.limits)
    advisor = _build_advisor(args, cfg)
    if advisor is not None:
        print(f"WARNING: --glm-advisor consults GLM once per setup per tick "
              f"(up to ~{args.ticks} ticks) — this is billable GLM API usage.")
    state_dir = tempfile.mkdtemp(prefix="dryrun_")
    memory = Memory(state_dir)
    os.environ["BOT_ALLOW_LIVE"] = "1"  # arm the sim venue (no real money involved)

    total_submitted = 0
    total_rejected = 0
    ticks_run = 0
    try:
        for k in range(warmup, len(sub) + 1):
            window = sub[:k]
            rep = run_live_once(cfg, broker, risk, memory, window, advisor=advisor)
            if rep.skipped:
                continue
            ticks_run += 1
            total_submitted += len(rep.submitted)
            total_rejected += len(rep.rejections)
    finally:
        os.environ.pop("BOT_ALLOW_LIVE", None)

    print("== LIVE dry-run (simulated schedule, SimVenueClient) ==")
    print(f"symbol       : {cfg.symbol}")
    print(f"ticks run    : {ticks_run} (one run_live_once per new bar)")
    print(f"orders placed at venue : {len(sim.placed)}")
    print(f"submitted    : {total_submitted}  rejected (risk-gated): {total_rejected}")
    if sim.placed:
        o = sim.placed[0]
        print(f"first order  : {o['side']} {o['qty']:.4f} {o['symbol']} "
              f"entry={o['entry']:.2f} stop={o['stop']:.2f} target={o['target']:.2f}")
    # prove resumption: state cursor advanced and persists
    st = memory.load_state()
    print(f"state cursor : last_live_bar={st.get('last_live_bar')} (persisted to {state_dir})")
    print(f"sanity       : venue order count == submitted -> "
          f"{'OK' if len(sim.placed) == total_submitted else 'MISMATCH'}")
    print("\nThis exercised the real live code path end-to-end. To run it against "
          "the Alpaca paper sandbox, re-run with --alpaca and your paper keys.")
    return 0 if len(sim.placed) == total_submitted else 1


def run_alpaca(args, cfg, candles) -> int:
    if os.environ.get("BOT_ALLOW_LIVE") != "1":
        print("refusing: set BOT_ALLOW_LIVE=1 to place orders on the paper sandbox",
              file=sys.stderr)
        return 2
    for var in ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"):
        if not os.environ.get(var):
            print(f"refusing: missing {var} in the environment", file=sys.stderr)
            return 2
    client = AlpacaClient()  # paper sandbox by default
    broker = LiveBroker(client, symbol=cfg.symbol, allow_live=True,
                        max_order_notional=args.max_notional)
    risk = RiskManager(cfg.limits)
    memory = Memory(cfg.state_dir)
    notifier = ConsoleNotifier()
    advisor = _build_advisor(args, cfg)
    print(f"== LIVE tick against Alpaca PAPER sandbox ({cfg.symbol}) ==")
    print(f"account equity: {broker.get_equity():.2f}")
    rep = run_live_once(cfg, broker, risk, memory, candles, advisor=advisor, notifier=notifier)
    print(rep.summary())
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="End-to-end live-path test harness")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--sim", action="store_true", help="simulated schedule (default)")
    mode.add_argument("--alpaca", action="store_true", help="one tick on Alpaca paper sandbox")
    ap.add_argument("--csv", default="findings/data/BTC-USD_1h.csv")
    ap.add_argument("--symbol", default="DRYRUN")
    ap.add_argument("--state-dir", default="./.bot_state")
    ap.add_argument("--ticks", type=int, default=300)
    ap.add_argument("--warmup", type=int, default=300)
    ap.add_argument("--min-rr", type=float, default=2.0)
    ap.add_argument("--risk-pct", type=float, default=0.01)
    ap.add_argument("--max-trades-per-day", type=int, default=3)
    ap.add_argument("--max-notional", type=float, default=2000.0)
    ap.add_argument("--glm-advisor", action="store_true",
                    help="consult an LLM as a subtractive trade advisor (needs the provider key)")
    ap.add_argument("--provider", default=os.environ.get("BOT_LLM_PROVIDER", "glm"),
                    choices=sorted(providers.PROVIDERS),
                    help="LLM provider for the advisor; free: gemini, groq, openrouter, ollama")
    ap.add_argument("--glm-model", default=os.environ.get("BOT_GLM_MODEL"),
                    help="override the provider's default model")
    ap.add_argument("--glm-fail-mode", choices=["closed", "open"], default="closed")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    candles = data.from_csv(args.csv)
    cfg = _config(args)
    return run_alpaca(args, cfg, candles) if args.alpaca else run_sim(args, cfg, candles)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
