"""Step 5: Intrinsic Value — Owner Earnings + 2-Stage DCF (Bull/Base/Bear) + Reverse DCF."""
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
    method1 = stmt.depreciation_amortization * config.MAINTENANCE_CAPEX_RATIO
    method1_label = f"D&A × {config.MAINTENANCE_CAPEX_RATIO} = ${method1:,.0f}"

    if revenue_growth_rate is not None and revenue_growth_rate > 0 and stmt.capital_expenditure > 0:
        method2 = stmt.capital_expenditure * (1 - revenue_growth_rate)
        method2_label = f"CapEx × (1 - {revenue_growth_rate:.1%}) = ${method2:,.0f}"
        divergence = abs(method1 - method2) / max(method1, method2, 1)
        if divergence > 0.30:
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
    """Run a single 2-stage DCF scenario."""
    adjusted_oe = owner_earnings * (1 - margin_compression)

    # 2-stage growth: full rate years 1-5, linear fade to terminal years 6-10
    projected = []
    fade_start = min(5, projection_years)
    for t in range(1, projection_years + 1):
        if t <= fade_start:
            g = growth_rate
        else:
            progress = (t - fade_start) / (projection_years - fade_start)
            g = growth_rate + (terminal_growth - growth_rate) * progress
        if t == 1:
            cf = adjusted_oe * (1 + g)
        else:
            cf = projected[-1] * (1 + g)
        projected.append(cf)

    final_cf = projected[-1]
    if discount_rate <= terminal_growth:
        terminal_growth = discount_rate - 0.01

    terminal_value = final_cf * (1 + terminal_growth) / (discount_rate - terminal_growth)
    pv_cfs = sum(cf / (1 + discount_rate) ** t for t, cf in enumerate(projected, 1))
    pv_terminal = terminal_value / (1 + discount_rate) ** projection_years
    total_pv = pv_cfs + pv_terminal
    per_share = total_pv / shares_outstanding if shares_outstanding > 0 else 0

    assumptions = [
        f"Scenario: {label} (2-stage DCF)",
        f"Base Owner Earnings: ${owner_earnings:,.0f}",
        f"Stage 1 (years 1-{fade_start}): {growth_rate:.1%} growth",
        f"Stage 2 (years {fade_start+1}-{projection_years}): fade → {terminal_growth:.1%}",
        f"Discount rate: {discount_rate:.1%}",
        f"Terminal growth: {terminal_growth:.1%}",
        f"Margin compression: {margin_compression:.0%}",
        f"Shares outstanding: {shares_outstanding:,.0f}",
    ]

    return ScenarioValuation(
        label=label,
        owner_earnings=owner_earnings,
        growth_rate=growth_rate,
        discount_rate=discount_rate,
        terminal_growth_rate=terminal_growth,
        maintenance_capex=0,
        maintenance_capex_method="",
        projected_cash_flows=[round(cf, 2) for cf in projected],
        terminal_value=round(terminal_value, 2),
        present_value=round(total_pv, 2),
        per_share_value=round(per_share, 2),
        assumptions=assumptions,
    )


def _compute_epv(owner_earnings_avg: float, discount_rate: float, shares: float) -> tuple[float, float]:
    if discount_rate <= 0:
        return 0.0, 0.0
    epv = owner_earnings_avg / discount_rate
    per_share = epv / shares if shares > 0 else 0
    return round(epv, 2), round(per_share, 2)


def _reverse_dcf(
    current_price: float, shares: float, owner_earnings: float,
    discount_rate: float, terminal_growth: float, projection_years: int = 10,
) -> dict:
    """Reverse DCF: what growth rate is the market pricing in?"""
    if shares <= 0 or current_price <= 0 or owner_earnings <= 0:
        return {"implied_growth": None, "implied_growth_pct": "N/A", "interpretation": "Cannot compute — invalid inputs"}

    market_value = current_price * shares
    low, high = -0.10, 0.50
    for _ in range(100):
        mid = (low + high) / 2
        pv = 0
        prev_cf = owner_earnings
        fade_start = min(5, projection_years)
        for t in range(1, projection_years + 1):
            if t <= fade_start:
                g = mid
            else:
                progress = (t - fade_start) / (projection_years - fade_start)
                g = mid + (terminal_growth - mid) * progress
            prev_cf = prev_cf * (1 + g) if t > 1 else owner_earnings * (1 + g)
            pv += prev_cf / (1 + discount_rate) ** t
        tv = prev_cf * (1 + terminal_growth) / (discount_rate - terminal_growth) if discount_rate > terminal_growth else 0
        pv += tv / (1 + discount_rate) ** projection_years
        if pv < market_value:
            low = mid
        else:
            high = mid

    implied = (low + high) / 2
    if implied > 0.30:
        interp = f"Market expects very aggressive growth ({implied:.1%}/yr). High risk if growth disappoints."
    elif implied > 0.15:
        interp = f"Market expects strong growth ({implied:.1%}/yr). Reasonable for proven growth company."
    elif implied > 0.05:
        interp = f"Market expects moderate growth ({implied:.1%}/yr). Reasonable for mature company."
    elif implied >= 0:
        interp = f"Market expects minimal growth ({implied:.1%}/yr). Potential value opportunity."
    else:
        interp = f"Market implies decline ({implied:.1%}/yr). Either deeply undervalued or facing real issues."

    return {"implied_growth": round(implied, 4), "implied_growth_pct": f"{implied:.1%}", "interpretation": interp}


def analyze_valuation(
    history: FinancialHistory,
    discount_rate: float | None = None,
    terminal_growth: float | None = None,
    projection_years: int | None = None,
) -> ValuationResult:
    """Compute intrinsic value using Owner Earnings + 2-stage DCF in 3 scenarios."""
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
    price = history.current_price

    evidence = []

    # Revenue growth for maintenance capex
    revenues = [s.revenue for s in stmts if s.revenue > 0]
    rev_growth = _cagr(revenues[0], revenues[-1], len(revenues) - 1) if len(revenues) >= 2 else None

    # ── Owner Earnings (3-year weighted average to normalize) ──
    latest = stmts[-1]
    oe_yearly = []
    for s in stmts[-3:]:
        mc, _ = _estimate_maintenance_capex(s, rev_growth)
        oe_yearly.append(_compute_owner_earnings(s, mc))

    if len(oe_yearly) == 3:
        oe = oe_yearly[2] * 0.50 + oe_yearly[1] * 0.30 + oe_yearly[0] * 0.20
        evidence.append(f"Owner Earnings (3yr weighted avg): ${oe:,.0f}")
        evidence.append(f"  FY{stmts[-1].fiscal_year}: ${oe_yearly[2]:,.0f} (50%), FY{stmts[-2].fiscal_year}: ${oe_yearly[1]:,.0f} (30%), FY{stmts[-3].fiscal_year}: ${oe_yearly[0]:,.0f} (20%)")
    elif len(oe_yearly) == 2:
        oe = oe_yearly[1] * 0.60 + oe_yearly[0] * 0.40
        evidence.append(f"Owner Earnings (2yr weighted avg): ${oe:,.0f}")
    else:
        maint_capex_tmp, _ = _estimate_maintenance_capex(latest, rev_growth)
        oe = _compute_owner_earnings(latest, maint_capex_tmp)
        evidence.append(f"Owner Earnings ({latest.fiscal_year}): ${oe:,.0f}")

    maint_capex, maint_method = _estimate_maintenance_capex(latest, rev_growth)
    evidence.append(f"Maintenance CapEx: {maint_method}")

    # Historical earnings growth
    earnings = [s.net_income for s in stmts if s.net_income > 0]
    hist_earn_cagr = _cagr(earnings[0], earnings[-1], len(earnings) - 1) if len(earnings) >= 2 else 0.05
    if hist_earn_cagr is None:
        hist_earn_cagr = 0.05

    # Revenue cross-check
    rev_cagr = _cagr(revenues[0], revenues[-1], len(revenues) - 1) if len(revenues) >= 2 else None

    # Hard cap at 40% — no company sustains >40% for a decade
    if hist_earn_cagr > 0.40:
        evidence.append(f"⚠️ Historical earnings CAGR {hist_earn_cagr:.1%} extreme — capping at 40%")
        hist_earn_cagr = 0.40

    # Short history haircut
    if len(stmts) < 5 and hist_earn_cagr > 0.25:
        evidence.append(f"⚠️ Only {len(stmts)} years of data — applying short-history haircut")
        hist_earn_cagr = hist_earn_cagr * 0.7

    # Blend if earnings growth >> revenue growth
    if rev_cagr is not None and hist_earn_cagr is not None:
        if hist_earn_cagr > rev_cagr * 2 and hist_earn_cagr > 0.15:
            evidence.append(f"⚠️ Earnings growth ({hist_earn_cagr:.1%}) >> revenue growth ({rev_cagr:.1%}) — blending")
            hist_earn_cagr = (hist_earn_cagr + rev_cagr) / 2
        evidence.append(f"Revenue CAGR: {rev_cagr:.1%}")

    evidence.append(f"Growth rate used: {hist_earn_cagr:.1%}")

    growth_company = hist_earn_cagr is not None and hist_earn_cagr > 0.20
    if growth_company:
        evidence.append(f"High-growth company detected (CAGR {hist_earn_cagr:.1%})")

    shares = history.shares_outstanding
    if shares <= 0:
        shares = latest.shares_outstanding

    # Sanity: OE vs market cap
    if price > 0 and shares > 0:
        market_cap = price * shares
        oe_yield = oe / market_cap if market_cap > 0 else 0
        if oe_yield > 0.50:
            evidence.append(f"⚠️ Owner Earnings yield {oe_yield:.0%} of market cap — possible data error")

    # ── Three scenarios ──
    scenarios_config = config.SCENARIOS

    def _calc_growth(sc: dict, name: str = "") -> float:
        g = hist_earn_cagr * sc["growth_multiplier"]
        cap = sc["growth_cap"]
        if growth_company and name == "bull":
            cap = min(cap * 1.20, 0.18)
        return min(max(g, 0), cap)

    results = {}
    for name in ["bull", "base", "bear"]:
        sc = scenarios_config[name]
        growth = _calc_growth(sc, name)
        scenario_dr = sc["discount_rate"]
        if disc_rate != config.DISCOUNT_RATE:
            scenario_dr = sc["discount_rate"] + (disc_rate - config.DISCOUNT_RATE)
        scenario_tg = sc["terminal_growth"]
        if term_growth != config.TERMINAL_GROWTH_RATE:
            scenario_tg = sc["terminal_growth"] + (term_growth - config.TERMINAL_GROWTH_RATE)
        sv = _run_dcf(
            owner_earnings=oe, growth_rate=growth, discount_rate=scenario_dr,
            terminal_growth=scenario_tg, margin_compression=sc["margin_compression"],
            projection_years=proj_years, shares_outstanding=shares, label=name,
        )
        sv.maintenance_capex = maint_capex
        sv.maintenance_capex_method = maint_method
        results[name] = sv
        evidence.append(f"{name.upper()} IV: ${sv.per_share_value:,.2f}/share (growth={growth:.1%}, disc={scenario_dr:.0%})")

    # EPV
    epv, epv_ps = _compute_epv(oe, disc_rate, shares)
    evidence.append(f"EPV: ${epv_ps:,.2f}/share (OE ${oe:,.0f} / {disc_rate:.0%})")

    # Reverse DCF
    reverse = _reverse_dcf(price, shares, oe, disc_rate, term_growth, proj_years)
    evidence.append(f"Reverse DCF implied growth: {reverse.get('implied_growth_pct', 'N/A')} — {reverse.get('interpretation', '')}")

    # Sensitivity table
    sensitivity = []
    for dr in [0.08, 0.09, 0.10, 0.11, 0.12]:
        row = {"discount_rate": dr}
        for tg in [0.02, 0.03, 0.04]:
            sv_temp = _run_dcf(
                owner_earnings=oe, growth_rate=_calc_growth(scenarios_config["base"]),
                discount_rate=dr, terminal_growth=tg,
                margin_compression=scenarios_config["base"]["margin_compression"],
                projection_years=proj_years, shares_outstanding=shares, label="sensitivity",
            )
            row[f"tg_{tg:.0%}"] = sv_temp.per_share_value
        sensitivity.append(row)

    base_iv = results["base"].per_share_value
    if price > 0 and (base_iv > price * 10 or base_iv < price * 0.1):
        evidence.append(f"⚠️ VALUATION OUTLIER: Base IV ${base_iv:.2f} vs price ${price:.2f}")

    rationale = (
        f"Intrinsic value estimated via 2-stage Owner Earnings DCF over {proj_years} years. "
        f"Bull: ${results['bull'].per_share_value:,.2f}, "
        f"Base: ${results['base'].per_share_value:,.2f}, "
        f"Bear: ${results['bear'].per_share_value:,.2f}. "
        f"EPV: ${epv_ps:,.2f}/share. "
        f"Reverse DCF: market implies {reverse.get('implied_growth_pct', 'N/A')} growth."
    )

    return ValuationResult(
        bull=results["bull"], base=results["base"], bear=results["bear"],
        epv=epv, epv_per_share=epv_ps, current_price=price,
        sensitivity_table=sensitivity, evidence=evidence, rationale=rationale,
    )
