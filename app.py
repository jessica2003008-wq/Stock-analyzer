"""Buffett Analyzer — Streamlit UI with native tab navigation + styled HTML panels."""
from __future__ import annotations
import os, sys
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
#  Shared CSS injected once into Streamlit
# ─────────────────────────────────────────────────────────────────────────────
GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500;600&display=swap');

:root {
  --bg:#f8f9fb; --surface:#fff; --surface2:#f2f4f7; --border:#e2e6ec;
  --text:#111827; --text-muted:#6b7280; --text-dim:#9ca3af;
  --accent:#1d6fa5; --accent-dim:rgba(29,111,165,.08);
  --green:#059669; --green-dim:rgba(5,150,105,.08);
  --red:#dc2626;   --red-dim:rgba(220,38,38,.08);
  --blue:#2563eb;  --blue-dim:rgba(37,99,235,.08);
  --warn:#d97706;  --warn-dim:rgba(217,119,6,.08);
  --radius:10px;   --shadow:0 1px 3px rgba(0,0,0,.07);
}

/* report panel base */
.rp { font-family:'DM Sans',sans-serif; color:var(--text); line-height:1.6; background:var(--bg); }
.rp .section-header { display:flex; align-items:baseline; gap:12px; margin-bottom:18px; padding-bottom:12px; border-bottom:1px solid var(--border); }
.rp .section-title  { font-family:'Playfair Display',serif; font-size:21px; font-weight:700; }
.rp .section-step   { font-family:'DM Mono',monospace; font-size:11px; color:var(--text-dim); letter-spacing:1px; text-transform:uppercase; }
.rp .score-chip     { margin-left:auto; font-family:'DM Mono',monospace; font-size:12px; padding:3px 9px; border-radius:4px; font-weight:500; white-space:nowrap; }
.rp .score-high { background:var(--green-dim); color:var(--green); border:1px solid rgba(5,150,105,.25); }
.rp .score-mid  { background:var(--warn-dim);  color:var(--warn);  border:1px solid rgba(217,119,6,.25); }
.rp .score-low  { background:var(--red-dim);   color:var(--red);   border:1px solid rgba(220,38,38,.25); }
.rp .card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:17px; margin-bottom:13px; box-shadow:var(--shadow); }
.rp .card-title { font-size:11px; color:var(--text-dim); text-transform:uppercase; letter-spacing:1px; margin-bottom:9px; font-weight:600; }
.rp .metrics-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(148px,1fr)); gap:9px; margin:13px 0; }
.rp .metric { background:var(--surface2); border:1px solid var(--border); border-radius:8px; padding:12px; }
.rp .metric-label { font-size:11px; color:var(--text-muted); margin-bottom:3px; }
.rp .metric-value { font-family:'DM Mono',monospace; font-size:17px; font-weight:500; color:var(--text); }
.rp .metric-value.green { color:var(--green); } .rp .metric-value.amber { color:var(--warn); } .rp .metric-value.red { color:var(--red); }
.rp .alert { border-radius:8px; padding:10px 14px; margin-bottom:11px; font-size:14px; display:flex; gap:9px; }
.rp .alert-warn  { background:var(--warn-dim);  border:1px solid rgba(217,119,6,.2);  color:var(--warn);  }
.rp .alert-info  { background:var(--blue-dim);  border:1px solid rgba(37,99,235,.2);  color:var(--blue);  }
.rp .alert-red   { background:var(--red-dim);   border:1px solid rgba(220,38,38,.2);  color:var(--red);   }
.rp .alert-green { background:var(--green-dim); border:1px solid rgba(5,150,105,.2);  color:var(--green); }
.rp table { width:100%; border-collapse:collapse; font-size:14px; margin:9px 0; }
.rp th { background:var(--surface2); padding:8px 12px; text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.8px; color:var(--text-muted); border-bottom:1px solid var(--border); font-weight:600; }
.rp td { padding:8px 12px; border-bottom:1px solid var(--border); color:var(--text); vertical-align:middle; }
.rp tr:last-child td { border-bottom:none; } .rp tr:hover td { background:var(--surface2); }
.rp td.mono { font-family:'DM Mono',monospace; }
.rp td.green { color:var(--green); } .rp td.red { color:var(--red); } .rp td.amber { color:var(--warn); }
.rp .heat-1 { background:rgba(5,150,105,.15); } .rp .heat-2 { background:rgba(5,150,105,.08); }
.rp .heat-3 { background:rgba(217,119,6,.08);  } .rp .heat-4 { background:rgba(220,38,38,.08); } .rp .heat-5 { background:rgba(220,38,38,.14); }
.rp .score-bar-row   { margin-bottom:12px; }
.rp .score-bar-label { display:flex; justify-content:space-between; font-size:13px; margin-bottom:4px; }
.rp .score-bar-label span:last-child { font-family:'DM Mono',monospace; }
.rp .score-bar-bg    { height:5px; background:var(--border); border-radius:3px; overflow:hidden; }
.rp .score-bar-fill  { height:100%; border-radius:3px; }
.rp .moat-grid { display:grid; grid-template-columns:1fr 1fr; gap:9px; margin:11px 0; }
.rp .moat-item { background:var(--surface2); border:1px solid var(--border); border-radius:8px; padding:11px; }
.rp .moat-name { font-size:12px; color:var(--text-muted); margin-bottom:5px; display:flex; justify-content:space-between; }
.rp .moat-score { font-family:'DM Mono',monospace; font-size:12px; color:var(--text); }
.rp .moat-bar  { height:4px; background:var(--border); border-radius:2px; overflow:hidden; }
.rp .moat-fill { height:100%; border-radius:2px; background:var(--accent); }
.rp .risk-item { display:flex; gap:11px; padding:11px 0; border-bottom:1px solid var(--border); font-size:14px; }
.rp .risk-item:last-child { border-bottom:none; }
.rp .risk-dot  { width:8px; height:8px; border-radius:50%; margin-top:5px; flex-shrink:0; }
.rp .risk-high .risk-dot { background:var(--red);  } .rp .risk-med .risk-dot { background:var(--warn); }
.rp .risk-label { font-weight:500; margin-bottom:2px; } .rp .risk-desc { color:var(--text-muted); font-size:13px; }
.rp p  { font-size:14px; color:var(--text-muted); line-height:1.65; margin-bottom:10px; }
.rp strong { color:var(--text); }
.rp ul { list-style:none; padding:0; }
.rp ul li { font-size:14px; color:var(--text-muted); padding:3px 0 3px 14px; position:relative; }
.rp ul li::before { content:'—'; position:absolute; left:0; color:var(--text-dim); }
.rp .disclaimer { font-size:11px; color:var(--text-dim); background:var(--surface2); border:1px solid var(--border); border-radius:6px; padding:9px 13px; margin-top:18px; line-height:1.5; }

/* news */
.rp .news-toolbar { display:flex; gap:7px; margin-bottom:18px; flex-wrap:wrap; }
.rp .nfbtn { font-size:12px; padding:5px 13px; border-radius:20px; border:1px solid var(--border); background:var(--surface2); color:var(--text-muted); cursor:pointer; font-family:'DM Sans',sans-serif; }
.rp .nfbtn:hover { border-color:var(--accent); color:var(--text); }
.rp .nfbtn.active { background:var(--accent-dim); border-color:var(--accent); color:var(--accent); }
.rp .news-item { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:16px 18px; margin-bottom:10px; cursor:pointer; box-shadow:var(--shadow); }
.rp .news-item:hover { border-color:var(--accent); }
.rp .news-item-top { display:flex; align-items:flex-start; justify-content:space-between; gap:14px; margin-bottom:7px; }
.rp .news-item-title { font-size:15px; font-weight:500; line-height:1.4; color:var(--text); }
.rp .news-meta { display:flex; align-items:center; gap:9px; margin-top:7px; }
.rp .news-source { font-size:12px; color:var(--text-muted); } .rp .news-date { font-family:'DM Mono',monospace; font-size:11px; color:var(--text-dim); }
.rp .news-tag { font-size:11px; padding:2px 7px; border-radius:4px; font-weight:500; flex-shrink:0; }
.rp .tag-filing  { background:var(--blue-dim);  color:var(--blue);  border:1px solid rgba(37,99,235,.25); }
.rp .tag-earnings{ background:var(--green-dim); color:var(--green); border:1px solid rgba(5,150,105,.25); }
.rp .tag-risk    { background:var(--red-dim);   color:var(--red);   border:1px solid rgba(220,38,38,.25); }
.rp .tag-analyst { background:var(--warn-dim);  color:var(--warn);  border:1px solid rgba(217,119,6,.25); }
.rp .tag-news    { background:var(--surface2);  color:var(--text-muted); border:1px solid var(--border); }
.rp .news-summary{ font-size:13px; color:var(--text-muted); line-height:1.5; }
.rp .news-loading{ text-align:center; padding:40px 20px; color:var(--text-muted); }
.rp .spinner { width:28px; height:28px; border:2px solid var(--border); border-top-color:var(--accent); border-radius:50%; animation:spin .8s linear infinite; margin:0 auto 14px; }
@keyframes spin { to { transform:rotate(360deg); } }
.rp .refresh-btn { font-size:12px; padding:5px 13px; border-radius:20px; border:1px solid var(--border); background:var(--surface2); color:var(--text-muted); cursor:pointer; font-family:'DM Sans',sans-serif; margin-left:auto; }
.rp .refresh-btn:hover { border-color:var(--accent); color:var(--accent); }

/* streamlit tab style tweaks */
[data-testid="stTabs"] [data-baseweb="tab"] { font-family:'DM Sans',sans-serif; }
</style>
"""


# ─────────────────────────────────────────────────────────────────────────────
#  Per-tab HTML builders  (each returns a <div class="rp">…</div> snippet)
# ─────────────────────────────────────────────────────────────────────────────

def _wrap(inner: str) -> str:
    """Wrap a tab panel in the rp class + inject CSS inline for components.html."""
    return f"""<!doctype html><html><head><meta charset="utf-8">
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
body{{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);line-height:1.6;padding:20px}}
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
.score-bar-fill{{height:100%;border-radius:3px}}
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
p{{font-size:14px;color:var(--text-muted);line-height:1.65;margin-bottom:10px}}
strong{{color:var(--text)}}
ul{{list-style:none;padding:0}}
ul li{{font-size:14px;color:var(--text-muted);padding:3px 0 3px 14px;position:relative}}
ul li::before{{content:'—';position:absolute;left:0;color:var(--text-dim)}}
.disclaimer{{font-size:11px;color:var(--text-dim);background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:9px 13px;margin-top:18px;line-height:1.5}}
.news-toolbar{{display:flex;gap:7px;margin-bottom:18px;flex-wrap:wrap}}
.nfbtn{{font-size:12px;padding:5px 13px;border-radius:20px;border:1px solid var(--border);background:var(--surface2);color:var(--text-muted);cursor:pointer;font-family:'DM Sans',sans-serif}}
.nfbtn:hover{{border-color:var(--accent);color:var(--text)}}
.nfbtn.active{{background:var(--accent-dim);border-color:var(--accent);color:var(--accent)}}
.news-item{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px;margin-bottom:10px;cursor:pointer;box-shadow:var(--shadow)}}
.news-item:hover{{border-color:var(--accent)}}
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
.news-loading{{text-align:center;padding:40px 20px;color:var(--text-muted)}}
.spinner{{width:28px;height:28px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite;margin:0 auto 14px}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.refresh-btn{{font-size:12px;padding:5px 13px;border-radius:20px;border:1px solid var(--border);background:var(--surface2);color:var(--text-muted);cursor:pointer;margin-left:auto}}
.refresh-btn:hover{{border-color:var(--accent);color:var(--accent)}}
</style></head><body>{inner}</body></html>"""


def _sc(sc):
    try:
        f = float(sc)
        return "score-high" if f >= 70 else ("score-mid" if f >= 50 else "score-low")
    except: return "score-mid"

def _pct(val, d=1):
    if val is None: return "N/A"
    try: return f"{float(val):.{d}f}%"
    except: return str(val)

def _money(val, cs, d=2):
    if val is None: return "N/A"
    try: return f"{cs}{float(val):,.{d}f}"
    except: return str(val)

def _num(val, suffix="", d=2):
    if val is None: return "N/A"
    try: return f"{float(val):.{d}f}{suffix}"
    except: return str(val)


# ── Individual tab builders ───────────────────────────────────────────────────

def tab_overview(r) -> str:
    comp = r.competence
    cs   = "¥" if getattr(r, "currency", "") == "CNY" else "$"
    warn = ""
    for w in (r.warnings or []):
        warn += f'<div class="alert alert-warn"><span>⚠</span><div>{w}</div></div>'
    if getattr(r, "currency_note", ""):
        warn += f'<div class="alert alert-info"><span>ℹ</span><div>{r.currency_note}</div></div>'

    segs = ""
    for seg in (comp.revenue_segments or []):
        segs += f'<div class="metric"><div class="metric-label">{seg.get("segment","")}</div><div class="metric-value amber">{seg.get("pct_revenue","")}%</div></div>'

    flags = "".join(f"<li>{f}</li>" for f in (comp.complexity_flags or []))

    # top metrics row
    v  = r.valuation
    m  = r.margin_of_safety
    mc = "green" if (m.margin_of_safety_pct or 0) > 25 else ("amber" if (m.margin_of_safety_pct or 0) > 0 else "red")
    top = f"""<div class="metrics-grid" style="margin-bottom:18px">
      <div class="metric"><div class="metric-label">Current Price</div><div class="metric-value">{_money(v.current_price,cs)}</div></div>
      <div class="metric"><div class="metric-label">Base IV</div><div class="metric-value green">{_money(v.base.per_share_value,cs)}</div></div>
      <div class="metric"><div class="metric-label">Margin of Safety</div><div class="metric-value {mc}">{_pct(m.margin_of_safety_pct)}</div></div>
      <div class="metric"><div class="metric-label">Composite Score</div><div class="metric-value amber">{int(r.recommendation.composite_score or 0)}/100</div></div>
    </div>"""

    inner = f"""
    <div class="section-header">
      <span class="section-step">Step 1</span>
      <span class="section-title">Circle of Competence</span>
      <span class="score-chip {_sc(comp.score)}">{int(comp.score or 0)}/100 · {comp.predictability or ''}</span>
    </div>
    {warn}{top}
    <p>{comp.business_model_summary or ''}</p>
    {"<div class='card'><div class='card-title'>Revenue Mix</div><div class='metrics-grid'>" + segs + "</div></div>" if segs else ""}
    {"<div class='card'><div class='card-title'>Complexity Flags</div><ul>" + flags + "</ul></div>" if flags else ""}
    <div class="card"><div class="card-title">Rationale</div><p>{comp.rationale or ''}</p></div>
    """
    return _wrap(inner)


def tab_moat(r) -> str:
    moat = r.moat
    srcs = ""
    for ms in (moat.moat_sources or []):
        src = ms.source if hasattr(ms,"source") else ms.get("source","")
        st2 = ms.strength if hasattr(ms,"strength") else ms.get("strength",50)
        ev  = ms.evidence if hasattr(ms,"evidence") else ms.get("evidence","")
        srcs += f"""<div class="moat-item">
          <div class="moat-name">{src}<span class="moat-score">{st2}</span></div>
          <div class="moat-bar"><div class="moat-fill" style="width:{st2}%"></div></div>
          <div style="font-size:12px;color:var(--text-muted);margin-top:5px">{ev}</div></div>"""

    mt = moat.margin_trend or {}
    mt_html = ""
    if mt:
        mt_html = f"""<div class="card"><div class="card-title">Margin Trends</div>
        <div class="metrics-grid">
          <div class="metric"><div class="metric-label">Gross Margin 5yr</div><div class="metric-value">{mt.get("gross_margin_5yr_trend","N/A")}</div></div>
          <div class="metric"><div class="metric-label">Operating Margin 5yr</div><div class="metric-value">{mt.get("operating_margin_5yr_trend","N/A")}</div></div>
        </div></div>"""

    inner = f"""
    <div class="section-header">
      <span class="section-step">Step 2</span>
      <span class="section-title">Economic Moat</span>
      <span class="score-chip {_sc(moat.score)}">{int(moat.score or 0)}/100 · {moat.moat_type or ''}</span>
    </div>
    <div class="moat-grid">{srcs}</div>
    {mt_html}
    <div class="card"><div class="card-title">Durability: {moat.durability_assessment or ''}</div><p>{moat.rationale or ''}</p></div>
    """
    return _wrap(inner)


def tab_financials(r) -> str:
    fq   = r.financial_quality
    s    = r.stability
    mets = fq.metrics or {}

    def mc(label, key, suffix="", hi=True, thr=0):
        val = mets.get(key)
        if val is None: return ""
        try:
            f = float(val)
            if abs(f) <= 1 and "margin" in key: f *= 100
            col = "green" if (f > thr if hi else f < thr) else "red"
            return f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value {col}">{f:.2f}{suffix}</div></div>'
        except: return f'<div class="metric"><div class="metric-label">{label}</div><div class="metric-value">{val}</div></div>'

    flags = ""
    for flag in (fq.flags or []):
        cls  = "alert-red" if any(w in flag.lower() for w in ["negative","low","warn","high debt"]) else "alert-green"
        flags += f'<div class="alert {cls}"><span>{"✕" if cls=="alert-red" else "✓"}</span><div>{flag}</div></div>'

    stab_rows = [
        ("Revenue CAGR 5yr",       f"{_num(s.revenue_cagr_5yr,'%',1)}"  if s.revenue_cagr_5yr  is not None else "N/A", "green" if (s.revenue_cagr_5yr or 0)>5 else "amber"),
        ("Revenue CAGR 10yr",      f"{_num(s.revenue_cagr_10yr,'%',1)}" if s.revenue_cagr_10yr is not None else "N/A", ""),
        ("Earnings CAGR 5yr",      f"{_num(s.earnings_cagr_5yr,'%',1)}" if s.earnings_cagr_5yr is not None else "N/A", "green" if (s.earnings_cagr_5yr or 0)>5 else "amber"),
        ("Revenue Volatility CoV", _num(s.revenue_volatility,"",2)       if s.revenue_volatility  else "N/A", "green" if (s.revenue_volatility or 1)<0.3 else "red"),
        ("Earnings Volatility CoV",_num(s.earnings_volatility,"",2)      if s.earnings_volatility else "N/A", "green" if (s.earnings_volatility or 1)<0.3 else "red"),
        ("Consecutive Profit Yrs", str(s.consecutive_profit_years or "N/A"), "green" if (s.consecutive_profit_years or 0)>=7 else "amber"),
        ("Dividend Consistency",   s.dividend_consistency or "N/A", ""),
        ("Revenue Trend R²",       _num(s.regression_r_squared,"",2) if s.regression_r_squared else "N/A", ""),
    ]
    sr = "".join(f"<tr><td>{l}</td><td class='mono {c}'>{v}</td></tr>" for l,v,c in stab_rows)

    inner = f"""
    <div class="section-header">
      <span class="section-step">Step 3 + 4</span>
      <span class="section-title">Financial Quality &amp; Stability</span>
      <span class="score-chip {_sc(fq.score)}">Quality {int(fq.score or 0)} · Stability {int(s.score or 0)}</span>
    </div>
    <div class="metrics-grid">
      {mc("ROE 5yr avg","roe_avg_5yr","%",True,15)}
      {mc("ROIC 5yr avg","roic_avg_5yr","%",True,10)}
      {mc("Debt / Equity","debt_to_equity_current","×",False,1)}
      {mc("Interest Coverage","interest_coverage","×",True,3)}
      {mc("FCF / Net Income","fcf_to_net_income_avg","×",True,0.8)}
      {mc("Gross Margin avg","gross_margin_avg","%",True,40)}
      {mc("Operating Margin avg","operating_margin_avg","%",True,10)}
      {mc("CapEx / Revenue avg","capex_to_revenue_avg","%",False,15)}
    </div>
    {flags}
    <div class="card"><div class="card-title">Financial Quality Rationale</div><p>{fq.rationale or ''}</p></div>
    <div class="card"><div class="card-title">Stability Metrics</div>
      <table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>{sr}</tbody></table>
      <p style="margin-top:12px">{s.rationale or ''}</p>
    </div>"""
    return _wrap(inner)



def tab_valuation(r) -> str:
    import json as _json
    v  = r.valuation
    m  = r.margin_of_safety
    cs = "¥" if getattr(r, "currency", "") == "CNY" else "$"

    def heat(val):
        if not v.current_price or not val: return ""
        r2 = val / v.current_price
        return "heat-1" if r2>2 else ("heat-2" if r2>1.5 else ("heat-3" if r2>1 else ("heat-4" if r2>0.7 else "heat-5")))

    # Serialise all scenarios into one JS object
    def sc_dict(name, sc):
        return {
            "label": name,
            "owner_earnings": sc.owner_earnings,
            "growth_rate": sc.growth_rate,
            "discount_rate": sc.discount_rate,
            "terminal_growth_rate": sc.terminal_growth_rate,
            "maintenance_capex": sc.maintenance_capex,
            "maintenance_capex_method": sc.maintenance_capex_method,
            "projected_cash_flows": sc.projected_cash_flows,
            "terminal_value": sc.terminal_value,
            "present_value": sc.present_value,
            "per_share_value": sc.per_share_value,
            "assumptions": sc.assumptions,
            "current_price": v.current_price,
            "cs": cs,
        }

    all_sc = {
        "Bull": sc_dict("Bull", v.bull),
        "Base": sc_dict("Base", v.base),
        "Bear": sc_dict("Bear", v.bear),
        "EPV": {
            "label": "EPV",
            "owner_earnings": v.base.owner_earnings,
            "growth_rate": 0,
            "discount_rate": v.base.discount_rate,
            "terminal_growth_rate": 0,
            "projected_cash_flows": [],
            "terminal_value": 0,
            "present_value": v.epv,
            "per_share_value": v.epv_per_share,
            "current_price": v.current_price,
            "cs": cs,
            "assumptions": [
                "EPV = Owner Earnings / Discount Rate (zero growth assumed)",
                f"Owner Earnings: {cs}{v.base.owner_earnings:,.0f}",
                f"Discount Rate: {v.base.discount_rate:.0%}",
                f"EPV total: {cs}{v.epv:,.0f}",
            ],
        }
    }
    sc_json = _json.dumps(all_sc, ensure_ascii=False)

    # Scenario table rows
    scen = ""
    for name, sc_obj, col in [("Bull", v.bull, "green"), ("Base", v.base, "amber"), ("Bear", v.bear, "red")]:
        iv  = sc_obj.per_share_value
        vsp = f"{((iv/v.current_price)-1)*100:+.1f}%" if iv and v.current_price else "N/A"
        vc  = "green" if iv and v.current_price and iv > v.current_price else "red"
        scen += f"""<tr class="scen-row" onclick="openPanel('{name}')" title="Click to see full breakdown">
          <td><strong>{name}</strong> <span class="detail-hint">↗ detail</span></td>
          <td class="mono">{sc_obj.growth_rate:.1%}</td>
          <td class="mono">{sc_obj.discount_rate:.0%}</td>
          <td class="mono">{sc_obj.terminal_growth_rate:.0%}</td>
          <td class="mono {col} clickval">{_money(iv, cs)}</td>
          <td class="mono {vc}">{vsp}</td></tr>"""

    if v.epv_per_share and v.current_price:
        ec  = "green" if v.epv_per_share > v.current_price else "red"
        epv_pct = f"{((v.epv_per_share/v.current_price)-1)*100:+.1f}%"
        scen += f"""<tr class="scen-row" onclick="openPanel('EPV')" title="Click to see EPV breakdown">
          <td><strong>EPV</strong> <span class="detail-hint">↗ detail</span></td>
          <td class="mono">0%</td><td class="mono">—</td><td class="mono">—</td>
          <td class="mono clickval">{_money(v.epv_per_share, cs)}</td>
          <td class="mono {ec}">{epv_pct}</td></tr>"""

    # Sensitivity table
    sens = ""
    if v.sensitivity_table:
        sr = ""
        for row in v.sensitivity_table:
            dr = row.get("discount_rate", 0)
            v2, v3, v4 = row.get("tg_2%", 0), row.get("tg_3%", 0), row.get("tg_4%", 0)
            sr += f"<tr><td>{dr:.0%}</td><td class='mono {heat(v2)}'>{_money(v2,cs)}</td><td class='mono {heat(v3)}'>{_money(v3,cs)}</td><td class='mono {heat(v4)}'>{_money(v4,cs)}</td></tr>"
        sens = f"""<div class="card"><div class="card-title">Sensitivity — Discount Rate × Terminal Growth</div>
          <table><thead><tr><th>Discount</th><th>TG 2%</th><th>TG 3%</th><th>TG 4%</th></tr></thead>
          <tbody>{sr}</tbody></table>
          <p style="font-size:12px;color:var(--text-dim);margin-top:8px">Green = significant upside. Red = near or below current price.</p></div>"""

    # Evidence trail
    evidence_items = "".join(
        f'<li style="font-family:\'DM Mono\',monospace;font-size:12px;color:var(--text-muted);'
        f'padding:3px 0 3px 14px;position:relative;border-bottom:1px solid var(--border)">'
        f'<span style="position:absolute;left:0;color:var(--text-dim)">›</span>{e}</li>'
        for e in (v.evidence or [])
    )

    mc_color = "green" if (m.margin_of_safety_pct or 0) > 25 else ("amber" if (m.margin_of_safety_pct or 0) > 0 else "red")

    inner = f"""
<style>
.scen-row {{ cursor:pointer; transition:background .12s; }}
.scen-row:hover td {{ background:rgba(29,111,165,.06) !important; }}
.scen-row.active-row td {{ background:rgba(29,111,165,.10) !important; border-color:rgba(29,111,165,.2); }}
.detail-hint {{ font-size:11px; color:var(--accent); margin-left:4px; }}
.clickval {{ cursor:pointer; text-decoration:underline dotted var(--accent); }}
/* split layout */
.val-layout {{ display:flex; gap:14px; align-items:flex-start; }}
.val-left  {{ flex:1; min-width:0; }}
.val-right {{ width:360px; flex-shrink:0; }}
/* panel */
.detail-panel {{ background:#fff; border:1px solid var(--border); border-radius:10px;
  box-shadow:0 4px 20px rgba(0,0,0,.10); overflow:hidden; display:none; }}
.detail-panel.open {{ display:block; animation:slideIn .2s ease; }}
@keyframes slideIn {{ from{{opacity:0;transform:translateY(-8px)}} to{{opacity:1;transform:translateY(0)}} }}
.dp-header {{ padding:14px 16px 12px; border-bottom:1px solid var(--border); background:var(--surface2); }}
.dp-title  {{ font-family:'Playfair Display',serif; font-size:16px; font-weight:700; margin-bottom:2px; }}
.dp-sub    {{ font-size:11px; color:var(--text-muted); }}
.dp-result {{ display:grid; grid-template-columns:1fr 1fr; gap:0; border-bottom:1px solid var(--border); }}
.dp-result-cell {{ padding:12px 16px; }}
.dp-result-cell:first-child {{ border-right:1px solid var(--border); }}
.dp-lbl    {{ font-size:10px; color:var(--text-dim); text-transform:uppercase; letter-spacing:1px; margin-bottom:3px; }}
.dp-val    {{ font-family:'DM Mono',monospace; font-size:22px; font-weight:500; }}
.dp-body   {{ padding:14px 16px; max-height:540px; overflow-y:auto; }}
.dp-section-title {{ font-size:10px; color:var(--text-dim); text-transform:uppercase;
  letter-spacing:1px; font-weight:600; margin:12px 0 6px; }}
.dp-section-title:first-child {{ margin-top:0; }}
/* param inputs */
.param-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px; }}
.param-item {{ background:var(--surface2); border:1px solid var(--border); border-radius:7px; padding:8px 10px; }}
.param-lbl  {{ font-size:10px; color:var(--text-muted); margin-bottom:4px; }}
.param-row  {{ display:flex; align-items:center; gap:4px; }}
.param-inp  {{ flex:1; border:none; background:transparent; font-family:'DM Mono',monospace;
  font-size:14px; color:var(--text); outline:none; width:0; min-width:0; }}
.param-inp:focus {{ color:var(--accent); }}
.param-unit {{ font-size:11px; color:var(--text-dim); flex-shrink:0; }}
.recalc-btn {{ width:100%; padding:8px; background:var(--accent); color:#fff; border:none;
  border-radius:7px; font-size:13px; font-weight:500; cursor:pointer;
  font-family:'DM Sans',sans-serif; margin-bottom:12px; }}
.recalc-btn:hover {{ background:#1558830; opacity:.9; }}
/* recalc result */
.recalc-result {{ background:var(--surface2); border:1px solid var(--border); border-radius:7px;
  padding:10px 12px; margin-bottom:12px; display:none; }}
.recalc-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
/* cf bars */
.cf-row  {{ display:flex; align-items:center; gap:6px; margin-bottom:5px; }}
.cf-yr   {{ font-family:'DM Mono',monospace; font-size:10px; color:var(--text-dim); width:28px; flex-shrink:0; }}
.cf-bar  {{ height:14px; border-radius:2px; min-width:3px; }}
.cf-amt  {{ font-family:'DM Mono',monospace; font-size:11px; color:var(--text-muted); white-space:nowrap; }}
/* pv breakdown */
.pv-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
.pv-cell {{ border-radius:7px; padding:10px 12px; }}
/* assumptions */
.assump-item {{ font-family:'DM Mono',monospace; font-size:11px; color:var(--text-muted);
  padding:4px 0 4px 12px; position:relative; border-bottom:1px solid var(--border); }}
.assump-item:last-child {{ border-bottom:none; }}
.assump-item::before {{ content:'›'; position:absolute; left:0; color:var(--text-dim); }}
</style>

<div class="section-header">
  <span class="section-step">Step 5 + 6</span>
  <span class="section-title">Intrinsic Value &amp; Margin of Safety</span>
  <span class="score-chip {_sc(m.score)}">MoS {int(m.score or 0)}/100 · {_pct(m.margin_of_safety_pct)}</span>
</div>

<div style="font-size:12px;color:var(--accent);background:var(--accent-dim);border:1px solid rgba(29,111,165,.2);
  border-radius:6px;padding:7px 12px;margin-bottom:14px">
  💡 <strong>Click any scenario row</strong> to open the full calculation breakdown and edit parameters on the right →
</div>

<div class="metrics-grid" style="margin-bottom:16px">
  <div class="metric"><div class="metric-label">Current Price</div><div class="metric-value">{_money(v.current_price,cs)}</div></div>
  <div class="metric clickval" onclick="openPanel('Base')" title="Click for Base IV detail">
    <div class="metric-label">Base IV ↗</div><div class="metric-value green">{_money(v.base.per_share_value,cs)}</div></div>
  <div class="metric"><div class="metric-label">Margin of Safety</div><div class="metric-value {mc_color}">{_pct(m.margin_of_safety_pct)}</div></div>
  <div class="metric clickval" onclick="openPanel('EPV')" title="Click for EPV detail">
    <div class="metric-label">EPV / Share ↗</div><div class="metric-value amber">{_money(v.epv_per_share,cs)}</div></div>
  <div class="metric"><div class="metric-label">Bull Upside</div><div class="metric-value green">{_pct(m.bull_upside_pct)}</div></div>
  <div class="metric"><div class="metric-label">Bear Downside</div><div class="metric-value red">{_pct(m.bear_downside_pct)}</div></div>
</div>

<!-- SPLIT LAYOUT -->
<div class="val-layout">
  <!-- LEFT: table + sensitivity -->
  <div class="val-left">
    <div class="card">
      <div class="card-title">Scenario Range — click any row for full breakdown →</div>
      <table>
        <thead><tr><th>Scenario</th><th>Growth</th><th>Discount</th><th>Term. Growth</th><th>Per Share IV</th><th>vs Price</th></tr></thead>
        <tbody id="scen-tbody">{scen}</tbody>
      </table>
    </div>
    {sens}
    <div class="card">
      <div class="card-title">Calculation Evidence Trail</div>
      <ul style="list-style:none;padding:0">{evidence_items}</ul>
    </div>
    <div class="card"><div class="card-title">Valuation Rationale</div><p>{v.rationale or ''}</p></div>
    <div class="card"><div class="card-title">MoS Verdict: {m.verdict or ''}</div><p>{m.rationale or ''}</p></div>
  </div>

  <!-- RIGHT: detail panel (appears when row clicked) -->
  <div class="val-right">
    <div id="detail-panel" class="detail-panel">

      <!-- Header -->
      <div class="dp-header">
        <div class="dp-title" id="dp-title">Select a scenario</div>
        <div class="dp-sub" id="dp-sub">Click any row in the table</div>
      </div>

      <!-- IV + vs price -->
      <div class="dp-result">
        <div class="dp-result-cell">
          <div class="dp-lbl">Intrinsic Value / Share</div>
          <div class="dp-val" id="dp-iv">—</div>
        </div>
        <div class="dp-result-cell">
          <div class="dp-lbl">vs Market Price</div>
          <div class="dp-val" id="dp-vs">—</div>
        </div>
      </div>

      <!-- Scrollable body -->
      <div class="dp-body">

        <!-- Editable params -->
        <div class="dp-section-title">Parameters — edit &amp; recalculate ✏️</div>
        <div class="param-grid" id="dp-params"></div>
        <button class="recalc-btn" onclick="recalc()">↻ Recalculate DCF</button>
        <div class="recalc-result" id="dp-recalc">
          <div class="dp-section-title" style="margin-top:0">Recalculated Result</div>
          <div class="recalc-grid" id="dp-recalc-grid"></div>
        </div>

        <!-- Assumptions -->
        <div class="dp-section-title">Assumptions</div>
        <div id="dp-assumptions"></div>

        <!-- Cash flows -->
        <div id="dp-cf-wrap">
          <div class="dp-section-title">Projected Cash Flows</div>
          <div id="dp-cfs"></div>
        </div>

        <!-- PV breakdown -->
        <div id="dp-pv-wrap">
          <div class="dp-section-title">PV Breakdown</div>
          <div class="pv-grid" id="dp-pv"></div>
          <div style="margin-top:8px;background:var(--surface2);border:1px solid var(--border);
            border-radius:7px;padding:9px 12px;display:flex;justify-content:space-between">
            <span style="font-size:12px;color:var(--text-muted)">Total Enterprise Value</span>
            <span style="font-family:'DM Mono',monospace;font-size:13px;font-weight:500" id="dp-pv-total">—</span>
          </div>
        </div>

      </div><!-- /dp-body -->
    </div><!-- /detail-panel -->
  </div><!-- /val-right -->
</div><!-- /val-layout -->

<script>
var _SCENARIOS = {sc_json};
var _curData   = null;
var _curName   = null;

var COLORS = {{Bull:'#059669', Base:'#d97706', Bear:'#dc2626', EPV:'#2563eb'}};

function openPanel(name) {{
  var data = _SCENARIOS[name];
  if (!data) return;
  _curData = data;
  _curName = name;

  // Highlight active row
  document.querySelectorAll('.scen-row').forEach(function(tr) {{
    tr.classList.remove('active-row');
    if (tr.querySelector('strong') && tr.querySelector('strong').textContent === name)
      tr.classList.add('active-row');
  }});

  var col = COLORS[name] || '#1d6fa5';
  var csp = data.cs || '$';
  var iv  = data.per_share_value || 0;
  var prc = data.current_price   || 0;

  document.getElementById('dp-title').textContent = name + ' Scenario — DCF Breakdown';
  document.getElementById('dp-sub').textContent   = name === 'EPV'
    ? 'Earnings Power Value (zero-growth assumption)'
    : '2-Stage Owner Earnings DCF · edit values below to recalculate';

  var el = document.getElementById('dp-iv');
  el.textContent = csp + iv.toLocaleString('en', {{minimumFractionDigits:2, maximumFractionDigits:2}});
  el.style.color = col;

  var pct = prc > 0 ? ((iv/prc - 1)*100) : 0;
  var elv = document.getElementById('dp-vs');
  elv.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(1) + '%';
  elv.style.color = pct >= 0 ? '#059669' : '#dc2626';

  renderParams(data, col);
  renderAssumptions(data);
  renderCFs(data, col);
  renderPV(data, col, csp);

  document.getElementById('dp-recalc').style.display = 'none';
  var panel = document.getElementById('detail-panel');
  panel.classList.add('open');
  panel.scrollIntoView({{behavior:'smooth', block:'nearest'}});
}}

// ── Editable params ───────────────────────────────────────────────────────
var FIELDS = [
  {{key:'owner_earnings',      label:'Owner Earnings',  scale:1e6,  suffix:'M',  decimals:1}},
  {{key:'growth_rate',         label:'Growth Rate',     scale:100,  suffix:'%',  decimals:1}},
  {{key:'discount_rate',       label:'Discount Rate',   scale:100,  suffix:'%',  decimals:1}},
  {{key:'terminal_growth_rate',label:'Terminal Growth', scale:100,  suffix:'%',  decimals:1}},
  {{key:'maintenance_capex',   label:'Maint CapEx',     scale:1e6,  suffix:'M',  decimals:1}},
];

function renderParams(data, col) {{
  var html = '';
  for (var i=0; i<FIELDS.length; i++) {{
    var f   = FIELDS[i];
    var raw = data[f.key];
    if (raw === undefined || raw === null) continue;
    var disp = (raw * f.scale).toFixed(f.decimals);
    html += '<div class="param-item">' +
            '<div class="param-lbl">' + f.label + '</div>' +
            '<div class="param-row">' +
            '<input class="param-inp" id="pi-' + f.key + '" type="number" step="any" value="' + disp + '">' +
            '<span class="param-unit">' + f.suffix + '</span></div></div>';
  }}
  document.getElementById('dp-params').innerHTML = html;
}}

// ── Recalculate ───────────────────────────────────────────────────────────
function recalc() {{
  if (!_curData) return;
  var data = JSON.parse(JSON.stringify(_curData));

  for (var i=0; i<FIELDS.length; i++) {{
    var f   = FIELDS[i];
    var inp = document.getElementById('pi-' + f.key);
    if (inp) {{
      var v2 = parseFloat(inp.value);
      if (!isNaN(v2)) data[f.key] = v2 / f.scale;
    }}
  }}

  var oe  = data.owner_earnings;
  var g   = data.growth_rate;
  var dr  = data.discount_rate;
  var tg  = data.terminal_growth_rate;
  var N   = 10, fade = 5;
  var csp = data.cs || '$';
  var prc = data.current_price || 0;
  if (dr <= tg) tg = dr - 0.01;

  var cfs = [], prev = oe;
  for (var t=1; t<=N; t++) {{
    var gRate = t <= fade ? g : g + (tg - g)*((t-fade)/(N-fade));
    var cf    = prev * (1 + gRate);
    cfs.push(cf); prev = cf;
  }}
  var finalCf = cfs[N-1];
  var tv  = finalCf * (1+tg) / (dr-tg);
  var pvCf = cfs.reduce(function(a,c,i){{return a+c/Math.pow(1+dr,i+1);}}, 0);
  var pvTv = tv / Math.pow(1+dr, N);
  var total= pvCf + pvTv;

  var origShares = (_curData.present_value > 0 && _curData.per_share_value > 0)
    ? _curData.present_value / _curData.per_share_value : 1;
  var ps  = origShares > 0 ? total / origShares : 0;
  var pct = prc > 0 ? ((ps/prc-1)*100) : 0;
  var col = COLORS[_curName] || '#1d6fa5';
  var fmt = function(v2){{ return v2>=1e9?(v2/1e9).toFixed(2)+'B':(v2/1e6).toFixed(0)+'M'; }};

  document.getElementById('dp-recalc-grid').innerHTML =
    '<div><div class="dp-lbl">New IV / Share</div>' +
    '<div style="font-family:\'DM Mono\',monospace;font-size:18px;font-weight:500;color:' + col + '">' +
    csp + ps.toLocaleString('en',{{minimumFractionDigits:2,maximumFractionDigits:2}}) + '</div></div>' +
    '<div><div class="dp-lbl">vs Price</div>' +
    '<div style="font-family:\'DM Mono\',monospace;font-size:18px;font-weight:500;color:' + (pct>=0?'#059669':'#dc2626') + '">' +
    (pct>=0?'+':'') + pct.toFixed(1) + '%</div></div>' +
    '<div><div class="dp-lbl">PV of CFs</div>' +
    '<div style="font-family:\'DM Mono\',monospace;font-size:13px;color:var(--text-muted)">' + csp + fmt(pvCf) + '</div></div>' +
    '<div><div class="dp-lbl">PV of Terminal</div>' +
    '<div style="font-family:\'DM Mono\',monospace;font-size:13px;color:var(--text-muted)">' + csp + fmt(pvTv) + '</div></div>';

  // Update header numbers
  document.getElementById('dp-iv').textContent = csp + ps.toLocaleString('en',{{minimumFractionDigits:2,maximumFractionDigits:2}});
  document.getElementById('dp-iv').style.color = col;
  document.getElementById('dp-vs').textContent = (pct>=0?'+':'') + pct.toFixed(1) + '%';
  document.getElementById('dp-vs').style.color = pct>=0?'#059669':'#dc2626';

  var el = document.getElementById('dp-recalc');
  el.style.display = 'block';
}}

// ── Assumptions ───────────────────────────────────────────────────────────
function renderAssumptions(data) {{
  var items = (data.assumptions || []);
  if (data.maintenance_capex_method)
    items = items.concat(['Maint CapEx method: ' + data.maintenance_capex_method]);
  var html = '';
  for (var i=0; i<items.length; i++)
    html += '<div class="assump-item">' + items[i] + '</div>';
  document.getElementById('dp-assumptions').innerHTML = html || '<div class="assump-item">No assumptions recorded.</div>';
}}

// ── Cash flow bars ────────────────────────────────────────────────────────
function renderCFs(data, col) {{
  var cfs = data.projected_cash_flows || [];
  var wrap = document.getElementById('dp-cf-wrap');
  if (!cfs.length) {{ wrap.style.display='none'; return; }}
  wrap.style.display = 'block';
  var max  = Math.max.apply(null, cfs);
  var csp  = data.cs || '$';
  var html = '';
  for (var i=0; i<cfs.length; i++) {{
    var w   = max>0 ? (cfs[i]/max*220) : 0;
    var fmt = cfs[i]>=1e9?(cfs[i]/1e9).toFixed(2)+'B':(cfs[i]/1e6).toFixed(0)+'M';
    html += '<div class="cf-row"><span class="cf-yr">Yr'+(i+1)+'</span>' +
            '<div class="cf-bar" style="width:'+w.toFixed(0)+'px;background:'+col+'22;border-left:3px solid '+col+'"></div>' +
            '<span class="cf-amt">'+csp+fmt+'</span></div>';
  }}
  if (data.terminal_value) {{
    var tv  = data.terminal_value;
    var fmt2= tv>=1e9?(tv/1e9).toFixed(2)+'B':(tv/1e6).toFixed(0)+'M';
    html += '<div class="cf-row" style="margin-top:5px;padding-top:5px;border-top:1px dashed var(--border)">' +
            '<span class="cf-yr" style="color:var(--accent)">TV</span>' +
            '<div class="cf-bar" style="width:220px;background:var(--accent-dim);border-left:3px solid var(--accent)"></div>' +
            '<span class="cf-amt" style="color:var(--accent)">'+csp+fmt2+'</span></div>';
  }}
  document.getElementById('dp-cfs').innerHTML = html;
}}

// ── PV breakdown ──────────────────────────────────────────────────────────
function renderPV(data, col, csp) {{
  var wrap = document.getElementById('dp-pv-wrap');
  if (!data.present_value) {{ wrap.style.display='none'; return; }}
  wrap.style.display = 'block';
  var pvTv  = data.present_value > 0 && data.terminal_value > 0
    ? data.terminal_value / Math.pow(1+(data.discount_rate||0.1), 10) : 0;
  var pvCf  = Math.max(data.present_value - pvTv, 0);
  pvTv = data.present_value - pvCf;
  var pctCf = data.present_value > 0 ? (pvCf/data.present_value*100) : 50;
  var fmt   = function(v2){{ return v2>=1e9?(v2/1e9).toFixed(2)+'B':(v2/1e6).toFixed(0)+'M'; }};

  document.getElementById('dp-pv').innerHTML =
    '<div class="pv-cell" style="background:'+col+'11;border:1px solid '+col+'33">' +
    '<div class="dp-lbl">PV of Cash Flows</div>' +
    '<div style="font-family:\'DM Mono\',monospace;font-size:15px;font-weight:500;color:'+col+'">' + csp+fmt(pvCf) + '</div>' +
    '<div style="font-size:11px;color:var(--text-dim)">'+pctCf.toFixed(0)+'% of total</div></div>' +
    '<div class="pv-cell" style="background:var(--accent-dim);border:1px solid rgba(29,111,165,.2)">' +
    '<div class="dp-lbl">PV of Terminal Value</div>' +
    '<div style="font-family:\'DM Mono\',monospace;font-size:15px;font-weight:500;color:var(--accent)">' + csp+fmt(pvTv) + '</div>' +
    '<div style="font-size:11px;color:var(--text-dim)">'+(100-pctCf).toFixed(0)+'% of total</div></div>';

  document.getElementById('dp-pv-total').textContent = csp + fmt(data.present_value);
}}
</script>"""
    return _wrap(inner)



def tab_risks(r) -> str:
    items = ""
    for issue in (r.validation_issues or []):
        sev = issue.get("severity","")
        cls = "risk-high" if sev=="error" else "risk-med"
        items += f"""<div class="risk-item {cls}"><div class="risk-dot"></div>
          <div><div class="risk-label">{"❌" if sev=="error" else "⚠"} {issue.get("category","").replace("_"," ").title()}</div>
          <div class="risk-desc">{issue.get("message","")}</div></div></div>"""
    s = r.stability
    if (s.revenue_volatility or 0) > 0.4:
        items += f"""<div class="risk-item risk-med"><div class="risk-dot"></div>
          <div><div class="risk-label">📉 High Revenue Volatility</div>
          <div class="risk-desc">CoV {_num(s.revenue_volatility,"",2)} — reduces DCF confidence.</div></div></div>"""
    if not items:
        items = '<p style="color:var(--text-muted)">No material risk flags identified.</p>'

    mon = "".join(
        f"<tr><td>{mi}</td><td class='mono amber'>—</td><td>Review position</td></tr>"
        for mi in (r.recommendation.monitoring_metrics or [])
    )
    mon_tbl = f"""<div class="card"><div class="card-title">Monitoring Triggers</div>
      <table><thead><tr><th>Metric</th><th>Alert Level</th><th>Action</th></tr></thead>
      <tbody>{mon}</tbody></table></div>""" if mon else ""

    inner = f"""
    <div class="section-header">
      <span class="section-step">Risk Register</span>
      <span class="section-title">Key Risks</span>
    </div>
    <div class="card">{items}</div>{mon_tbl}"""
    return _wrap(inner)


def tab_news(r) -> str:
    tk = r.ticker.replace("'","\\'")
    co = (r.name or r.ticker).replace("'","\\'")
    inner = f"""
    <div class="section-header">
      <span class="section-step">Live</span>
      <span class="section-title">News &amp; Regulatory Filings</span>
    </div>
    <div class="news-toolbar">
      <button class="nfbtn active" onclick="fN('all',this)">All</button>
      <button class="nfbtn" onclick="fN('filing',this)">📋 SEC Filings</button>
      <button class="nfbtn" onclick="fN('earnings',this)">📈 Earnings</button>
      <button class="nfbtn" onclick="fN('risk',this)">⚠ Regulatory</button>
      <button class="nfbtn" onclick="fN('analyst',this)">🔬 Analyst</button>
      <button class="nfbtn" onclick="fN('news',this)">📰 News</button>
      <button class="refresh-btn" onclick="load()">↻ Refresh</button>
    </div>
    <div id="nc"><div class="news-loading"><div class="spinner"></div><div>Loading {r.ticker} news…</div></div></div>
    <div class="disclaimer">⚠ AI-powered web search. Always verify from primary sources. Not financial advice.</div>
    <script>
    var _T='{tk}',_C='{co}',_F='all';
    function fN(t,b){{_F=t;document.querySelectorAll('.nfbtn').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.querySelectorAll('.ni').forEach(x=>{{x.style.display=(t==='all'||x.dataset.t===t)?'block':'none';}});}}
    async function load(){{
      var c=document.getElementById('nc');
      c.innerHTML='<div class="news-loading"><div class="spinner"></div><div>Searching '+_T+' news…</div></div>';
      try{{
        var r=await fetch("https://api.anthropic.com/v1/messages",{{method:"POST",headers:{{"Content-Type":"application/json"}},
          body:JSON.stringify({{model:"claude-sonnet-4-20250514",max_tokens:1000,
            tools:[{{type:"web_search_20250305",name:"web_search"}}],
            system:"You are a financial research assistant. Search for recent news about "+_T+" ("+_C+"). Return ONLY a raw JSON array (no markdown): [{{\\\"title\\\":\\\"...\\\",\\\"source\\\":\\\"...\\\",\\\"date\\\":\\\"YYYY-MM-DD\\\",\\\"summary\\\":\\\"2-3 sentences\\\",\\\"type\\\":\\\"filing|earnings|risk|analyst|news\\\",\\\"impact\\\":\\\"high|medium|low\\\",\\\"url\\\":\\\"...\\\"}}]. 6-8 items sorted by date.",
            messages:[{{role:"user",content:"Latest news filings earnings for "+_T+". JSON only."}}]}})}});
        var d=await r.json(),raw='';
        for(var b of d.content)if(b.type==='text')raw+=b.text;
        var cl=raw.replace(/```json|```/g,'').trim(),s=cl.indexOf('['),e=cl.lastIndexOf(']');
        if(s<0||e<0)throw 0;
        render(JSON.parse(cl.slice(s,e+1)));
      }}catch(err){{c.innerHTML='<div class="alert alert-warn"><span>⚠</span><div>Unable to load live news — deploy with a valid Anthropic API key.</div></div>';}}
    }}
    function render(items){{
      var c=document.getElementById('nc');
      if(!items||!items.length){{c.innerHTML='<div class="news-loading">No items found.</div>';return;}}
      var tM={{filing:'<span class="news-tag tag-filing">📋 Filing</span>',earnings:'<span class="news-tag tag-earnings">📈 Earnings</span>',risk:'<span class="news-tag tag-risk">⚠ Regulatory</span>',analyst:'<span class="news-tag tag-analyst">🔬 Analyst</span>',news:'<span class="news-tag tag-news">📰 News</span>'}};
      var iM={{high:'<span style="font-size:12px;color:var(--red)">● High</span>',medium:'<span style="font-size:12px;color:var(--warn)">● Medium</span>',low:'<span style="font-size:12px;color:var(--text-muted)">● Low</span>'}};
      c.innerHTML=items.map(i=>'<div class="news-item ni" data-t="'+i.type+'" '+(i.url?'onclick="window.open(\''+i.url+'\',\'_blank\')"':'')+'><div class="news-item-top"><div class="news-item-title">'+i.title+'</div>'+(tM[i.type]||tM.news)+'</div><div class="news-summary">'+i.summary+'</div><div class="news-meta"><span class="news-source">'+i.source+'</span><span class="news-date">'+i.date+'</span>'+(iM[i.impact]||'')+'</div></div>').join('');
      if(_F!=='all')document.querySelectorAll('.ni').forEach(x=>{{x.style.display=x.dataset.t===_F?'block':'none';}});
    }}
    load();
    </script>"""
    return _wrap(inner)


def tab_conclusion(r) -> str:
    rec = r.recommendation
    sb  = rec.score_breakdown or {}
    bars = ""
    for key, label, w in [("circle_of_competence","Circle of Competence",10),("moat","Moat",25),("financial_quality","Financial Quality",20),("stability","Stability",15),("margin_of_safety","Margin of Safety",30)]:
        v2 = sb.get(key, 0)
        try: v2 = float(v2)
        except: v2 = 0
        bc = "var(--green)" if v2>=70 else ("var(--warn)" if v2>=50 else "var(--red)")
        bars += f"""<div class="score-bar-row">
          <div class="score-bar-label"><span>{label} <small style="color:var(--text-dim)">({w}%)</small></span><span>{int(v2)}</span></div>
          <div class="score-bar-bg"><div class="score-bar-fill" style="width:{v2}%;background:{bc}"></div></div></div>"""

    inner = f"""
    <div class="section-header">
      <span class="section-step">Final</span>
      <span class="section-title">Investment Conclusion</span>
      <span class="score-chip {_sc(rec.composite_score)}">{int(rec.composite_score or 0)}/100</span>
    </div>
    <div class="card"><div class="card-title">Score Breakdown</div><div style="margin-top:12px">{bars}</div></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0">
      <div class="alert alert-green"><span>✓</span><div><strong>Bull Case</strong><br><span style="font-size:13px">{rec.bull_case or ''}</span></div></div>
      <div class="alert alert-red"><span>✕</span><div><strong>Bear Case</strong><br><span style="font-size:13px">{rec.bear_case or ''}</span></div></div>
    </div>
    <div class="card"><div class="card-title">Recommendation</div><p><strong>{rec.action} — {rec.position_size}.</strong></p></div>
    <div class="disclaimer">Report generated {r.analysis_date}. For informational purposes only. Not investment advice.</div>"""
    return _wrap(inner)




def render_valuation_native(report):
    """Valuation tab rendered entirely with Streamlit native widgets — no iframe."""
    import numpy as np

    v   = report.valuation
    m   = report.margin_of_safety
    cs  = "¥" if getattr(report, "currency", "") == "CNY" else "$"

    def fmt_money(val):
        if val is None: return "N/A"
        try: return f"{cs}{float(val):,.2f}"
        except: return str(val)

    def fmt_pct(val):
        if val is None: return "N/A"
        try: return f"{float(val):.1f}%"
        except: return str(val)

    # ── Top metrics ──────────────────────────────────────────────────────────
    mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
    mc1.metric("Current Price",    fmt_money(v.current_price))
    mc2.metric("Base IV",          fmt_money(v.base.per_share_value))
    mc3.metric("Margin of Safety", fmt_pct(m.margin_of_safety_pct))
    mc4.metric("EPV / Share",      fmt_money(v.epv_per_share))
    mc5.metric("Bull Upside",      fmt_pct(m.bull_upside_pct))
    mc6.metric("Bear Downside",    fmt_pct(m.bear_downside_pct))

    st.markdown("---")
    st.caption("👇 Click **▶ Detail** on any scenario to see full calculation and edit parameters")

    # ── Scenario table + expanders ────────────────────────────────────────────
    scenarios = [
        ("🟢 Bull", v.bull,  "bull"),
        ("🟡 Base", v.base,  "base"),
        ("🔴 Bear", v.bear,  "bear"),
    ]

    def run_dcf(oe, g, dr, tg, proj_years=10):
        """Re-run 2-stage DCF with given params, return (cfs, tv, pv_cf, pv_tv, total, per_share)."""
        fade = min(5, proj_years)
        if dr <= tg:
            tg = dr - 0.01
        cfs, prev = [], oe
        for t in range(1, proj_years + 1):
            g_rate = g if t <= fade else g + (tg - g) * ((t - fade) / (proj_years - fade))
            cf = prev * (1 + g_rate)
            cfs.append(cf)
            prev = cf
        tv     = cfs[-1] * (1 + tg) / (dr - tg)
        pv_cf  = sum(cf / (1 + dr) ** (i + 1) for i, cf in enumerate(cfs))
        pv_tv  = tv / (1 + dr) ** proj_years
        total  = pv_cf + pv_tv
        shares = (v.base.present_value / v.base.per_share_value
                  if v.base.present_value > 0 and v.base.per_share_value > 0 else 1)
        per_share = total / shares if shares > 0 else 0
        return cfs, tv, pv_cf, pv_tv, total, per_share

    for label, sc, key in scenarios:
        iv  = sc.per_share_value or 0
        vsp = f"{((iv / v.current_price) - 1) * 100:+.1f}%" if iv and v.current_price else "N/A"

        # One-line summary row
        cols = st.columns([2, 1.5, 1.5, 1.5, 2, 1.5, 1])
        cols[0].markdown(f"**{label}**")
        cols[1].markdown(f"`{sc.growth_rate:.1%}` growth")
        cols[2].markdown(f"`{sc.discount_rate:.0%}` discount")
        cols[3].markdown(f"`{sc.terminal_growth_rate:.0%}` terminal")
        cols[4].markdown(f"**{fmt_money(iv)}** / share")
        cols[5].markdown(vsp)

        with st.expander(f"▶ Detail & Edit — {label.split()[-1]}", expanded=False):

            st.markdown(f"#### {label} — DCF Breakdown")

            # ── Editable parameters ─────────────────────────────────────────
            st.markdown("**Edit parameters and recalculate:**")
            p1, p2, p3, p4, p5 = st.columns(5)
            oe_m  = p1.number_input("Owner Earnings (M)",
                        value=round(sc.owner_earnings / 1e6, 1),
                        step=1.0, key=f"{key}_oe")
            g_pct = p2.number_input("Growth Rate (%)",
                        value=round(sc.growth_rate * 100, 1),
                        step=0.1, min_value=-20.0, max_value=80.0, key=f"{key}_g")
            dr_pct= p3.number_input("Discount Rate (%)",
                        value=round(sc.discount_rate * 100, 1),
                        step=0.1, min_value=1.0, max_value=30.0, key=f"{key}_dr")
            tg_pct= p4.number_input("Terminal Growth (%)",
                        value=round(sc.terminal_growth_rate * 100, 1),
                        step=0.1, min_value=0.0, max_value=10.0, key=f"{key}_tg")
            mc_m  = p5.number_input("Maint CapEx (M)",
                        value=round((sc.maintenance_capex or 0) / 1e6, 1),
                        step=1.0, key=f"{key}_mc")

            # Live recalculation (runs whenever any input changes)
            new_oe = oe_m * 1e6
            new_g  = g_pct / 100
            new_dr = dr_pct / 100
            new_tg = tg_pct / 100

            try:
                n_cfs, n_tv, n_pv_cf, n_pv_tv, n_total, n_ps = run_dcf(new_oe, new_g, new_dr, new_tg)
                n_vs    = f"{((n_ps / v.current_price) - 1) * 100:+.1f}%" if v.current_price else "N/A"
                delta_s = f"{n_ps - iv:+.2f}" if abs(n_ps - iv) > 0.001 else None
                cfs_to_show, tv_to_show = n_cfs, n_tv
                st.markdown("**\U0001f4ca Live Result**")
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("IV / Share",       f"{cs}{n_ps:,.2f}", delta=delta_s)
                r2.metric("vs Market Price",  n_vs)
                r3.metric("PV of Cash Flows", f"{cs}{n_pv_cf/1e6:.0f}M")
                r4.metric("PV of Terminal",   f"{cs}{n_pv_tv/1e6:.0f}M")
            except Exception as e:
                st.warning(f"Calculation error: {e}")
                cfs_to_show = sc.projected_cash_flows or []
                tv_to_show  = sc.terminal_value or 0

            st.markdown("---")

            # ── Two-column detail ───────────────────────────────────────────
            dl, dr_col = st.columns([1, 1])

            with dl:
                # Assumptions
                st.markdown("**📋 Assumptions used**")
                for assumption in (sc.assumptions or []):
                    st.caption(f"› {assumption}")
                if sc.maintenance_capex_method:
                    st.caption(f"› Maint CapEx: {sc.maintenance_capex_method}")

            with dr_col:
                # PV breakdown
                st.markdown("**💰 PV Breakdown**")
                if sc.present_value and sc.terminal_value:
                    pv_tv_orig = sc.terminal_value / (1 + sc.discount_rate) ** 10
                    pv_cf_orig = max(sc.present_value - pv_tv_orig, 0)
                    pv_tv_orig = sc.present_value - pv_cf_orig
                    b1, b2 = st.columns(2)
                    b1.metric("PV of Cash Flows",
                              f"{cs}{pv_cf_orig/1e6:.0f}M",
                              f"{pv_cf_orig/sc.present_value*100:.0f}% of total")
                    b2.metric("PV of Terminal Value",
                              f"{cs}{pv_tv_orig/1e6:.0f}M",
                              f"{pv_tv_orig/sc.present_value*100:.0f}% of total")
                    st.metric("Total Enterprise Value", f"{cs}{sc.present_value/1e6:.0f}M")

            # ── Cash flow chart ─────────────────────────────────────────────
            if cfs_to_show:
                st.markdown("**📈 Projected Cash Flows**")
                import pandas as pd
                years = [f"Yr {i+1}" for i in range(len(cfs_to_show))]
                df_cf = pd.DataFrame({"Year": years, f"Cash Flow ({cs}M)": [cf/1e6 for cf in cfs_to_show]})
                st.bar_chart(df_cf.set_index("Year"), height=200)
                if tv_to_show:
                    st.caption(f"Terminal Value: {cs}{tv_to_show/1e6:.0f}M")

        st.markdown("")  # spacer between scenarios

    # ── EPV expander ─────────────────────────────────────────────────────────
    cols = st.columns([2, 1.5, 1.5, 1.5, 2, 1.5, 1])
    cols[0].markdown("**⚪ EPV**")
    cols[1].markdown("`0%` growth")
    cols[2].markdown(f"`{v.base.discount_rate:.0%}` discount")
    cols[3].markdown("—")
    cols[4].markdown(f"**{fmt_money(v.epv_per_share)}** / share")
    epv_vs = f"{((v.epv_per_share / v.current_price) - 1) * 100:+.1f}%" if v.epv_per_share and v.current_price else "N/A"
    cols[5].markdown(epv_vs)

    with st.expander("▶ Detail — EPV (Earnings Power Value)", expanded=False):
        st.markdown("#### EPV — Zero-Growth Assumption")
        st.info(f"**Formula:** EPV = Owner Earnings ÷ Discount Rate  \n"
                f"= {cs}{v.base.owner_earnings/1e6:.1f}M ÷ {v.base.discount_rate:.0%}  \n"
                f"= **{cs}{v.epv/1e6:.0f}M** total  \n"
                f"= **{cs}{v.epv_per_share:,.2f} per share**")
        st.caption("EPV assumes zero earnings growth — a conservative floor value. "
                   "If IV > EPV, growth is required to justify the price.")

    st.markdown("---")

    # ── Sensitivity table ─────────────────────────────────────────────────────
    if v.sensitivity_table:
        st.markdown("**Sensitivity Table — Discount Rate × Terminal Growth**")
        import pandas as pd
        rows = []
        for row in v.sensitivity_table:
            dr = row.get("discount_rate", 0)
            rows.append({
                "Discount Rate": f"{dr:.0%}",
                f"TG 2%": f"{cs}{row.get('tg_2%',0):,.0f}",
                f"TG 3%": f"{cs}{row.get('tg_3%',0):,.0f}",
                f"TG 4%": f"{cs}{row.get('tg_4%',0):,.0f}",
            })
        st.dataframe(pd.DataFrame(rows).set_index("Discount Rate"), use_container_width=True)
        st.caption("Values are per-share intrinsic value estimates at the given discount/terminal growth combination.")

    st.markdown("---")

    # ── Evidence trail ────────────────────────────────────────────────────────
    with st.expander("📋 Full Calculation Evidence Trail", expanded=False):
        for e in (v.evidence or []):
            st.caption(f"› {e}")

    st.caption(v.rationale or "")
    st.caption(f"MoS Verdict: **{m.verdict or ''}** — {m.rationale or ''}")

def render_report(report):
    """Render a full report using Streamlit native tabs."""
    rec = report.recommendation
    rec_action = (rec.action or "").upper()

    # ── Header banner using Streamlit ─────────────────────────────────────────
    col_l, col_r = st.columns([3, 1])
    with col_l:
        st.markdown(f"### `{report.ticker}` &nbsp; {report.name or report.ticker}")
    with col_r:
        color = "🟢" if "BUY" in rec_action else ("🔴" if "SELL" in rec_action else "🟡")
        st.markdown(f"**{color} {rec.action} · {rec.position_size}** &nbsp;&nbsp; Score: **{int(rec.composite_score or 0)}/100**")

    st.divider()

    # ── Native Streamlit tabs ─────────────────────────────────────────────────
    t1, t2, t3, t4, t5, t6, t7 = st.tabs([
        "◎ Overview", "⬡ Moat", "▦ Financials",
        "◈ Valuation", "△ Risks", "⚡ News & Filings", "✦ Conclusion"
    ])

    with t1: components.html(tab_overview(report),    height=620, scrolling=True)
    with t2: components.html(tab_moat(report),        height=520, scrolling=True)
    with t3: components.html(tab_financials(report),  height=620, scrolling=True)
    with t4: render_valuation_native(report)
    with t5: components.html(tab_risks(report),       height=500, scrolling=True)
    with t6: components.html(tab_news(report),        height=600, scrolling=True)
    with t7: components.html(tab_conclusion(report),  height=580, scrolling=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Full HTML export (for download)
# ─────────────────────────────────────────────────────────────────────────────

def build_export_html(report) -> str:
    """Single-file HTML with all tabs, for download only."""
    parts = {
        "overview":   tab_overview(report),
        "moat":       tab_moat(report),
        "financials": tab_financials(report),
        "valuation":  tab_valuation(report),
        "risks":      tab_risks(report),
        "news":       tab_news(report),
        "final":      tab_conclusion(report),
    }
    # Extract <body> content from each _wrap() result
    def body(html):
        s = html.find("<body>") + 6
        e = html.find("</body>")
        return html[s:e]

    tabs_html = ""
    for key, label in [("overview","◎ Overview"),("moat","⬡ Moat"),("financials","▦ Financials"),
                        ("valuation","◈ Valuation"),("risks","△ Risks"),("news","⚡ News"),("final","✦ Conclusion")]:
        active = "active" if key == "overview" else ""
        tabs_html += f'<div id="tab-{key}" class="tab-panel {active}">{body(parts[key])}</div>'

    # Use the CSS from _wrap but adapt for single page
    sample_css = parts["overview"]
    css_start = sample_css.find("<style>") + 7
    css_end   = sample_css.find("</style>")
    css = sample_css[css_start:css_end]

    rec = report.recommendation
    rec_action = (rec.action or "").upper()
    rec_color = "green" if "BUY" in rec_action else ("red" if "SELL" in rec_action else "amber")

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{report.ticker} — Investment Analysis</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
{css}
html,body{{height:100%;margin:0}}
body{{display:flex;flex-direction:column;overflow:hidden}}
.ex-header{{flex-shrink:0;background:#fff;border-bottom:1px solid #e2e6ec;padding:14px 28px;display:flex;align-items:center;justify-content:space-between;height:55px;box-shadow:0 1px 3px rgba(0,0,0,.07)}}
.ex-ticker{{font-family:'DM Mono',monospace;font-size:13px;font-weight:500;background:rgba(29,111,165,.08);color:#1d6fa5;border:1px solid rgba(29,111,165,.3);border-radius:6px;padding:4px 10px;letter-spacing:1px}}
.ex-title{{font-family:'Playfair Display',serif;font-size:17px;font-weight:700;margin-left:12px}}
.ex-rec{{font-size:12px;font-weight:600;padding:4px 13px;border-radius:20px;letter-spacing:.5px}}
.rec-green{{background:rgba(5,150,105,.08);color:#059669;border:1px solid rgba(5,150,105,.3)}}
.rec-red{{background:rgba(220,38,38,.08);color:#dc2626;border:1px solid rgba(220,38,38,.3)}}
.rec-amber{{background:rgba(217,119,6,.08);color:#d97706;border:1px solid rgba(217,119,6,.3)}}
.ex-body{{flex:1;display:flex;overflow:hidden}}
.ex-nav{{width:190px;flex-shrink:0;background:#fff;border-right:1px solid #e2e6ec;padding:16px 0;overflow-y:auto}}
.ex-nav-lbl{{font-size:10px;color:#9ca3af;padding:7px 16px 3px;letter-spacing:1px;text-transform:uppercase}}
.ex-nav-item{{display:flex;align-items:center;gap:8px;padding:8px 16px;cursor:pointer;font-size:13px;color:#6b7280;border-left:2px solid transparent;transition:all .15s;user-select:none}}
.ex-nav-item:hover{{color:#111827;background:#f2f4f7}}
.ex-nav-item.active{{color:#1d6fa5;border-left-color:#1d6fa5;background:rgba(29,111,165,.08);font-weight:500}}
.ex-nav-div{{height:1px;background:#e2e6ec;margin:5px 12px}}
.ex-content{{flex:1;overflow-y:auto;padding:24px 28px;background:#f8f9fb}}
.tab-panel{{display:none}}.tab-panel.active{{display:block}}
</style></head><body>
<div class="ex-header">
  <div style="display:flex;align-items:center">
    <span class="ex-ticker">{report.ticker}</span>
    <span class="ex-title">{report.name or report.ticker}</span>
  </div>
  <div style="display:flex;align-items:center;gap:10px">
    <span style="font-family:'DM Mono',monospace;font-size:13px;color:#6b7280">Score <span style="color:#1d6fa5;font-weight:500">{int(rec.composite_score or 0)}/100</span></span>
    <span class="ex-rec rec-{rec_color}">{rec.action} · {rec.position_size}</span>
  </div>
</div>
<div class="ex-body">
  <nav class="ex-nav">
    <div class="ex-nav-lbl">Analysis</div>
    <div class="ex-nav-item active" onclick="sw('overview',this)">◎ Overview</div>
    <div class="ex-nav-item" onclick="sw('moat',this)">⬡ Moat</div>
    <div class="ex-nav-item" onclick="sw('financials',this)">▦ Financials</div>
    <div class="ex-nav-item" onclick="sw('valuation',this)">◈ Valuation</div>
    <div class="ex-nav-item" onclick="sw('risks',this)">△ Risks</div>
    <div class="ex-nav-div"></div>
    <div class="ex-nav-lbl">Live Data</div>
    <div class="ex-nav-item" onclick="sw('news',this)">⚡ News &amp; Filings</div>
    <div class="ex-nav-div"></div>
    <div class="ex-nav-lbl">Report</div>
    <div class="ex-nav-item" onclick="sw('final',this)">✦ Conclusion</div>
  </nav>
  <main class="ex-content">{tabs_html}</main>
</div>
<script>
function sw(name,el){{
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.ex-nav-item').forEach(n=>n.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  el.classList.add('active');
}}
</script></body></html>"""


# ─────────────────────────────────────────────────────────────────────────────
#  Streamlit App
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Buffett Analyzer", page_icon="🔬", layout="wide")
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

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

tab_company, tab_industry = st.tabs(["📊 Company Analysis", "🏭 Industry Analysis"])

# ── Company ───────────────────────────────────────────────────────────────────
with tab_company:
    col1, col2 = st.columns([4, 1])
    with col1:
        ticker = st.text_input("ticker", placeholder="Enter ticker  e.g. AAPL  PDD  TSLA",
                               key="company_ticker", label_visibility="collapsed")
    with col2:
        run_company = st.button("🔍 Analyze", key="run_company", type="primary", use_container_width=True)

    # Run analysis and cache in session_state
    if run_company and ticker:
        config.MIN_MOAT_SCORE = min_moat; config.MIN_FINANCIAL_SCORE = min_fq; config.MIN_STABILITY_SCORE = min_stab
        progress = st.empty()
        def company_progress(msg): progress.info(msg)
        with st.spinner(f"Analyzing {ticker.upper()}…"):
            try:
                data_client = YFinanceClient()
                llm = None
                if anthropic_key:
                    try: llm = ClaudeClient(api_key=anthropic_key)
                    except LLMError: st.warning("⚠️ Anthropic key invalid — running without LLM")
                edgar = EdgarClient() if use_edgar else None
                report = run_company_analysis(
                    ticker=ticker, data_client=data_client, llm=llm, edgar=edgar,
                    discount_rate=discount_rate, terminal_growth=terminal_growth,
                    projection_years=projection_years, progress_callback=company_progress,
                )
                progress.empty()
                # Save to session state so parameter edits don't wipe the report
                st.session_state["company_report"] = report
                st.session_state["company_ticker_done"] = ticker.upper()
            except YFinanceError as e: progress.empty(); st.error(f"❌ Data Error: {e}")
            except RuntimeError  as e: progress.empty(); st.error(f"❌ {e}")
            except Exception     as e: progress.empty(); st.error(f"❌ {e}"); st.exception(e)

    # Render from session_state (persists across reruns caused by number_input changes)
    if "company_report" in st.session_state:
        report = st.session_state["company_report"]
        render_report(report)
        st.divider()
        md   = report_to_markdown(report)
        html = build_export_html(report)
        c1, c2, c3 = st.columns(3)
        tk = st.session_state.get("company_ticker_done", "report")
        with c1: st.download_button("📥 JSON",     data=report_to_json(report), file_name=f"{tk}_report.json", mime="application/json", key="dl_json_co")
        with c2: st.download_button("📄 Markdown", data=md,                     file_name=f"{tk}_report.md",   mime="text/markdown",    key="dl_md_co")
        with c3: st.download_button("🌐 HTML",     data=html,                   file_name=f"{tk}_report.html",  mime="text/html",       key="dl_html_co")

        output_dir = os.path.join(os.path.dirname(__file__), "output")
        os.makedirs(output_dir, exist_ok=True)
        for fn, ct in [(f"{tk}_report.json", report_to_json(report)),
                       (f"{tk}_report.md",   md),
                       (f"{tk}_report.html",  html)]:
            open(os.path.join(output_dir, fn), "w", encoding="utf-8").write(ct)

# ── Industry ──────────────────────────────────────────────────────────────────
with tab_industry:
    col1, col2 = st.columns([4, 1])
    with col1:
        industry = st.text_input("industry", placeholder="Enter industry  e.g. Semiconductors",
                                 key="industry_name", label_visibility="collapsed")
    with col2:
        run_industry = st.button("🔍 Analyze", key="run_industry", type="primary", use_container_width=True)

    if run_industry and industry:
        config.MIN_MOAT_SCORE = min_moat; config.MIN_FINANCIAL_SCORE = min_fq; config.MIN_STABILITY_SCORE = min_stab
        progress = st.empty()
        def industry_progress(msg): progress.info(msg)
        with st.spinner(f"Analyzing {industry}…"):
            try:
                data_client = YFinanceClient()
                llm = None
                if anthropic_key:
                    try: llm = ClaudeClient(api_key=anthropic_key)
                    except LLMError: st.warning("⚠️ Anthropic key invalid — running without LLM")
                edgar = EdgarClient() if use_edgar else None
                report = run_industry_analysis(
                    industry=industry, data_client=data_client, llm=llm, edgar=edgar,
                    n=universe_size, sort_by=sort_method, min_market_cap=min_mcap,
                    discount_rate=discount_rate, terminal_growth=terminal_growth,
                    projection_years=projection_years, progress_callback=industry_progress,
                )
                progress.empty()
                st.session_state["industry_report"] = report
                st.session_state["industry_name_done"] = industry
            except YFinanceError as e: progress.empty(); st.error(f"❌ Data Error: {e}")
            except Exception     as e: progress.empty(); st.error(f"❌ {e}"); st.exception(e)

    if "industry_report" in st.session_state:
        report = st.session_state["industry_report"]
        st.success(f"✅ {len(report.all_reports)} companies analyzed, {len(report.top_5)} in top 5.")
        if report.top_5:
            st.subheader("🏆 Top Picks")
            pick_tabs = st.tabs([f"#{i+1} {r.ticker}" for i, r in enumerate(report.top_5)])
            for tab, r in zip(pick_tabs, report.top_5):
                with tab: render_report(r)
        st.divider()
        md   = industry_report_to_markdown(report)
        safe = st.session_state.get("industry_name_done","industry").replace(" ","_").replace("/","_")
        c1, c2, c3 = st.columns(3)
        with c1: st.download_button("📥 JSON",     data=report.model_dump_json(indent=2), file_name=f"{safe}_industry.json", mime="application/json", key="dl_json_ind")
        with c2: st.download_button("📄 Markdown", data=md,                               file_name=f"{safe}_industry.md",   mime="text/markdown",    key="dl_md_ind")
        with c3:
            if report.top_5:
                st.download_button("🌐 Top Pick HTML", data=build_export_html(report.top_5[0]),
                                   file_name=f"{safe}_top1.html", mime="text/html", key="dl_html_ind")

st.divider()
st.caption("Buffett Analyzer v2.0 — For research purposes only. Not financial advice.")
