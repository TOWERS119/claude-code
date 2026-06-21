# ICT / SMC Strategy Engine (bot addon)

A dependency-free Python implementation of the ICT / Smart Money Concepts entry
gate described in [`../notes/ict-smc-addon.md`](../notes/ict-smc-addon.md), with
a look-ahead-safe backtester and honest out-of-sample validation.

This is the **strategy + validation layer** of the agent architecture in
[`../notes/trading-knowledge-base.md`](../notes/trading-knowledge-base.md) (§4).
It is a *scaffold to test rules*, **not** a profitable system — see the caveats.

## Why it's built this way

- **Pure standard library.** No numpy/pandas. It runs unchanged inside a
  stateless cloud agent run (no install step, no dependency drift).
- **Look-ahead-safe by construction.** Swings are only used after their
  `confirmed_at` bar; setups arm at the MSS bar; fills happen strictly later;
  same-bar stop+target counts as a stop. (Tested.)
- **Validation is the product.** The numbers that matter are out-of-sample. On
  random data the strategy is correctly a net loser — that's the proof there's
  no leak.

## Layout

```
ict_smc_bot/
├── ict_smc/
│   ├── types.py        # Candle, Swing, FVG, Setup, Trade, Params (all knobs)
│   ├── detectors.py    # ATR, swings, displacement, FVGs, order blocks
│   ├── strategy.py     # the entry gate (sweep → MSS → PD array → risk geometry)
│   ├── backtest.py     # simulator, metrics, train_test, walk_forward
│   ├── risk.py         # RiskManager: sizing, circuit breaker, kill-switch, whitelist
│   ├── broker.py       # PaperBroker (bar-by-bar bracket orders) + LiveBroker stub
│   ├── memory.py       # atomic file state + append-only trade log
│   ├── config.py       # BotConfig, env overrides, get_secret (env-only)
│   ├── engine.py       # run_once: the stateless agent invocation tying it together
│   ├── performance.py  # equity curve, buy&hold benchmark, alpha, weekly review
│   ├── notify.py       # alerting: console / file / webhook (Slack-style)
│   ├── live.py         # VenueClient + safety-gated LiveBroker + run_live_once
│   ├── routine.py      # run_routine: scheduled step + notify + weekly review
│   └── data.py         # CSV loader + synthetic OHLC generator
│   ├── glm.py          # GlmClient (Zhipu, OpenAI-compatible) + robust JSON extract
│   ├── advisor.py      # TradeAdvisor: subtractive GLM gate (veto/downsize)
│   ├── research.py     # GLM strategy proposals judged by walk_forward + noise floor
│   └── http.py         # shared injectable HTTP transport
├── run_backtest.py     # CLI: full / train-test / walk-forward research report
├── run_bot.py          # CLI: stateless paper-trading "run once" (resumable)
├── run_glm_research.py # CLI: GLM proposes strategies, walk-forward judges them
├── fetch_coinbase.py   # pull real OHLCV (public API, no key) into a CSV
├── strategy_spec.md    # the numeric rule spec
├── ROUTINE.md          # operating the bot as a scheduled agent (paper/live)
├── GLM.md              # optional GLM integration (capabilities 3 & 4)
└── tests/              # 89 tests: strategy + risk/exec/engine + infra + glm
```

## Running it as a scheduled agent

See [`ROUTINE.md`](ROUTINE.md) for the full operating guide. In short: the
infrastructure adds a **performance/benchmark** layer (alpha vs buy & hold, with
an honest self-grade that refuses to grade tiny samples), an **alerting** layer
(console / file / webhook), a **safety-gated live execution** path, and a
**routine** wrapper for cron / Claude Code routines.

Live trading is fail-closed: `LiveBroker` places no order unless constructed with
`allow_live=True` **and** the environment sets `BOT_ALLOW_LIVE=1`, with a hard
notional cap below the `RiskManager`. `AlpacaClient` is implemented and defaults
to the **paper sandbox** (`paper-api.alpaca.markets`) — header auth, injectable
HTTP, fully unit-tested without keys; see [`ROUTINE.md`](ROUTINE.md) for the
go-live snippet. The whole live path is also testable offline via `SimVenueClient`,
and `CoinbaseClient` remains a documented skeleton (Coinbase Advanced needs
ES256/JWT signing + has no usable sandbox).

## GLM integration (optional, off by default)

GLM (Zhipu AI, e.g. `glm-4.6`) can plug in two ways — see [`GLM.md`](GLM.md).
Both share `GlmClient` (OpenAI-compatible, injectable HTTP, key from
`GLM_API_KEY` in the env only) and are **off unless `BOT_GLM_ENABLED=1`**.

- **Strategy research (capability 3)** — GLM proposes *parameter sets* (never
  code; a whitelist of `Params` fields, clamped to safe ranges), each judged by
  the same `walk_forward` rig and compared to the random-data **noise floor**.
  Proposals that don't clear the floor are flagged `SUB-NOISE-FLOOR`. Cost fields
  are excluded so GLM can't fake profit by lowering costs.
  `GLM_API_KEY=… python3 run_glm_research.py --csv data.csv --rounds 3`
- **Trade decision-maker (capability 4)** — `TradeAdvisor` reviews a setup the
  strategy already produced and may only **veto** or **downsize** it
  (`size_factor` clamped to [0,1] in code). It cannot create a trade, increase
  size, or relax the `RiskManager`, which stays the final authority. **Fail-closed
  by default** (GLM error/timeout → skip the trade).

GLM **cannot create edge** here: research is judged by the same brutal rig, and
as a decision-maker it's strictly subtractive behind the RiskManager.

## The full bot (strategy + risk + execution + memory)

Beyond backtesting, the package runs as an autonomous **paper-trading agent**
built the way the knowledge base prescribes — stateless runs over file-based
memory, with risk enforced as a hard chokepoint:

```bash
# One stateless run; advance only 1500 new bars, persisting to ./.bot_state
python3 run_bot.py --synthetic --bars 4000 --max-bars 1500 --state-dir ./.bot_state
# Run it again: it resumes from the saved cursor (true stateless-run model)
python3 run_bot.py --synthetic --bars 4000 --state-dir ./.bot_state
```

The layers:

- **`engine.run_once`** — the single agent invocation: restore state → advance
  over new bars → resolve fills/exits → log trades → enforce halts → risk-gate
  and submit fresh setups → persist. Schedule it (cron / Claude Code routine) and
  it behaves like a live agent.
- **`RiskManager`** — every setup is a *request*; this is the only path to an
  order. Enforces (in order) kill-switch (max drawdown), daily loss breaker,
  whitelist, max concurrent positions, max trades/day, min reward:risk,
  fractional sizing, and a hard notional cap (sizing only ever shrinks).
- **`PaperBroker`** — deterministic bar-by-bar bracket-order engine with the same
  conservative fill/cost rules as the backtester; fully serializable so state
  survives between stateless runs. `LiveBroker` is a deliberate non-functional
  stub so nothing here can place a real order by accident.
- **`Memory`** — atomic `state.json` (cursor, equity peak, daily counters, broker
  state) + append-only `trades.jsonl` audit log.
- **`config.get_secret`** — API keys come from environment variables only, never
  the repo or a `.env`. Going live means implementing `LiveBroker` against your
  venue's SDK behind an explicit opt-in.

## Quick start

```bash
cd ict_smc_bot

# Reproducible synthetic run (no data needed):
python3 run_backtest.py --synthetic --bars 5000 --seed 7 --allow-ob-only

# Your own OHLCV csv (header: open,high,low,close[,volume,timestamp]):
python3 run_backtest.py --csv data/BTCUSDT_15m.csv --min-rr 2.5 --entry-level deep

# Tests:
python3 -m unittest discover -s tests -v
```

### Library use

```python
from ict_smc.types import Params
from ict_smc import data
from ict_smc.backtest import run, walk_forward

candles = data.synthetic(n=4000, seed=7)        # or data.from_csv("ohlcv.csv")
params  = Params(min_rr=2.0, entry_level="mid")

result = run(candles, params)
print(result.report())

folds, oos = walk_forward(candles, params,
                          grid={"min_rr": [1.5, 2.0, 2.5, 3.0]}, n_folds=4)
print("aggregate OOS:", oos.report())
```

## Reading the output

```
trades=50 (L25/S25)  win%=28.0  PF=0.72  expectancy=-0.204R  ...
```

- **expectancy (R)** — average profit per trade in units of risk. This is the
  number to watch. Positive *out-of-sample* is the only thing that counts.
- **PF** — profit factor (gross win / gross loss). >1 to be viable.
- The **walk-forward AGGREGATE OOS** line is the headline. Expect it near
  `−costs` on synthetic data — and treat a big positive number there as a **bug
  signal**, not a discovery.

## Getting real data (optional)

Keep the core import-clean; fetch data with a throwaway script:

```python
# pip install ccxt
import ccxt, csv
ohlcv = ccxt.binance().fetch_ohlcv("BTC/USDT", timeframe="15m", limit=1000)
with open("data/BTCUSDT_15m.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["timestamp","open","high","low","close","volume"])
    w.writerows(ohlcv)
```

Then `--csv data/BTCUSDT_15m.csv`. For multi-timeframe ICT (4H bias → 15m entry,
per addon §10) run the gate on each timeframe and require agreement; that wiring
is the documented next step, not yet built.

## Honest limitations (read this)

This intentionally implements **only the structural core** of the addon (sweep,
MSS, FVG/OB, discount/premium, risk geometry). It omits the softer confluences —
SMT divergence, the two-lines regime, session timing, candle continuity, EMA
bias. Add them **one at a time, each validated out-of-sample**; adding them all
at once is the over-fitting trap the notes warn about.

ICT/SMC is highly discretionary; this encodes one defensible interpretation of
its rules. **No edge is demonstrated or implied.** Backtest profits — especially
optimizer-selected ones — are hypotheses until they survive out-of-sample and
walk-forward. Paper-trade for a meaningful period; enforce risk limits
**broker-side**, not just in code. See `../notes/trading-knowledge-base.md` §5–6.
