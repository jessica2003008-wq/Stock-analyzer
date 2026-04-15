"""Company report assembly — runs all analysis modules and generates JSON + Markdown."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Callable, Optional

from data.schemas import CompanyReport
from data.edgar_client import EdgarClient
from llm.claude_client import ClaudeClient
from analysis.circle_of_competence import analyze_circle_of_competence
from analysis.moat_proxy import analyze_moat
from analysis.financial_quality import analyze_financial_quality
from analysis.stability import analyze_stability
from analysis.valuation import analyze_valuation
from analysis.margin_of_safety import analyze_margin_of_safety
from analysis.recommendation import generate_recommendation
from validation.report_validator import validate_report

logger = logging.getLogger(__name__)


def run_company_analysis(
    ticker: str,
    data_client,
    llm: Optional[ClaudeClient] = None,
    edgar: Optional[EdgarClient] = None,
    discount_rate: float | None = None,
    terminal_growth: float | None = None,
    projection_years: int | None = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> CompanyReport:
    """Run the full company analysis pipeline."""

    warnings: list[str] = []
    ticker = ticker.upper().strip()

    def _progress(msg: str) -> None:
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    _progress(f"[{ticker}] Fetching financial data...")
    try:
        history = data_client.get_financial_history(ticker)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch financial data for {ticker}: {e}") from e

    if not history or not history.statements:
        raise RuntimeError(f"No financial statements found for {ticker}")

    if len(history.statements) < 5:
        warnings.append(
            f"Only {len(history.statements)} years of data available; results may be less reliable."
        )

    filing = None
    if edgar:
        _progress(f"[{ticker}] Fetching SEC filing text...")
        try:
            filing = edgar.get_latest_10k_text(ticker)
            if not filing or not filing.sections:
                warnings.append(
                    "EDGAR 10-K text not found; using yfinance business description instead."
                )
                filing = None
        except Exception as e:
            warnings.append(f"EDGAR fetch failed: {e}; using yfinance data only.")
            filing = None

    _progress(f"[{ticker}] Step 1: Circle of Competence...")
    competence = analyze_circle_of_competence(history, filing, llm)

    _progress(f"[{ticker}] Step 2: Moat Proxy...")
    moat = analyze_moat(history, filing, llm)

    _progress(f"[{ticker}] Step 3: Financial Quality...")
    financial_quality = analyze_financial_quality(history)

    _progress(f"[{ticker}] Step 4: Stability...")
    stability = analyze_stability(history)

    _progress(f"[{ticker}] Step 5: Intrinsic Value...")
    valuation = analyze_valuation(
        history,
        discount_rate=discount_rate,
        terminal_growth=terminal_growth,
        projection_years=projection_years,
    )

    _progress(f"[{ticker}] Step 6: Margin of Safety...")
    margin_of_safety = analyze_margin_of_safety(valuation)

    _progress(f"[{ticker}] Generating recommendation...")
    recommendation = generate_recommendation(
        competence,
        moat,
        financial_quality,
        stability,
        valuation,
        margin_of_safety,
    )

    report = CompanyReport(
        ticker=ticker,
        name=history.profile.name or ticker,
        analysis_date=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        competence=competence,
        moat=moat,
        financial_quality=financial_quality,
        stability=stability,
        valuation=valuation,
        margin_of_safety=margin_of_safety,
        recommendation=recommendation,
        warnings=warnings,
    )

    if re.match(r"^\d{6}\.(SS|SZ)$", ticker):
        report.currency = "CNY"
        report.currency_note = "All values in Chinese Yuan (¥ CNY)"

    _progress(f"[{ticker}] Validating report...")
    try:
        validation = validate_report(report)
        report.validation_summary = validation.summary
        report.validation_issues = [
            {
                "severity": issue.severity,
                "category": issue.category,
                "message": issue.message,
            }
            for issue in validation.issues
        ]
        if not validation.passed:
            report.warnings.append(f"VALIDATION FAILED: {validation.summary}")
    except Exception as e:
        report.warnings.append(f"Validation step failed: {e}")

    _progress(f"[{ticker}] Analysis complete.")
    return report


def report_to_json(report: CompanyReport) -> str:
    """Serialize report to JSON."""
    return report.model_dump_json(indent=2)


def _render_list(items: list[str]) -> list[str]:
    if not items:
        return ["- None"]
    return [f"- {item}" for item in items]


def report_to_markdown(report: CompanyReport) -> str:
    """Render a company report into Markdown."""
    lines: list[str] = [
        f"# {report.ticker} — {report.name}",
        f"**Analysis Date:** {report.analysis_date}",
        "",
    ]

    if report.currency_note:
        lines.extend([f"**Currency:** {report.currency_note}", ""])

    if report.warnings:
        lines.append("## Warnings")
        lines.extend(_render_list(report.warnings))
        lines.append("")

    lines.extend(
        [
            "## Final Recommendation",
            f"- **Action:** {report.recommendation.action}",
            f"- **Position Size:** {report.recommendation.position_size}",
            f"- **Composite Score:** {report.recommendation.composite_score:.1f}/100",
            "",
            f"**Bull Case:** {report.recommendation.bull_case}",
            "",
            f"**Bear Case:** {report.recommendation.bear_case}",
            "",
            "### Monitoring Metrics",
            *_render_list(report.recommendation.monitoring_metrics),
            "",
        ]
    )

    lines.extend(
        [
            "## 1. Circle of Competence",
            f"- **Score:** {report.competence.score}/100",
            f"- **Predictability:** {report.competence.predictability}",
            f"- **Business Model Summary:** {report.competence.business_model_summary}",
            "",
            "**Complexity Flags**",
            *_render_list(report.competence.complexity_flags),
            "",
            "**Evidence**",
            *_render_list(report.competence.evidence),
            "",
        ]
    )

    lines.extend(
        [
            "## 2. Moat",
            f"- **Score:** {report.moat.score}/100",
            f"- **Moat Type:** {report.moat.moat_type}",
            f"- **Durability:** {report.moat.durability_assessment}",
            "",
            "**Evidence**",
            *_render_list(report.moat.evidence),
            "",
        ]
    )

    lines.extend(
        [
            "## 3. Financial Quality",
            f"- **Score:** {report.financial_quality.score}/100",
            "",
            "**Flags**",
            *_render_list(report.financial_quality.flags),
            "",
            "**Evidence**",
            *_render_list(report.financial_quality.evidence),
            "",
        ]
    )

    lines.extend(
        [
            "## 4. Stability",
            f"- **Score:** {report.stability.score}/100",
            f"- **5Y Revenue CAGR:** {report.stability.revenue_cagr_5yr}",
            f"- **5Y Earnings CAGR:** {report.stability.earnings_cagr_5yr}",
            f"- **Consecutive Profit Years:** {report.stability.consecutive_profit_years}",
            "",
            "**Evidence**",
            *_render_list(report.stability.evidence),
            "",
        ]
    )

    lines.extend(
        [
            "## 5. Valuation",
            f"- **Current Price:** ${report.valuation.current_price:,.2f}",
            f"- **Bull IV / Share:** ${report.valuation.bull.per_share_value:,.2f}",
            f"- **Base IV / Share:** ${report.valuation.base.per_share_value:,.2f}",
            f"- **Bear IV / Share:** ${report.valuation.bear.per_share_value:,.2f}",
            f"- **EPV / Share:** ${report.valuation.epv_per_share:,.2f}",
            "",
            "**Evidence**",
            *_render_list(report.valuation.evidence),
            "",
        ]
    )

    lines.extend(
        [
            "## 6. Margin of Safety",
            f"- **Score:** {report.margin_of_safety.score}/100",
            f"- **Verdict:** {report.margin_of_safety.verdict}",
            f"- **Margin of Safety:** {report.margin_of_safety.margin_of_safety_pct:.2f}%",
            f"- **Bull Upside:** {report.margin_of_safety.bull_upside_pct:.2f}%",
            f"- **Bear Downside:** {report.margin_of_safety.bear_downside_pct:.2f}%",
            "",
            "**Evidence**",
            *_render_list(report.margin_of_safety.evidence),
            "",
        ]
    )

    if report.validation_summary or report.validation_issues:
        lines.extend(
            [
                "## Validation",
                f"- **Summary:** {report.validation_summary or 'No validation summary'}",
                "",
            ]
        )
        if report.validation_issues:
            lines.append("**Issues**")
            for issue in report.validation_issues:
                sev = issue.get("severity", "unknown")
                cat = issue.get("category", "general")
                msg = issue.get("message", "")
                lines.append(f"- [{sev}] {cat}: {msg}")
            lines.append("")

    return "\n".join(lines)
