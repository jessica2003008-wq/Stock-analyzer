"""Step 4: Stability — Deterministic scoring."""
from __future__ import annotations
import logging
import numpy as np
from data.schemas import FinancialHistory, StabilityResult

logger = logging.getLogger(__name__)


def _cagr(first: float, last: float, years: int) -> float | None:
    """Compound annual growth rate."""
    if first <= 0 or last <= 0 or years <= 0:
        return None
    return (last / first) ** (1 / years) - 1


def _coefficient_of_variation(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    arr = np.array(values)
    mean = np.mean(arr)
    if mean == 0:
        return None
    return float(np.std(arr) / abs(mean))


def _r_squared(values: list[float]) -> float | None:
    """R² of a linear fit (measures trend reliability)."""
    if len(values) < 3:
        return None
    x = np.arange(len(values))
    y = np.array(values)
    # Linear regression
    coeffs = np.polyfit(x, y, 1)
    y_pred = np.polyval(coeffs, x)
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    if ss_tot == 0:
        return 1.0  # Perfectly flat = perfectly predictable
    return float(1 - ss_res / ss_tot)


def _score_metric(value: float | None, thresholds: list[tuple[float, int]], higher_is_better: bool = True) -> int:
    if value is None:
        return 0
    for threshold, score in thresholds:
        if higher_is_better:
            if value >= threshold:
                return score
        else:
            if value <= threshold:
                return score
    return thresholds[-1][1] if thresholds else 0


def analyze_stability(history: FinancialHistory) -> StabilityResult:
    """Compute earnings and revenue stability score."""
    stmts = history.statements
    if not stmts:
        return StabilityResult(
            score=0,
            evidence=["No financial statements available"],
            rationale="Cannot assess stability without financial statements.",
        )

    evidence = []
    revenues = [(s.fiscal_year, s.revenue) for s in stmts if s.revenue > 0]
    earnings = [(s.fiscal_year, s.net_income) for s in stmts]

    # ── Revenue CAGR ──
    rev_values = [r for _, r in revenues]
    recent_5_rev = rev_values[-5:] if len(rev_values) >= 5 else rev_values

    rev_cagr_5 = None
    if len(rev_values) >= 5:
        rev_cagr_5 = _cagr(rev_values[-5], rev_values[-1], 4)
        evidence.append(f"Revenue CAGR (5yr): {rev_cagr_5*100:.1f}%")

    rev_cagr_10 = None
    if len(rev_values) >= 10:
        rev_cagr_10 = _cagr(rev_values[-10], rev_values[-1], 9)
        evidence.append(f"Revenue CAGR (10yr): {rev_cagr_10*100:.1f}%")

    # ── Earnings CAGR ──
    earn_values = [e for _, e in earnings]
    positive_earnings = [e for e in earn_values if e > 0]

    earn_cagr_5 = None
    if len(earn_values) >= 5 and earn_values[-5] > 0 and earn_values[-1] > 0:
        earn_cagr_5 = _cagr(earn_values[-5], earn_values[-1], 4)
        evidence.append(f"Earnings CAGR (5yr): {earn_cagr_5*100:.1f}%")

    # ── Volatility (CoV) ──
    rev_vol = _coefficient_of_variation(recent_5_rev)
    if rev_vol is not None:
        evidence.append(f"Revenue CoV (5yr): {rev_vol:.3f}")

    earn_recent_5 = earn_values[-5:] if len(earn_values) >= 5 else earn_values
    earn_vol = _coefficient_of_variation(earn_recent_5)
    if earn_vol is not None:
        evidence.append(f"Earnings CoV (5yr): {earn_vol:.3f}")

    # ── Consecutive Profit Years ──
    consec = 0
    for s in reversed(stmts):
        if s.net_income > 0:
            consec += 1
        else:
            break
    evidence.append(f"Consecutive profit years: {consec}")

    # ── Dividend Consistency ──
    div_years = sum(1 for s in stmts if s.dividends_paid > 0)
    total_years = len(stmts)
    if div_years == total_years and total_years >= 5:
        div_consistency = "Consistent"
    elif div_years > 0:
        div_consistency = "Irregular"
    else:
        div_consistency = "None"
    evidence.append(f"Dividends: {div_consistency} ({div_years}/{total_years} years)")

    # ── R² of revenue trend ──
    r2 = _r_squared(rev_values) if len(rev_values) >= 3 else None
    if r2 is not None:
        evidence.append(f"Revenue trend R²: {r2:.3f}")

    # ── Scoring ──
    rev_cagr_score = _score_metric(
        rev_cagr_5, [(0.15, 100), (0.10, 85), (0.05, 70), (0.0, 50), (-1, 20)]
    )
    earn_cagr_score = _score_metric(
        earn_cagr_5, [(0.15, 100), (0.10, 85), (0.05, 70), (0.0, 50), (-1, 20)]
    )
    rev_vol_score = _score_metric(
        rev_vol, [(0.05, 100), (0.10, 80), (0.15, 60), (0.25, 40), (999, 20)],
        higher_is_better=False,
    )
    earn_vol_score = _score_metric(
        earn_vol, [(0.10, 100), (0.15, 80), (0.25, 60), (0.40, 40), (999, 20)],
        higher_is_better=False,
    )
    consec_score = _score_metric(
        consec, [(10, 100), (8, 85), (5, 65), (3, 40), (0, 15)]
    )
    r2_score = _score_metric(
        r2, [(0.95, 100), (0.85, 80), (0.70, 60), (0.50, 40), (0, 20)]
    )

    # Composite
    composite = (
        rev_cagr_score * 0.20 +
        earn_cagr_score * 0.20 +
        rev_vol_score * 0.20 +
        earn_vol_score * 0.20 +
        consec_score * 0.10 +
        r2_score * 0.10
    )

    rationale = (
        f"Stability composite: {composite:.0f}/100. "
        f"Revenue CAGR 5yr: {rev_cagr_5*100:.1f}% " if rev_cagr_5 else "Revenue CAGR 5yr: N/A "
    )
    rationale += (
        f"Earnings CAGR 5yr: {earn_cagr_5*100:.1f}%. " if earn_cagr_5 else "Earnings CAGR 5yr: N/A. "
    )
    rationale += f"{consec} consecutive profit years. Dividends: {div_consistency}."

    return StabilityResult(
        score=int(round(composite)),
        revenue_cagr_5yr=round(rev_cagr_5 * 100, 2) if rev_cagr_5 else None,
        revenue_cagr_10yr=round(rev_cagr_10 * 100, 2) if rev_cagr_10 else None,
        earnings_cagr_5yr=round(earn_cagr_5 * 100, 2) if earn_cagr_5 else None,
        revenue_volatility=round(rev_vol, 4) if rev_vol else None,
        earnings_volatility=round(earn_vol, 4) if earn_vol else None,
        consecutive_profit_years=consec,
        dividend_consistency=div_consistency,
        regression_r_squared=round(r2, 4) if r2 else None,
        evidence=evidence,
        rationale=rationale,
    )
