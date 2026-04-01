"""Buffett Analyzer — Streamlit UI with inline enhanced HTML report."""
from __future__ import annotations

import os
import sys
from datetime import datetime

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from data.yfinance_client import YFinanceClient, YFinanceError
from data.edgar_client import EdgarClient
from llm.claude_client import ClaudeClient, LLMError
from reports.company_report import run_company_analysis, report_to_json, report_to_markdown
from reports.industry_report_gen import run_industry_analysis, industry_report_to_markdown

anthropic_key = st.secrets.get("ANTHROPIC_API_KEY", "")

if "cache_version" not in st.session_state or st.session_state.cache_version != "v2.1.1":
    st.cache_data.clear()
    st.session_state.cache_version = "v2.1.1"


# ─────────────────────────────────────────────────────────────────────────────
#  HTML Report Builder
# ─────────────────────────────────────────────────────────────────────────────

def build_report_html(report) -> str:
    r    = report
    rec  = r.recommendation
    v    = r.valuation
    m    = r.margin_of_safety
    fq   = r.financial_quality
    s    = r.stability
    moat = r.moat
    comp = r.competence
    cs   = "¥" if getattr(r, "currency", "") == "CNY" else "$"

    def pct(val, d=1):
        if val is None: return "N/A"
        try: return f"{float(val):.{d}f}%"
        except: return str(val)

    def money(val, d=2):
        if val is None: return "N/A"
        try: return f"{cs}{float(val):,.{d}f}"
        except: return str(val)

    def num(val, suffix="", d=2):
        if val is None: return "N/A"
        try: return f"{float(val):.{d}f}{suffix}"
        except: return str(val)

    def sc_cls(sc):
        try:
            f = float(sc)
            return "score-high" if f >= 70 else ("score-mid" if f >= 50 else "score-low")
        except: return "score-mid"

    rec_action = (rec.action or "").upper()
    rec_color  = "green" if "BUY" in rec_action else ("red" if "SELL" in rec_action else "amber")
    total      = int(rec.composite_score or 0)

    # ── Warnings ──────────────────────────────────────────────────────────────
    warn_html = ""
    for w in (r.warnings or []):
        warn_html += f'<div class="alert alert-warn"><span>⚠</span><div>{w}</div></div>'
    if getattr(r, "currency_note", ""):
        warn_html += f'<div class="alert alert-info"><span>ℹ</span><div>{r.currency_note}</div></div>'

    # ── Overview ──────────────────────────────────────────────────────────────
    segs_html = ""
    for seg in (comp.revenue_segments or []):
        nm    = seg.get("segment", "")
        pct_r = seg.get("pct_revenue", "")
        segs_html += f'<div class="metric"><div class="metric-label">{nm}</div><div class="metric-value amber">{pct_r}%</div></div>'

    flags_html = "".join(f"<li>{f}</li>" for f in (comp.complexity_flags or []))

    overview = f"""
    <div class="section-header">
      <span class="section-step">Step 1</span>
      <span class="section-title">Circle of Competence</span>
      <span class="score-chip {sc_cls(comp.score)}">{int(comp.score or 0)}/100 · {comp.predictability or ''}</span>
    </div>
    {warn_html}
    <p>{comp.business_model_summary or ''}</p>
    {"<div class='card'><div class='card-title'>Revenue Mix</div><div class='metrics-grid'>" + segs_html + "</div></div>" if segs_html else ""}
    {"<div class='card'><div class='card-title'>Complexity Flags</div><ul>" + flags_html + "</ul></div>" if flags_html else ""}
    <div class="card"><div class="card-title">Rationale</div><p>{comp.rationale or ''}</p></div>
    """

    # ── Moat ──────────────────────────────────────────────────────────────────
    moat_src_html = ""
    for ms in (moat.moat_sources or []):
        src      = ms.source   if hasattr(ms, "source")   else ms.get("source", "")
        strength = ms.strength if hasattr(ms, "strength") else ms.get("strength", 50)
        evidence = ms.evidence if hasattr(ms, "evidence") else ms.get("evidence", "")
        moat_src_html += f"""
        <div class="moat-item">
          <div class="moat-name">{src}<span class="moat-score">{strength}</span></div>
          <div class="moat-bar"><div class="moat-fill" style="width:{strength}%"></div></div>
          <div style="font-size:12px;color:var(--text-muted);margin-top:5px;">{evidence}</div>
        </div>"""

    mt = moat.margin_trend or {}
    margin_html = ""
    if mt:
        margin_html = f"""<div class="card"><div class="card-title">Margin Trends</div>
        <div class="metrics-grid">
          <div class="metric"><div class="metric-label">Gross Margin 5yr</div><div class="metric-value">{mt.get("gross_margin_5yr_trend","N/A")}</div></div>
          <div class="metric"><div class="metric-label">Operating Margin 5yr</div><div class="metric-value">{mt.get("operating_margin_5yr_trend","N/A")}</div></div>
        </div></div>"""

    moat_tab = f"""
    <div class="section-header">
      <span class="section-step">Step 2</span>
      <span class="section-title">Economic Moat</span>
      <span class="score-chip {sc_cls(moat.score)}">{int(moat.score or 0)}/100 · {moat.moat_type or ''}</span>
    </div>
    <div class="moat-grid">{moat_src_html}</div>
    {margin_html}
    <div class="card"><div class="card-title">Durability: {moat.durability_assessment or ''}</div><p>{moat.rationale or ''}</p></div>
    """

    # ── Financials ────────────────────────────────────────────────────────────
    mets = fq.metrics or {}

    def m_card(label, key, suffix="", hi=True, thr=0):
        val = mets.get(key)
        if val is None: return ""
        try:
            f = float(val)
            # convert decimal pct to %
            if abs(f) <= 1 and "margin" in key:
                f *= 100
            disp = f"{f:.2f}{suffix}"
            col  = "green" if (f > thr if hi else f < thr) else "red"
        except:
            disp = str(val); col = ""
        return f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value {col}">{disp}</div></div>'

    flag_cards = ""
    for flag in (fq.flags or []):
        cls  = "alert-red" if any(w in flag.lower() for w in ["negative","low","warn","⚠","high debt"]) else "alert-green"
        icon = "✕" if cls == "alert-red" else "✓"
        flag_cards += f'<div class="alert {cls}"><span>{icon}</span><div>{flag}</div></div>'

    stab_rows = [
        ("Revenue CAGR 5yr",       f"{num(s.revenue_cagr_5yr,'%',1)}"  if s.revenue_cagr_5yr  is not None else "N/A",
         "green" if (s.revenue_cagr_5yr  or 0) > 5 else "amber"),
        ("Revenue CAGR 10yr",      f"{num(s.revenue_cagr_10yr,'%',1)}" if s.revenue_cagr_10yr is not None else "N/A", ""),
        ("Earnings CAGR 5yr",      f"{num(s.earnings_cagr_5yr,'%',1)}" if s.earnings_cagr_5yr is not None else "N/A",
         "green" if (s.earnings_cagr_5yr or 0) > 5 else "amber"),
        ("Revenue Volatility (CoV)",  num(s.revenue_volatility,"",2)   if s.revenue_volatility  else "N/A",
         "green" if (s.revenue_volatility  or 1) < 0.3 else "red"),
        ("Earnings Volatility (CoV)", num(s.earnings_volatility,"",2)  if s.earnings_volatility else "N/A",
         "green" if (s.earnings_volatility or 1) < 0.3 else "red"),
        ("Consecutive Profit Yrs", str(s.consecutive_profit_years or "N/A"),
         "green" if (s.consecutive_profit_years or 0) >= 7 else "amber"),
        ("Dividend Consistency",   s.dividend_consistency or "N/A", ""),
        ("Revenue Trend R²",       num(s.regression_r_squared,"",2)    if s.regression_r_squared else "N/A", ""),
    ]
    stab_rows_html = "".join(
        f"<tr><td>{lbl}</td><td class='mono {col}'>{val}</td></tr>"
        for lbl, val, col in stab_rows
    )

    financials = f"""
    <div class="section-header">
      <span class="section-step">Step 3 + 4</span>
      <span class="section-title">Financial Quality &amp; Stability</span>
      <span class="score-chip {sc_cls(fq.score)}">Quality {int(fq.score or 0)} · Stability {int(s.score or 0)}</span>
    </div>
    <div class="metrics-grid">
      {m_card("ROE 5yr avg",          "roe_avg_5yr",            "%", True,  15)}
      {m_card("ROIC 5yr avg",         "roic_avg_5yr",           "%", True,  10)}
      {m_card("Debt / Equity",        "debt_to_equity_current", "×", False,  1)}
      {m_card("Interest Coverage",    "interest_coverage",      "×", True,   3)}
      {m_card("FCF / Net Income",     "fcf_to_net_income_avg",  "×", True, 0.8)}
      {m_card("Gross Margin avg",     "gross_margin_avg",       "%", True,  40)}
      {m_card("Operating Margin avg", "operating_margin_avg",   "%", True,  10)}
      {m_card("CapEx / Revenue avg",  "capex_to_revenue_avg",   "%", False, 15)}
    </div>
    {flag_cards}
    <div class="card"><div class="card-title">Financial Quality Rationale</div><p>{fq.rationale or ''}</p></div>
    <div class="card"><div class="card-title">Stability Metrics</div>
      <table><thead><tr><th>Metric</th><th>Value</th></tr></thead>
      <tbody>{stab_rows_html}</tbody></table>
      <p style="margin-top:12px;">{s.rationale or ''}</p>
    </div>
    """

    # ── Valuation ─────────────────────────────────────────────────────────────
    scen_rows = ""
    for name, sc, col in [("Bull", v.bull, "green"), ("Base", v.base, "amber"), ("Bear", v.bear, "red")]:
        iv = sc.per_share_value
        if iv and v.current_price:
            vs_pct = f"{((iv / v.current_price) - 1)*100:+.1f}%"
            vs_col = "green" if iv > v.current_price else "red"
        else:
            vs_pct, vs_col = "N/A", ""
        scen_rows += f"""<tr>
          <td><strong>{name}</strong></td>
          <td class="mono">{sc.growth_rate:.1%}</td>
          <td class="mono">{sc.discount_rate:.0%}</td>
          <td class="mono">{sc.terminal_growth_rate:.0%}</td>
          <td class="mono {col}">{money(iv)}</td>
          <td class="mono {vs_col}">{vs_pct}</td></tr>"""
    if v.epv_per_share and v.current_price:
        epv_vs = f"{((v.epv_per_share / v.current_price) - 1)*100:+.1f}%"
        epv_c  = "green" if v.epv_per_share > v.current_price else "red"
        scen_rows += f"""<tr><td><strong>EPV</strong></td><td class="mono">0%</td><td class="mono">—</td>
          <td class="mono">—</td><td class="mono">{money(v.epv_per_share)}</td>
          <td class="mono {epv_c}">{epv_vs}</td></tr>"""

    sens_html = ""
    if v.sensitivity_table:
        def heat(val):
            if not v.current_price or not val: return ""
            r2 = val / v.current_price
            return "heat-1" if r2 > 2 else ("heat-2" if r2 > 1.5 else ("heat-3" if r2 > 1 else ("heat-4" if r2 > 0.7 else "heat-5")))
        s_rows = ""
        for row in v.sensitivity_table:
            dr = row.get("discount_rate", 0)
            v2, v3, v4 = row.get("tg_2%", 0), row.get("tg_3%", 0), row.get("tg_4%", 0)
            s_rows += f"<tr><td>{dr:.0%}</td><td class='mono {heat(v2)}'>{money(v2)}</td><td class='mono {heat(v3)}'>{money(v3)}</td><td class='mono {heat(v4)}'>{money(v4)}</td></tr>"
        sens_html = f"""<div class="card"><div class="card-title">Sensitivity — Discount Rate × Terminal Growth</div>
          <table class="heat-table"><thead><tr><th>Discount</th><th>TG 2%</th><th>TG 3%</th><th>TG 4%</th></tr></thead>
          <tbody>{s_rows}</tbody></table>
          <p style="font-size:12px;color:var(--text-dim);margin-top:8px;">Green = significant upside. Red = near or below current price.</p></div>"""

    mos_col = "green" if (m.margin_of_safety_pct or 0) > 25 else ("amber" if (m.margin_of_safety_pct or 0) > 0 else "red")

    valuation = f"""
    <div class="section-header">
      <span class="section-step">Step 5 + 6</span>
      <span class="section-title">Intrinsic Value &amp; Margin of Safety</span>
      <span class="score-chip {sc_cls(m.score)}">MoS {int(m.score or 0)}/100 · {pct(m.margin_of_safety_pct)}</span>
    </div>
    <div class="metrics-grid">
      <div class="metric"><div class="metric-label">Current Price</div><div class="metric-value">{money(v.current_price)}</div></div>
      <div class="metric"><div class="metric-label">Base IV</div><div class="metric-value green">{money(v.base.per_share_value)}</div></div>
      <div class="metric"><div class="metric-label">Margin of Safety</div><div class="metric-value {mos_col}">{pct(m.margin_of_safety_pct)}</div></div>
      <div class="metric"><div class="metric-label">EPV / Share</div><div class="metric-value amber">{money(v.epv_per_share)}</div></div>
      <div class="metric"><div class="metric-label">Bull Upside</div><div class="metric-value green">{pct(m.bull_upside_pct)}</div></div>
      <div class="metric"><div class="metric-label">Bear Downside</div><div class="metric-value red">{pct(m.bear_downside_pct)}</div></div>
    </div>
    <div class="card"><div class="card-title">Scenario Range vs Current Price</div>
      <table><thead><tr><th>Scenario</th><th>Growth</th><th>Discount</th><th>Term. Growth</th><th>Per Share IV</th><th>vs Price</th></tr></thead>
      <tbody>{scen_rows}</tbody></table></div>
    {sens_html}
    <div class="card"><div class="card-title">Valuation Rationale</div><p>{v.rationale or ''}</p></div>
    <div class="card"><div class="card-title">MoS Verdict: {m.verdict or ''}</div><p>{m.rationale or ''}</p></div>
    """

    # ── Risks ─────────────────────────────────────────────────────────────────
    risk_items = ""
    for issue in (r.validation_issues or []):
        sev  = issue.get("severity", "")
        cls  = "risk-high" if sev == "error" else "risk-med"
        icon = "❌" if sev == "error" else "⚠"
        cat  = issue.get("category", "").replace("_", " ").title()
        msg  = issue.get("message", "")
        risk_items += f"""<div class="risk-item {cls}"><div class="risk-dot"></div>
          <div><div class="risk-label">{icon} {cat}</div><div class="risk-desc">{msg}</div></div></div>"""
    if (s.revenue_volatility or 0) > 0.4:
        risk_items += f"""<div class="risk-item risk-med"><div class="risk-dot"></div>
          <div><div class="risk-label">📉 High Revenue Volatility</div>
          <div class="risk-desc">CoV {num(s.revenue_volatility,'',2)} — reduces DCF confidence.</div></div></div>"""
    if not risk_items:
        risk_items = '<p style="color:var(--text-muted)">No material risk flags identified.</p>'

    mon_rows = "".join(
        f"<tr><td>{mi}</td><td class='mono amber'>—</td><td>Review position</td></tr>"
        for mi in (rec.monitoring_metrics or [])
    )
    mon_table = f"""<div class="card"><div class="card-title">Monitoring Triggers</div>
      <table><thead><tr><th>Metric</th><th>Alert Level</th><th>Action</th></tr></thead>
      <tbody>{mon_rows}</tbody></table></div>""" if mon_rows else ""

    risks = f"""
    <div class="section-header">
      <span class="section-step">Risk Register</span>
      <span class="section-title">Key Risks</span>
    </div>
    <div class="card">{risk_items}</div>
    {mon_table}
    """

    # ── News ──────────────────────────────────────────────────────────────────
    # ticker/name injected safely — no JS template literal conflict
    ticker_js   = r.ticker.replace("'", "\\'")
    coname_js   = (r.name or r.ticker).replace("'", "\\'")

    news = f"""
    <div class="section-header">
      <span class="section-step">Live</span>
      <span class="section-title">News &amp; Regulatory Filings</span>
    </div>
    <div class="news-toolbar">
      <button class="news-filter-btn active" onclick="filterNews('all',this)">All</button>
      <button class="news-filter-btn" onclick="filterNews('filing',this)">📋 SEC Filings</button>
      <button class="news-filter-btn" onclick="filterNews('earnings',this)">📈 Earnings</button>
      <button class="news-filter-btn" onclick="filterNews('risk',this)">⚠ Regulatory</button>
      <button class="news-filter-btn" onclick="filterNews('analyst',this)">🔬 Analyst</button>
      <button class="news-filter-btn" onclick="filterNews('news',this)">📰 News</button>
      <button class="refresh-btn" onclick="reloadNews()">↻ Refresh</button>
    </div>
    <div id="news-container">
      <div class="news-loading"><div class="spinner"></div><div>Loading {r.ticker} news…</div></div>
    </div>
    <div class="disclaimer">
      ⚠ This tab uses AI-powered web search. Results may contain errors.
      Always verify from primary sources (SEC EDGAR, IR page). Not financial advice.
    </div>
    <script>
    var _TICKER = '{ticker_js}';
    var _CONAME = '{coname_js}';
    </script>
    """

    # ── Final ─────────────────────────────────────────────────────────────────
    sb   = rec.score_breakdown or {}
    bars = ""
    for key, label, weight in [
        ("circle_of_competence", "Circle of Competence", 10),
        ("moat",                 "Moat",                 25),
        ("financial_quality",    "Financial Quality",    20),
        ("stability",            "Stability",            15),
        ("margin_of_safety",     "Margin of Safety",     30),
    ]:
        val_s = sb.get(key, 0)
        try: val_s = float(val_s)
        except: val_s = 0
        bar_col = "var(--green)" if val_s >= 70 else ("var(--warn)" if val_s >= 50 else "var(--red)")
        bars += f"""<div class="score-bar-row">
          <div class="score-bar-label">
            <span>{label} <small style="color:var(--text-dim)">({weight}%)</small></span>
            <span>{int(val_s)}</span>
          </div>
          <div class="score-bar-bg"><div class="score-bar-fill" style="width:{val_s}%;background:{bar_col}"></div></div>
        </div>"""

    final = f"""
    <div class="section-header">
      <span class="section-step">Final</span>
      <span class="section-title">Investment Conclusion</span>
      <span class="score-chip {sc_cls(total)}">{total}/100</span>
    </div>
    <div class="card"><div class="card-title">Score Breakdown</div><div style="margin-top:12px;">{bars}</div></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0;">
      <div class="alert alert-green"><span>✓</span>
        <div><strong>Bull Case</strong><br><span style="font-size:13px;">{rec.bull_case or ''}</span></div>
      </div>
      <div class="alert alert-red"><span>✕</span>
        <div><strong>Bear Case</strong><br><span style="font-size:13px;">{rec.bear_case or ''}</span></div>
      </div>
    </div>
    <div class="card"><div class="card-title">Recommendation</div>
      <p><strong>{rec.action} — {rec.position_size}.</strong></p>
    </div>
    <div class="disclaimer">Report generated {r.analysis_date}. For informational purposes only. Not investment advice.</div>
    """

    # ── Assemble page ─────────────────────────────────────────────────────────
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{r.ticker} — Investment Analysis</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
:root{{--bg:#f8f9fb;--surface:#fff;--surface2:#f2f4f7;--border:#e2e6ec;
  --text:#111827;--text-muted:#6b7280;--text-dim:#9ca3af;
  --accent:#1d6fa5;--accent-dim:rgba(29,111,165,.08);
  --green:#059669;--green-dim:rgba(5,150,105,.08);
  --red:#dc2626;--red-dim:rgba(220,38,38,.08);
  --blue:#2563eb;--blue-dim:rgba(37,99,235,.08);
  --warn:#d97706;--warn-dim:rgba(217,119,6,.08);
  --radius:10px;--shadow:0 1px 3px rgba(0,0,0,.07)}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);line-height:1.6;min-height:100vh}}
.header{{background:var(--surface);border-bottom:1px solid var(--border);padding:16px 32px;
  display:flex;align-items:center;justify-content:space-between;
  position:sticky;top:0;z-index:100;box-shadow:var(--shadow)}}
.header-left{{display:flex;align-items:center;gap:12px}}
.ticker-badge{{font-family:'DM Mono',monospace;font-size:13px;font-weight:500;
  background:var(--accent-dim);color:var(--accent);border:1px solid rgba(29,111,165,.3);
  border-radius:6px;padding:4px 10px;letter-spacing:1px}}
.header-title{{font-family:'Playfair Display',serif;font-size:18px;font-weight:700}}
.header-right{{display:flex;align-items:center;gap:10px}}
.rec-badge{{font-size:12px;font-weight:600;padding:4px 13px;border-radius:20px;letter-spacing:.5px}}
.rec-green{{background:var(--green-dim);color:var(--green);border:1px solid rgba(5,150,105,.3)}}
.rec-red{{background:var(--red-dim);color:var(--red);border:1px solid rgba(220,38,38,.3)}}
.rec-amber{{background:var(--warn-dim);color:var(--warn);border:1px solid rgba(217,119,6,.3)}}
.score-pill{{font-family:'DM Mono',monospace;font-size:13px;color:var(--text-muted)}}
.score-pill span{{color:var(--accent);font-weight:500}}
.layout{{display:flex}}
.sidebar{{width:198px;background:var(--surface);border-right:1px solid var(--border);padding:18px 0;
  position:sticky;top:57px;height:calc(100vh - 57px);overflow-y:auto;flex-shrink:0}}
.nav-label{{font-size:10px;color:var(--text-dim);padding:8px 18px 4px;letter-spacing:1px;text-transform:uppercase}}
.nav-item{{display:flex;align-items:center;gap:9px;padding:9px 18px;cursor:pointer;font-size:13px;
  color:var(--text-muted);border-left:2px solid transparent;transition:all .15s;white-space:nowrap;user-select:none}}
.nav-item:hover{{color:var(--text);background:var(--surface2)}}
.nav-item.active{{color:var(--accent);border-left-color:var(--accent);background:var(--accent-dim);font-weight:500}}
.nav-icon{{font-size:14px;width:16px;text-align:center}}
.nav-divider{{height:1px;background:var(--border);margin:6px 14px}}
.content{{flex:1;padding:26px 32px;max-width:860px;min-width:0}}
.tab-panel{{display:none}}.tab-panel.active{{display:block}}
.section-header{{display:flex;align-items:baseline;gap:12px;margin-bottom:18px;padding-bottom:12px;border-bottom:1px solid var(--border)}}
.section-title{{font-family:'Playfair Display',serif;font-size:21px;font-weight:700}}
.section-step{{font-family:'DM Mono',monospace;font-size:11px;color:var(--text-dim);letter-spacing:1px;text-transform:uppercase}}
.score-chip{{margin-left:auto;font-family:'DM Mono',monospace;font-size:12px;padding:3px 9px;border-radius:4px;font-weight:500;white-space:nowrap}}
.score-high{{background:var(--green-dim);color:var(--green);border:1px solid rgba(5,150,105,.25)}}
.score-mid{{background:var(--warn-dim);color:var(--warn);border:1px solid rgba(217,119,6,.25)}}
.score-low{{background:var(--red-dim);color:var(--red);border:1px solid rgba(220,38,38,.25)}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:17px;margin-bottom:13px;box-shadow:var(--shadow)}}
.card-title{{font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px;margin-bottom:9px;font-weight:600}}
.metrics-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(148px,1fr));gap:9px;margin:13px 0}}
.metric{{background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:12px}}
.metric-label{{font-size:11px;color:var(--text-muted);margin-bottom:3px}}
.metric-value{{font-family:'DM Mono',monospace;font-size:17px;font-weight:500;color:var(--text)}}
.metric-value.green{{color:var(--green)}}.metric-value.amber{{color:var(--warn)}}.metric-value.red{{color:var(--red)}}
.alert{{border-radius:8px;padding:10px 14px;margin-bottom:11px;font-size:14px;display:flex;gap:9px}}
.alert-warn{{background:var(--warn-dim);border:1px solid rgba(217,119,6,.2);color:var(--warn)}}
.alert-info{{background:var(--blue-dim);border:1px solid rgba(37,99,235,.2);color:var(--blue)}}
.alert-red{{background:var(--red-dim);border:1px solid rgba(220,38,38,.2);color:var(--red)}}
.alert-green{{background:var(--green-dim);border:1px solid rgba(5,150,105,.2);color:var(--green)}}
table{{width:100%;border-collapse:collapse;font-size:14px;margin:9px 0}}
th{{background:var(--surface2);padding:8px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:var(--text-muted);border-bottom:1px solid var(--border);font-weight:600}}
td{{padding:8px 12px;border-bottom:1px solid var(--border);color:var(--text);vertical-align:middle}}
tr:last-child td{{border-bottom:none}}tr:hover td{{background:var(--surface2)}}
td.mono{{font-family:'DM Mono',monospace}}td.green{{color:var(--green)}}td.red{{color:var(--red)}}td.amber{{color:var(--warn)}}
.heat-1{{background:rgba(5,150,105,.15)}}.heat-2{{background:rgba(5,150,105,.08)}}
.heat-3{{background:rgba(217,119,6,.08)}}.heat-4{{background:rgba(220,38,38,.08)}}.heat-5{{background:rgba(220,38,38,.14)}}
.score-bar-row{{margin-bottom:12px}}
.score-bar-label{{display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px}}
.score-bar-label span:last-child{{font-family:'DM Mono',monospace}}
.score-bar-bg{{height:5px;background:var(--border);border-radius:3px;overflow:hidden}}
.score-bar-fill{{height:100%;border-radius:3px;transition:width .6s ease}}
.moat-grid{{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:11px 0}}
.moat-item{{background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:11px}}
.moat-name{{font-size:12px;color:var(--text-muted);margin-bottom:5px;display:flex;justify-content:space-between}}
.moat-score{{font-family:'DM Mono',monospace;font-size:12px;color:var(--text)}}
.moat-bar{{height:4px;background:var(--border);border-radius:2px;overflow:hidden}}
.moat-fill{{height:100%;border-radius:2px;background:var(--accent)}}
.risk-item{{display:flex;gap:11px;padding:11px 0;border-bottom:1px solid var(--border);font-size:14px}}
.risk-item:last-child{{border-bottom:none}}
.risk-dot{{width:8px;height:8px;border-radius:50%;margin-top:5px;flex-shrink:0}}
.risk-high .risk-dot{{background:var(--red)}}.risk-med .risk-dot{{background:var(--warn)}}
.risk-label{{font-weight:500;margin-bottom:2px}}.risk-desc{{color:var(--text-muted);font-size:13px}}
.news-toolbar{{display:flex;gap:7px;margin-bottom:18px;flex-wrap:wrap}}
.news-filter-btn{{font-size:12px;padding:5px 13px;border-radius:20px;border:1px solid var(--border);
  background:var(--surface2);color:var(--text-muted);cursor:pointer;transition:all .15s;font-family:'DM Sans',sans-serif}}
.news-filter-btn:hover{{border-color:var(--accent);color:var(--text)}}
.news-filter-btn.active{{background:var(--accent-dim);border-color:var(--accent);color:var(--accent)}}
.news-item{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  padding:16px 18px;margin-bottom:10px;transition:border-color .15s,box-shadow .15s;cursor:pointer;box-shadow:var(--shadow)}}
.news-item:hover{{border-color:var(--accent);box-shadow:0 4px 12px rgba(29,111,165,.08)}}
.news-item-top{{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;margin-bottom:7px}}
.news-item-title{{font-size:15px;font-weight:500;line-height:1.4;color:var(--text)}}
.news-meta{{display:flex;align-items:center;gap:9px;margin-top:7px}}
.news-source{{font-size:12px;color:var(--text-muted)}}.news-date{{font-family:'DM Mono',monospace;font-size:11px;color:var(--text-dim)}}
.news-tag{{font-size:11px;padding:2px 7px;border-radius:4px;font-weight:500;flex-shrink:0}}
.tag-filing{{background:var(--blue-dim);color:var(--blue);border:1px solid rgba(37,99,235,.25)}}
.tag-earnings{{background:var(--green-dim);color:var(--green);border:1px solid rgba(5,150,105,.25)}}
.tag-risk{{background:var(--red-dim);color:var(--red);border:1px solid rgba(220,38,38,.25)}}
.tag-analyst{{background:var(--warn-dim);color:var(--warn);border:1px solid rgba(217,119,6,.25)}}
.tag-news{{background:var(--surface2);color:var(--text-muted);border:1px solid var(--border)}}
.news-summary{{font-size:13px;color:var(--text-muted);line-height:1.5}}
.news-impact{{display:inline-flex;align-items:center;gap:4px;font-size:12px;margin-top:7px}}
.impact-high{{color:var(--red)}}.impact-med{{color:var(--warn)}}.impact-low{{color:var(--text-muted)}}
.news-loading{{text-align:center;padding:50px 20px;color:var(--text-muted)}}
.spinner{{width:28px;height:28px;border:2px solid var(--border);border-top-color:var(--accent);
  border-radius:50%;animation:spin .8s linear infinite;margin:0 auto 14px}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.refresh-btn{{display:flex;align-items:center;gap:7px;font-size:13px;padding:7px 14px;
  border-radius:8px;border:1px solid var(--border);background:var(--surface2);
  color:var(--text-muted);cursor:pointer;transition:all .15s;font-family:'DM Sans',sans-serif;margin-left:auto}}
.refresh-btn:hover{{border-color:var(--accent);color:var(--accent)}}
.disclaimer{{font-size:11px;color:var(--text-dim);background:var(--surface2);
  border:1px solid var(--border);border-radius:6px;padding:9px 13px;margin-top:18px;line-height:1.5}}
p{{font-size:14px;color:var(--text-muted);line-height:1.65;margin-bottom:10px}}
strong{{color:var(--text)}}
ul{{list-style:none;padding:0}}
ul li{{font-size:14px;color:var(--text-muted);padding:3px 0 3px 14px;position:relative}}
ul li::before{{content:'—';position:absolute;left:0;color:var(--text-dim)}}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <span class="ticker-badge">{r.ticker}</span>
    <span class="header-title">{r.name or r.ticker}</span>
  </div>
  <div class="header-right">
    <span class="score-pill">Score <span>{total}/100</span></span>
    <span class="rec-badge rec-{rec_color}">{rec.action} · {rec.position_size}</span>
  </div>
</div>

<div class="layout">
  <nav class="sidebar">
    <div class="nav-label">Analysis</div>
    <div class="nav-item active" onclick="switchTab('overview',this)"><span class="nav-icon">◎</span> Overview</div>
    <div class="nav-item" onclick="switchTab('moat',this)"><span class="nav-icon">⬡</span> Moat</div>
    <div class="nav-item" onclick="switchTab('financials',this)"><span class="nav-icon">▦</span> Financials</div>
    <div class="nav-item" onclick="switchTab('valuation',this)"><span class="nav-icon">◈</span> Valuation</div>
    <div class="nav-item" onclick="switchTab('risks',this)"><span class="nav-icon">△</span> Risks</div>
    <div class="nav-divider"></div>
    <div class="nav-label">Live Data</div>
    <div class="nav-item" onclick="switchTab('news',this)"><span class="nav-icon">⚡</span> News &amp; Filings</div>
    <div class="nav-divider"></div>
    <div class="nav-label">Report</div>
    <div class="nav-item" onclick="switchTab('final',this)"><span class="nav-icon">✦</span> Conclusion</div>
  </nav>

  <main class="content">
    <div id="tab-overview"   class="tab-panel active">{overview}</div>
    <div id="tab-moat"       class="tab-panel">{moat_tab}</div>
    <div id="tab-financials" class="tab-panel">{financials}</div>
    <div id="tab-valuation"  class="tab-panel">{valuation}</div>
    <div id="tab-risks"      class="tab-panel">{risks}</div>
    <div id="tab-news"       class="tab-panel">{news}</div>
    <div id="tab-final"      class="tab-panel">{final}</div>
  </main>
</div>

<script>
function switchTab(name, el) {{
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  el.classList.add('active');
  if (name === 'news' && !window._newsLoaded) reloadNews();
}}

var _currentFilter = 'all';
function filterNews(type, btn) {{
  _currentFilter = type;
  document.querySelectorAll('.news-filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.news-item').forEach(item => {{
    item.style.display = (type === 'all' || item.dataset.type === type) ? 'block' : 'none';
  }});
}}

window._newsLoaded = false;
async function reloadNews() {{
  window._newsLoaded = true;
  var container = document.getElementById('news-container');
  container.innerHTML = '<div class="news-loading"><div class="spinner"></div><div>Searching for ' + _TICKER + ' news\u2026</div></div>';
  try {{
    var resp = await fetch("https://api.anthropic.com/v1/messages", {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{
        model: "claude-sonnet-4-20250514",
        max_tokens: 1000,
        tools: [{{type: "web_search_20250305", name: "web_search"}}],
        system: "You are a financial research assistant. Search for recent news about " + _TICKER + " (" + _CONAME + "). Return ONLY a raw JSON array (no markdown, no backticks): [{{\"title\":\"...\",\"source\":\"...\",\"date\":\"YYYY-MM-DD\",\"summary\":\"2-3 sentences\",\"type\":\"filing|earnings|risk|analyst|news\",\"impact\":\"high|medium|low\",\"url\":\"...\"}}]. Include SEC filings, earnings, regulatory news, analyst ratings. 6-8 items, sorted by date descending.",
        messages: [{{role:"user", content:"Search for and return latest news, filings, earnings for " + _TICKER + ". Return as JSON array only."}}]
      }})
    }});
    var data = await resp.json();
    var raw = '';
    for (var i = 0; i < data.content.length; i++) {{
      if (data.content[i].type === 'text') raw += data.content[i].text;
    }}
    var clean = raw.replace(/```json|```/g,'').trim();
    var s = clean.indexOf('['), e = clean.lastIndexOf(']');
    if (s === -1 || e === -1) throw new Error('no json');
    renderNews(JSON.parse(clean.slice(s, e+1)));
  }} catch(err) {{
    container.innerHTML = '<div class="alert alert-warn"><span>⚠</span><div>Unable to load live news. Deploy with a valid Anthropic API key to enable this feature.</div></div>';
  }}
}}

function renderNews(items) {{
  var container = document.getElementById('news-container');
  if (!items || !items.length) {{ container.innerHTML = '<div class="news-loading">No recent items found.</div>'; return; }}
  var tagMap = {{
    filing:   '<span class="news-tag tag-filing">&#x1F4CB; Filing</span>',
    earnings: '<span class="news-tag tag-earnings">&#x1F4C8; Earnings</span>',
    risk:     '<span class="news-tag tag-risk">&#x26A0; Regulatory</span>',
    analyst:  '<span class="news-tag tag-analyst">&#x1F52C; Analyst</span>',
    news:     '<span class="news-tag tag-news">&#x1F4F0; News</span>'
  }};
  var impactMap = {{
    high:   '<span class="news-impact impact-high">&#x25CF; High Impact</span>',
    medium: '<span class="news-impact impact-med">&#x25CF; Medium</span>',
    low:    '<span class="news-impact impact-low">&#x25CF; Low</span>'
  }};
  var html = '';
  for (var i = 0; i < items.length; i++) {{
    var item = items[i];
    var onclick = item.url ? 'onclick="window.open(\\'' + item.url + '\\',\\'_blank\\')"' : '';
    html += '<div class="news-item" data-type="' + item.type + '" ' + onclick + '>'
      + '<div class="news-item-top"><div class="news-item-title">' + item.title + '</div>'
      + (tagMap[item.type] || tagMap.news) + '</div>'
      + '<div class="news-summary">' + item.summary + '</div>'
      + '<div class="news-meta"><span class="news-source">' + item.source + '</span>'
      + '<span class="news-date">' + item.date + '</span>'
      + (impactMap[item.impact] || '') + '</div></div>';
  }}
  container.innerHTML = html;
  if (_currentFilter !== 'all') {{
    document.querySelectorAll('.news-item').forEach(function(item) {{
      item.style.display = item.dataset.type === _currentFilter ? 'block' : 'none';
    }});
  }}
}}
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
#  Streamlit App
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Buffett Analyzer",
    page_icon="🔬",
    layout="wide",
)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configuration")
    st.divider()
    st.subheader("Valuation Parameters")
    projection_years = st.slider("Projection Years", 5, 15, config.PROJECTION_YEARS)
    discount_rate    = st.slider("Discount Rate (%)", 5, 20, int(config.DISCOUNT_RATE * 100)) / 100
    terminal_growth  = st.slider("Terminal Growth (%)", 1, 6, int(config.TERMINAL_GROWTH_RATE * 100)) / 100
    st.divider()
    st.subheader("Industry Settings")
    universe_size = st.slider("Universe Size (N)", 5, 50, config.DEFAULT_UNIVERSE_SIZE)
    sort_method   = st.selectbox("Sort By", ["market_cap", "revenue"])
    min_mcap      = st.number_input("Min Market Cap ($B)", value=config.MIN_MARKET_CAP / 1e9, min_value=0.1, step=0.5) * 1e9
    st.divider()
    st.subheader("Hard Filter Thresholds")
    min_moat = st.slider("Min Moat Score", 0, 100, config.MIN_MOAT_SCORE)
    min_fq   = st.slider("Min Financial Quality Score", 0, 100, config.MIN_FINANCIAL_SCORE)
    min_stab = st.slider("Min Stability Score", 0, 100, config.MIN_STABILITY_SCORE)
    use_edgar = st.checkbox("Fetch SEC EDGAR filings", value=True)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_company, tab_industry = st.tabs(["📊 Company Analysis", "🏭 Industry Analysis"])

# ── Company Analysis ──────────────────────────────────────────────────────────
with tab_company:
    col1, col2 = st.columns([4, 1])
    with col1:
        ticker = st.text_input(
            "ticker", placeholder="Enter ticker  e.g. AAPL  PDD  TSLA",
            key="company_ticker", label_visibility="collapsed"
        )
    with col2:
        run_company = st.button("🔍 Analyze", key="run_company", type="primary", use_container_width=True)

    if run_company and ticker:
        config.MIN_MOAT_SCORE      = min_moat
        config.MIN_FINANCIAL_SCORE = min_fq
        config.MIN_STABILITY_SCORE = min_stab

        progress = st.empty()

        def company_progress(msg: str):
            progress.info(msg)

        with st.spinner(f"Analyzing {ticker.upper()}…"):
            try:
                data_client = YFinanceClient()
                llm = None
                if anthropic_key:
                    try:
                        llm = ClaudeClient(api_key=anthropic_key)
                    except LLMError:
                        st.warning("⚠️ Anthropic key invalid — running without LLM")

                edgar = EdgarClient() if use_edgar else None

                report = run_company_analysis(
                    ticker=ticker,
                    data_client=data_client,
                    llm=llm,
                    edgar=edgar,
                    discount_rate=discount_rate,
                    terminal_growth=terminal_growth,
                    projection_years=projection_years,
                    progress_callback=company_progress,
                )

                progress.empty()

                # ── Render report inline ──────────────────────────────────────
                html = build_report_html(report)
                components.html(html, height=820, scrolling=True)

                # ── Download buttons ──────────────────────────────────────────
                st.divider()
                md = report_to_markdown(report)
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.download_button("📥 JSON", data=report_to_json(report),
                                       file_name=f"{ticker.upper()}_report.json", mime="application/json")
                with c2:
                    st.download_button("📄 Markdown", data=md,
                                       file_name=f"{ticker.upper()}_report.md", mime="text/markdown")
                with c3:
                    st.download_button("🌐 HTML Report", data=html,
                                       file_name=f"{ticker.upper()}_report.html", mime="text/html")

                # Save to output/
                output_dir = os.path.join(os.path.dirname(__file__), "output")
                os.makedirs(output_dir, exist_ok=True)
                for fname, content in [
                    (f"{ticker.upper()}_report.json", report_to_json(report)),
                    (f"{ticker.upper()}_report.md",   md),
                    (f"{ticker.upper()}_report.html",  html),
                ]:
                    with open(os.path.join(output_dir, fname), "w", encoding="utf-8") as f:
                        f.write(content)

            except YFinanceError as e:
                progress.empty(); st.error(f"❌ Data Error: {e}")
            except RuntimeError as e:
                progress.empty(); st.error(f"❌ {e}")
            except Exception as e:
                progress.empty(); st.error(f"❌ Unexpected error: {e}"); st.exception(e)

# ── Industry Analysis ─────────────────────────────────────────────────────────
with tab_industry:
    col1, col2 = st.columns([4, 1])
    with col1:
        industry = st.text_input(
            "industry", placeholder="Enter industry  e.g. Semiconductors  Cloud Computing",
            key="industry_name", label_visibility="collapsed"
        )
    with col2:
        run_industry = st.button("🔍 Analyze", key="run_industry", type="primary", use_container_width=True)

    if run_industry and industry:
        config.MIN_MOAT_SCORE      = min_moat
        config.MIN_FINANCIAL_SCORE = min_fq
        config.MIN_STABILITY_SCORE = min_stab

        progress = st.empty()

        def industry_progress(msg: str):
            progress.info(msg)

        with st.spinner(f"Analyzing {industry}…"):
            try:
                data_client = YFinanceClient()
                llm = None
                if anthropic_key:
                    try:
                        llm = ClaudeClient(api_key=anthropic_key)
                    except LLMError:
                        st.warning("⚠️ Anthropic key invalid — running without LLM")

                edgar = EdgarClient() if use_edgar else None

                report = run_industry_analysis(
                    industry=industry,
                    data_client=data_client,
                    llm=llm,
                    edgar=edgar,
                    n=universe_size,
                    sort_by=sort_method,
                    min_market_cap=min_mcap,
                    discount_rate=discount_rate,
                    terminal_growth=terminal_growth,
                    projection_years=projection_years,
                    progress_callback=industry_progress,
                )

                progress.empty()
                st.success(f"✅ {len(report.all_reports)} companies analyzed, {len(report.top_5)} in top 5.")

                # Show each top pick as a full report in its own tab
                if report.top_5:
                    st.subheader("🏆 Top Picks")
                    pick_tabs = st.tabs([f"#{i+1} {r.ticker}" for i, r in enumerate(report.top_5)])
                    for tab, r in zip(pick_tabs, report.top_5):
                        with tab:
                            components.html(build_report_html(r), height=820, scrolling=True)

                # Downloads
                st.divider()
                md   = industry_report_to_markdown(report)
                safe = industry.replace(" ", "_").replace("/", "_")
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.download_button("📥 JSON", data=report.model_dump_json(indent=2),
                                       file_name=f"{safe}_industry.json", mime="application/json")
                with c2:
                    st.download_button("📄 Markdown", data=md,
                                       file_name=f"{safe}_industry.md", mime="text/markdown")
                with c3:
                    if report.top_5:
                        st.download_button("🌐 Top Pick HTML",
                                           data=build_report_html(report.top_5[0]),
                                           file_name=f"{safe}_top1.html", mime="text/html")

            except YFinanceError as e:
                progress.empty(); st.error(f"❌ Data Error: {e}")
            except Exception as e:
                progress.empty(); st.error(f"❌ Unexpected error: {e}"); st.exception(e)

st.divider()
st.caption("Buffett Analyzer v2.0 — For research purposes only. Not financial advice.")
