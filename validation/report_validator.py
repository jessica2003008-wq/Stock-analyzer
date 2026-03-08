"""Report Validation Agent — checks every report for math/logic consistency."""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from data.schemas import CompanyReport

logger = logging.getLogger(__name__)


@dataclass
class ValidationIssue:
    severity: str  # "error" | "warning" | "info"
    category: str
    message: str
    field: str = ""


@dataclass
class ValidationResult:
    passed: bool = True
    issues: list[ValidationIssue] = field(default_factory=list)
    summary: str = ""
    
    def add(self, severity: str, category: str, message: str, field_name: str = ""):
        issue = ValidationIssue(severity=severity, category=category, message=message, field=field_name)
        self.issues.append(issue)
        if severity == "error":
            self.passed = False
    
    @property
    def errors(self):
        return [i for i in self.issues if i.severity == "error"]
    
    @property
    def warnings(self):
        return [i for i in self.issues if i.severity == "warning"]


def validate_report(report: CompanyReport) -> ValidationResult:
    result = ValidationResult()
    _check_valuation_math(report, result)
    _check_shares_market_cap(report, result)
    _check_fcf_consistency(report, result)
    _check_score_ranges(report, result)
    _check_valuation_ordering(report, result)
    _check_margin_of_safety_math(report, result)
    _check_composite_score(report, result)
    _check_abnormal_values(report, result)
    _check_growth_rate_sanity(report, result)
    
    n_err = len(result.errors)
    n_warn = len(result.warnings)
    n_info = len([i for i in result.issues if i.severity == "info"])
    result.summary = f"Validation: {n_err} errors, {n_warn} warnings, {n_info} info"
    if n_err > 0:
        result.summary += f" — FAILED ({', '.join(e.message[:60] for e in result.errors[:3])})"
    logger.info(f"Validation for {report.ticker}: {result.summary}")
    return result


def _check_valuation_math(report, result):
    v = report.valuation
    for scenario_name in ["bull", "base", "bear"]:
        s = getattr(v, scenario_name)
        if not s.projected_cash_flows:
            continue
        dr = s.discount_rate
        if dr <= 0:
            result.add("error", "math", f"{scenario_name}: discount rate is {dr}, must be positive", "valuation")
            continue
        pv_cfs = sum(cf / (1 + dr) ** t for t, cf in enumerate(s.projected_cash_flows, 1))
        n = len(s.projected_cash_flows)
        pv_tv = s.terminal_value / (1 + dr) ** n if n > 0 else 0
        computed_pv = pv_cfs + pv_tv
        if s.present_value != 0:
            pct_diff = abs(computed_pv - s.present_value) / abs(s.present_value)
            if pct_diff > 0.05:
                result.add("error", "math", 
                    f"{scenario_name}: PV mismatch — computed ${computed_pv:,.0f} vs reported ${s.present_value:,.0f} ({pct_diff:.1%} off)",
                    "valuation")
    if v.bull.per_share_value > 0 and v.base.per_share_value > 0 and v.bear.per_share_value > 0:
        if not (v.bull.per_share_value >= v.base.per_share_value >= v.bear.per_share_value):
            result.add("error", "valuation",
                f"Scenario ordering violated: Bull=${v.bull.per_share_value:.2f}, Base=${v.base.per_share_value:.2f}, Bear=${v.bear.per_share_value:.2f}",
                "valuation")


def _check_shares_market_cap(report, result):
    v = report.valuation
    for scenario_name in ["bull", "base", "bear"]:
        s = getattr(v, scenario_name)
        if s.per_share_value > 0 and s.present_value > 0:
            implied_shares = s.present_value / s.per_share_value
            if implied_shares < 1000:
                result.add("warning", "consistency",
                    f"{scenario_name}: implied shares {implied_shares:,.0f} — suspiciously low", "shares")


def _check_fcf_consistency(report, result):
    fq = report.financial_quality
    fcf_ratio = fq.metrics.get("fcf_to_net_income_avg")
    if fcf_ratio is not None:
        if fcf_ratio > 3.0:
            result.add("warning", "consistency", f"FCF/NI ratio of {fcf_ratio:.2f} unusually high", "fcf")
        if fcf_ratio < -1.0:
            result.add("warning", "consistency", f"FCF/NI ratio of {fcf_ratio:.2f} deeply negative", "fcf")


def _check_score_ranges(report, result):
    checks = [
        ("competence", report.competence.score),
        ("moat", report.moat.score),
        ("financial_quality", report.financial_quality.score),
        ("stability", report.stability.score),
        ("margin_of_safety", report.margin_of_safety.score),
    ]
    for name, score in checks:
        if not (0 <= score <= 100):
            result.add("error", "range", f"{name} score {score} outside 0-100", name)


def _check_valuation_ordering(report, result):
    v = report.valuation
    if v.bull.growth_rate < v.base.growth_rate:
        result.add("warning", "valuation",
            f"Bull growth ({v.bull.growth_rate:.1%}) < base ({v.base.growth_rate:.1%})", "growth_rates")
    if v.base.growth_rate < v.bear.growth_rate:
        result.add("warning", "valuation",
            f"Base growth ({v.base.growth_rate:.1%}) < bear ({v.bear.growth_rate:.1%})", "growth_rates")


def _check_margin_of_safety_math(report, result):
    m = report.margin_of_safety
    if m.base_intrinsic_value > 0 and m.current_price > 0:
        expected_mos = (m.base_intrinsic_value - m.current_price) / m.base_intrinsic_value * 100
        if abs(expected_mos - m.margin_of_safety_pct) > 1.0:
            result.add("error", "math",
                f"MoS% mismatch: computed {expected_mos:.1f}% vs reported {m.margin_of_safety_pct:.1f}%",
                "margin_of_safety")


def _check_composite_score(report, result):
    rec = report.recommendation
    breakdown = rec.score_breakdown
    from config import WEIGHTS
    computed = 0
    for key, weight in WEIGHTS.items():
        score = breakdown.get(key, 0)
        computed += score * weight
    if abs(computed - rec.composite_score) > 1.0:
        result.add("error", "math",
            f"Composite score mismatch: computed {computed:.1f} vs reported {rec.composite_score:.1f}",
            "composite_score")


def _check_abnormal_values(report, result):
    v = report.valuation
    price = v.current_price
    if price > 0:
        base_iv = v.base.per_share_value
        if base_iv > 0:
            ratio = base_iv / price
            if ratio > 5:
                result.add("error", "abnormal",
                    f"Base IV ${base_iv:,.2f} is {ratio:.1f}x price ${price:,.2f} — likely data/currency error",
                    "valuation")
            elif ratio > 3:
                result.add("warning", "abnormal",
                    f"Base IV ${base_iv:,.2f} is {ratio:.1f}x price ${price:,.2f} — review assumptions",
                    "valuation")
            elif ratio < 0.1:
                result.add("warning", "abnormal",
                    f"Base IV ${base_iv:,.2f} is {ratio:.2f}x price — extremely low", "valuation")
        bull_iv = v.bull.per_share_value
        if bull_iv > 0 and bull_iv > price * 5:
            result.add("error", "abnormal",
                f"Bull IV ${bull_iv:,.2f} is {bull_iv/price:.1f}x price — unrealistic", "valuation")
    if v.epv_per_share > 0 and v.base.per_share_value > 0:
        ratio = v.base.per_share_value / v.epv_per_share
        if ratio > 5:
            result.add("warning", "abnormal", f"Base IV is {ratio:.1f}x EPV — growth too aggressive", "valuation")
    if v.base.owner_earnings < 0:
        result.add("warning", "abnormal", f"Negative owner earnings (${v.base.owner_earnings:,.0f})", "valuation")


def _check_growth_rate_sanity(report, result):
    v = report.valuation
    s = report.stability
    base_growth = v.base.growth_rate
    hist_rev_cagr = s.revenue_cagr_5yr
    if hist_rev_cagr is not None and base_growth > 0:
        hist_decimal = hist_rev_cagr / 100
        if base_growth > hist_decimal * 2 and base_growth > 0.10:
            result.add("warning", "valuation",
                f"Base growth ({base_growth:.1%}) >2x historical revenue CAGR ({hist_rev_cagr:.1f}%)",
                "growth_rate")


def format_validation_markdown(validation: ValidationResult, ticker: str = "") -> str:
    lines = [
        f"## ✅ Validation Check {'— ' + ticker if ticker else ''}",
        f"**Status:** {'PASSED ✅' if validation.passed else 'FAILED ❌'}",
        f"**Summary:** {validation.summary}", "",
    ]
    if validation.errors:
        lines.append("### ❌ Errors")
        for e in validation.errors:
            lines.append(f"- **[{e.category}]** {e.message}")
        lines.append("")
    if validation.warnings:
        lines.append("### ⚠️ Warnings")
        for w in validation.warnings:
            lines.append(f"- **[{w.category}]** {w.message}")
        lines.append("")
    if not validation.issues:
        lines.append("All checks passed. No issues found.")
    return "\n".join(lines)
