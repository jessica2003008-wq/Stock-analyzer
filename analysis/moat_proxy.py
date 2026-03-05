"""Step 2: Moat Proxy — LLM + deterministic analysis."""
from __future__ import annotations
import logging
from data.schemas import (
    CompanyProfile, FinancialHistory, FilingText, MoatResult, MoatSource,
)
from llm.claude_client import ClaudeClient, LLMError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Buffett-style investment analyst assessing a company's economic moat.
Evaluate these five moat sources independently (each 0-100):

1. Brand / Pricing Power (25% weight): Gross margin level + trend, brand strength
2. Switching Costs (25% weight): Customer lock-in, contracts, integration
3. Network Effects (20% weight): User growth correlation, platform dynamics
4. Cost Advantages (15% weight): Operating margin vs peers, scale
5. Intangible Assets (15% weight): Patents, licenses, regulatory barriers

Moat classification:
- Wide: weighted score >= 75
- Narrow: weighted score 50-74
- None: weighted score < 50

Durability: Based on 5-year margin trends — Expanding = Strengthening, flat = Durable, contracting = Eroding

Respond with ONLY valid JSON (no markdown, no code blocks):
{
  "score": <int 0-100>,
  "moat_type": "Wide|Narrow|None",
  "moat_sources": [
    {"source": "brand", "strength": <0-100>, "evidence": "<text>"},
    {"source": "switching_costs", "strength": <0-100>, "evidence": "<text>"},
    {"source": "network_effects", "strength": <0-100>, "evidence": "<text>"},
    {"source": "cost_advantages", "strength": <0-100>, "evidence": "<text>"},
    {"source": "intangible_assets", "strength": <0-100>, "evidence": "<text>"}
  ],
  "durability_assessment": "Durable|Eroding|Strengthening",
  "margin_trend": {"gross_margin_5yr_trend": "<direction>", "operating_margin_5yr_trend": "<direction>"},
  "evidence": ["<evidence1>", ...],
  "rationale": "<paragraph>"
}"""


def _compute_margin_trends(history: FinancialHistory) -> dict:
    """Deterministic margin trend calculation."""
    stmts = history.statements
    if len(stmts) < 2:
        return {"gross_margin_5yr_trend": "unknown", "operating_margin_5yr_trend": "unknown"}

    recent_5 = stmts[-5:] if len(stmts) >= 5 else stmts

    gm_first = recent_5[0].gross_profit / recent_5[0].revenue if recent_5[0].revenue > 0 else 0
    gm_last = recent_5[-1].gross_profit / recent_5[-1].revenue if recent_5[-1].revenue > 0 else 0
    om_first = recent_5[0].operating_income / recent_5[0].revenue if recent_5[0].revenue > 0 else 0
    om_last = recent_5[-1].operating_income / recent_5[-1].revenue if recent_5[-1].revenue > 0 else 0

    def trend(first, last):
        diff = last - first
        if abs(diff) < 0.02:
            return "stable"
        return "expanding" if diff > 0 else "contracting"

    return {
        "gross_margin_5yr_trend": trend(gm_first, gm_last),
        "operating_margin_5yr_trend": trend(om_first, om_last),
        "gross_margin_first": round(gm_first * 100, 1),
        "gross_margin_last": round(gm_last * 100, 1),
        "operating_margin_first": round(om_first * 100, 1),
        "operating_margin_last": round(om_last * 100, 1),
    }


def analyze_moat(
    history: FinancialHistory,
    filing: FilingText | None = None,
    llm: ClaudeClient | None = None,
) -> MoatResult:
    """Assess economic moat strength."""
    profile = history.profile
    margin_trends = _compute_margin_trends(history)
    latest = history.statements[-1] if history.statements else None

    context_parts = [
        f"Company: {profile.name} ({profile.ticker})",
        f"Sector: {profile.sector} | Industry: {profile.industry}",
        f"Description: {profile.description[:2000]}",
    ]

    if latest and latest.revenue > 0:
        context_parts.append(
            f"Latest financials ({latest.fiscal_year}): "
            f"Revenue ${latest.revenue:,.0f}, "
            f"Gross Margin {latest.gross_profit/latest.revenue*100:.1f}%, "
            f"Operating Margin {latest.operating_income/latest.revenue*100:.1f}%, "
            f"R&D ${latest.research_and_development:,.0f}" if latest.research_and_development else ""
        )

    context_parts.append(f"Margin trends: {margin_trends}")

    if filing and filing.sections:
        if "business" in filing.sections:
            context_parts.append(f"10-K Business (excerpt): {filing.sections['business'][:2000]}")
        if "risk_factors" in filing.sections:
            context_parts.append(f"10-K Risk Factors (excerpt): {filing.sections['risk_factors'][:2000]}")

    user_prompt = "\n\n".join(filter(None, context_parts))

    if llm is None:
        return _deterministic_fallback(profile, history, margin_trends)

    try:
        result = llm.analyze(SYSTEM_PROMPT, user_prompt)

        # Parse moat sources
        sources = []
        for s in result.get("moat_sources", []):
            sources.append(MoatSource(
                source=s.get("source", ""),
                strength=s.get("strength", 0),
                evidence=s.get("evidence", ""),
            ))

        return MoatResult(
            score=result.get("score", 0),
            moat_type=result.get("moat_type", "None"),
            moat_sources=sources,
            durability_assessment=result.get("durability_assessment", "Durable"),
            margin_trend=margin_trends,
            evidence=result.get("evidence", []),
            rationale=result.get("rationale", ""),
        )
    except (LLMError, Exception) as e:
        logger.warning(f"LLM analysis failed for moat: {e}")
        return _deterministic_fallback(profile, history, margin_trends)


def _deterministic_fallback(
    profile: CompanyProfile,
    history: FinancialHistory,
    margin_trends: dict,
) -> MoatResult:
    """Fallback using margin levels as moat proxy."""
    stmts = history.statements
    if not stmts:
        return MoatResult(evidence=["No data"], rationale="No data available for moat assessment.")

    recent = stmts[-5:] if len(stmts) >= 5 else stmts
    avg_gm = sum(
        s.gross_profit / s.revenue for s in recent if s.revenue > 0
    ) / len(recent) * 100 if recent else 0

    # High gross margins suggest moat
    if avg_gm >= 60:
        score, moat_type = 80, "Wide"
    elif avg_gm >= 40:
        score, moat_type = 60, "Narrow"
    elif avg_gm >= 25:
        score, moat_type = 45, "Narrow"
    else:
        score, moat_type = 30, "None"

    gm_trend = margin_trends.get("gross_margin_5yr_trend", "unknown")
    if gm_trend == "expanding":
        durability = "Strengthening"
    elif gm_trend == "contracting":
        durability = "Eroding"
        score = max(score - 10, 0)
    else:
        durability = "Durable"

    return MoatResult(
        score=score,
        moat_type=moat_type,
        moat_sources=[],
        durability_assessment=durability,
        margin_trend=margin_trends,
        evidence=[
            f"Avg gross margin (5yr): {avg_gm:.1f}%",
            f"Margin trend: {gm_trend}",
            "LLM unavailable — heuristic scoring based on margin levels",
        ],
        rationale=f"Heuristic moat assessment based on {avg_gm:.1f}% average gross margin. "
                  f"Margins {gm_trend}. Full LLM analysis was unavailable.",
    )
