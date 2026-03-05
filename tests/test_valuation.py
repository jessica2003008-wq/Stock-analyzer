"""Unit tests for valuation module."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from data.schemas import FinancialHistory, FinancialStatement, CompanyProfile
from analysis.valuation import analyze_valuation, _compute_owner_earnings, _estimate_maintenance_capex


def _make_history(years=10, revenue_start=100_000, revenue_growth=0.08,
                  net_income_margin=0.15, da_ratio=0.05, capex_ratio=0.07,
                  price=50.0, shares=1_000_000):
    """Create a synthetic FinancialHistory for testing."""
    stmts = []
    rev = revenue_start
    for i in range(years):
        ni = rev * net_income_margin
        da = rev * da_ratio
        capex = rev * capex_ratio
        stmts.append(FinancialStatement(
            fiscal_year=2015 + i,
            revenue=rev,
            cost_of_revenue=rev * 0.6,
            gross_profit=rev * 0.4,
            operating_income=rev * 0.20,
            net_income=ni,
            eps=ni / shares,
            shares_outstanding=shares,
            total_assets=rev * 2,
            total_liabilities=rev * 0.8,
            total_equity=rev * 1.2,
            long_term_debt=rev * 0.3,
            total_debt=rev * 0.4,
            cash_and_equivalents=rev * 0.1,
            depreciation_amortization=da,
            capital_expenditure=capex,
            operating_cash_flow=ni + da,
            free_cash_flow=ni + da - capex,
            dividends_paid=ni * 0.3,
            change_in_working_capital=-rev * 0.01,
        ))
        rev *= (1 + revenue_growth)

    profile = CompanyProfile(
        ticker="TEST",
        name="Test Corp",
        sector="Technology",
        industry="Software",
    )

    return FinancialHistory(
        ticker="TEST",
        profile=profile,
        statements=stmts,
        current_price=price,
        current_market_cap=price * shares,
        shares_outstanding=shares,
    )


class TestOwnerEarnings:
    def test_basic_calculation(self):
        stmt = FinancialStatement(
            fiscal_year=2024,
            net_income=100_000,
            depreciation_amortization=20_000,
            change_in_working_capital=-5_000,
        )
        maint_capex = 20_000
        oe = _compute_owner_earnings(stmt, maint_capex)
        # 100k + 20k - 20k + (-5k) = 95k
        assert oe == 95_000

    def test_zero_capex(self):
        stmt = FinancialStatement(
            fiscal_year=2024,
            net_income=50_000,
            depreciation_amortization=10_000,
            change_in_working_capital=0,
        )
        oe = _compute_owner_earnings(stmt, 0)
        # 50k + 10k - 0 + 0 = 60k
        assert oe == 60_000


class TestMaintenanceCapex:
    def test_method1_default(self):
        stmt = FinancialStatement(
            fiscal_year=2024,
            depreciation_amortization=20_000,
            capital_expenditure=30_000,
        )
        capex, method = _estimate_maintenance_capex(stmt, None)
        # Should use D&A × 1.0 = 20000
        assert capex == 20_000
        assert "D&A" in method

    def test_cross_check_no_divergence(self):
        stmt = FinancialStatement(
            fiscal_year=2024,
            depreciation_amortization=20_000,
            capital_expenditure=25_000,
        )
        # Growth rate 10%: Method2 = 25000 * (1-0.10) = 22500
        # Method1 = 20000. Divergence = 2500/22500 = 11% < 30%
        capex, method = _estimate_maintenance_capex(stmt, 0.10)
        assert capex == 20_000  # Method1 when no big divergence
        assert "cross-check" in method

    def test_conservative_on_divergence(self):
        stmt = FinancialStatement(
            fiscal_year=2024,
            depreciation_amortization=10_000,
            capital_expenditure=50_000,
        )
        # Growth rate 5%: Method2 = 50000 * 0.95 = 47500
        # Method1 = 10000. Divergence huge. Should pick 47500 (higher)
        capex, method = _estimate_maintenance_capex(stmt, 0.05)
        assert capex > 10_000  # Should pick the conservative (higher) estimate
        assert "CONSERVATIVE" in method


class TestValuation:
    def test_produces_three_scenarios(self):
        h = _make_history()
        result = analyze_valuation(h)
        assert result.bull.per_share_value > 0
        assert result.base.per_share_value > 0
        assert result.bear.per_share_value > 0

    def test_bull_greater_than_base_greater_than_bear(self):
        h = _make_history()
        result = analyze_valuation(h)
        assert result.bull.per_share_value > result.base.per_share_value
        assert result.base.per_share_value > result.bear.per_share_value

    def test_sensitivity_table_generated(self):
        h = _make_history()
        result = analyze_valuation(h)
        assert len(result.sensitivity_table) > 0
        # Should have discount rate rows
        assert "discount_rate" in result.sensitivity_table[0]

    def test_epv_computed(self):
        h = _make_history()
        result = analyze_valuation(h)
        assert result.epv > 0
        assert result.epv_per_share > 0

    def test_insufficient_data(self):
        h = _make_history(years=2)
        result = analyze_valuation(h)
        assert "Insufficient" in result.evidence[0] or result.rationale != ""

    def test_custom_discount_rate(self):
        h = _make_history()
        result_10 = analyze_valuation(h, discount_rate=0.10)
        result_15 = analyze_valuation(h, discount_rate=0.15)
        # Higher discount rate → lower value
        assert result_15.base.per_share_value < result_10.base.per_share_value

    def test_evidence_populated(self):
        h = _make_history()
        result = analyze_valuation(h)
        assert len(result.evidence) > 0
        # Should mention owner earnings
        assert any("Owner Earnings" in e for e in result.evidence)
