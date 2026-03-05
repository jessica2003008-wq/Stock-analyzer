"""Unit tests for financial quality module."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from data.schemas import FinancialHistory, FinancialStatement, CompanyProfile
from analysis.financial_quality import analyze_financial_quality, _score_metric, _safe_div


def _make_history(
    years=5, roe=0.20, de=0.5, gm=0.40, om=0.20,
    fcf_ratio=1.0, revenue=1_000_000,
):
    """Create synthetic history with configurable metrics."""
    stmts = []
    for i in range(years):
        equity = revenue * 1.0
        ni = equity * roe
        debt = equity * de
        stmts.append(FinancialStatement(
            fiscal_year=2020 + i,
            revenue=revenue,
            cost_of_revenue=revenue * (1 - gm),
            gross_profit=revenue * gm,
            operating_income=revenue * om,
            net_income=ni,
            eps=ni / 1_000_000,
            shares_outstanding=1_000_000,
            total_assets=revenue * 2,
            total_liabilities=revenue * 0.8,
            total_equity=equity,
            long_term_debt=debt * 0.6,
            total_debt=debt,
            cash_and_equivalents=revenue * 0.1,
            depreciation_amortization=revenue * 0.05,
            capital_expenditure=revenue * 0.07,
            operating_cash_flow=ni + revenue * 0.05,
            free_cash_flow=ni * fcf_ratio,
            dividends_paid=ni * 0.3,
            change_in_working_capital=0,
        ))
        revenue *= 1.05

    profile = CompanyProfile(ticker="TEST", name="Test Corp", sector="Tech", industry="Software")
    return FinancialHistory(
        ticker="TEST", profile=profile, statements=stmts,
        current_price=50, current_market_cap=50_000_000, shares_outstanding=1_000_000,
    )


class TestScoreMetric:
    def test_high_roe(self):
        score = _score_metric(0.25, [(0.20, 100), (0.15, 80), (0.10, 60), (0.05, 40), (0, 20)])
        assert score == 100

    def test_low_roe(self):
        score = _score_metric(0.03, [(0.20, 100), (0.15, 80), (0.10, 60), (0.05, 40), (0, 20)])
        assert score == 20

    def test_none_value(self):
        score = _score_metric(None, [(0.20, 100)])
        assert score == 0

    def test_lower_is_better(self):
        # D/E: lower is better
        score = _score_metric(0.2, [(0.3, 100), (0.5, 85), (1.0, 65)], higher_is_better=False)
        assert score == 100


class TestSafeDiv:
    def test_normal(self):
        assert _safe_div(10, 5) == 2.0

    def test_zero_denominator(self):
        assert _safe_div(10, 0) is None


class TestFinancialQuality:
    def test_high_quality_company(self):
        h = _make_history(roe=0.25, de=0.3, gm=0.50, fcf_ratio=1.2)
        result = analyze_financial_quality(h)
        assert result.score >= 70
        assert len(result.evidence) > 0

    def test_low_quality_company(self):
        h = _make_history(roe=0.03, de=3.0, gm=0.15, fcf_ratio=0.3)
        result = analyze_financial_quality(h)
        assert result.score < 50
        assert len(result.flags) > 0

    def test_empty_history(self):
        profile = CompanyProfile(ticker="X", name="X", sector="", industry="")
        h = FinancialHistory(
            ticker="X", profile=profile, statements=[],
            current_price=0, current_market_cap=0, shares_outstanding=0,
        )
        result = analyze_financial_quality(h)
        assert result.score == 0

    def test_evidence_traceable(self):
        h = _make_history()
        result = analyze_financial_quality(h)
        # Evidence should reference specific years and values
        roe_evidence = [e for e in result.evidence if "ROE" in e]
        assert len(roe_evidence) > 0

    def test_metrics_populated(self):
        h = _make_history()
        result = analyze_financial_quality(h)
        assert "roe_avg_5yr" in result.metrics
        assert "roic_avg_5yr" in result.metrics
        assert "debt_to_equity_current" in result.metrics

    def test_negative_equity_flag(self):
        h = _make_history()
        h.statements[-1].total_equity = -100_000
        result = analyze_financial_quality(h)
        assert any("Negative" in f for f in result.flags)

    def test_score_range(self):
        h = _make_history()
        result = analyze_financial_quality(h)
        assert 0 <= result.score <= 100
