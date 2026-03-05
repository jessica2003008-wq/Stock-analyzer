"""Ranking algorithm with hard filters."""
from __future__ import annotations
import logging
from data.schemas import CompanyReport, RankedCompany
import config

logger = logging.getLogger(__name__)


def apply_hard_filters(report: CompanyReport) -> tuple[bool, list[str]]:
    """Apply hard filters. Returns (passed, list of failures)."""
    failures = []

    if report.moat.score < config.MIN_MOAT_SCORE:
        failures.append(f"Moat score {report.moat.score} < {config.MIN_MOAT_SCORE}")

    if report.financial_quality.score < config.MIN_FINANCIAL_SCORE:
        failures.append(f"Financial quality {report.financial_quality.score} < {config.MIN_FINANCIAL_SCORE}")

    if report.stability.score < config.MIN_STABILITY_SCORE:
        failures.append(f"Stability score {report.stability.score} < {config.MIN_STABILITY_SCORE}")

    # Price must be <= 85% of base IV
    price = report.margin_of_safety.current_price
    base_iv = report.margin_of_safety.base_intrinsic_value
    if base_iv > 0 and price > base_iv * config.MAX_PRICE_TO_IV_RATIO:
        failures.append(
            f"Price ${price:.2f} > {config.MAX_PRICE_TO_IV_RATIO:.0%} of base IV ${base_iv:.2f}"
        )

    return len(failures) == 0, failures


def check_bear_risk(report: CompanyReport) -> tuple[bool, str]:
    """Check bear-case downside. Returns (is_flagged, justification)."""
    bear_downside = report.margin_of_safety.bear_downside_pct
    if bear_downside > config.MAX_BEAR_DOWNSIDE_PCT:
        justification = (
            f"⚠️ Bear-case downside of {bear_downside:.1f}% exceeds {config.MAX_BEAR_DOWNSIDE_PCT}% threshold. "
            f"Bear IV: ${report.margin_of_safety.bear_intrinsic_value:.2f} vs "
            f"price ${report.margin_of_safety.current_price:.2f}. "
            f"Bear case: {report.recommendation.bear_case}"
        )
        return True, justification
    return False, ""


def rank_companies(reports: list[CompanyReport]) -> list[RankedCompany]:
    """Apply hard filters, compute composite scores, rank, return results."""
    ranked = []

    for report in reports:
        passed, failures = apply_hard_filters(report)
        bear_flagged, bear_justification = check_bear_risk(report)

        if not passed:
            ranked.append(RankedCompany(
                ticker=report.ticker,
                name=report.name,
                composite_score=report.recommendation.composite_score,
                score_breakdown=report.recommendation.score_breakdown,
                action=report.recommendation.action,
                margin_of_safety_pct=report.margin_of_safety.margin_of_safety_pct,
                bear_downside_pct=report.margin_of_safety.bear_downside_pct,
                bear_risk_flag=bear_flagged,
                bear_justification=bear_justification,
                passed_all_filters=False,
                filter_failures=failures,
            ))
            continue

        ranked.append(RankedCompany(
            ticker=report.ticker,
            name=report.name,
            composite_score=report.recommendation.composite_score,
            score_breakdown=report.recommendation.score_breakdown,
            action=report.recommendation.action,
            margin_of_safety_pct=report.margin_of_safety.margin_of_safety_pct,
            bear_downside_pct=report.margin_of_safety.bear_downside_pct,
            bear_risk_flag=bear_flagged,
            bear_justification=bear_justification,
            passed_all_filters=True,
            filter_failures=[],
        ))

    # Sort: passed filters first, then by composite score descending
    ranked.sort(key=lambda r: (r.passed_all_filters, r.composite_score), reverse=True)

    return ranked
