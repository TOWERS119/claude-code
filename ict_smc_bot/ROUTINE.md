# Running the bot as a scheduled agent

This is the operational guide for running `ict_smc_bot` as an autonomous,
scheduled agent — the "execution layer" from
[`../notes/trading-knowledge-base.md`](../notes/trading-knowledge-base.md) §3–4.
The bar is **beat buy & hold**, on paper, before any capital.

> Reminder from the research: the ICT/SMC strategy showed **no edge** on real BTC
> data. Run this on **paper** to exercise the infrastructure, not because the
> strategy is expected to make money. Swap in a validated strategy before going
> anywhere near live.

## The stateless model

Every invocation wakes with no memory. State lives in files under `state_dir`
(`state.json` cursor + equity peak + daily counters + broker state;
`trades.jsonl` audit log). A run advances over the bars that arrived since the
last cursor, then persists. This is what makes it safe to schedule: each run is
independent and resumable.

## Schedule (suggested)

| When | Command | Job |
|---|---|---|
| Every bar close (e.g. each 15m/1h) | `python3 run_bot.py --csv <latest> --state-dir ./.bot_state` | advance, risk-gate, submit paper orders |
| Friday close | add `--weekly-review` (via routine) | benchmark vs buy & hold, self-grade |

For a **Claude Code routine** (cloud): point it at this repo, run the command
above on a cron trigger, and **commit `state.json` + `trades.jsonl` back to the
branch** at the end of each run (the routine needs push permission) — otherwise
the next run sees stale state. Keep secrets in the routine's cloud environment
variables, never in the repo.

## Programmatic entry point

```python
from ict_smc.config import from_env          # reads BOT_* overrides
from ict_smc.notify import from_env as notifier_from_env
from ict_smc.routine import run_routine
from ict_smc import data

config = from_env()
candles = data.from_csv("data/BTC-USD_15m.csv")   # your latest feed
result = run_routine(config, candles,
                     notifier=notifier_from_env(),
                     weekly_review=False)
print(result.run_summary)
```

## Configuration (environment variables)

Non-secret config (all optional; conservative defaults):

```
BOT_SYMBOL=BTC-USD
BOT_STATE_DIR=./.bot_state
BOT_RISK_PCT=0.01                # 1% risk per trade
BOT_RISK_MAX_CONCURRENT=1
BOT_RISK_MAX_TRADES_PER_DAY=3
BOT_RISK_MAX_DAILY_LOSS=0.03     # daily circuit breaker
BOT_RISK_MAX_DRAWDOWN=0.15       # kill-switch
BOT_RISK_WHITELIST=BTC-USD,ETH-USD
BOT_WEBHOOK_URL=...              # optional alerts (Slack: also BOT_WEBHOOK_KEY=text)
BOT_NOTIFY_FILE=alerts.log       # optional file sink
```

Secrets (read from the environment only, never the repo):

```
COINBASE_API_KEY=...
COINBASE_API_SECRET=...
```

## Going live (deliberately gated)

Live trading is **fail-closed** and requires implementing a venue client first.

1. Implement `CoinbaseClient` (or another `VenueClient`) in `ict_smc/live.py` —
   signing, `get_account_equity`, `get_open_positions`, `place_bracket`,
   `cancel_all`. Test against the venue's **sandbox** first.
2. Construct `LiveBroker(client, symbol=..., allow_live=True, max_order_notional=...)`
   and drive it with `run_live_once` instead of `run_once`.
3. Arm it: set `BOT_ALLOW_LIVE=1`. **Both** `allow_live=True` *and* the env var
   are required — two independent switches, both fail-closed.
4. Hard limits live in three places: the `RiskManager` (pre-trade), the
   `LiveBroker` notional cap (defence in depth), and — most importantly —
   **broker-side limits on the exchange account itself** (max order size, no
   withdrawal permission on the API key). Do not rely on code alone.

## Guardrails checklist (do not skip)

- [ ] Paper-trade for a meaningful period (months, not days); review runs.
- [ ] API keys in env vars only; least privilege (no withdrawal); rotate if leaked.
- [ ] Risk caps enforced broker-side, not just in the prompt/code.
- [ ] Weekly review actually beats the benchmark before considering capital.
- [ ] Watch the first many runs; alert on halts (kill-switch / daily breaker).
