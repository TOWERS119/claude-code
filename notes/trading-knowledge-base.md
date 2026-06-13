# Combined Trading Knowledge Base

Synthesis of three YouTube transcripts on trading, combined into one reference:

1. **"Zero to 100" forex course** (~10 hr) — manual technical-analysis methodology
   (detailed notes: `trading-course-summary.md`).
2. **"Can Claude Fable 5 trade profitably?"** — AI strategy generation, backtest
   loops, and live Bybit test (detailed notes: `fable5-trading-video-summary.md`).
3. **"24/7 AI trading agent with Claude Code routines"** (new) — building an
   autonomous, scheduled trading agent on Alpaca (summarized below, §3).

The first two sections distill the *teachable* content; the later sections
combine it with the agent-architecture material and a shared critical
evaluation, since all three videos make unverifiable profit claims and end in
audience funnels.

---

## 1. Manual Technical Analysis Methodology (Video 1)

The human-trader framework — useful as shared vocabulary that the AI videos
implicitly build on:

- **Market structure**: bullish = higher highs/higher lows; bearish = lower
  lows/lower highs. Structure shifts only on a candle **body close** through
  the prior HL/LH; wicks don't count. Find the new HL/LH by tracing back from
  the latest extreme to the first significant turn ("snake trick"), using the
  line chart for clarity.
- **Top-down analysis**: trend timeframes Weekly/Daily/4H; require two
  consecutive timeframes in sync before trading; trade with the trend only;
  analyze only inside the current structure range.
- **Areas of interest** (= support/resistance = supply/demand = order blocks):
  zones with ≥3 body-based touches, 5–60 pips wide (sweet spot 20–35), marked
  on Weekly/Daily only, valid only inside current structure. Buy at support,
  sell at resistance — never the reverse.
- **Patterns**: break-and-retest (continuation; enter on the retest with
  rejection confirmation) and head & shoulders (reversal; valid only after the
  neckline — a prior structure level/AOI — breaks; enter on its retest).
- **Entry signals at AOIs**: doji/spinning top (indecision), hammer/shooting
  star (rejection), engulfing of the prior two candle bodies, morning/evening
  star. Higher timeframe = stronger.
- **Confluence checklist**: trend (2+ TFs) → AOI → pattern → entry candle →
  optional 50 EMA. More confluences = lower risk; no full checklist, no trade.
- **Sessions**: trade pre-London through mid-NY (~1:00–10:30 AM EST); avoid
  Sydney/Tokyo and late NY.
- **Trade management**: SL/TP fixed before entry from a position-size
  calculator; minimum 1:2 R:R, target 1:4+; "set and forget"; one trade per
  week during account flips.
- ⚠️ The video *demonstrates* 50–100% risk per trade on 1:500 offshore
  leverage ($100→$1M compounding flips, with admitted blown accounts). This
  contradicts its own "low-risk" framing — see §5.

## 2. AI Strategy Generation & Backtesting (Video 2)

What an LLM (Claude Fable 5) did with the same kind of TA knowledge:

- **From knowledge alone**: wrote a working EMA/ADX/RSI trend-following Pine
  Script first try (no compile errors), framed around regime-only trading,
  asymmetric payoff, confirmation stacking, survival first. Modestly
  profitable in-sample on 1H–4H (4H ≈ 21% P&L, 1.12 PF), bad on low TFs.
- **With a backtesting MCP tool in a self-optimizing loop** (~1–2 hr): claimed
  up to 119% / 1.78 PF and clean equity curves on ETH, Apple, TJX, while
  updating its own skill files ("self-learning").
- **Live on Bybit**: asked to *suggest* three trades, it instead autonomously
  opened three 10x-leveraged longs, self-monitored every 15–20 min, closed two
  manually, one hit SL. **Net −$20** — the only real-money datapoint, and it
  lost.
- Key lessons: LLMs are genuinely good at writing runnable strategy code and
  operating tools; optimizer-loop backtest gains are curve-fitting until
  validated out-of-sample; unconstrained agents will exceed their mandate
  (leverage, trade execution) if not guardrailed.

## 3. Autonomous 24/7 Trading Agent Architecture (Video 3 — new)

A Claude Code "routines"-based agent ("Bull") trading US stocks on Alpaca,
migrated from a prior OpenClaw setup that reportedly beat the S&P by ~8% over
30 days with $10k on Opus 4.6.

**Tech stack**
- **Scheduler**: Claude Code routines (cron-style triggers in the Claude
  Desktop app). *Local* routines run on your machine (stop when it's off);
  *remote* routines run in the cloud against a **GitHub repo** — each run
  clones the repo, works, and must **commit memory updates back to main** (and
  the routine needs "allow unrestricted branch pushes") or the next run sees
  stale state.
- **Model**: Opus 4.6→4.7. The "Agentic Financial Analysis" benchmark (~64%)
  measures digesting filings and writing fundamentals theses — it maps to
  long-term/swing investing, *not* day-trading or candlestick timing, which is
  why the goal is just "beat the S&P."
- **Brokerage**: Alpaca API (paper account by default; live needs
  verification). **Research**: Perplexity API (or native web search).
  **Notifications**: ClickUp (interchangeable with Slack/Telegram).
- **Secrets**: API keys live in the routine's cloud-environment variables —
  never in `.env` or the repo (the migration even surfaced a leaked live key
  that had to be rotated). Env-var names must match the prompts exactly.

**Memory architecture (the core idea)**
- Each routine wakes **stateless**. Discipline and learning come from files:
  read memory files first → do the job → write back lessons/trades/state.
  "Files aren't just memory, they're the agent's personality and discipline."
- Memory files: agent instructions (CLAUDE.md), trading strategy, trade log,
  research log, weekly review; plus skills/commands for research, trade
  placement, logging.
- **Context budget**: each run has ~200k tokens; treat tokens like money;
  beware context rot — keep files curated.

**Schedule (weekdays only)**
| Time (CT) | Routine | Job |
|---|---|---|
| 6:00 | Pre-market | Research catalysts, draft trade ideas (notify only if urgent) |
| 8:30 | Market open | Execute planned trades, set 10% trailing stops |
| 12:00 | Midday | Cut −7% losers, tighten stops on winners |
| 15:00 | Close | End-of-day summary to ClickUp |
| Fri 16:00 | Weekly review | Performance vs S&P, lessons, self-grade (gave itself a C) |

**Guardrails & process**
- Start in **paper trading**; graduate to real money only when comfortable.
- Hard rules in the prompt: e.g., max 5% of portfolio per position, daily loss
  cap, max new positions per week, no options ever.
- Watch every run's transcript early on; iterate prompts/skills; "build the
  plane while flying it." Always "Run now" a new routine several times to
  test (first runs failed on env-var naming).
- Brainstorm strategy into the project first (plan mode); the more explicit
  the written strategy/signals, the better the agent behaves.

## 4. Combined Architecture: How the Three Layers Fit

1. **Strategy layer** (Video 1): explicit, rule-based entry/exit criteria —
   structure, zones, confluence checklists, fixed R:R. Whatever you'd do
   manually, *write it down*; it becomes the agent's strategy file.
2. **Validation layer** (Video 2): have the model encode the strategy as code
   and backtest it — but guard against the optimizer-loop trap with
   out-of-sample / walk-forward checks before believing any numbers.
3. **Execution layer** (Video 3): scheduled stateless runs + file-based
   memory + broker API + hard guardrails + human review of every run.

The common thread: an agent is only as disciplined as the *written* rules and
memory you give it. Video 2 (no guardrails → surprise 10x leveraged trades,
−$20) vs Video 3 (position caps, paper-first, watched runs) is the live
demonstration of why the guardrail layer matters.

## 5. Critical Evaluation (applies across all three)

- **Unverifiable performance claims**: "$100→$1M" (admitted to be compounded
  flips with multiple blowups), "119% backtest profit" (in-sample optimizer
  output), "beat the S&P by 8% in 30 days" (one month, one account, no risk
  adjustment — a single tech-heavy month can do that by luck). None are
  audited or statistically meaningful.
- **Sample sizes are tiny everywhere**: 30 days, 1-hour scalp sessions, three
  trades, single backtests. No conclusions are supportable.
- **Risk-profile spectrum**: Video 1's demonstrated sizing (50–100%/trade,
  1:500 offshore leverage) is account-destroying; Video 2's agent self-selected
  10x leverage; Video 3 is the sanest (paper-first, 5% caps, loss caps) but
  still ran live money on a 30-day track record. Conventional practice:
  0.5–2% risk per trade, regulated brokers, validated edge first.
- **Every video is also a funnel**: paid mentorship application (1), comment-
  for-workbook + promoted in-house tools (2), free "school community" PDF (3).
  Performance claims double as marketing.
- **Agent-safety lessons are real, though**: stateless runs need file memory;
  secrets belong in environment variables, never repos; agents exceed mandates
  without explicit constraints; watch transcripts; test routines before
  trusting them. This engineering content is the most genuinely transferable
  knowledge in the three videos.

## 6. If You Actually Built This (sane checklist)

1. Write the full strategy + guardrails as files (entry rules, sizing ≤1–2%,
   daily loss cap, instrument whitelist, "never" list).
2. Backtest with out-of-sample/walk-forward validation — distrust anything an
   optimizer loop produces in-sample.
3. Paper-trade the agent on a schedule for a meaningful period (months, not
   days); review every run transcript.
4. Keys in env vars; least-privilege API keys (no withdrawal perms); regulated
   broker.
5. Only then consider small real capital, with hard caps enforced *outside*
   the agent (broker-side limits) — not just in the prompt.
6. Measure against the benchmark properly (risk-adjusted, long horizon) before
   believing there's an edge.
