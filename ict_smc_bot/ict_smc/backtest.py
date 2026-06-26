"""Event-driven simulator, metrics, and honest out-of-sample validation.

Design choices that keep the numbers trustworthy (these directly answer the
over-fitting warnings in ``notes/ict-smc-addon.md``):

* No look-ahead. Setups are armed at the MSS bar; fills happen strictly on later
  bars. Swings are only used after ``confirmed_at``.
* Conservative intrabar resolution. If a single bar trades through both stop and
  target, the **stop** is assumed hit first.
* Costs are real. Adverse slippage and per-side commission are applied to every
  fill.
* No overlapping positions. One trade at a time, so results aren't inflated by
  implicit pyramiding.
* Validation is the point. ``train_test`` and ``walk_forward`` report
  out-of-sample results; ``walk_forward`` optimizes on in-sample folds and scores
  the *next* fold, which is where any curve-fit edge falls apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from itertools import product
from typing import Dict, List, Optional, Tuple

from .types import Candle, Setup, Trade, Params
from .strategy import generate_setups


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
@dataclass
class BacktestResult:
    trades: List[Trade] = field(default_factory=list)
    starting_equity: float = 0.0
    final_equity: float = 0.0
    equity_curve: List[Tuple[int, float]] = field(default_factory=list)

    num_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    expectancy_r: float = 0.0
    avg_win_r: float = 0.0
    avg_loss_r: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    longs: int = 0
    shorts: int = 0

    def report(self) -> str:
        pf = "inf" if self.profit_factor == float("inf") else f"{self.profit_factor:.2f}"
        return (
            f"trades={self.num_trades} (L{self.longs}/S{self.shorts})  "
            f"win%={self.win_rate * 100:5.1f}  PF={pf:>5}  "
            f"expectancy={self.expectancy_r:+.3f}R  "
            f"avgW={self.avg_win_r:+.2f}R avgL={self.avg_loss_r:+.2f}R  "
            f"ret={self.total_return_pct * 100:+.1f}%  maxDD={self.max_drawdown_pct * 100:.1f}%"
        )


def _metrics_from_trades(
    trades: List[Trade], starting_equity: float, final_equity: float,
    curve: List[Tuple[int, float]], max_dd: float,
) -> BacktestResult:
    res = BacktestResult(
        trades=trades,
        starting_equity=starting_equity,
        final_equity=final_equity,
        equity_curve=curve,
        num_trades=len(trades),
        max_drawdown_pct=max_dd,
    )
    if not trades:
        return res
    wins = [t for t in trades if t.r_multiple > 0]
    losses = [t for t in trades if t.r_multiple <= 0]
    res.wins, res.losses = len(wins), len(losses)
    res.win_rate = len(wins) / len(trades)
    res.gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    res.gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
    res.profit_factor = (
        res.gross_profit / res.gross_loss if res.gross_loss > 0 else float("inf")
    )
    res.expectancy_r = sum(t.r_multiple for t in trades) / len(trades)
    res.avg_win_r = sum(t.r_multiple for t in wins) / len(wins) if wins else 0.0
    res.avg_loss_r = sum(t.r_multiple for t in losses) / len(losses) if losses else 0.0
    res.total_return_pct = (
        (final_equity - starting_equity) / starting_equity if starting_equity else 0.0
    )
    res.longs = sum(1 for t in trades if t.direction == "long")
    res.shorts = sum(1 for t in trades if t.direction == "short")
    return res


# --------------------------------------------------------------------------- #
# Simulation
# --------------------------------------------------------------------------- #
def _resolve(candles: List[Candle], f: int, entry: float, stop: float,
             target: float, long: bool, params: Params) -> Tuple[int, float, str]:
    """Walk forward from the fill bar; return (exit_index, exit_price, outcome).
    Conservative: same-bar stop-and-target counts as a stop."""
    end = min(len(candles) - 1, f + params.trade_max_bars)
    for b in range(f, end + 1):
        c = candles[b]
        if long:
            hit_stop, hit_tgt = c.low <= stop, c.high >= target
        else:
            hit_stop, hit_tgt = c.high >= stop, c.low <= target
        if hit_stop:
            return b, stop, "stop"
        if hit_tgt:
            return b, target, "target"
    return end, candles[end].close, "timeout"


def backtest(candles: List[Candle], setups: List[Setup], params: Params) -> BacktestResult:
    """Simulate a time-ordered list of setups with one position at a time."""
    n = len(candles)
    equity = params.starting_equity
    peak = equity
    max_dd = 0.0
    trades: List[Trade] = []
    curve: List[Tuple[int, float]] = [(0, equity)]
    busy_until = -1
    slip = params.slippage_bps / 10_000.0
    comm = params.commission_bps / 10_000.0

    for st in sorted(setups, key=lambda s: s.armed_at):
        if st.armed_at < busy_until:
            continue
        long = st.direction == "long"
        sign = 1 if long else -1

        # --- pending limit: find the first bar that fills it ---
        win_end = min(n - 1, st.armed_at + params.entry_valid_bars)
        fill: Optional[int] = None
        for b in range(st.armed_at + 1, win_end + 1):
            c = candles[b]
            if (long and c.low <= st.entry) or (not long and c.high >= st.entry):
                fill = b
                break
        if fill is None:
            continue  # order expired unfilled

        exit_idx, exit_px, outcome = _resolve(
            candles, fill, st.entry, st.stop, st.target, long, params
        )

        # --- apply adverse slippage and per-side commission ---
        entry_eff = st.entry * (1 + sign * slip)
        exit_eff = exit_px * (1 - sign * slip)
        risk_per_unit = abs(entry_eff - st.stop)
        if risk_per_unit <= 0:
            continue
        risk_cash = equity * params.risk_pct
        size = risk_cash / risk_per_unit
        gross = (exit_eff - entry_eff) * sign * size
        commission = (entry_eff + exit_eff) * size * comm
        pnl = gross - commission
        equity += pnl
        r_multiple = pnl / risk_cash if risk_cash else 0.0

        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)

        trades.append(Trade(
            direction=st.direction, setup=st, entry_index=fill, entry_price=entry_eff,
            exit_index=exit_idx, exit_price=exit_eff, outcome=outcome,
            r_multiple=r_multiple, pnl=pnl, equity_after=equity,
        ))
        curve.append((exit_idx, equity))
        busy_until = exit_idx + 1

    return _metrics_from_trades(trades, params.starting_equity, equity, curve, max_dd)


def run(candles: List[Candle], params: Params) -> BacktestResult:
    """Convenience: generate setups and backtest in one call."""
    setups, _ = generate_setups(candles, params)
    return backtest(candles, setups, params)


# --------------------------------------------------------------------------- #
# Out-of-sample validation
# --------------------------------------------------------------------------- #
def train_test(
    candles: List[Candle], params: Params, split: float = 0.7
) -> Tuple[BacktestResult, BacktestResult]:
    """Single chronological split. Setups are generated once; trades are bucketed
    into in-sample / out-of-sample by the bar the trade was armed on."""
    setups, _ = generate_setups(candles, params)
    cut = int(len(candles) * split)
    train = [s for s in setups if s.armed_at < cut]
    test = [s for s in setups if s.armed_at >= cut]
    return backtest(candles, train, params), backtest(candles, test, params)


def _grid_combos(grid: Dict[str, list]) -> List[Dict[str, object]]:
    if not grid:
        return [{}]
    keys = list(grid)
    return [dict(zip(keys, vals)) for vals in product(*(grid[k] for k in keys))]


def walk_forward(
    candles: List[Candle],
    base_params: Params,
    grid: Optional[Dict[str, list]] = None,
    n_folds: int = 4,
    min_train_trades: int = 5,
) -> Tuple[List[dict], BacktestResult]:
    """Rolling walk-forward. The series is cut into ``n_folds + 1`` equal
    segments; for fold ``k`` we optimize the parameter ``grid`` on segment ``k``
    (in-sample, by expectancy with a minimum trade count) and *evaluate the
    locked params on segment ``k+1``* (out-of-sample). OOS trades are aggregated
    into one result.

    This is the honest test: an edge that only exists in-sample evaporates here.
    Run it on random data and the aggregated OOS expectancy should sit around
    ``-costs``; a strongly positive number on random data means a bug or
    look-ahead leak, not alpha.
    """
    grid = grid or {}
    combos = _grid_combos(grid)
    n = len(candles)
    seg = n // (n_folds + 1)
    folds: List[dict] = []
    oos_trades: List[Trade] = []

    for k in range(n_folds):
        tr_lo, tr_hi = k * seg, (k + 1) * seg
        te_lo, te_hi = (k + 1) * seg, (k + 2) * seg if k + 2 <= n_folds + 1 else n

        best_combo: Dict[str, object] = combos[0]
        best_score = float("-inf")
        for combo in combos:
            p = replace(base_params, **combo)
            setups, _ = generate_setups(candles, p)
            tr = [s for s in setups if tr_lo <= s.armed_at < tr_hi]
            res = backtest(candles, tr, p)
            if res.num_trades >= min_train_trades and res.expectancy_r > best_score:
                best_score, best_combo = res.expectancy_r, combo

        p = replace(base_params, **best_combo)
        setups, _ = generate_setups(candles, p)
        te = [s for s in setups if te_lo <= s.armed_at < te_hi]
        oos = backtest(candles, te, p)
        oos_trades.extend(oos.trades)
        folds.append({
            "fold": k,
            "train_range": (tr_lo, tr_hi),
            "test_range": (te_lo, te_hi),
            "chosen": best_combo,
            "train_expectancy_r": best_score,
            "oos": oos,
        })

    # Aggregate OOS trades into a single result (R-multiple based; sizing-neutral).
    agg = _metrics_from_trades(
        oos_trades, base_params.starting_equity, base_params.starting_equity, [], 0.0
    )
    return folds, agg
