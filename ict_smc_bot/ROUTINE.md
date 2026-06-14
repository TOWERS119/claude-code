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
ALPACA_API_KEY_ID=...        # from the Alpaca paper dashboard
ALPACA_API_SECRET_KEY=...
```

## Sandbox / live via Alpaca (implemented)

`AlpacaClient` is implemented and defaults to the **paper sandbox**
(`https://paper-api.alpaca.markets`). It uses simple header auth (no request
signing) and an injectable HTTP layer, so it's fully unit-tested without keys.

```python
import os
from ict_smc.live import AlpacaClient, LiveBroker, run_live_once
from ict_smc.config import BotConfig
from ict_smc.risk import RiskManager
from ict_smc.memory import Memory
from ict_smc import data

# 1) keys in the environment only (paper account)
#    export ALPACA_API_KEY_ID=...  ALPACA_API_SECRET_KEY=...
client = AlpacaClient()                      # paper sandbox by default
broker = LiveBroker(client, symbol="AAPL",   # bracket orders need an equity symbol
                    allow_live=True, max_order_notional=2_000.0)

cfg = BotConfig(symbol="AAPL", state_dir="./.bot_state")
risk = RiskManager(cfg.limits)
mem = Memory(cfg.state_dir)
candles = data.from_csv("data/AAPL_15m.csv")  # your latest feed

# 2) arm the env switch (the SECOND of the two required switches)
os.environ["BOT_ALLOW_LIVE"] = "1"
report = run_live_once(cfg, broker, risk, mem, candles)
print(report.summary())
```

Two notes specific to Alpaca: bracket orders are an **equities** feature and need
**whole-share** quantities (use an equity symbol like `AAPL` to demo); set the
base URL to `AlpacaClient.LIVE_URL` only when you genuinely mean real money.

## Going truly live (deliberately gated)

1. Start on the **paper sandbox** above for a meaningful period.
2. Both `allow_live=True` *and* `BOT_ALLOW_LIVE=1` are required — two independent
   fail-closed switches.
3. Hard limits live in three places: the `RiskManager` (pre-trade), the
   `LiveBroker` notional cap (defence in depth), and — most importantly —
   **broker-side limits on the account itself** (max order size, no withdrawal
   permission on the API key). Do not rely on code alone.
4. For other venues, implement the `VenueClient` protocol (`CoinbaseClient` is a
   skeleton — note Coinbase Advanced needs ES256/JWT signing, a crypto
   dependency, and has no usable trading sandbox).

## Guardrails checklist (do not skip)

- [ ] Paper-trade for a meaningful period (months, not days); review runs.
- [ ] API keys in env vars only; least privilege (no withdrawal); rotate if leaked.
- [ ] Risk caps enforced broker-side, not just in the prompt/code.
- [ ] Weekly review actually beats the benchmark before considering capital.
- [ ] Watch the first many runs; alert on halts (kill-switch / daily breaker).
