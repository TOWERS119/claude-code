#!/usr/bin/env python3
"""One-command quickstart for the GLM features.

The only thing you need to add is a GLM API key:

    export GLM_API_KEY=...        # from Zhipu / z.ai

Then start with a single command (data is pulled from Coinbase's public endpoint,
no key needed; use --csv to run fully offline against a saved file):

    # GLM proposes strategies; the walk-forward rig judges them honestly
    GLM_API_KEY=... python3 quickstart.py research --csv findings/data/BTC-USD_1h.csv

    # Run the paper simulator with GLM as a subtractive trade advisor
    GLM_API_KEY=... python3 quickstart.py advisor  --csv findings/data/BTC-USD_1h.csv

No installs (pure standard library) and no broker keys: this path is
paper/simulator only. The GLM advisor can only veto or shrink trades behind the
RiskManager, and research is judged by the same out-of-sample + noise-floor rig
as everything else — GLM cannot create edge or place a real order here.
"""

from __future__ import annotations

import argparse
import collections
import logging
import os
import sys
import tempfile

from ict_smc import data
from ict_smc.types import Candle, Params
from ict_smc.glm import GlmClient
from ict_smc import research
from ict_smc.advisor import TradeAdvisor
from ict_smc.config import BotConfig
from ict_smc.risk import RiskManager
from ict_smc.memory import Memory
from ict_smc.engine import run_once, build_broker
from ict_smc import performance


def _load_candles(args):
    """Load candles from --csv (offline) or fetch from Coinbase (keyless)."""
    if args.csv:
        return data.from_csv(args.csv), args.csv
    import fetch_coinbase
    print(f"fetching {args.bars} x {args.granularity}s candles for {args.symbol} "
          f"from Coinbase (no key needed) ...")
    rows = fetch_coinbase.fetch(args.symbol, args.granularity, args.bars)
    candles = [Candle(ts, o, h, l, c, v) for ts, o, h, l, c, v in rows]
    return candles, f"{args.symbol} {args.granularity}s x{len(candles)}"


def _make_client(args):
    """Build the GLM client (overridable in tests via _CLIENT_FACTORY)."""
    return _CLIENT_FACTORY(model=args.model, base_url=args.base_url)


def _default_client_factory(*, model, base_url):
    return GlmClient(base_url=base_url, model=model)


# Indirection so tests can inject a fake client without network/keys.
_CLIENT_FACTORY = _default_client_factory


def _require_key() -> bool:
    if not os.environ.get("GLM_API_KEY"):
        print("refusing: set GLM_API_KEY in the environment (get one from Zhipu / z.ai). "
              "Never put it in the repo.", file=sys.stderr)
        return False
    return True


def cmd_research(args) -> int:
    if not _require_key():
        return 2
    candles, source = _load_candles(args)
    base = Params(require_fvg=False, min_rr=2.0)
    client = _make_client(args)
    print(f"running GLM strategy research on {source} "
          f"(~{args.rounds * args.batch} proposals = billable GLM calls) ...")
    report = research.run_research(client, candles, base, n_rounds=args.rounds,
                                   batch_size=args.batch, n_folds=args.n_folds,
                                   logger=logging.getLogger("quickstart"))
    print(f"\nnoise floor: {report.noise_floor:+.3f}R (random-data OOS expectancy)")
    print(f"{'rank':>4}  {'OOS E':>8}  {'PF':>5}  {'trades':>6}  {'margin':>7}  flag")
    for i, r in enumerate(report.ranked, 1):
        if r.error:
            print(f"{i:>4}  {'--':>8}  {'--':>5}  {'--':>6}  {'--':>7}  SKIPPED ({r.error})")
            continue
        pf = "inf" if r.oos_profit_factor == float("inf") else f"{r.oos_profit_factor:.2f}"
        flag = "PASS" if r.passes_noise_floor else "SUB-NOISE-FLOOR"
        print(f"{i:>4}  {r.oos_expectancy_r:>+8.3f}  {pf:>5}  {r.oos_num_trades:>6}  "
              f"{r.margin:>+7.3f}  {flag}")
        print(f"        params: {r.params_overrides}")
    print()
    if report.best:
        print(f"best beating the noise floor: {report.best.params_overrides}")
    else:
        print("No proposal cleared the noise floor — i.e. no edge found. That's the "
              "expected, honest result.")
    return 0


def cmd_advisor(args) -> int:
    if not _require_key():
        return 2
    candles, source = _load_candles(args)
    state_dir = tempfile.mkdtemp(prefix="quickstart_")
    cfg = BotConfig(symbol=args.symbol, state_dir=state_dir)
    cfg.params = Params(require_fvg=False, min_rr=2.0)
    mem = Memory(state_dir)
    risk = RiskManager(cfg.limits)
    broker = build_broker(cfg, mem)
    client = _make_client(args)
    advisor = TradeAdvisor(client, enabled=True, fail_mode=args.fail_mode)

    print(f"running the paper simulator on {source} with the GLM advisor "
          f"(one GLM call per setup; this is billable) ...")
    report = run_once(cfg, broker, risk, mem, candles, advisor=advisor)

    # count what GLM actually did (from the recorded rejections)
    actions = collections.Counter()
    for _, _, reason in report.rejections:
        if "advisor veto" in reason:
            actions["veto"] += 1
        elif "downsized to zero" in reason:
            actions["downsize->0"] += 1
    trades = mem.read_trades()
    perf = performance.summarize(trades, cfg.starting_equity, candles)

    print("\n== paper run with GLM advisor ==")
    print(report.summary())
    print(f"GLM actions: vetoes={actions['veto']} downsized-to-zero={actions['downsize->0']} "
          f"(allowed/downsized setups became the {len(report.submitted)} submitted orders)")
    print(f"performance: {perf.summary()}")
    print("\nReminder: paper only. The advisor can only veto/shrink behind the "
          "RiskManager; it cannot place a real order or manufacture an edge.")
    return 0


def main(argv) -> int:
    ap = argparse.ArgumentParser(description="One-command GLM quickstart (needs GLM_API_KEY)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--csv", default=None, help="run offline from a CSV instead of fetching")
        p.add_argument("--symbol", default="BTC-USD")
        p.add_argument("--granularity", type=int, default=3600, help="seconds (3600=1h)")
        p.add_argument("--bars", type=int, default=2000)
        p.add_argument("--model", default=os.environ.get("BOT_GLM_MODEL", "glm-4.6"))
        p.add_argument("--base-url",
                       default=os.environ.get("BOT_GLM_BASE_URL", GlmClient.DEFAULT_BASE_URL),
                       help="GLM endpoint; for z.ai (international) use "
                            "https://api.z.ai/api/paas/v4 (or set BOT_GLM_BASE_URL)")

    pr = sub.add_parser("research", help="GLM proposes strategies; walk-forward judges them")
    common(pr)
    pr.add_argument("--rounds", type=int, default=3)
    pr.add_argument("--batch", type=int, default=4)
    pr.add_argument("--n-folds", type=int, default=4)
    pr.set_defaults(func=cmd_research)

    pa = sub.add_parser("advisor", help="paper sim with GLM as a subtractive trade advisor")
    common(pa)
    pa.add_argument("--fail-mode", choices=["closed", "open"], default="closed")
    pa.set_defaults(func=cmd_advisor)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
