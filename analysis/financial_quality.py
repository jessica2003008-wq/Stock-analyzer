"""Step 3: Financial Quality — Deterministic scoring."""
from __future__ import annotations
import logging
from data.schemas import FinancialHistory, FinancialQualityResult

logger = logging.getLogger(__name__)


def _safe_div(a: float, b: float) -> float | None:
    if b == 0 or b is None:
        return None
    return a / b


def _score_metric(value: float | None, thresholds: list[tuple[float, int]], higher_is_better: bool = True) -> int:
    """Score a metric against thresholds. Returns 0-100."""
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


def _coefficient_of_variation(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    import numpy as np
    arr = np.array(values)
    mean = np.mean(arr)
    if mean == 0:
        return None
    return float(np.std(arr) / abs(mean))


def analyze_financial_quality(history: FinancialHistory) -> FinancialQualityResult:
    """Compute financial quality score from historical financials."""
    stmts = history.statements
    if not stmts:
        return FinancialQualityResult(
            score=0,
            flags=["No financial statements available"],
            evidence=["No data"],
            rationale="Cannot assess financial quality without financial statements.",
        )

    recent_5 = stmts[-5:] if len(stmts) >= 5 else stmts
    metrics = {}
    evidence = []
    flags = []

    # ── ROE (5yr avg) ──
    roes = []
    for s in recent_5:
        roe = _safe_div(s.net_income, s.total_equity)
        if roe is not None:
            roes.append(roe)
            evidence.append(f"ROE {s.fiscal_year}: {roe*100:.1f}% (net_income={s.net_income:,.0f} / equity={s.total_equity:,.0f})")
    roe_avg = sum(roes) / len(roes) if roes else None
    metrics["roe_avg_5yr"] = round(roe_avg * 100, 2) if roe_avg else None
    metrics["roe_values"] = {s.fiscal_year: round(r * 100, 2) for s, r in zip(recent_5, roes)}
    roe_score = _score_metric(roe_avg, [(0.20, 100), (0.15, 80), (0.10, 60), (0.05, 40), (0, 20)])

    if roe_avg is not None and roe_avg < 0.10:
        flags.append("Low ROE (<10%)")
    if len(roes) >= 2 and roes[-1] < roes[0]:
        flags.append("Declining ROE trend")
        metrics["roe_trend"] = "declining"
    else:
        metrics["roe_trend"] = "stable/improving"

    # ── ROIC (5yr avg) ──
    roics = []
    for s in recent_5:
        invested_capital = s.total_equity + s.total_debt - s.cash_and_equivalents
        if invested_capital > 0:
            roic = s.operating_income * (1 - 0.21) / invested_capital  # After tax
            roics.append(roic)
            evidence.append(f"ROIC {s.fiscal_year}: {roic*100:.1f}%")
    roic_avg = sum(roics) / len(roics) if roics else None
    metrics["roic_avg_5yr"] = round(roic_avg * 100, 2) if roic_avg else None
    roic_score = _score_metric(roic_avg, [(0.15, 100), (0.12, 80), (0.08, 60), (0.05, 40), (0, 20)])

    # ── Debt-to-Equity ──
    latest = stmts[-1]
    de = _safe_div(latest.total_debt, latest.total_equity)
    metrics["debt_to_equity_current"] = round(de, 2) if de is not None else None
    evidence.append(f"D/E {latest.fiscal_year}: {de:.2f}" if de is not None else "D/E: N/A (zero equity)")
    de_score = _score_metric(de, [(0.3, 100), (0.5, 85), (1.0, 65), (2.0, 40), (999, 15)], higher_is_better=False)

    if de is not None and de > 1.5:
        flags.append(f"High debt load (D/E={de:.2f})")

    # D/E trend
    des = []
    for s in recent_5:
        d = _safe_div(s.total_debt, s.total_equity)
        if d is not None:
            des.append(d)
    if len(des) >= 2:
        metrics["debt_to_equity_trend"] = "increasing" if des[-1] > des[0] else "decreasing"
    else:
        metrics["debt_to_equity_trend"] = "unknown"

    # ── Interest Coverage ──
    interest_expense = latest.operating_income - latest.net_income  # rough proxy
    if interest_expense > 0:
        ic = latest.operating_income / interest_expense
    else:
        ic = 100.0  # No interest expense = great coverage
    metrics["interest_coverage"] = round(ic, 1)
    evidence.append(f"Interest coverage {latest.fiscal_year}: {ic:.1f}x")
    ic_score = _score_metric(ic, [(15, 100), (8, 80), (4, 60), (2, 40), (0, 15)])

    if ic < 4:
        flags.append(f"Low interest coverage ({ic:.1f}x)")

    # ── FCF / Net Income (earnings quality) ──
    fcf_ratios = []
    for s in recent_5:
        r = _safe_div(s.free_cash_flow, s.net_income)
        if r is not None and s.net_income > 0:
            fcf_ratios.append(r)
            evidence.append(f"FCF/NI {s.fiscal_year}: {r:.2f}")
    fcf_avg = sum(fcf_ratios) / len(fcf_ratios) if fcf_ratios else None
    metrics["fcf_to_net_income_avg"] = round(fcf_avg, 2) if fcf_avg else None
    fcf_score = _score_metric(fcf_avg, [(1.0, 100), (0.8, 80), (0.6, 60), (0.4, 40), (0, 20)])

    # ── Gross Margin Stability ──
    gross_margins = []
    for s in recent_5:
        gm = _safe_div(s.gross_profit, s.revenue)
        if gm is not None:
            gross_margins.append(gm)
            evidence.append(f"Gross margin {s.fiscal_year}: {gm*100:.1f}%")
    metrics["gross_margin_avg"] = round(sum(gross_margins) / len(gross_margins) * 100, 2) if gross_margins else None
    gm_cov = _coefficient_of_variation(gross_margins)
    metrics["gross_margin_stability_cov"] = round(gm_cov, 4) if gm_cov is not None else None
    gm_score = _score_metric(gm_cov, [(0.05, 100), (0.10, 75), (0.20, 50), (999, 25)], higher_is_better=False) if gm_cov else 50

    # ── Operating Margin ──
    op_margins = []
    for s in recent_5:
        om = _safe_div(s.operating_income, s.revenue)
        if om is not None:
            op_margins.append(om)
    metrics["operating_margin_avg"] = round(sum(op_margins) / len(op_margins) * 100, 2) if op_margins else None

    # ── CapEx to Revenue ──
    capex_ratios = []
    for s in recent_5:
        cr = _safe_div(s.capital_expenditure, s.revenue)
        if cr is not None:
            capex_ratios.append(cr)
    metrics["capex_to_revenue_avg"] = round(sum(capex_ratios) / len(capex_ratios) * 100, 2) if capex_ratios else None

    # ── Current Ratio ──
    current_assets = latest.cash_and_equivalents + (latest.total_assets - latest.total_liabilities)  # rough
    # Better: use total_assets - long_term assets, but we approximate
    cr = _safe_div(latest.total_assets - latest.long_term_debt, latest.total_liabilities) if latest.total_liabilities else None
    # Simplified: use equity + liabilities / liabilities as proxy
    cr = _safe_div(latest.cash_and_equivalents, latest.total_liabilities - latest.long_term_debt) if (latest.total_liabilities - latest.long_term_debt) > 0 else 2.0
    metrics["current_ratio_proxy"] = round(cr, 2) if cr else None
    cr_score = _score_metric(cr, [(2.0, 100), (1.5, 80), (1.0, 60), (0.7, 40), (0, 15)])

    # Negative equity flag
    if latest.total_equity <= 0:
        flags.append("Negative stockholders' equity — potential financial distress")
        de_score = 0

    # ── Composite Score ──
    weights = {
        "roe": (roe_score, 0.20),
        "roic": (roic_score, 0.20),
        "debt_to_equity": (de_score, 0.15),
        "interest_coverage": (ic_score, 0.10),
        "fcf_quality": (fcf_score, 0.15),
        "gross_margin_stability": (gm_score, 0.10),
        "current_ratio": (cr_score, 0.10),
    }

    composite = sum(score * weight for score, weight in weights.values())
    metrics["sub_scores"] = {k: v[0] for k, v in weights.items()}

    rationale_parts = [f"Financial quality composite: {composite:.0f}/100."]
    if flags:
        rationale_parts.append(f"Flags: {', '.join(flags)}.")
    rationale_parts.append(
        f"Key metrics — ROE avg: {metrics.get('roe_avg_5yr', 'N/A')}%, "
        f"ROIC avg: {metrics.get('roic_avg_5yr', 'N/A')}%, "
        f"D/E: {metrics.get('debt_to_equity_current', 'N/A')}, "
        f"FCF/NI: {metrics.get('fcf_to_net_income_avg', 'N/A')}."
    )

    return FinancialQualityResult(
        score=int(round(composite)),
        metrics=metrics,
        flags=flags,
        evidence=evidence,
        rationale=" ".join(rationale_parts),
    )
