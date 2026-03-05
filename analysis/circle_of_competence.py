"""Step 1: Circle of Competence — LLM-powered analysis."""
from __future__ import annotations
import json
import logging
from data.schemas import (
    CompanyProfile, FinancialHistory, FilingText, CompetenceResult,
)
from llm.claude_client import ClaudeClient, LLMError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a Buffett-style investment analyst assessing whether a company falls within a
typical investor's circle of competence. You must evaluate:

1. How simple and understandable the business model is
2. How predictable the revenue streams are
3. Whether the company has clear, explainable competitive dynamics

Score on a 0-100 scale:
- 80-100: Highly understandable (simple model, ≤3 segments, predictable demand)
- 60-79: Reasonably understandable (moderate complexity, ≤5 segments)
- 40-59: Somewhat complex (multi-segment, some opaque drivers)
- 20-39: Complex (conglomerate, financial engineering)
- 0-19: Opaque (cannot clearly explain how it makes money)

Respond with ONLY valid JSON (no markdown, no code blocks) in this exact format:
{
  "score": <int 0-100>,
  "business_model_summary": "<2-3 sentence plain English>",
  "revenue_segments": [{"segment": "<name>", "pct_revenue": <float>}],
  "predictability": "High|Medium|Low",
  "complexity_flags": ["<flag1>", ...],
  "evidence": ["<data point or filing excerpt backing the score>", ...],
  "rationale": "<paragraph explaining score>"
}"""


def analyze_circle_of_competence(
    history: FinancialHistory,
    filing: FilingText | None = None,
    llm: ClaudeClient | None = None,
) -> CompetenceResult:
    """Assess business understandability."""
    profile = history.profile
    latest = history.statements[-1] if history.statements else None

    # Build context for LLM
    context_parts = [
        f"Company: {profile.name} ({profile.ticker})",
        f"Sector: {profile.sector} | Industry: {profile.industry}",
        f"Description: {profile.description[:2000]}",
    ]

    if latest:
        context_parts.append(
            f"Latest financials ({latest.fiscal_year}): "
            f"Revenue ${latest.revenue:,.0f}, "
            f"Net Income ${latest.net_income:,.0f}, "
            f"Gross Margin {latest.gross_profit/latest.revenue*100:.1f}%" if latest.revenue > 0 else ""
        )

    if filing and filing.sections:
        if "business" in filing.sections:
            context_parts.append(f"10-K Business section (excerpt): {filing.sections['business'][:3000]}")

    user_prompt = "\n\n".join(context_parts)

    if llm is None:
        # Fallback: deterministic-only scoring
        return _deterministic_fallback(profile, history)

    try:
        result = llm.analyze(SYSTEM_PROMPT, user_prompt)
        return CompetenceResult(**result)
    except (LLMError, Exception) as e:
        logger.warning(f"LLM analysis failed for circle of competence: {e}")
        return _deterministic_fallback(profile, history)


def _deterministic_fallback(profile: CompanyProfile, history: FinancialHistory) -> CompetenceResult:
    """Fallback scoring when LLM is unavailable."""
    # Simple heuristic based on industry
    simple_industries = {
        "Consumer Defensive", "Beverages", "Household Products",
        "Retail", "Insurance", "Banking", "Restaurants",
    }
    complex_industries = {
        "Biotechnology", "Semiconductors Equipment", "Financial Services",
        "Capital Markets", "Insurance—Specialty",
    }

    if profile.industry in simple_industries:
        score = 75
        predictability = "High"
    elif profile.industry in complex_industries:
        score = 45
        predictability = "Low"
    else:
        score = 60
        predictability = "Medium"

    return CompetenceResult(
        score=score,
        business_model_summary=f"{profile.name} operates in {profile.industry}. "
                               f"LLM analysis unavailable — using heuristic scoring.",
        revenue_segments=[],
        predictability=predictability,
        complexity_flags=["LLM analysis unavailable — heuristic scoring applied"],
        evidence=[f"Industry: {profile.industry}", f"Sector: {profile.sector}"],
        rationale=f"Heuristic score based on industry classification ({profile.industry}). "
                  f"Full LLM analysis was unavailable.",
    )
