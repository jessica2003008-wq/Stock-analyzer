"""Company report assembly — runs all analysis modules and generates JSON + Markdown."""
from __future__ import annotations
import json
import logging
from datetime import datetime
from data.schemas import (
    FinancialHistory, FilingText, CompanyReport,
)
from data.yfinance_client import YFinanceClient
from data.edgar_client import EdgarClient
from llm.claude_client import ClaudeClient, LLMError
from analysis.circle_of_competence import analyze_circle_of_competence
from analysis.moat_proxy import analyze_moat
from analysis.financial_quality import analyze_financial_quality
from analysis.stability import analyze_stability
from analysis.valuation import analyze_valuation
from analysis.margin_of_safety import analyze_margin_of_safety
from analysis.recommendation import generate_recommendation

logger = logging.getLogger(__name__)


def run_company_analysis(
    ticker: str,
    data_client: YFinanceClient,
    llm: ClaudeClient | None = None,
    edgar: EdgarClient | None = None,
    discount_rate: float | None = None,
    terminal_growth: float | None = None,
    projection_years: int | None = None,
    progress_callback=None,
) -> CompanyReport:
    """Run full Buffett-style analysis on a single company."""
    warnings = []
    ticker = ticker.upper()

    def _progress(msg: str):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    # ── Data Fetch ──
    _progress(f"[{ticker}] Fetching financial data...")
    try:
        history = data_client.get_financial_history(ticker)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch financial data for {ticker}: {e}")

    if not history.statements:
        raise RuntimeError(f"No financial statements found for {ticker}")

    if len(history.statements) < 5:
        warnings.append(
            f"Only {len(history.statements)} years of data available; scores may be less reliable"
        )

    # ── EDGAR Filing ──
    filing = None
    if edgar:
        _progress(f"[{ticker}] Fetching SEC filing text...")
        try:
            filing = edgar.get_latest_10k_text(ticker)
            if not filing.sections:
                warnings.append("EDGAR 10-K text not found; using yfinance business description instead")
                filing = None
        except Exception as e:
            warnings.append(f"EDGAR fetch failed: {e}; using yfinance data only")
            filing = None

    # ── Step 1: Circle of Competence ──
    _progress(f"[{ticker}] Step 1: Circle of Competence...")
    competence = analyze_circle_of_competence(history, filing, llm)

    # ── Step 2: Moat Proxy ──
    _progress(f"[{ticker}] Step 2: Moat Proxy...")
    moat = analyze_moat(history, filing, llm)

    # ── Step 3: Financial Quality ──
    _progress(f"[{ticker}] Step 3: Financial Quality...")
    fq = analyze_financial_quality(history)

    # ── Step 4: Stability ──
    _progress(f"[{ticker}] Step 4: Stability...")
    stab = analyze_stability(history)

    # ── Step 5: Intrinsic Value ──
    _progress(f"[{ticker}] Step 5: Intrinsic Value...")
    val = analyze_valuation(history, discount_rate, terminal_growth, projection_years)

    # ── Step 6: Margin of Safety ──
    _progress(f"[{ticker}] Step 6: Margin of Safety...")
    mos = analyze_margin_of_safety(val)

    # ── Final Recommendation ──
    _progress(f"[{ticker}] Generating recommendation...")
    rec = generate_recommendation(competence, moat, fq, stab, val, mos)

    report = CompanyReport(
        ticker=ticker,
        name=history.profile.name,
        analysis_date=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        competence=competence,
        moat=moat,
        financial_quality=fq,
        stability=stab,
        valuation=val,
        margin_of_safety=mos,
        recommendation=rec,
        warnings=warnings,
    )

    _progress(f"[{ticker}] Analysis complete. Recommendation: {rec.action} ({rec.position_size})")
    return report


def report_to_json(report: CompanyReport) -> str:
    """Serialize report to JSON."""
    return report.model_dump_json(indent=2)


def report_to_markdown(report: CompanyReport) -> str:
    """Generate Markdown report from CompanyReport."""
    r = report
    v = r.valuation
    m = r.margin_of_safety
    rec = r.recommendation

    lines = [
        f"# {r.name} ({r.ticker}) — Buffett Analysis Report",
        f"**Date:** {r.analysis_date}",
        f"**Recommendation:** {rec.action} | **Position Size:** {rec.position_size} | **Composite Score:** {rec.composite_score:.0f}/100",
        "",
    ]

    if r.warnings:
        lines.append("## ⚠️ Warnings")
        for w in r.warnings:
            lines.append(f"- {w}")
        lines.append("")

    # Step 1
    lines.extend([
        "---",
        "## Step 1: Circle of Competence",
        f"**Score:** {r.competence.score}/100 | **Predictability:** {r.competence.predictability}",
        "",
        f"{r.competence.business_model_summary}",
        "",
    ])
    if r.competence.revenue_segments:
        lines.append("**Revenue Segments:**")
        for seg in r.competence.revenue_segments:
            lines.append(f"- {seg.get('segment', 'N/A')}: {seg.get('pct_revenue', 'N/A')}%")
        lines.append("")
    if r.competence.complexity_flags:
        lines.append(f"**Complexity Flags:** {', '.join(r.competence.complexity_flags)}")
        lines.append("")
    lines.append(f"**Rationale:** {r.competence.rationale}")
    lines.append("")

    # Step 2
    lines.extend([
        "---",
        "## Step 2: Moat Proxy",
        f"**Score:** {r.moat.score}/100 | **Type:** {r.moat.moat_type} | **Durability:** {r.moat.durability_assessment}",
        "",
    ])
    if r.moat.moat_sources:
        lines.append("**Moat Sources:**")
        for ms in r.moat.moat_sources:
            lines.append(f"- **{ms.source}**: {ms.strength}/100 — {ms.evidence}")
        lines.append("")
    mt = r.moat.margin_trend
    if mt:
        lines.append(f"**Margin Trends:** Gross {mt.get('gross_margin_5yr_trend', 'N/A')}, Operating {mt.get('operating_margin_5yr_trend', 'N/A')}")
        lines.append("")
    lines.append(f"**Rationale:** {r.moat.rationale}")
    lines.append("")

    # Step 3
    fq = r.financial_quality
    lines.extend([
        "---",
        "## Step 3: Financial Quality",
        f"**Score:** {fq.score}/100",
        "",
    ])
    metrics = fq.metrics
    lines.append("**Key Metrics:**")
    for key in ["roe_avg_5yr", "roic_avg_5yr", "debt_to_equity_current",
                 "interest_coverage", "fcf_to_net_income_avg", "gross_margin_avg",
                 "operating_margin_avg", "capex_to_revenue_avg"]:
        val = metrics.get(key, "N/A")
        label = key.replace("_", " ").title()
        if isinstance(val, float):
            lines.append(f"- {label}: {val:.2f}")
        else:
            lines.append(f"- {label}: {val}")
    lines.append("")
    if fq.flags:
        lines.append(f"**Flags:** {', '.join(fq.flags)}")
        lines.append("")
    lines.append(f"**Rationale:** {fq.rationale}")
    lines.append("")

    # Step 4
    s = r.stability
    lines.extend([
        "---",
        "## Step 4: Stability",
        f"**Score:** {s.score}/100",
        "",
        f"- Revenue CAGR (5yr): {s.revenue_cagr_5yr}%"
        if s.revenue_cagr_5yr is not None else "- Revenue CAGR (5yr): N/A",
        f"- Revenue CAGR (10yr): {s.revenue_cagr_10yr}%"
        if s.revenue_cagr_10yr is not None else "- Revenue CAGR (10yr): N/A",
        f"- Earnings CAGR (5yr): {s.earnings_cagr_5yr}%"
        if s.earnings_cagr_5yr is not None else "- Earnings CAGR (5yr): N/A",
        f"- Revenue Volatility (CoV): {s.revenue_volatility}" if s.revenue_volatility else "- Revenue Volatility: N/A",
        f"- Earnings Volatility (CoV): {s.earnings_volatility}" if s.earnings_volatility else "- Earnings Volatility: N/A",
        f"- Consecutive Profit Years: {s.consecutive_profit_years}",
        f"- Dividend Consistency: {s.dividend_consistency}",
        f"- Revenue Trend R²: {s.regression_r_squared}" if s.regression_r_squared else "- Revenue Trend R²: N/A",
        "",
        f"**Rationale:** {s.rationale}",
        "",
    ])

    # Step 5
    lines.extend([
        "---",
        "## Step 5: Intrinsic Value",
        "",
        "| Scenario | Per Share IV | Growth | Discount | Terminal Growth |",
        "|----------|-------------|--------|----------|-----------------|",
        f"| **Bull** | ${v.bull.per_share_value:,.2f} | {v.bull.growth_rate:.1%} | {v.bull.discount_rate:.0%} | {v.bull.terminal_growth_rate:.0%} |",
        f"| **Base** | ${v.base.per_share_value:,.2f} | {v.base.growth_rate:.1%} | {v.base.discount_rate:.0%} | {v.base.terminal_growth_rate:.0%} |",
        f"| **Bear** | ${v.bear.per_share_value:,.2f} | {v.bear.growth_rate:.1%} | {v.bear.discount_rate:.0%} | {v.bear.terminal_growth_rate:.0%} |",
        "",
        f"**EPV Sanity Check:** ${v.epv_per_share:,.2f}/share",
        f"**Current Price:** ${v.current_price:,.2f}",
        "",
        f"**Maintenance CapEx:** {v.base.maintenance_capex_method}",
        "",
    ])

    # Sensitivity table
    if v.sensitivity_table:
        lines.append("**Sensitivity Table (Base scenario, varying discount & terminal growth):**")
        lines.append("")
        lines.append("| Discount Rate | TG 2% | TG 3% | TG 4% |")
        lines.append("|---------------|-------|-------|-------|")
        for row in v.sensitivity_table:
            lines.append(
                f"| {row['discount_rate']:.0%} | "
                f"${row.get('tg_2%', 0):,.2f} | "
                f"${row.get('tg_3%', 0):,.2f} | "
                f"${row.get('tg_4%', 0):,.2f} |"
            )
        lines.append("")

    lines.append(f"**Rationale:** {v.rationale}")
    lines.append("")

    # Step 6
    lines.extend([
        "---",
        "## Step 6: Margin of Safety",
        f"**Score:** {m.score}/100 | **Verdict:** {m.verdict}",
        "",
        f"- Current Price: ${m.current_price:,.2f}",
        f"- Base Intrinsic Value: ${m.base_intrinsic_value:,.2f}",
        f"- Margin of Safety: {m.margin_of_safety_pct:.1f}%",
        f"- Bull Upside: {m.bull_upside_pct:.1f}%",
        f"- Bear Downside: {m.bear_downside_pct:.1f}%",
        "",
        f"**Rationale:** {m.rationale}",
        "",
    ])

    # Final Recommendation
    lines.extend([
        "---",
        "## Final Recommendation",
        f"### {rec.action} — {rec.position_size} Position",
        f"**Composite Score:** {rec.composite_score:.0f}/100",
        "",
        "**Score Breakdown:**",
    ])
    for k, v_score in rec.score_breakdown.items():
        w = config.WEIGHTS.get(k, 0)
        lines.append(f"- {k.replace('_', ' ').title()}: {v_score}/100 (weight: {w:.0%})")
    lines.extend([
        "",
        f"**Bull Case:** {rec.bull_case}",
        "",
        f"**Bear Case:** {rec.bear_case}",
        "",
        "**Monitoring Metrics:**",
    ])
    for metric in rec.monitoring_metrics:
        lines.append(f"- {metric}")

    lines.extend(["", "---", f"*Report generated {r.analysis_date}*"])

    return "\n".join(lines)
