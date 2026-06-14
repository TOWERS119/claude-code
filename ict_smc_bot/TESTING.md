# Where and how to test the bot

Three levels, cheapest first. Each is runnable; the last needs your (free) Alpaca
paper keys.

## 1. Unit + integration tests (no keys, runs anywhere)

```bash
python3 -m unittest discover -s tests        # 55 tests
```

Covers: strategy detectors + look-ahead safety (`test_ict_smc.py`), risk /
paper-broker / engine (`test_bot.py`), performance / notify / live safety gates /
Alpaca request-building with a fake transport (`test_infra.py`), and the
end-to-end live pipeline (`test_e2e.py`).

## 2. End-to-end dry-run (no keys, real code path)

Runs the actual production flow — data → `generate_setups` → `RiskManager` →
`LiveBroker` → `run_live_once` → venue → persisted state — as a simulated
schedule against `SimVenueClient`:

```bash
python3 run_live_dryrun.py --sim --csv findings/data/BTC-USD_1h.csv \
    --symbol AAPL --ticks 300
```

It reports orders placed at the venue, risk rejections, the persisted state
cursor, and a sanity check that venue orders == submitted. This is "test-test"
without spending anything: the same code that would talk to Alpaca, exercised
end-to-end with the venue swapped for a simulator.

## 3. Real Alpaca paper sandbox (free account, no real money)

This is the genuine sandbox — a real broker endpoint, simulated money.

1. **Get paper keys.** Create a free Alpaca account, open the **Paper Trading**
   dashboard, generate an API key + secret.
2. **Put them in the environment only** (never the repo):
   ```bash
   export ALPACA_API_KEY_ID=...        # paper key
   export ALPACA_API_SECRET_KEY=...
   ```
3. **Arm the second safety switch** (both are required):
   ```bash
   export BOT_ALLOW_LIVE=1
   ```
4. **Feed equity bars.** Alpaca bracket orders need an equity symbol with
   whole-share quantities (e.g. `AAPL`). Provide a CSV of recent bars
   (`timestamp,open,high,low,close,volume`); once you have keys you can pull them
   from Alpaca's own data API, or use any provider.
5. **Run one scheduled tick against the sandbox:**
   ```bash
   python3 run_live_dryrun.py --alpaca --symbol AAPL --csv data/AAPL_15m.csv
   ```
   It prints your paper account equity and the result of the tick (submitted /
   rejected). Schedule the same command (cron / Claude Code routine) to run the
   agent continuously; see [`ROUTINE.md`](ROUTINE.md).

### Safety recap

- Orders require **both** `LiveBroker(allow_live=True)` **and** `BOT_ALLOW_LIVE=1`.
  The dry-run and tests prove that with either switch off, **zero** orders reach
  the venue.
- Keep the base URL on the **paper** endpoint until you have run for a meaningful
  period and the weekly review consistently beats the benchmark. Per
  [`findings/FINDINGS.md`](findings/FINDINGS.md), this strategy does **not** —
  so this stays a plumbing/learning exercise, not a path to live capital.
