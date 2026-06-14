"""Performance reporting and benchmarking.

The bar for this whole project is *beat a passive benchmark* (buy & hold), not
"get rich". This module reconstructs the equity curve from the trade log,
compares it against buy & hold over the same window, and produces a weekly-review
text with an honest self-grade — including refusing to grade on a sample too
small to mean anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence

from .types import Candle


@dataclass
class PerformanceReport:
    starting_equity: float
    final_equity: float
    total_return: float          # strategy, fraction
    buy_hold_return: float       # benchmark, fraction
    alpha: float                 # total_return - buy_hold_return
    num_trades: int
    win_rate: float
    profit_factor: float
    expectancy_r: float
    avg_win_r: float
    avg_loss_r: float
    max_drawdown: float
    sharpe_per_trade: float
    grade: str

    def summary(self) -> str:
        pf = "inf" if self.profit_factor == float("inf") else f"{self.profit_factor:.2f}"
        return (
            f"return={self.total_return * 100:+.1f}%  "
            f"buy&hold={self.buy_hold_return * 100:+.1f}%  "
            f"alpha={self.alpha * 100:+.1f}%  "
            f"trades={self.num_trades} win%={self.win_rate * 100:.0f} PF={pf} "
            f"E={self.expectancy_r:+.2f}R maxDD={self.max_drawdown * 100:.1f}%  "
            f"grade={self.grade}"
        )


def buy_and_hold_return(candles: Sequence[Candle], start: int = 0, end: int = -1) -> float:
    if not candles:
        return 0.0
    a = candles[start].close
    b = candles[end].close
    return (b - a) / a if a else 0.0


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: Sequence[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def _grade(num_trades: int, alpha: float, profit_factor: float, expectancy_r: float) -> str:
    if num_trades < 30:
        return "I (insufficient sample; need >=30 trades)"
    if alpha <= 0 or profit_factor <= 1.0 or expectancy_r <= 0:
        return "F (no edge vs benchmark)"
    if profit_factor >= 1.5 and expectancy_r >= 0.2 and alpha > 0:
        return "B (positive, validate further)"
    return "C (marginal; likely noise)"


def summarize(
    trades: List[dict],
    starting_equity: float,
    candles: Sequence[Candle],
    bh_start: int = 0,
    bh_end: int = -1,
) -> PerformanceReport:
    """Build a report from the JSONL trade log (dicts with ``pnl`` and
    ``r_multiple``). Equity is reconstructed as starting + cumulative pnl."""
    equity = starting_equity
    peak = starting_equity
    max_dd = 0.0
    rs: List[float] = []
    gross_profit = 0.0
    gross_loss = 0.0
    wins = 0
    for t in trades:
        pnl = float(t["pnl"])
        r = float(t["r_multiple"])
        rs.append(r)
        equity += pnl
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
        if pnl > 0:
            gross_profit += pnl
            wins += 1
        else:
            gross_loss += abs(pnl)

    n = len(trades)
    win_rate = wins / n if n else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    expectancy = _mean(rs)
    avg_win = _mean([r for r in rs if r > 0])
    avg_loss = _mean([r for r in rs if r <= 0])
    sd = _std(rs)
    sharpe = (expectancy / sd * (n ** 0.5)) if sd > 0 else 0.0

    total_return = (equity - starting_equity) / starting_equity if starting_equity else 0.0
    bh = buy_and_hold_return(candles, bh_start, bh_end)
    alpha = total_return - bh

    return PerformanceReport(
        starting_equity=starting_equity,
        final_equity=equity,
        total_return=total_return,
        buy_hold_return=bh,
        alpha=alpha,
        num_trades=n,
        win_rate=win_rate,
        profit_factor=pf,
        expectancy_r=expectancy,
        avg_win_r=avg_win,
        avg_loss_r=avg_loss,
        max_drawdown=max_dd,
        sharpe_per_trade=sharpe,
        grade=_grade(n, alpha, pf, expectancy),
    )


def weekly_review_text(report: PerformanceReport, period_label: str = "this week") -> str:
    """A markdown self-review, in the spirit of the knowledge-base agent that
    graded itself a C. Honest about benchmark and sample size."""
    pf = "inf" if report.profit_factor == float("inf") else f"{report.profit_factor:.2f}"
    beat = "BEAT" if report.alpha > 0 else "LAGGED"
    lines = [
        f"# Weekly review — {period_label}",
        "",
        f"- Equity: {report.starting_equity:,.2f} -> {report.final_equity:,.2f} "
        f"({report.total_return * 100:+.2f}%)",
        f"- Benchmark (buy & hold): {report.buy_hold_return * 100:+.2f}%",
        f"- **Alpha: {report.alpha * 100:+.2f}% — {beat} the benchmark**",
        f"- Trades: {report.num_trades} | win rate {report.win_rate * 100:.0f}% "
        f"| profit factor {pf} | expectancy {report.expectancy_r:+.2f}R",
        f"- Avg win {report.avg_win_r:+.2f}R / avg loss {report.avg_loss_r:+.2f}R "
        f"| max drawdown {report.max_drawdown * 100:.1f}%",
        f"- Per-trade Sharpe (rough): {report.sharpe_per_trade:+.2f}",
        "",
        f"**Self-grade: {report.grade}**",
        "",
    ]
    if report.num_trades < 30:
        lines.append(
            "> Caveat: sample is too small to conclude anything. Do not change "
            "strategy or sizing off this; keep paper-trading and accumulate trades."
        )
    elif report.alpha <= 0:
        lines.append(
            "> Not beating a passive benchmark. The honest move is to keep this on "
            "paper and not deploy capital until alpha is consistently positive."
        )
    elif report.expectancy_r <= 0 or report.profit_factor <= 1.0:
        lines.append(
            "> 'Beating the benchmark' here is misleading: per-trade expectancy is "
            "not positive, so the apparent alpha is just low exposure during a "
            "falling market, not a real edge. Graded on expectancy, not luck."
        )
    return "\n".join(lines)
