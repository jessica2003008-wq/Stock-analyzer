"""Final Recommendation — Composite scoring + action."""
from __future__ import annotations
from data.schemas import (
    CompetenceResult, MoatResult, FinancialQualityResult,
    StabilityResult, ValuationResult, MarginOfSafetyResult,
    RecommendationResult,
)
import config


def generate_recommendation(
    competence: CompetenceResult,
    moat: MoatResult,
    financial_quality: FinancialQualityResult,
    stability: StabilityResult,
    valuation: ValuationResult,
    margin_of_safety: MarginOfSafetyResult,
) -> RecommendationResult:
    """Generate final Buy/Watch/Avoid recommendation."""
    weights = config.WEIGHTS

    score_breakdown = {
        "circle_of_competence": competence.score,
        "moat_proxy": moat.score,
        "financial_quality": financial_quality.score,
        "stability": stability.score,
        "margin_of_safety": margin_of_safety.score,
    }

    composite = (
        competence.score * weights["circle_of_competence"] +
        moat.score * weights["moat_proxy"] +
        financial_quality.score * weights["financial_quality"] +
        stability.score * weights["stability"] +
        margin_of_safety.score * weights["margin_of_safety"]
    )

    # Action + position size
    if composite >= 80:
        action, position_size = "Buy", "Full"
    elif composite >= 70:
        action, position_size = "Buy", "Half"
    elif composite >= 60:
        action, position_size = "Buy", "Starter"
    elif composite >= 50:
        action, position_size = "Watch", "None"
    else:
        action, position_size = "Avoid", "None"

    # Bull case
    bull_points = []
    if moat.moat_type == "Wide":
        bull_points.append(f"Wide economic moat ({moat.score}/100)")
    if margin_of_safety.margin_of_safety_pct > 20:
        bull_points.append(f"{margin_of_safety.margin_of_safety_pct:.0f}% margin of safety")
    if stability.revenue_cagr_5yr and stability.revenue_cagr_5yr > 10:
        bull_points.append(f"Strong revenue growth ({stability.revenue_cagr_5yr:.1f}% CAGR)")
    if financial_quality.score >= 80:
        bull_points.append(f"Excellent financial quality ({financial_quality.score}/100)")
    if not bull_points:
        bull_points.append(f"Composite score of {composite:.0f}/100")
    bull_case = ". ".join(bull_points) + "."

    # Bear case
    bear_points = []
    if margin_of_safety.bear_downside_pct > 25:
        bear_points.append(f"Significant bear-case downside ({margin_of_safety.bear_downside_pct:.0f}%)")
    if financial_quality.flags:
        bear_points.append(f"Financial flags: {', '.join(financial_quality.flags[:3])}")
    if moat.durability_assessment == "Eroding":
        bear_points.append("Eroding competitive moat")
    if margin_of_safety.verdict == "Overvalued":
        bear_points.append(f"Currently overvalued (MoS: {margin_of_safety.margin_of_safety_pct:.0f}%)")
    if not bear_points:
        bear_points.append("No major red flags identified")
    bear_case = ". ".join(bear_points) + "."

    # Monitoring metrics
    monitoring = []
    latest_metrics = financial_quality.metrics
    if latest_metrics.get("gross_margin_avg"):
        threshold = latest_metrics["gross_margin_avg"] * 0.9
        monitoring.append(f"Gross margin drops below {threshold:.1f}%")
    if latest_metrics.get("debt_to_equity_current"):
        monitoring.append(f"D/E ratio exceeds {latest_metrics['debt_to_equity_current'] * 1.5:.1f}")
    if latest_metrics.get("roe_avg_5yr"):
        monitoring.append(f"ROE falls below {latest_metrics['roe_avg_5yr'] * 0.7:.1f}%")
    monitoring.append("Moat shows signs of erosion (margin compression >5% YoY)")
    monitoring.append("Management changes or strategic pivots")

    evidence = [
        f"Composite score: {composite:.1f}/100",
        f"Weights: {weights}",
    ]
    for k, v in score_breakdown.items():
        evidence.append(f"{k}: {v}/100 × {weights.get(k, 0):.0%} = {v * weights.get(k, 0):.1f}")

    rationale = (
        f"Composite score {composite:.0f}/100 → {action} ({position_size} position). "
        f"Bull: {bull_case} Bear: {bear_case}"
    )

    return RecommendationResult(
        action=action,
        position_size=position_size,
        composite_score=round(composite, 2),
        score_breakdown=score_breakdown,
        bull_case=bull_case,
        bear_case=bear_case,
        monitoring_metrics=monitoring,
        evidence=evidence,
        rationale=rationale,
    )
