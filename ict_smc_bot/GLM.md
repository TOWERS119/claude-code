# GLM integration

Optional integration of GLM (Zhipu AI's latest model, e.g. `glm-4.6`) for two
capabilities. **Off by default.** Both share one client (`ict_smc/glm.py`),
pure-stdlib, with an injectable HTTP transport (so everything is unit-tested
without keys or network) and the API key read from the environment only.

## Quickstart (one command)

The fastest way to start — only needs `GLM_API_KEY` (no installs, no broker keys;
data from the keyless Coinbase endpoint or `--csv` for offline):

```bash
export GLM_API_KEY=...
python3 quickstart.py research --csv findings/data/BTC-USD_1h.csv   # capability 3
python3 quickstart.py advisor  --csv findings/data/BTC-USD_1h.csv   # capability 4 (paper sim)
```

Both refuse cleanly (no network) if `GLM_API_KEY` is unset. `research` prints a
ranked, noise-floor-flagged table; `advisor` prints a paper run report, a buy &
hold comparison, and a count of GLM veto/downsize actions.

## Configuration

```
BOT_GLM_ENABLED=1                 # master switch (default off)
BOT_GLM_MODEL=glm-4.6             # "latest version" is just the model id
BOT_GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4   # or the z.ai endpoint
BOT_GLM_FAIL_MODE=closed          # closed (default) | open
BOT_GLM_MIN_SIZE_FACTOR=0.0       # floor on advisor downsizing
BOT_GLM_TIMEOUT=20
GLM_API_KEY=...                   # SECRET — env only, never the repo, never logged
```

## Capability 3 — GLM proposes strategies, the rig judges them

GLM proposes **parameter sets**, not code. There is no `exec`/`eval`: a proposal
is a JSON object whose keys are a whitelist subset of `Params` fields; each value
is type-coerced and clamped to a safe range, then applied via
`dataclasses.replace`. Every proposal is scored by the same `walk_forward`
out-of-sample rig used everywhere else, and compared to a **noise floor** =
`walk_forward` on random (`data.synthetic`) data. Anything not clearing the floor
by a margin is flagged `SUB-NOISE-FLOOR`.

```bash
GLM_API_KEY=... python3 run_glm_research.py --csv findings/data/BTC-USD_1h.csv --rounds 3
python3 run_glm_research.py --synthetic --dry-prompt    # inspect the prompt, no API call
```

**Proposal schema** (all keys optional; omitted keys keep defaults). Cost/equity
fields are deliberately **excluded** so GLM cannot fake profit by lowering costs:

| field | type | range |
|---|---|---|
| `swing_lookback` | int | 1–6 |
| `atr_period` | int | 5–50 |
| `displacement_atr_mult` | float | 0.5–3.0 |
| `displacement_body_ratio` | float | 0.3–0.9 |
| `require_displacement_fvg` | bool | |
| `sweep_max_age` | int | 5–60 |
| `mss_max_age` | int | 3–40 |
| `require_fvg` | bool | |
| `use_ob_fallback` | bool | |
| `entry_level` | enum | edge / mid / deep |
| `equilibrium_filter` | bool | |
| `stop_buffer_atr` | float | 0.0–1.0 |
| `min_rr` | float | 1.0–5.0 |
| `entry_valid_bars` | int | 3–40 |
| `trade_max_bars` | int | 10–200 |
| `allow_long` / `allow_short` | bool | |

The model replies `{"proposals": [ {…}, … ]}`; out-of-range or unknown values are
clamped/dropped by `sanitize_proposal` (the bot never trusts the model's numbers).

## Capability 4 — GLM as a subtractive trade decision-maker

`TradeAdvisor` reviews each setup the deterministic strategy already produced and
returns a verdict that can only **reduce** exposure:

```json
{"action": "allow" | "downsize" | "veto", "size_factor": 0.0-1.0, "reason": "short"}
```

Authority model (per setup): `advisor.review` → if **veto**, skip (no risk call) →
`risk.evaluate` (unchanged, **final authority**) → `qty = decision.qty ×
size_factor` → `submit_bracket`. Guarantees enforced in code, not by trusting GLM:

- `size_factor` is clamped to `[0, 1]` on verdict construction — an upsize is
  structurally impossible (a returned `2.0` becomes `1.0`).
- GLM only ever sees existing setups — it cannot originate a trade.
- The advisor runs *around* the RiskManager and never relaxes its limits.
- **Fail-closed by default**: any GLM error/timeout/malformed reply skips the
  trade (`BOT_GLM_FAIL_MODE=closed`). `open` mode passes through to the
  RiskManager unchanged (advice-only, still risk-gated) when GLM is down.
- The advisor **never raises** into the run loop.

Wired into both `run_once` (paper engine) and `run_live_once` (live path). Try it
end-to-end on the simulated venue:

```bash
GLM_API_KEY=... BOT_GLM_ENABLED=1 python3 run_live_dryrun.py --sim --glm-advisor \
    --csv findings/data/BTC-USD_1h.csv --ticks 100
```

> Cost note: in `--sim` mode the advisor is consulted once per setup per tick, so
> `--glm-advisor` makes up to `--ticks` billable GLM calls. The runner prints a
> warning up front. Real live use (`--alpaca`, or a scheduled `run_live_once`) is
> one tick per bar, so it's one small batch of calls per bar.

## Honesty & safety

- **GLM cannot create edge.** Research proposals are judged by the same
  out-of-sample + noise-floor rig as everything else (`findings/FINDINGS.md`);
  they can't lower modeled costs and can't run code.
- **GLM cannot bypass risk.** As a decision-maker it is strictly subtractive and
  fail-closed, behind the RiskManager which remains the sole final authority.
- **Off by default; secrets in env only.** Nothing calls GLM unless
  `BOT_GLM_ENABLED=1`; the key is read via `get_secret("GLM_API_KEY")` and never
  logged or committed.
