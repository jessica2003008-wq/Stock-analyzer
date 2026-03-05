"""Unit tests for stability module."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from data.schemas import FinancialHistory, FinancialStatement, CompanyProfile
from analysis.stability import analyze_stability, _cagr, _coefficient_of_variation, _r_squared


class TestCAGR:
    def test_positive_growth(self):
        result = _cagr(100, 200, 5)
        assert result is not None
        assert abs(result - 0.1487) < 0.001  # ~14.87%

    def test_no_growth(self):
        result = _cagr(100, 100, 5)
        assert result is not None
        assert abs(result) < 0.001

    def test_negative_input(self):
        assert _cagr(-100, 200, 5) is None

    def test_zero_years(self):
        assert _cagr(100, 200, 0) is None


class TestCoV:
    def test_stable_values(self):
        cov = _coefficient_of_variation([100, 101, 99, 100, 102])
        assert cov is not None
        assert cov < 0.05

    def test_volatile_values(self):
        cov = _coefficient_of_variation([50, 150, 30, 200, 80])
        assert cov is not None
        assert cov > 0.3

    def test_single_value(self):
        assert _coefficient_of_variation([100]) is None


class TestRSquared:
    def test_perfect_linear(self):
        r2 = _r_squared([100, 200, 300, 400, 500])
        assert r2 is not None
        assert r2 > 0.99

    def test_noisy_data(self):
        r2 = _r_squared([100, 300, 50, 400, 200])
        assert r2 is not None
        assert r2 < 0.8

    def test_too_few_points(self):
        assert _r_squared([100, 200]) is None


def _make_stable_history(years=10):
    stmts = []
    rev = 1_000_000
    for i in range(years):
        stmts.append(FinancialStatement(
            fiscal_year=2015 + i,
            revenue=rev,
            net_income=rev * 0.15,
            dividends_paid=rev * 0.05,
        ))
        rev *= 1.08
    profile = CompanyProfile(ticker="STBL", name="Stable Corp", sector="Consumer", industry="Beverages")
    return FinancialHistory(
        ticker="STBL", profile=profile, statements=stmts,
        current_price=50, current_market_cap=50_000_000, shares_outstanding=1_000_000,
    )


def _make_volatile_history(years=10):
    stmts = []
    revenues = [100, 300, 50, 400, 150, 500, 80, 350, 200, 600]
    for i in range(years):
        rev = revenues[i] * 10_000
        stmts.append(FinancialStatement(
            fiscal_year=2015 + i,
            revenue=rev,
            net_income=rev * 0.10 if i % 2 == 0 else -rev * 0.05,
        ))
    profile = CompanyProfile(ticker="VOL", name="Volatile Corp", sector="Energy", industry="Oil")
    return FinancialHistory(
        ticker="VOL", profile=profile, statements=stmts,
        current_price=20, current_market_cap=20_000_000, shares_outstanding=1_000_000,
    )


class TestStability:
    def test_stable_company_scores_high(self):
        h = _make_stable_history()
        result = analyze_stability(h)
        assert result.score >= 60

    def test_volatile_company_scores_low(self):
        h = _make_volatile_history()
        result = analyze_stability(h)
        assert result.score < 50

    def test_revenue_cagr_computed(self):
        h = _make_stable_history()
        result = analyze_stability(h)
        assert result.revenue_cagr_5yr is not None
        assert result.revenue_cagr_5yr > 0

    def test_consecutive_profit_years(self):
        h = _make_stable_history()
        result = analyze_stability(h)
        assert result.consecutive_profit_years == 10

    def test_dividend_consistency(self):
        h = _make_stable_history()
        result = analyze_stability(h)
        assert result.dividend_consistency == "Consistent"

    def test_empty_history(self):
        profile = CompanyProfile(ticker="X", name="X", sector="", industry="")
        h = FinancialHistory(
            ticker="X", profile=profile, statements=[],
            current_price=0, current_market_cap=0, shares_outstanding=0,
        )
        result = analyze_stability(h)
        assert result.score == 0

    def test_evidence_populated(self):
        h = _make_stable_history()
        result = analyze_stability(h)
        assert len(result.evidence) > 0

    def test_score_range(self):
        h = _make_stable_history()
        result = analyze_stability(h)
        assert 0 <= result.score <= 100
