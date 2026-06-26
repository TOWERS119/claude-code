#!/usr/bin/env python3
"""LLM strategy-research runner (capability 3).

The chosen LLM proposes strategy parameter sets; each is validated by the SAME
walk-forward out-of-sample rig used everywhere else and compared to the
random-data noise floor. Proposals that don't clear the floor are flagged
SUB-NOISE-FLOOR.

    GROQ_API_KEY=... python3 run_glm_research.py --provider groq --csv findings/data/BTC-USD_1h.csv
    GLM_API_KEY=...  python3 run_glm_research.py --synthetic --bars 4000 --rounds 2

Pick a provider with --provider (default glm; free: gemini, groq, openrouter,
ollama) and set its key in the environment (never the repo). Use --dry-prompt to
print the seed prompt without calling the API.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from ict_smc import data
from ict_smc.types import Params
from ict_smc import research, providers


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="LLM strategy research (walk-forward judged)")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--synthetic", action="store_true")
    src.add_argument("--csv", type=str)
    ap.add_argument("--bars", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--n-folds", type=int, default=4)
    ap.add_argument("--min-oos-trades", type=int, default=10)
    ap.add_argument("--provider", default=os.environ.get("BOT_LLM_PROVIDER", "glm"),
                    choices=sorted(providers.PROVIDERS),
                    help="LLM provider; free: gemini, groq, openrouter, ollama")
    ap.add_argument("--model", default=os.environ.get("BOT_GLM_MODEL"),
                    help="override the provider's default model")
    ap.add_argument("--base-url", default=os.environ.get("BOT_GLM_BASE_URL"),
                    help="override the provider's default endpoint")
    ap.add_argument("--dry-prompt", action="store_true",
                    help="print the seed prompt and exit (no API call)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    base = Params(require_fvg=False, min_rr=2.0)

    if args.dry_prompt:
        msgs = research._build_research_messages(base, noise_floor=-0.20,
                                                 batch_size=args.batch, history=[])
        for m in msgs:
            print(f"--- {m['role']} ---\n{m['content']}\n")
        return 0

    key_msg = providers.require_key(args.provider)
    if key_msg:
        print(key_msg, file=sys.stderr)
        return 2

    candles = (data.synthetic(n=args.bars, seed=args.seed) if args.synthetic
               else data.from_csv(args.csv))
    source = f"synthetic(n={args.bars})" if args.synthetic else args.csv

    client = providers.make_client(args.provider, model=args.model, base_url=args.base_url)
    report = research.run_research(
        client, candles, base, n_rounds=args.rounds, batch_size=args.batch,
        n_folds=args.n_folds, min_oos_trades=args.min_oos_trades,
        logger=logging.getLogger("research"),
    )

    print(f"\n== strategy research via '{args.provider}' ==")
    print(f"source     : {source}")
    print(f"noise floor: {report.noise_floor:+.3f}R (random-data OOS expectancy)")
    print(f"proposals  : {len(report.ranked)} over {report.rounds} round(s)\n")
    print(f"{'rank':>4}  {'OOS E':>8}  {'PF':>5}  {'trades':>6}  {'margin':>7}  flag")
    for i, r in enumerate(report.ranked, 1):
        if r.error:
            print(f"{i:>4}  {'--':>8}  {'--':>5}  {'--':>6}  {'--':>7}  SKIPPED ({r.error})")
            continue
        flag = "PASS" if r.passes_noise_floor else "SUB-NOISE-FLOOR"
        pf = "inf" if r.oos_profit_factor == float("inf") else f"{r.oos_profit_factor:.2f}"
        print(f"{i:>4}  {r.oos_expectancy_r:>+8.3f}  {pf:>5}  {r.oos_num_trades:>6}  "
              f"{r.margin:>+7.3f}  {flag}")
        print(f"        params: {r.params_overrides}")
    print()
    if report.best:
        print(f"best beating the noise floor: {report.best.params_overrides} "
              f"({report.best.oos_expectancy_r:+.3f}R, margin {report.best.margin:+.3f})")
    else:
        print("No proposal cleared the noise floor — i.e. no edge found. This is the "
              "expected, honest result; an edge should NOT appear on random data, and "
              "rarely survives on real data either.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
