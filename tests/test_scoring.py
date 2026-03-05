"""Unit tests for scoring and recommendation."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from data.schemas import (
    CompetenceResult, MoatResult, FinancialQualityResult,
    StabilityResult, ValuationResult, MarginOfSafetyResult,
    ScenarioValuation,
)
from analysis.recommendation import generate_recommendation
from analysis.margin_of_safety import analyze_margin_of_safety


class TestMarginOfSafety:
    def test_undervalued(self):
        v = ValuationResult(
            bull=ScenarioValuation(per_share_value=200),
            base=ScenarioValuation(per_share_value=150),
            bear=ScenarioValuation(per_share_value=80),
            current_price=100,
        )
        result = analyze_margin_of_safety(v)
        assert result.margin_of_safety_pct > 0
        assert result.verdict == "Undervalued"

    def test_overvalued(self):
        v = ValuationResult(
            bull=ScenarioValuation(per_share_value=120),
            base=ScenarioValuation(per_share_value=80),
            bear=ScenarioValuation(per_share_value=50),
            current_price=100,
        )
        result = analyze_margin_of_safety(v)
        assert result.margin_of_safety_pct < 0
        assert result.verdict in ("Fairly Valued", "Overvalued")

    def test_zero_price(self):
        v = ValuationResult(
            bull=ScenarioValuation(per_share_value=100),
            base=ScenarioValuation(per_share_value=80),
            bear=ScenarioValuation(per_share_value=50),
            current_price=0,
        )
        result = analyze_margin_of_safety(v)
        assert result.score == 0

    def test_score_range(self):
        v = ValuationResult(
            bull=ScenarioValuation(per_share_value=200),
            base=ScenarioValuation(per_share_value=150),
            bear=ScenarioValuation(per_share_value=80),
            current_price=100,
        )
        result = analyze_margin_of_safety(v)
        assert 0 <= result.score <= 100


class TestRecommendation:
    def _make_inputs(self, comp=80, moat=85, fq=75, stab=70, mos_score=90, mos_pct=35):
        return (
            CompetenceResult(score=comp),
            MoatResult(score=moat, moat_type="Wide"),
            FinancialQualityResult(score=fq, metrics={"roe_avg_5yr": 20, "debt_to_equity_current": 0.5, "gross_margin_avg": 40}),
            StabilityResult(score=stab, revenue_cagr_5yr=12),
            ValuationResult(),
            MarginOfSafetyResult(score=mos_score, margin_of_safety_pct=mos_pct, bear_downside_pct=15),
        )

    def test_buy_full(self):
        inputs = self._make_inputs(comp=85, moat=90, fq=85, stab=80, mos_score=95)
        result = generate_recommendation(*inputs)
        assert result.action == "Buy"
        assert result.position_size == "Full"
        assert result.composite_score >= 80

    def test_watch(self):
        inputs = self._make_inputs(comp=50, moat=55, fq=50, stab=50, mos_score=50)
        result = generate_recommendation(*inputs)
        assert result.action in ("Watch", "Avoid")

    def test_avoid(self):
        inputs = self._make_inputs(comp=20, moat=25, fq=30, stab=25, mos_score=10)
        result = generate_recommendation(*inputs)
        assert result.action == "Avoid"
        assert result.position_size == "None"

    def test_composite_score_weighted(self):
        inputs = self._make_inputs()
        result = generate_recommendation(*inputs)
        # Verify composite matches weighted sum
        expected = (
            80 * 0.10 +   # competence
            85 * 0.25 +   # moat
            75 * 0.20 +   # fq
            70 * 0.15 +   # stability
            90 * 0.30     # mos
        )
        assert abs(result.composite_score - expected) < 0.1

    def test_score_breakdown_populated(self):
        inputs = self._make_inputs()
        result = generate_recommendation(*inputs)
        assert "circle_of_competence" in result.score_breakdown
        assert "moat_proxy" in result.score_breakdown
        assert "financial_quality" in result.score_breakdown

    def test_monitoring_metrics_populated(self):
        inputs = self._make_inputs()
        result = generate_recommendation(*inputs)
        assert len(result.monitoring_metrics) > 0

    def test_bull_bear_cases_populated(self):
        inputs = self._make_inputs()
        result = generate_recommendation(*inputs)
        assert len(result.bull_case) > 0
        assert len(result.bear_case) > 0
