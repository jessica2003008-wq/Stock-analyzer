"""Unit tests for ranking module."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from data.schemas import (
    CompanyReport, CompetenceResult, MoatResult, FinancialQualityResult,
    StabilityResult, ValuationResult, MarginOfSafetyResult,
    RecommendationResult, ScenarioValuation,
)
from industry.ranking import apply_hard_filters, check_bear_risk, rank_companies


def _make_report(
    ticker="TEST", moat=80, fq=80, stab=70,
    price=100, base_iv=150, bear_iv=90,
    composite=75,
):
    """Create a minimal CompanyReport for ranking tests."""
    mos_pct = (base_iv - price) / base_iv * 100
    bear_down = (price - bear_iv) / price * 100

    return CompanyReport(
        ticker=ticker,
        name=f"{ticker} Corp",
        competence=CompetenceResult(score=70),
        moat=MoatResult(score=moat),
        financial_quality=FinancialQualityResult(score=fq),
        stability=StabilityResult(score=stab),
        valuation=ValuationResult(current_price=price),
        margin_of_safety=MarginOfSafetyResult(
            score=75,
            current_price=price,
            base_intrinsic_value=base_iv,
            bull_intrinsic_value=base_iv * 1.5,
            bear_intrinsic_value=bear_iv,
            margin_of_safety_pct=mos_pct,
            bull_upside_pct=50,
            bear_downside_pct=bear_down,
        ),
        recommendation=RecommendationResult(
            action="Buy",
            composite_score=composite,
            score_breakdown={"moat_proxy": moat, "financial_quality": fq, "stability": stab},
            bear_case="Some bear case text.",
        ),
    )


class TestHardFilters:
    def test_all_pass(self):
        r = _make_report(moat=80, fq=80, stab=70, price=100, base_iv=150)
        passed, failures = apply_hard_filters(r)
        assert passed is True
        assert len(failures) == 0

    def test_moat_fail(self):
        r = _make_report(moat=60)
        passed, failures = apply_hard_filters(r)
        assert passed is False
        assert any("Moat" in f for f in failures)

    def test_fq_fail(self):
        r = _make_report(fq=60)
        passed, failures = apply_hard_filters(r)
        assert passed is False
        assert any("Financial" in f for f in failures)

    def test_stability_fail(self):
        r = _make_report(stab=50)
        passed, failures = apply_hard_filters(r)
        assert passed is False
        assert any("Stability" in f for f in failures)

    def test_price_too_high(self):
        # Price 100, base IV 110 → price is 90.9% of IV, > 85%
        r = _make_report(price=100, base_iv=110)
        passed, failures = apply_hard_filters(r)
        assert passed is False
        assert any("Price" in f for f in failures)


class TestBearRisk:
    def test_no_flag(self):
        r = _make_report(price=100, bear_iv=85)  # 15% downside
        flagged, _ = check_bear_risk(r)
        assert flagged is False

    def test_flag_high_downside(self):
        r = _make_report(price=100, bear_iv=60)  # 40% downside
        flagged, justification = check_bear_risk(r)
        assert flagged is True
        assert "⚠️" in justification


class TestRanking:
    def test_ranking_order(self):
        reports = [
            _make_report("A", composite=60),
            _make_report("B", composite=80),
            _make_report("C", composite=70),
        ]
        ranked = rank_companies(reports)
        passed = [r for r in ranked if r.passed_all_filters]
        assert passed[0].ticker == "B"
        assert passed[1].ticker == "C"
        assert passed[2].ticker == "A"

    def test_failed_filters_ranked_last(self):
        reports = [
            _make_report("PASS", moat=80, composite=60),
            _make_report("FAIL", moat=50, composite=90),  # Fails moat filter
        ]
        ranked = rank_companies(reports)
        assert ranked[0].ticker == "PASS"  # Passed filters, comes first
        assert ranked[1].ticker == "FAIL"

    def test_zero_companies(self):
        ranked = rank_companies([])
        assert ranked == []

    def test_bear_flag_preserved(self):
        r = _make_report("RISKY", price=100, bear_iv=60)
        ranked = rank_companies([r])
        assert ranked[0].bear_risk_flag is True
