"""Step 5: Intrinsic Value — Owner Earnings + DCF (Bull/Base/Bear)."""
from __future__ import annotations
import logging
import numpy as np
from data.schemas import FinancialHistory, ValuationResult, ScenarioValuation
import config

logger = logging.getLogger(__name__)


def _cagr(first: float, last: float, years: int) -> float | None:
    if first <= 0 or last <= 0 or years <= 0:
        return None
    return (last / first) ** (1 / years) - 1


def _compute_owner_earnings(stmt, maintenance_capex: float) -> float:
    """Owner Earnings = Net Income + D&A - Maintenance CapEx ± ΔWC"""
    return (
        stmt.net_income
        + stmt.depreciation_amortization
        - maintenance_capex
        + stmt.change_in_working_capital
    )


def _estimate_maintenance_capex(stmt, revenue_growth_rate: float | None) -> tuple[float, str]:
    """
    Estimate maintenance CapEx using two methods, pick conservative.
    Method 1: D&A × maintenance_capex_ratio
    Method 2: CapEx × (1 - revenue_growth_rate)
    """
    method1 = stmt.depreciation_amortization * config.MAINTENANCE_CAPEX_RATIO
    method1_label = f"D&A × {config.MAINTENANCE_CAPEX_RATIO} = ${method1:,.0f}"

    if revenue_growth_rate is not None and revenue_growth_rate > 0 and stmt.capital_expenditure > 0:
        method2 = stmt.capital_expenditure * (1 - revenue_growth_rate)
        method2_label = f"CapEx × (1 - {revenue_growth_rate:.1%}) = ${method2:,.0f}"

        divergence = abs(method1 - method2) / max(method1, method2, 1)
        if divergence > 0.30:
            # Use more conservative (higher) estimate
            if method1 > method2:
                return method1, f"{method1_label} [CONSERVATIVE — methods diverge by {divergence:.0%}; Method2: {method2_label}]"
            else:
                return method2, f"{method2_label} [CONSERVATIVE — methods diverge by {divergence:.0%}; Method1: {method1_label}]"
        return method1, f"{method1_label} [cross-check: {method2_label}, divergence {divergence:.0%}]"

    return method1, method1_label


def _run_dcf(
    owner_earnings: float,
    growth_rate: float,
    discount_rate: float,
    terminal_growth: float,
    projection_years: int,
    margin_compression: float,
    shares_outstanding: float,
    label: str,
) -> ScenarioValuation:
    """Run a single DCF scenario."""
    # Apply margin compression to base OE
    adjusted_oe = owner_earnings * (1 - margin_compression)

    projected = []
    for t in range(1, projection_years + 1):
        cf = adjusted_oe * (1 + growth_rate) ** t
        projected.append(cf)

    # Terminal value
    final_cf = projected[-1]
    if discount_rate <= terminal_growth:
        terminal_growth = discount_rate - 0.01  # Safety: avoid division by zero/negative

    terminal_value = final_cf * (1 + terminal_growth) / (discount_rate - terminal_growth)

    # Present values
    pv_cfs = sum(cf / (1 + discount_rate) ** t for t, cf in enumerate(projected, 1))
    pv_terminal = terminal_value / (1 + discount_rate) ** projection_years
    total_pv = pv_cfs + pv_terminal

    per_share = total_pv / shares_outstanding if shares_outstanding > 0 else 0

    assumptions = [
        f"Scenario: {label}",
        f"Base Owner Earnings: ${owner_earnings:,.0f}",
        f"Growth rate: {growth_rate:.1%}",
        f"Discount rate: {discount_rate:.1%}",
        f"Terminal growth: {terminal_growth:.1%}",
        f"Margin compression: {margin_compression:.0%}",
        f"Projection: {projection_years} years",
        f"Shares outstanding: {shares_outstanding:,.0f}",
    ]

    return ScenarioValuation(
        label=label,
        owner_earnings=owner_earnings,
        growth_rate=growth_rate,
        discount_rate=discount_rate,
        terminal_growth_rate=terminal_growth,
        maintenance_capex=0,  # Set by caller
        maintenance_capex_method="",  # Set by caller
        projected_cash_flows=[round(cf, 2) for cf in projected],
        terminal_value=round(terminal_value, 2),
        present_value=round(total_pv, 2),
        per_share_value=round(per_share, 2),
        assumptions=assumptions,
    )


def _compute_epv(owner_earnings_avg: float, discount_rate: float, shares: float) -> tuple[float, float]:
    """Earnings Power Value = Adjusted Earnings / Cost of Capital."""
    if discount_rate <= 0:
        return 0.0, 0.0
    epv = owner_earnings_avg / discount_rate
    per_share = epv / shares if shares > 0 else 0
    return round(epv, 2), round(per_share, 2)


def analyze_valuation(
    history: FinancialHistory,
    discount_rate: float | None = None,
    terminal_growth: float | None = None,
    projection_years: int | None = None,
) -> ValuationResult:
    """Compute intrinsic value using Owner Earnings + DCF in 3 scenarios."""
    stmts = history.statements
    if not stmts or len(stmts) < 3:
        return ValuationResult(
            current_price=history.current_price,
            evidence=["Insufficient financial history (<3 years)"],
            rationale="Cannot compute valuation with fewer than 3 years of data.",
        )

    proj_years = projection_years or config.PROJECTION_YEARS
    disc_rate = discount_rate or config.DISCOUNT_RATE
    term_growth = terminal_growth or config.TERMINAL_GROWTH_RATE

    evidence = []

    # Historical revenue growth for maintenance capex estimation
    revenues = [s.revenue for s in stmts if s.revenue > 0]
    rev_growth = _cagr(revenues[0], revenues[-1], len(revenues) - 1) if len(revenues) >= 2 else None

    # Compute Owner Earnings for most recent year
    latest = stmts[-1]
    maint_capex, maint_method = _estimate_maintenance_capex(latest, rev_growth)
    oe = _compute_owner_earnings(latest, maint_capex)
    evidence.append(f"Owner Earnings ({latest.fiscal_year}): ${oe:,.0f}")
    evidence.append(f"Maintenance CapEx: {maint_method}")

    # Historical earnings growth
    earnings = [s.net_income for s in stmts if s.net_income > 0]
    hist_earn_cagr = _cagr(earnings[0], earnings[-1], len(earnings) - 1) if len(earnings) >= 2 else 0.05

    if hist_earn_cagr is None:
        hist_earn_cagr = 0.05
    evidence.append(f"Historical earnings CAGR: {hist_earn_cagr:.1%}")

    shares = history.shares_outstanding
    if shares <= 0:
        shares = latest.shares_outstanding

    # ── Three scenarios ──
    scenarios_config = config.SCENARIOS

    def _calc_growth(sc: dict) -> float:
        g = hist_earn_cagr * sc["growth_multiplier"]
        return min(max(g, 0), sc["growth_cap"])

    results = {}
    for name in ["bull", "base", "bear"]:
        sc = scenarios_config[name]
        growth = _calc_growth(sc)
        # If user overrides discount_rate, shift all scenario rates proportionally
        scenario_dr = sc["discount_rate"]
        if disc_rate != config.DISCOUNT_RATE:
            offset = disc_rate - config.DISCOUNT_RATE
            scenario_dr = sc["discount_rate"] + offset
        scenario_tg = sc["terminal_growth"]
        if term_growth != config.TERMINAL_GROWTH_RATE:
            scenario_tg = sc["terminal_growth"] + (term_growth - config.TERMINAL_GROWTH_RATE)
        sv = _run_dcf(
            owner_earnings=oe,
            growth_rate=growth,
            discount_rate=scenario_dr,
            terminal_growth=scenario_tg,
            margin_compression=sc["margin_compression"],
            projection_years=proj_years,
            shares_outstanding=shares,
            label=name,
        )
        sv.maintenance_capex = maint_capex
        sv.maintenance_capex_method = maint_method
        results[name] = sv
        evidence.append(f"{name.upper()} IV: ${sv.per_share_value:,.2f}/share (growth={growth:.1%}, disc={sc['discount_rate']:.0%})")

    # EPV sanity check
    oe_values = []
    for s in stmts[-3:]:
        mc, _ = _estimate_maintenance_capex(s, rev_growth)
        oe_values.append(_compute_owner_earnings(s, mc))
    oe_avg = sum(oe_values) / len(oe_values) if oe_values else oe
    epv, epv_ps = _compute_epv(oe_avg, disc_rate, shares)
    evidence.append(f"EPV: ${epv_ps:,.2f}/share (avg OE ${oe_avg:,.0f} / {disc_rate:.0%})")

    # Sensitivity table
    sensitivity = []
    for dr in [0.08, 0.09, 0.10, 0.11, 0.12]:
        row = {"discount_rate": dr}
        for tg in [0.02, 0.03, 0.04]:
            sv_temp = _run_dcf(
                owner_earnings=oe,
                growth_rate=_calc_growth(scenarios_config["base"]),
                discount_rate=dr,
                terminal_growth=tg,
                margin_compression=scenarios_config["base"]["margin_compression"],
                projection_years=proj_years,
                shares_outstanding=shares,
                label="sensitivity",
            )
            row[f"tg_{tg:.0%}"] = sv_temp.per_share_value
        sensitivity.append(row)

    # Check for outliers
    base_iv = results["base"].per_share_value
    price = history.current_price
    if price > 0 and (base_iv > price * 10 or base_iv < price * 0.1):
        evidence.append(f"⚠️ VALUATION OUTLIER: Base IV ${base_iv:.2f} vs price ${price:.2f} — review assumptions")

    rationale = (
        f"Intrinsic value estimated via Owner Earnings DCF over {proj_years} years. "
        f"Bull: ${results['bull'].per_share_value:,.2f}, "
        f"Base: ${results['base'].per_share_value:,.2f}, "
        f"Bear: ${results['bear'].per_share_value:,.2f}. "
        f"EPV sanity check: ${epv_ps:,.2f}/share."
    )

    return ValuationResult(
        bull=results["bull"],
        base=results["base"],
        bear=results["bear"],
        epv=epv,
        epv_per_share=epv_ps,
        current_price=price,
        sensitivity_table=sensitivity,
        evidence=evidence,
        rationale=rationale,
    )
