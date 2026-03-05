"""Industry report — runs analysis on universe and ranks."""
from __future__ import annotations
import logging
from datetime import datetime
from data.schemas import IndustryReport, CompanyReport
from data.yfinance_client import YFinanceClient
from data.edgar_client import EdgarClient
from llm.claude_client import ClaudeClient
from industry.universe import build_universe
from industry.ranking import rank_companies
from reports.company_report import run_company_analysis, report_to_markdown
import config

logger = logging.getLogger(__name__)


def run_industry_analysis(
    industry: str,
    data_client: YFinanceClient,
    llm: ClaudeClient | None = None,
    edgar: EdgarClient | None = None,
    n: int = 20,
    sort_by: str = "market_cap",
    min_market_cap: float = 1_000_000_000,
    discount_rate: float | None = None,
    terminal_growth: float | None = None,
    projection_years: int | None = None,
    progress_callback=None,
) -> IndustryReport:
    """Run full industry analysis pipeline."""
    warnings = []

    def _progress(msg: str):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    # ── Build Universe ──
    _progress(f"Building universe for {industry}...")
    universe = build_universe(industry, data_client, n, sort_by, min_market_cap)

    if not universe.companies:
        return IndustryReport(
            industry=industry,
            analysis_date=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            universe=universe,
            warnings=[f"No companies found in {industry} matching criteria"],
        )

    _progress(f"Found {len(universe.companies)} companies in {industry}")

    # ── Analyze Each Company ──
    reports = []
    skipped = []

    for i, company in enumerate(universe.companies):
        _progress(f"Analyzing {company.ticker} ({i+1}/{len(universe.companies)})...")
        try:
            report = run_company_analysis(
                ticker=company.ticker,
                data_client=data_client,
                llm=llm,
                edgar=edgar,
                discount_rate=discount_rate,
                terminal_growth=terminal_growth,
                projection_years=projection_years,
                progress_callback=progress_callback,
            )
            reports.append(report)
        except Exception as e:
            reason = f"Analysis failed: {e}"
            logger.warning(f"Skipping {company.ticker}: {reason}")
            skipped.append({"ticker": company.ticker, "reason": reason})

    if not reports:
        warnings.append("All company analyses failed")
        return IndustryReport(
            industry=industry,
            analysis_date=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            universe=universe,
            skipped=skipped,
            warnings=warnings,
        )

    # ── Rank ──
    _progress("Ranking companies...")
    ranked = rank_companies(reports)
    passed = [r for r in ranked if r.passed_all_filters]
    top_5 = passed[:5]

    if len(passed) < 5:
        warnings.append(
            f"Only {len(passed)} of {len(reports)} companies passed all filters"
        )
    if len(passed) == 0:
        warnings.append(
            f"No companies in {industry} currently meet all investment criteria. "
            f"Closest misses: {', '.join(r.ticker for r in ranked[:3])}"
        )

    return IndustryReport(
        industry=industry,
        analysis_date=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        universe=universe,
        all_reports=reports,
        ranked=ranked,
        top_5=top_5,
        skipped=skipped,
        warnings=warnings,
    )


def industry_report_to_markdown(report: IndustryReport) -> str:
    """Generate Markdown for industry report."""
    lines = [
        f"# Industry Analysis: {report.industry}",
        f"**Date:** {report.analysis_date}",
        "",
    ]

    if report.warnings:
        lines.append("## ⚠️ Warnings")
        for w in report.warnings:
            lines.append(f"- {w}")
        lines.append("")

    # Universe
    lines.extend([
        "## Universe",
        f"**Sort Method:** {report.universe.sort_method} | "
        f"**Min Market Cap:** ${report.universe.min_market_cap/1e9:.1f}B | "
        f"**Companies Found:** {report.universe.total_found}",
        "",
        "| # | Ticker | Name | Market Cap | Rationale |",
        "|---|--------|------|-----------|-----------|",
    ])
    for i, c in enumerate(report.universe.companies):
        lines.append(
            f"| {i+1} | {c.ticker} | {c.name} | ${c.market_cap/1e9:.1f}B | {c.inclusion_rationale} |"
        )
    lines.append("")

    # Skipped
    if report.skipped:
        lines.append("## Skipped Companies")
        for s in report.skipped:
            lines.append(f"- **{s['ticker']}**: {s['reason']}")
        lines.append("")

    # Ranking
    lines.extend([
        "## Rankings (All Analyzed Companies)",
        "",
        "| Rank | Ticker | Score | Action | MoS% | Bear↓% | Filters | Flags |",
        "|------|--------|-------|--------|------|--------|---------|-------|",
    ])
    for i, r in enumerate(report.ranked):
        status = "✅" if r.passed_all_filters else "❌"
        flag = "⚠️" if r.bear_risk_flag else ""
        failures = "; ".join(r.filter_failures) if r.filter_failures else "—"
        lines.append(
            f"| {i+1} | {r.ticker} | {r.composite_score:.0f} | {r.action} | "
            f"{r.margin_of_safety_pct:.1f}% | {r.bear_downside_pct:.1f}% | "
            f"{status} {failures} | {flag} |"
        )
    lines.append("")

    # Top 5
    if report.top_5:
        lines.extend([
            "## 🏆 Top 5 Undervalued Companies",
            "",
        ])
        for i, r in enumerate(report.top_5):
            flag = " ⚠️ HIGHER RISK" if r.bear_risk_flag else ""
            lines.extend([
                f"### #{i+1}: {r.ticker} — Score {r.composite_score:.0f}/100 ({r.action}){flag}",
                f"- Margin of Safety: {r.margin_of_safety_pct:.1f}%",
                f"- Bear Downside: {r.bear_downside_pct:.1f}%",
            ])
            if r.bear_risk_flag:
                lines.append(f"- **Risk Justification:** {r.bear_justification}")
            lines.append(f"- Score Breakdown: {r.score_breakdown}")
            lines.append("")
    else:
        lines.append("## Top 5")
        lines.append("No companies passed all investment filters.")
        lines.append("")

    # Individual reports
    lines.append("---")
    lines.append("## Individual Company Reports")
    lines.append("")
    for rpt in report.all_reports:
        md = report_to_markdown(rpt)
        lines.append(md)
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)
