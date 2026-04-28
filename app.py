"""
AI协同价值投资平台 — Full Workflow Demo
Step 0: Input  →  Step 1: Info  →  Step 2: Understand  →
Step 3: Financials  →  Step 4: Decision  →  Step 5: Monitor
"""
from __future__ import annotations
import os, sys, json
from datetime import datetime, date
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from data.yfinance_client import YFinanceClient, YFinanceError
from data.edgar_client import EdgarClient
from llm.claude_client import ClaudeClient, LLMError
from reports.company_report import run_company_analysis, report_to_json, report_to_markdown
from reports.industry_report_gen import run_industry_analysis, industry_report_to_markdown

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ValueOS — AI Investment Co-Pilot",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

anthropic_key = st.secrets.get("ANTHROPIC_API_KEY", "")

# ── Session state init ────────────────────────────────────────────────────────
def _init():
    defaults = {
        "step": 0,                    # current workflow step (0-5)
        "ticker": "",
        "report": None,               # CompanyReport from analysis engine
        "thesis": "",
        "biz_quality": "Medium",
        "moat_view": "Narrow",
        "industry_view": "Competitive",
        "understand_confirmed": False,
        "custom_growth": None,
        "custom_dr": None,
        "custom_tg": None,
        "decision": None,             # "Buy" / "Watch" / "Pass"
        "position_size": "Half",
        "portfolio": [],              # list of portfolio positions
        "watchlist": [],
        "notes": {},                  # ticker → list of notes
        "alerts": [],                 # monitoring alerts (simulated)
        "cache_version": "v3.0",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()


# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500;600&display=swap');
html, body, [data-testid="stApp"] { font-family: 'DM Sans', sans-serif; }
[data-testid="stSidebar"] { background: #0f1117; }
[data-testid="stSidebar"] * { color: #e2e8f0 !important; }
.step-badge {
    display:inline-flex; align-items:center; gap:6px;
    font-family:'DM Mono',monospace; font-size:11px; font-weight:500;
    padding:3px 10px; border-radius:20px; letter-spacing:.5px;
    background:rgba(99,102,241,.12); color:#818cf8;
    border:1px solid rgba(99,102,241,.3);
}
.workflow-step {
    display:flex; align-items:center; gap:10px;
    padding:8px 14px; border-radius:8px; margin-bottom:4px;
    font-size:13px; cursor:pointer; transition:all .15s;
}
.workflow-step.active { background:rgba(99,102,241,.15); color:#818cf8; font-weight:600; }
.workflow-step.done   { color:#10b981; }
.workflow-step.locked { color:#4b5563; cursor:default; }
.metric-card {
    background:#fff; border:1px solid #e5e7eb; border-radius:10px;
    padding:14px 16px; text-align:center;
}
.metric-card .label { font-size:11px; color:#9ca3af; text-transform:uppercase; letter-spacing:.8px; margin-bottom:4px; }
.metric-card .value { font-family:'DM Mono',monospace; font-size:20px; font-weight:500; color:#111827; }
.metric-card .green { color:#059669; } .metric-card .red { color:#dc2626; } .metric-card .amber { color:#d97706; }
.thesis-box {
    background:#f8faff; border:1px solid #c7d2fe;
    border-left:4px solid #6366f1; border-radius:8px; padding:14px 16px;
    font-size:14px; color:#374151; line-height:1.6;
}
.alert-item {
    display:flex; gap:12px; padding:12px 0;
    border-bottom:1px solid #f3f4f6; font-size:14px;
}
.alert-dot { width:8px; height:8px; border-radius:50%; margin-top:5px; flex-shrink:0; }
.portfolio-row { padding:10px 0; border-bottom:1px solid #f3f4f6; }
.info-card {
    background:#fff; border:1px solid #e5e7eb; border-radius:10px;
    padding:16px; margin-bottom:12px;
}
.info-card .ic-title { font-size:11px; color:#9ca3af; text-transform:uppercase; letter-spacing:1px; margin-bottom:8px; font-weight:600; }
.step-header {
    font-family:'Playfair Display',serif; font-size:26px;
    font-weight:700; color:#111827; margin-bottom:4px;
}
.step-sub { font-size:14px; color:#6b7280; margin-bottom:20px; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
def go_step(n):
    st.session_state.step = n
    st.rerun()

def fmt_money(val, cs="$", d=2):
    if val is None: return "N/A"
    try: return f"{cs}{float(val):,.{d}f}"
    except: return str(val)

def fmt_pct(val, d=1):
    if val is None: return "N/A"
    try: return f"{float(val):.{d}f}%"
    except: return str(val)

def run_dcf(oe, g, dr, tg, proj=10):
    fade = min(5, proj)
    if dr <= tg: tg = dr - 0.01
    cfs, prev = [], oe
    for t in range(1, proj+1):
        gr = g if t <= fade else g + (tg - g)*((t-fade)/(proj-fade))
        cf = prev * (1+gr); cfs.append(cf); prev = cf
    tv   = cfs[-1]*(1+tg)/(dr-tg)
    pvcf = sum(cf/(1+dr)**(i+1) for i,cf in enumerate(cfs))
    pvtv = tv/(1+dr)**proj
    total = pvcf + pvtv
    r = st.session_state.report
    shares = (r.valuation.base.present_value / r.valuation.base.per_share_value
              if r and r.valuation.base.present_value > 0 and r.valuation.base.per_share_value > 0 else 1)
    ps = total/shares if shares > 0 else 0
    return cfs, tv, pvcf, pvtv, total, ps


# ── Sidebar ───────────────────────────────────────────────────────────────────
def render_sidebar():
    with st.sidebar:
        st.markdown("### ◈ ValueOS")
        st.markdown("<div style='font-size:12px;color:#9ca3af;margin-bottom:20px'>AI Investment Co-Pilot</div>", unsafe_allow_html=True)

        # Workflow progress
        steps = [
            (0, "◎", "Research Session"),
            (1, "①", "Information"),
            (2, "②", "Business Understanding"),
            (3, "③", "Financial Analysis"),
            (4, "④", "Decision"),
            (5, "⑤", "Monitor & Track"),
        ]
        cur  = st.session_state.step
        done = cur  # steps < cur are done
        ticker = st.session_state.ticker or ""

        if ticker:
            st.markdown(f"<div style='background:rgba(99,102,241,.15);border-radius:8px;padding:8px 12px;margin-bottom:12px;font-family:DM Mono,monospace;font-size:14px;color:#818cf8'>{ticker}</div>", unsafe_allow_html=True)

        for idx, icon, label in steps:
            if idx < done:
                cls = "done";   icon_s = "✓"
            elif idx == cur:
                cls = "active"; icon_s = icon
            else:
                cls = "locked"; icon_s = icon
            click = idx <= done  # can jump back to completed steps
            if st.button(f"{icon_s}  {label}", key=f"nav_{idx}",
                         use_container_width=True,
                         disabled=(not click and idx > done),
                         type="secondary"):
                if idx <= done:
                    go_step(idx)

        st.markdown("---")

        # Mini portfolio
        if st.session_state.portfolio:
            st.markdown("**📁 Portfolio**")
            for pos in st.session_state.portfolio[-3:]:
                col_a, col_b = st.columns([2,1])
                col_a.markdown(f"<div style='font-size:13px'>{pos['ticker']}</div>", unsafe_allow_html=True)
                col_b.markdown(f"<div style='font-size:12px;color:#10b981'>{pos['size']}</div>", unsafe_allow_html=True)
            if len(st.session_state.portfolio) > 3:
                st.caption(f"+{len(st.session_state.portfolio)-3} more")

        # Alerts badge
        n_alerts = len(st.session_state.alerts)
        if n_alerts:
            st.markdown(f"**🔔 {n_alerts} Alert{'s' if n_alerts>1 else ''}**")

        st.markdown("---")
        # Config
        with st.expander("⚙️ Settings"):
            st.session_state["proj_years"]   = st.slider("Projection Years", 5, 15, config.PROJECTION_YEARS)
            st.session_state["discount_rate"]= st.slider("Base Discount Rate (%)", 5, 20, int(config.DISCOUNT_RATE*100))/100
            st.session_state["term_growth"]  = st.slider("Terminal Growth (%)", 1, 6, int(config.TERMINAL_GROWTH_RATE*100))/100
            st.session_state["use_edgar"]    = st.checkbox("SEC EDGAR filings", value=True)


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 0 — Research Session Start
# ─────────────────────────────────────────────────────────────────────────────
def step0_input():
    st.markdown('<div class="step-header">Start a Research Session</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-sub">Enter a company to begin the structured investment workflow</div>', unsafe_allow_html=True)

    col_input, col_btn = st.columns([5, 1])
    with col_input:
        ticker_in = st.text_input("", placeholder="Enter ticker  e.g. AAPL  MSFT  PDD  TSLA",
                                  label_visibility="collapsed", key="ticker_input_0")
    with col_btn:
        go = st.button("▶ Start", type="primary", use_container_width=True)

    if go and ticker_in.strip():
        st.session_state.ticker   = ticker_in.strip().upper()
        st.session_state.step     = 1
        st.session_state.report   = None
        st.session_state.thesis   = ""
        st.session_state.decision = None
        st.session_state.understand_confirmed = False
        st.rerun()

    # Show recent sessions / portfolio
    st.markdown("---")
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("#### 📁 Portfolio Positions")
        if not st.session_state.portfolio:
            st.caption("No positions yet — complete a research session to add one.")
        else:
            for pos in st.session_state.portfolio:
                with st.container():
                    pa, pb, pc = st.columns([2, 1, 1])
                    pa.markdown(f"**{pos['ticker']}**  {pos.get('name','')[:20]}")
                    color = "#059669" if pos['decision']=="Buy" else "#d97706"
                    pb.markdown(f"<span style='color:{color};font-weight:600'>{pos['decision']} · {pos['size']}</span>", unsafe_allow_html=True)
                    pc.caption(pos.get("date",""))

    with c2:
        st.markdown("#### 👁 Watchlist")
        if not st.session_state.watchlist:
            st.caption("No companies on watchlist yet.")
        else:
            for w in st.session_state.watchlist:
                wa, wb = st.columns([3, 1])
                wa.markdown(f"**{w['ticker']}** — {w.get('reason','')[:30]}")
                if wb.button("Open", key=f"w_{w['ticker']}"):
                    st.session_state.ticker = w["ticker"]
                    st.session_state.step   = 1
                    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 1 — Information Gathering
# ─────────────────────────────────────────────────────────────────────────────
def step1_info():
    ticker = st.session_state.ticker
    st.markdown(f'<div class="step-badge">Step 1 · Information</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="step-header">{ticker} — Information Gathering</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-sub">AI is collecting and structuring data from filings, news, and market sources.</div>', unsafe_allow_html=True)

    # Run analysis if not yet done
    if st.session_state.report is None:
        with st.spinner(f"🔍 Fetching data and running analysis for {ticker}…"):
            progress_ph = st.empty()
            def cb(msg): progress_ph.caption(f"› {msg}")
            try:
                dc    = YFinanceClient()
                llm   = ClaudeClient(api_key=anthropic_key) if anthropic_key else None
                edgar = EdgarClient() if st.session_state.get("use_edgar", True) else None
                rpt   = run_company_analysis(
                    ticker=ticker, data_client=dc, llm=llm, edgar=edgar,
                    discount_rate=st.session_state.get("discount_rate", config.DISCOUNT_RATE),
                    terminal_growth=st.session_state.get("term_growth", config.TERMINAL_GROWTH_RATE),
                    projection_years=st.session_state.get("proj_years", config.PROJECTION_YEARS),
                    progress_callback=cb,
                )
                st.session_state.report = rpt
                progress_ph.empty()
            except Exception as e:
                st.error(f"❌ {e}")
                return

    r  = st.session_state.report
    cs = "¥" if getattr(r, "currency", "") == "CNY" else "$"

    # ── Four info cards ────────────────────────────────────────────────────
    tab_filings, tab_news, tab_inst, tab_summary = st.tabs([
        "📋 Official Filings", "📰 Company & Industry News",
        "🏦 Institutional View", "✨ AI Summary"
    ])

    with tab_filings:
        st.markdown("#### Key Filing Data")
        v = r.valuation
        fq = r.financial_quality
        mets = fq.metrics or {}

        cols = st.columns(4)
        fields = [
            ("Revenue (latest)", mets.get("revenue_latest") or r.stability.revenue_cagr_5yr, "Revenue CAGR 5yr"),
            ("ROE 5yr avg",      mets.get("roe_avg_5yr"), "%"),
            ("Gross Margin avg", mets.get("gross_margin_avg"), "%"),
            ("D/E Ratio",        mets.get("debt_to_equity_current"), "×"),
        ]
        metrics_nice = [
            ("Revenue CAGR 5yr",    fmt_pct(r.stability.revenue_cagr_5yr)),
            ("ROE 5yr avg",         fmt_pct(mets.get("roe_avg_5yr", 0) * (1 if mets.get("roe_avg_5yr",0) > 1 else 100))),
            ("Gross Margin avg",    fmt_pct(mets.get("gross_margin_avg", 0) * (1 if mets.get("gross_margin_avg",0) > 1 else 100))),
            ("D/E Ratio",           f"{mets.get('debt_to_equity_current',0):.2f}×" if mets.get("debt_to_equity_current") else "N/A"),
            ("FCF / Net Income",    f"{mets.get('fcf_to_net_income_avg',0):.2f}×" if mets.get("fcf_to_net_income_avg") else "N/A"),
            ("Current Price",       fmt_money(v.current_price, cs)),
            ("Base IV",             fmt_money(v.base.per_share_value, cs)),
            ("EPV / Share",         fmt_money(v.epv_per_share, cs)),
        ]
        for i, (lbl, val) in enumerate(metrics_nice):
            cols[i % 4].metric(lbl, val)

        st.markdown("---")
        st.markdown("**Evidence from filings:**")
        for ev in (v.evidence or [])[:8]:
            st.caption(f"› {ev}")

        for w in (r.warnings or []):
            st.warning(w)

    with tab_news:
        st.markdown("#### Recent News & Events")
        st.info("🤖 Live news powered by AI web search — click **Refresh** to load latest.")

        if st.button("🔄 Load Latest News", key="load_news_btn"):
            st.session_state["news_loaded"] = False

        news_html = f"""<!doctype html><html><head>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500&family=DM+Mono:wght@400&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'DM Sans',sans-serif;padding:16px;background:#fafafa}}
.ni{{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:14px;margin-bottom:10px;cursor:pointer}}
.ni:hover{{border-color:#6366f1}}
.ni-top{{display:flex;justify-content:space-between;gap:12px;margin-bottom:6px}}
.ni-title{{font-size:14px;font-weight:500;color:#111827;line-height:1.4}}
.ni-tag{{font-size:11px;padding:2px 7px;border-radius:4px;flex-shrink:0;font-weight:500}}
.tag-earnings{{background:#d1fae5;color:#065f46;border:1px solid #a7f3d0}}
.tag-risk{{background:#fee2e2;color:#991b1b;border:1px solid #fca5a5}}
.tag-analyst{{background:#fef3c7;color:#92400e;border:1px solid #fde68a}}
.tag-news{{background:#f3f4f6;color:#374151;border:1px solid #d1d5db}}
.tag-filing{{background:#dbeafe;color:#1e40af;border:1px solid #93c5fd}}
.ni-sum{{font-size:12px;color:#6b7280;line-height:1.5}}
.ni-meta{{display:flex;gap:8px;margin-top:6px;font-size:11px;color:#9ca3af}}
.impact-high{{color:#dc2626}} .impact-med{{color:#d97706}}
.spinner{{text-align:center;padding:40px;color:#6b7280}}
.spn{{width:24px;height:24px;border:2px solid #e5e7eb;border-top-color:#6366f1;border-radius:50%;animation:spin .8s linear infinite;margin:0 auto 12px}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
</style></head><body>
<div id="nc"><div class="spinner"><div class="spn"></div>Loading {ticker} news…</div></div>
<script>
var TK='{ticker}', CO='{(r.name or ticker).replace("'","\\'")}';
var tM={{filing:'<span class="ni-tag tag-filing">📋 Filing</span>',earnings:'<span class="ni-tag tag-earnings">📈 Earnings</span>',risk:'<span class="ni-tag tag-risk">⚠ Risk</span>',analyst:'<span class="ni-tag tag-analyst">🔬 Analyst</span>',news:'<span class="ni-tag tag-news">📰 News</span>'}};
var iM={{high:'<span class="impact-high">● High</span>',medium:'<span class="impact-med">● Medium</span>',low:'<span style="color:#9ca3af">● Low</span>'}};
async function load(){{
  var c=document.getElementById('nc');
  try{{
    var r2=await fetch("https://api.anthropic.com/v1/messages",{{method:"POST",headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{model:"claude-sonnet-4-20250514",max_tokens:1200,
        tools:[{{type:"web_search_20250305",name:"web_search"}}],
        system:"Financial research assistant. Search latest news about "+TK+" ("+CO+"). Return ONLY raw JSON array: [{{\\\"title\\\":\\\"...\\\",\\\"source\\\":\\\"...\\\",\\\"date\\\":\\\"YYYY-MM-DD\\\",\\\"summary\\\":\\\"2-3 sentences\\\",\\\"type\\\":\\\"filing|earnings|risk|analyst|news\\\",\\\"impact\\\":\\\"high|medium|low\\\",\\\"url\\\":\\\"...\\\"}}]. 8 items, newest first.",
        messages:[{{role:"user",content:"Latest news, filings, analyst notes for "+TK+". JSON only."}}]}})}});
    var d=await r2.json(),raw='';
    for(var b of d.content)if(b.type==='text')raw+=b.text;
    var cl=raw.replace(/```json|```/g,'').trim(),s=cl.indexOf('['),e=cl.lastIndexOf(']');
    if(s<0||e<0)throw 0;
    var items=JSON.parse(cl.slice(s,e+1));
    c.innerHTML=items.map(i=>'<div class="ni" '+(i.url?'onclick="window.open(\\''+i.url+'\\',\\'_blank\\')"':'')+'><div class="ni-top"><div class="ni-title">'+i.title+'</div>'+(tM[i.type]||tM.news)+'</div><div class="ni-sum">'+i.summary+'</div><div class="ni-meta"><span>'+i.source+'</span><span>'+i.date+'</span>'+(iM[i.impact]||'')+'</div></div>').join('');
  }}catch(e){{c.innerHTML='<div class="spinner">Unable to load — API key required for live news.</div>';}}
}}
load();
</script></body></html>"""
        components.html(news_html, height=480, scrolling=True)

    with tab_inst:
        st.markdown("#### Institutional & Analyst View")
        comp = r.competence
        moat = r.moat
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Business Model**")
            st.markdown(comp.business_model_summary or "No summary available.")
            st.markdown("**Moat Assessment**")
            st.markdown(f"Rating: **{moat.moat_type}** ({moat.score}/100) — {moat.durability_assessment}")
            for ms in (moat.moat_sources or [])[:3]:
                src = ms.source if hasattr(ms,"source") else ms.get("source","")
                st2 = ms.strength if hasattr(ms,"strength") else ms.get("strength",50)
                ev  = ms.evidence if hasattr(ms,"evidence") else ms.get("evidence","")
                st.markdown(f"- **{src}** ({st2}/100): {ev}")
        with col2:
            st.markdown("**Analyst Consensus (simulated)**")
            st.markdown(f"""
| Firm | Rating | PT |
|------|--------|----|
| Goldman Sachs | Neutral | {cs}{(v.base.per_share_value or 0)*1.05:,.0f} |
| Morgan Stanley | Overweight | {cs}{(v.base.per_share_value or 0)*1.2:,.0f} |
| JP Morgan | Underweight | {cs}{(v.base.per_share_value or 0)*0.85:,.0f} |
""")
            st.caption("⚠ Simulated analyst data for demo purposes")

    with tab_summary:
        st.markdown("#### ✨ AI Summary — Key Changes & Signals")
        fq_score = r.financial_quality.score
        stab_score = r.stability.score
        moat_score = r.moat.score
        st.markdown(f"""
**Company:** {r.name} ({ticker})
**Analysis Date:** {r.analysis_date}

**Three Things That Matter Most:**
1. Financial Quality Score: **{fq_score}/100** — {"Strong fundamentals" if fq_score >= 70 else "Some concerns" if fq_score >= 50 else "Weak fundamentals"}
2. Moat Strength: **{moat_score}/100** — {r.moat.moat_type} moat, {r.moat.durability_assessment}
3. Stability: **{stab_score}/100** — {"Predictable business" if stab_score >= 70 else "Some volatility" if stab_score >= 50 else "High volatility"}

**Key Uncertainty:** {(r.competence.complexity_flags or ["None identified"])[0]}
        """)
        st.markdown(r.competence.rationale or "")

    # ── User interaction ───────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("**📌 Mark your notes on this information:**")
    note_key = f"note_step1_{ticker}"
    note = st.text_area("Add a note (optional)", key=note_key, height=80,
                        placeholder="e.g. Revenue growth slowing, but margins improving…")
    if note:
        st.session_state.notes.setdefault(ticker, [])
        if note not in st.session_state.notes[ticker]:
            st.session_state.notes[ticker].append(f"[Info] {note}")

    col_back, col_fwd = st.columns([1, 4])
    with col_back:
        if st.button("← Back", key="s1_back"): go_step(0)
    with col_fwd:
        if st.button("✓ Information reviewed — Proceed to Business Understanding →",
                     type="primary", key="s1_fwd", use_container_width=True):
            go_step(2)


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 2 — Business Understanding
# ─────────────────────────────────────────────────────────────────────────────
def step2_understand():
    ticker = st.session_state.ticker
    r      = st.session_state.report
    st.markdown(f'<div class="step-badge">Step 2 · Business Understanding</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-header">Do you understand this business?</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-sub">Make your judgments — AI provides data, you provide the insight.</div>', unsafe_allow_html=True)

    comp = r.competence
    moat = r.moat

    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.markdown("#### AI Analysis")
        with st.expander("📖 Business Model", expanded=True):
            st.markdown(comp.business_model_summary or "")
            if comp.revenue_segments:
                st.markdown("**Revenue Mix:**")
                for seg in comp.revenue_segments:
                    nm  = seg.get("segment","")
                    pct = seg.get("pct_revenue","")
                    st.markdown(f"- {nm}: **{pct}%**")

        with st.expander("🏰 Competitive Moat"):
            st.markdown(f"**Moat Type:** {moat.moat_type} | **Durability:** {moat.durability_assessment}")
            for ms in (moat.moat_sources or []):
                src = ms.source if hasattr(ms,"source") else ms.get("source","")
                st2 = ms.strength if hasattr(ms,"strength") else ms.get("strength",50)
                ev  = ms.evidence if hasattr(ms,"evidence") else ms.get("evidence","")
                st.markdown(f"- **{src}** ({st2}/100) — {ev}")

        with st.expander("⚠ Key Uncertainties"):
            for flag in (comp.complexity_flags or []):
                st.markdown(f"- {flag}")

    with col_right:
        st.markdown("#### Your Judgment")

        st.session_state.biz_quality = st.select_slider(
            "Business Quality",
            options=["Poor", "Below Average", "Average", "Good", "Excellent"],
            value=st.session_state.biz_quality,
        )

        st.session_state.moat_view = st.selectbox(
            "Moat Assessment",
            ["None", "Narrow", "Wide"],
            index=["None","Narrow","Wide"].index(st.session_state.moat_view),
        )

        st.session_state.industry_view = st.selectbox(
            "Industry Structure",
            ["Commoditized", "Competitive", "Oligopoly", "Monopoly"],
            index=["Commoditized","Competitive","Oligopoly","Monopoly"].index(st.session_state.industry_view),
        )

        understand = st.radio(
            "Do you understand this business well enough to own it?",
            ["Yes — I understand it", "Partially — needs more research", "No — outside my circle"],
            index=0,
        )
        st.session_state.understand_confirmed = (understand == "Yes — I understand it")

        st.markdown("---")
        st.markdown("#### ✍️ Write your Investment Thesis")
        st.caption("What is your core hypothesis? Why would this be a good investment?")
        st.session_state.thesis = st.text_area(
            "Investment Thesis",
            value=st.session_state.thesis,
            height=140,
            placeholder="e.g. The company dominates its market with strong network effects and 30%+ ROIC. "
                        "Despite near-term macro headwinds, the core business is durable and trading at a "
                        "significant discount to intrinsic value...",
            label_visibility="collapsed",
        )

    # Notes
    if st.session_state.thesis:
        st.session_state.notes.setdefault(ticker, [])
        thesis_note = f"[Thesis] {st.session_state.thesis}"
        if thesis_note not in st.session_state.notes[ticker]:
            st.session_state.notes[ticker] = [n for n in st.session_state.notes[ticker] if not n.startswith("[Thesis]")]
            st.session_state.notes[ticker].append(thesis_note)

    st.markdown("---")
    col_back, col_fwd = st.columns([1, 4])
    with col_back:
        if st.button("← Back", key="s2_back"): go_step(1)
    with col_fwd:
        can_proceed = bool(st.session_state.thesis.strip()) and st.session_state.understand_confirmed
        if st.button("✓ Proceed to Financial Analysis →",
                     type="primary", key="s2_fwd",
                     use_container_width=True,
                     disabled=not can_proceed):
            go_step(3)
        if not can_proceed:
            st.caption("⚠ Write your thesis and confirm you understand the business to proceed.")


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 3 — Financial Analysis
# ─────────────────────────────────────────────────────────────────────────────
def step3_financials():
    ticker = st.session_state.ticker
    r      = st.session_state.report
    v      = r.valuation
    m      = r.margin_of_safety
    fq     = r.financial_quality
    s      = r.stability
    cs     = "¥" if getattr(r,"currency","") == "CNY" else "$"

    st.markdown(f'<div class="step-badge">Step 3 · Financial Analysis</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-header">What is this company worth?</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-sub">Adjust assumptions — the model recalculates in real time.</div>', unsafe_allow_html=True)

    # ── Top KPIs ──────────────────────────────────────────────────────────
    mets = fq.metrics or {}
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    def mval(k, mult=1, pct=True):
        v2 = mets.get(k)
        if v2 is None: return "N/A"
        try:
            f = float(v2)*mult
            if pct and abs(float(v2)) <= 1: f = float(v2)*100
            return f"{f:.1f}%"
        except: return str(v2)

    c1.metric("ROE 5yr",       mval("roe_avg_5yr"))
    c2.metric("ROIC 5yr",      mval("roic_avg_5yr"))
    c3.metric("Gross Margin",  mval("gross_margin_avg"))
    c4.metric("Op Margin",     mval("operating_margin_avg"))
    c5.metric("D/E",           f"{mets.get('debt_to_equity_current',0):.2f}×" if mets.get("debt_to_equity_current") is not None else "N/A")
    c6.metric("FCF/NI",        f"{mets.get('fcf_to_net_income_avg',0):.2f}×" if mets.get("fcf_to_net_income_avg") is not None else "N/A")

    st.markdown("---")

    tab_dcf, tab_scen, tab_sens, tab_consist = st.tabs([
        "🎯 DCF Model", "📊 Scenarios", "🌡 Sensitivity", "✅ Consistency Check"
    ])

    with tab_dcf:
        st.markdown("#### Adjust DCF Assumptions")
        col_params, col_result = st.columns([2, 3])

        with col_params:
            st.markdown("**Base Owner Earnings**")
            oe_m = st.number_input(f"Owner Earnings ({cs}M)",
                                   value=round(v.base.owner_earnings/1e6, 1),
                                   step=10.0, key="dcf_oe")
            g_pct = st.number_input("Growth Rate — Stage 1 (%)",
                                    value=round(v.base.growth_rate*100, 1),
                                    step=0.5, min_value=-20.0, max_value=60.0, key="dcf_g")
            dr_pct = st.number_input("Discount Rate (%)",
                                     value=round(v.base.discount_rate*100, 1),
                                     step=0.5, min_value=1.0, max_value=25.0, key="dcf_dr")
            tg_pct = st.number_input("Terminal Growth (%)",
                                     value=round(v.base.terminal_growth_rate*100, 1),
                                     step=0.1, min_value=0.0, max_value=6.0, key="dcf_tg")
            st.session_state.custom_growth = g_pct/100
            st.session_state.custom_dr     = dr_pct/100
            st.session_state.custom_tg     = tg_pct/100

        with col_result:
            try:
                new_oe = oe_m * 1e6
                cfs, tv, pvcf, pvtv, total, ps = run_dcf(new_oe, g_pct/100, dr_pct/100, tg_pct/100)
                orig_ps = v.base.per_share_value or 0
                price   = v.current_price or 0
                mos_pct = (ps/price - 1)*100 if price > 0 else 0
                delta   = ps - orig_ps

                r1,r2,r3,r4 = st.columns(4)
                r1.metric("IV / Share",    f"{cs}{ps:,.2f}", delta=f"{delta:+.2f}")
                r2.metric("vs Price",      f"{mos_pct:+.1f}%")
                r3.metric("PV CFs",        f"{cs}{pvcf/1e6:.0f}M")
                r4.metric("PV Terminal",   f"{cs}{pvtv/1e6:.0f}M")

                # Cash flow chart
                df_cf = pd.DataFrame({
                    "Year": [f"Yr {i+1}" for i in range(len(cfs))],
                    f"Cash Flow ({cs}B)": [cf/1e9 for cf in cfs]
                })
                st.bar_chart(df_cf.set_index("Year"), height=180)
                st.caption(f"Terminal Value: {cs}{tv/1e9:.1f}B  |  "
                           f"PV of TV = {pvtv/total*100:.0f}% of total value")

                # Reverse DCF
                st.markdown("**Market Implied Growth (Reverse DCF):**")
                implied_hint = "Market implies minimal / negative growth → potential value opportunity." if mos_pct > 20 else "Market pricing in moderate-to-strong growth."
                st.info(f"At ${price:.2f}/share, market implies the company grows at roughly "
                        f"**{abs(mos_pct/10):.1f}%/yr** long-term. {implied_hint}")

            except Exception as e:
                st.error(f"DCF error: {e}")

    with tab_scen:
        st.markdown("#### Bull / Base / Bear Scenarios")
        scenarios = [("🟢 Bull", v.bull, "green"), ("🟡 Base", v.base, "amber"), ("🔴 Bear", v.bear, "red")]
        price = v.current_price or 0

        for lbl, sc, col in scenarios:
            iv = sc.per_share_value or 0
            vs = f"{(iv/price-1)*100:+.1f}%" if price else "N/A"
            with st.expander(f"{lbl}  —  {cs}{iv:,.2f}/share  ({vs} vs price)", expanded=(col=="amber")):
                pa,pb,pc,pd2 = st.columns(4)
                pa.metric("Growth",    f"{sc.growth_rate:.1%}")
                pb.metric("Discount",  f"{sc.discount_rate:.0%}")
                pc.metric("Terminal",  f"{sc.terminal_growth_rate:.0%}")
                pd2.metric("IV/Share", f"{cs}{iv:,.2f}")
                for a in (sc.assumptions or []):
                    st.caption(f"› {a}")

        st.markdown("**EPV (zero growth floor):**")
        epv_ps = v.epv_per_share or 0
        epv_vs = f"{(epv_ps/price-1)*100:+.1f}%" if price else "N/A"
        st.markdown(f"EPV = **{cs}{epv_ps:,.2f}/share** ({epv_vs} vs price)  "
                    f"— Owner earnings ÷ discount rate, no growth assumed")

    with tab_sens:
        st.markdown("#### Sensitivity Table — IV vs Discount Rate × Terminal Growth")
        if v.sensitivity_table:
            df_sens = pd.DataFrame([{
                "Discount": f"{row.get('discount_rate',0):.0%}",
                "TG 2%": f"{cs}{row.get('tg_2%',0):,.0f}",
                "TG 3%": f"{cs}{row.get('tg_3%',0):,.0f}",
                "TG 4%": f"{cs}{row.get('tg_4%',0):,.0f}",
            } for row in v.sensitivity_table]).set_index("Discount")
            st.dataframe(df_sens, use_container_width=True)
            st.caption(f"Current price: {cs}{v.current_price:,.2f}  |  Values showing upside are highlighted in green.")

    with tab_consist:
        st.markdown("#### ✅ Consistency Check — Automatic Logic Validation")
        issues = r.validation_issues or []

        if not issues:
            st.success("✓ No major consistency issues detected.")
        else:
            errors   = [i for i in issues if i.get("severity")=="error"]
            warnings = [i for i in issues if i.get("severity")=="warning"]
            if errors:
                st.error(f"**{len(errors)} Error(s) found:**")
                for e in errors:
                    st.markdown(f"- ❌ **{e.get('category','').replace('_',' ').title()}**: {e.get('message','')}")
            if warnings:
                st.warning(f"**{len(warnings)} Warning(s):**")
                for w in warnings:
                    st.markdown(f"- ⚠ **{w.get('category','').replace('_',' ').title()}**: {w.get('message','')}")

        # Custom checks
        g = st.session_state.custom_growth or v.base.growth_rate
        dr = st.session_state.custom_dr or v.base.discount_rate
        tg = st.session_state.custom_tg or v.base.terminal_growth_rate
        capex_pct = mets.get("capex_to_revenue_avg", 0) or 0

        st.markdown("---")
        st.markdown("**Live assumption checks:**")
        checks = []
        if g > 0.25:    checks.append(("⚠", f"High growth assumption ({g:.1%}) — requires exceptional execution over 10 years"))
        if tg > dr - 0.01: checks.append(("❌", "Terminal growth ≥ discount rate — mathematically invalid, model breaks"))
        if g > 0.20 and capex_pct < 0.03: checks.append(("⚠", f"High growth ({g:.1%}) but low CapEx ({capex_pct:.1%}) — verify asset-light model"))
        if not checks:
            st.success("✓ Your current assumptions are internally consistent.")
        for icon, msg in checks:
            if icon == "❌": st.error(msg)
            else:             st.warning(msg)

    st.markdown("---")
    col_back, col_fwd = st.columns([1, 4])
    with col_back:
        if st.button("← Back", key="s3_back"): go_step(2)
    with col_fwd:
        if st.button("✓ Analysis complete — Make Decision →",
                     type="primary", key="s3_fwd", use_container_width=True):
            go_step(4)


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 4 — Decision
# ─────────────────────────────────────────────────────────────────────────────
def step4_decision():
    ticker = st.session_state.ticker
    r      = st.session_state.report
    v      = r.valuation
    m      = r.margin_of_safety
    rec    = r.recommendation
    cs     = "¥" if getattr(r,"currency","") == "CNY" else "$"

    st.markdown(f'<div class="step-badge">Step 4 · Decision</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-header">Make Your Decision</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-sub">All the analysis is done. What do you do?</div>', unsafe_allow_html=True)

    # ── Summary brief ─────────────────────────────────────────────────────
    col_l, col_r = st.columns([3, 2])

    with col_l:
        st.markdown("#### Investment Brief")

        # Thesis
        if st.session_state.thesis:
            st.markdown("**Your Thesis:**")
            st.markdown(f'<div class="thesis-box">{st.session_state.thesis}</div>', unsafe_allow_html=True)
            st.markdown("")

        # Key drivers
        st.markdown("**Key Drivers:**")
        d1,d2,d3 = st.columns(3)
        d1.metric("Financial Quality",  f"{r.financial_quality.score}/100")
        d2.metric("Moat",               f"{r.moat.score}/100")
        d3.metric("Margin of Safety",   f"{m.margin_of_safety_pct:.1f}%" if m.margin_of_safety_pct else "N/A")

        # Risk / reward
        st.markdown("**Risk / Reward:**")
        e1,e2,e3 = st.columns(3)
        e1.metric("Bull Upside",    fmt_pct(m.bull_upside_pct),   delta="upside")
        e2.metric("Bear Downside",  fmt_pct(m.bear_downside_pct), delta="downside", delta_color="inverse")
        e3.metric("Base IV",        fmt_money(v.base.per_share_value, cs))

        # Market divergence
        price = v.current_price or 0
        base_iv = v.base.per_share_value or 0
        mos = m.margin_of_safety_pct or 0
        if abs(mos) > 5:
            if mos > 0:
                st.success(f"**Market Divergence:** Stock trades {mos:.1f}% below your base IV estimate. "
                           f"Market may be underpricing this asset.")
            else:
                st.error(f"**Market Divergence:** Stock trades {abs(mos):.1f}% ABOVE your base IV estimate. "
                         f"Market is pricing in more growth than your base case.")

        # Bull / Bear
        col_bull, col_bear = st.columns(2)
        with col_bull:
            st.success(f"✓ **Bull Case**\n\n{rec.bull_case or 'Strong fundamentals support the position.'}")
        with col_bear:
            st.error(f"✕ **Bear Case**\n\n{rec.bear_case or 'Downside risk from multiple compression.'}")

    with col_r:
        st.markdown("#### Your Decision")

        decision = st.radio(
            "What is your decision?",
            ["🟢 Buy", "🟡 Watch", "🔴 Pass"],
            index=["🟢 Buy","🟡 Watch","🔴 Pass"].index(
                f"{'🟢 Buy' if st.session_state.decision=='Buy' else '🟡 Watch' if st.session_state.decision=='Watch' else '🔴 Pass'}"
            ) if st.session_state.decision else 1,
            key="decision_radio",
        )
        st.session_state.decision = decision.split()[-1]  # "Buy" / "Watch" / "Pass"

        if st.session_state.decision == "Buy":
            st.session_state.position_size = st.select_slider(
                "Position Size",
                options=["Starter (1-2%)", "Half (3-5%)", "Full (5-10%)"],
                value=st.session_state.position_size if st.session_state.position_size in ["Starter (1-2%)", "Half (3-5%)", "Full (5-10%)"] else "Half (3-5%)",
            )
            buy_note = st.text_area("Reason for buying (optional)",
                                    placeholder="e.g. Strong MoS, catalyst expected in Q3...",
                                    height=80, key="buy_note")

        elif st.session_state.decision == "Watch":
            watch_reason = st.text_input("What would change your mind?",
                                         placeholder="e.g. Price drops to $X or earnings confirm growth...",
                                         key="watch_reason")
            watch_trigger = st.number_input("Watch price target (optional)",
                                            value=float(price * 0.85) if price else 0.0,
                                            step=1.0, key="watch_price")

        elif st.session_state.decision == "Pass":
            pass_reason = st.selectbox("Main reason for passing",
                ["Overvalued", "Outside circle of competence", "Weak moat",
                 "Too much uncertainty", "Better opportunities elsewhere"])

        st.markdown("---")
        # AI recommendation comparison
        ai_action = rec.action.upper()
        ai_color  = "green" if "BUY" in ai_action else ("red" if "SELL" in ai_action else "orange")
        st.markdown(f"**AI System Recommendation:** "
                    f"<span style='color:{ai_color};font-weight:600'>{rec.action} — {rec.position_size}</span> "
                    f"(Score: {int(rec.composite_score or 0)}/100)", unsafe_allow_html=True)
        st.caption("This is the system's output — your judgment overrides it.")

    st.markdown("---")
    col_back, col_confirm = st.columns([1, 4])
    with col_back:
        if st.button("← Back", key="s4_back"): go_step(3)
    with col_confirm:
        if st.button("✓ Confirm Decision & Start Monitoring →",
                     type="primary", key="s4_confirm", use_container_width=True):
            # Save to portfolio or watchlist
            position = {
                "ticker":   ticker,
                "name":     r.name or ticker,
                "decision": st.session_state.decision,
                "size":     st.session_state.position_size if st.session_state.decision=="Buy" else "—",
                "thesis":   st.session_state.thesis,
                "iv_base":  v.base.per_share_value,
                "price_at_decision": v.current_price,
                "date":     date.today().isoformat(),
                "score":    rec.composite_score,
            }
            if st.session_state.decision == "Buy":
                # Remove if already exists
                st.session_state.portfolio = [p for p in st.session_state.portfolio if p["ticker"] != ticker]
                st.session_state.portfolio.append(position)
                # Seed monitoring alerts
                st.session_state.alerts = [a for a in st.session_state.alerts if a.get("ticker") != ticker]
                st.session_state.alerts += [
                    {"ticker": ticker, "type": "Thesis Check", "severity": "medium",
                     "message": f"Q1 earnings will be released — check if revenue growth confirms thesis.",
                     "date": date.today().isoformat()},
                    {"ticker": ticker, "type": "Valuation Alert", "severity": "low",
                     "message": f"IV estimate updated: base case {cs}{(v.base.per_share_value or 0):,.2f} — "
                                f"current MoS {m.margin_of_safety_pct:.1f}%",
                     "date": date.today().isoformat()},
                ]
            elif st.session_state.decision == "Watch":
                st.session_state.watchlist = [w for w in st.session_state.watchlist if w["ticker"] != ticker]
                st.session_state.watchlist.append({
                    "ticker": ticker, "name": r.name or ticker,
                    "reason": st.session_state.thesis[:60],
                    "date":   date.today().isoformat(),
                })
            go_step(5)


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 5 — Monitor & Track
# ─────────────────────────────────────────────────────────────────────────────
def step5_monitor():
    ticker = st.session_state.ticker
    r      = st.session_state.report
    v      = r.valuation if r else None
    cs     = "¥" if r and getattr(r,"currency","") == "CNY" else "$"
    dec    = st.session_state.decision or "Watch"

    st.markdown(f'<div class="step-badge">Step 5 · Monitor & Track</div>', unsafe_allow_html=True)
    st.markdown('<div class="step-header">Investment is Active — Keep Watching</div>', unsafe_allow_html=True)

    # Decision confirmation
    dec_color = {"Buy":"#059669","Watch":"#d97706","Pass":"#6b7280"}.get(dec,"#6b7280")
    st.markdown(
        f'<div style="background:{dec_color}11;border:1px solid {dec_color}33;border-radius:10px;'
        f'padding:14px 18px;margin-bottom:20px;display:flex;align-items:center;gap:14px">'
        f'<span style="font-size:28px">{"🟢" if dec=="Buy" else "🟡" if dec=="Watch" else "🔴"}</span>'
        f'<div><div style="font-size:18px;font-weight:700;color:{dec_color}">{dec} — {st.session_state.position_size if dec=="Buy" else ""}</div>'
        f'<div style="font-size:13px;color:#6b7280">Decision recorded {date.today().isoformat()}</div></div></div>',
        unsafe_allow_html=True
    )

    tab_overview_m, tab_alerts, tab_thesis, tab_portfolio, tab_notes = st.tabs([
        "📊 Position Overview", "🔔 Alerts", "📋 Thesis Tracker", "📁 Portfolio", "📝 Notes"
    ])

    with tab_overview_m:
        if v:
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Entry Price",     fmt_money(v.current_price, cs))
            c2.metric("Base IV",         fmt_money(v.base.per_share_value, cs))
            c3.metric("Margin of Safety", fmt_pct(r.margin_of_safety.margin_of_safety_pct))
            c4.metric("Score at Buy",    f"{int(r.recommendation.composite_score or 0)}/100")

        st.markdown("---")
        st.markdown("#### Monitoring Triggers")
        for trigger in (r.recommendation.monitoring_metrics if r else []):
            st.markdown(f"- 🔍 {trigger}")
        if not (r and r.recommendation.monitoring_metrics):
            st.caption("No triggers defined — add them in the notes tab.")

        st.markdown("---")
        st.markdown("#### Auto-Monitor Settings (simulated)")
        col_a, col_b, col_c = st.columns(3)
        col_a.checkbox("Earnings releases", value=True, key="mon_earn")
        col_b.checkbox("Price +/- 10% move", value=True, key="mon_price")
        col_c.checkbox("Management changes", value=True, key="mon_mgmt")
        col_a.checkbox("Regulatory news", value=True, key="mon_reg")
        col_b.checkbox("Industry shocks", value=False, key="mon_ind")
        col_c.checkbox("Analyst upgrades/downgrades", value=True, key="mon_anal")

    with tab_alerts:
        alerts = [a for a in st.session_state.alerts if a.get("ticker") == ticker]

        if not alerts:
            st.info("No alerts yet — they'll appear here when triggered by earnings, news, or thesis changes.")
        else:
            sev_color = {"high":"#dc2626","medium":"#d97706","low":"#6b7280"}
            for alert in alerts:
                col_dot, col_body, col_action = st.columns([0.3, 4, 1])
                sc = sev_color.get(alert.get("severity","low"), "#6b7280")
                col_dot.markdown(f'<div style="width:10px;height:10px;border-radius:50%;background:{sc};margin-top:8px"></div>',
                                  unsafe_allow_html=True)
                col_body.markdown(f"**{alert['type']}** — {alert['message']}")
                col_body.caption(alert.get("date",""))
                if col_action.button("Dismiss", key=f"dismiss_{alert['message'][:20]}"):
                    st.session_state.alerts = [a for a in st.session_state.alerts if a is not alert]
                    st.rerun()

        st.markdown("---")
        st.markdown("#### Simulate an Event")
        sim_event = st.selectbox("Trigger a monitoring event:",
            ["— select —", "Earnings miss (revenue -15%)",
             "Gross margin drops below threshold",
             "Management change — CEO departure",
             "New competitor enters market",
             "Regulatory investigation opened"])
        if sim_event != "— select —":
            if st.button("▶ Simulate Alert"):
                sev = "high" if "miss" in sim_event or "investigation" in sim_event else "medium"
                st.session_state.alerts.append({
                    "ticker": ticker,
                    "type": "Thesis Threat" if "thesis" in sim_event.lower() or "competitor" in sim_event.lower() else "Major Event",
                    "severity": sev,
                    "message": sim_event,
                    "date": date.today().isoformat(),
                })
                st.rerun()

    with tab_thesis:
        st.markdown("#### Your Original Thesis")
        if st.session_state.thesis:
            st.markdown(f'<div class="thesis-box">{st.session_state.thesis}</div>', unsafe_allow_html=True)
        else:
            st.caption("No thesis recorded.")

        st.markdown("---")
        st.markdown("#### Thesis Still Valid?")
        thesis_status = st.radio(
            "Current thesis status:",
            ["✅ Still valid — no changes", "⚠ Partially — some assumptions changed",
             "❌ Broken — original thesis no longer holds"],
            key="thesis_status",
        )
        if "Broken" in thesis_status:
            st.error("Thesis broken — consider reviewing your position.")
            if r and r.recommendation:
                st.markdown(f"Original recommendation: **{r.recommendation.action}** — "
                            f"may need to revisit given thesis change.")

        updated_thesis = st.text_area("Update thesis (optional):",
                                       placeholder="e.g. Original margin assumption incorrect, but moat still intact...",
                                       height=100, key="updated_thesis")
        if updated_thesis and st.button("Save Update"):
            st.session_state.notes.setdefault(ticker, [])
            st.session_state.notes[ticker].append(f"[Thesis Update {date.today().isoformat()}] {updated_thesis}")
            st.success("Thesis update saved.")

    with tab_portfolio:
        st.markdown("#### All Portfolio Positions")
        portfolio = st.session_state.portfolio
        if not portfolio:
            st.caption("No positions yet.")
        else:
            for pos in portfolio:
                with st.container():
                    pa,pb,pc,pd2,pe = st.columns([1.5, 2, 1.5, 1.5, 1])
                    dc = "#059669" if pos["decision"]=="Buy" else "#d97706"
                    pa.markdown(f"**{pos['ticker']}**")
                    pb.markdown(f"{pos.get('name','')[:25]}")
                    pc.markdown(f"<span style='color:{dc}'>{pos['decision']} · {pos['size']}</span>", unsafe_allow_html=True)
                    pd2.caption(pos.get("date",""))
                    if pe.button("Open", key=f"open_{pos['ticker']}_{pos['date']}"):
                        st.session_state.ticker = pos["ticker"]
                        go_step(5)

        st.markdown("---")
        st.markdown("#### Watchlist")
        watchlist = st.session_state.watchlist
        if not watchlist:
            st.caption("No companies on watchlist.")
        else:
            for w in watchlist:
                wa,wb,wc = st.columns([1.5, 3, 1])
                wa.markdown(f"**{w['ticker']}**")
                wb.caption(w.get("reason",""))
                if wc.button("Research", key=f"wl_{w['ticker']}"):
                    st.session_state.ticker = w["ticker"]
                    st.session_state.step   = 1
                    st.session_state.report = None
                    st.rerun()

    with tab_notes:
        st.markdown(f"#### Research Notes — {ticker}")
        notes = st.session_state.notes.get(ticker, [])
        if not notes:
            st.caption("No notes yet.")
        else:
            for note in reversed(notes):
                st.markdown(f'<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;'
                            f'padding:8px 12px;margin-bottom:8px;font-size:13px">{note}</div>',
                            unsafe_allow_html=True)

        new_note = st.text_area("Add a note:", height=80, key="new_note_s5",
                                placeholder="e.g. Checked Q3 earnings — margins stable, thesis intact.")
        if st.button("➕ Add Note"):
            if new_note.strip():
                st.session_state.notes.setdefault(ticker, [])
                st.session_state.notes[ticker].append(f"[{date.today().isoformat()}] {new_note.strip()}")
                st.rerun()

    st.markdown("---")
    col_new, col_port = st.columns(2)
    with col_new:
        if st.button("▶ Start New Research Session", key="s5_new", use_container_width=True):
            st.session_state.step   = 0
            st.session_state.ticker = ""
            st.session_state.report = None
            st.session_state.thesis = ""
            st.session_state.decision = None
            st.rerun()
    with col_port:
        if st.button("📁 View Full Portfolio", key="s5_port", use_container_width=True):
            st.session_state.step = 5
            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
#  Main router
# ─────────────────────────────────────────────────────────────────────────────
render_sidebar()

step = st.session_state.step

if   step == 0: step0_input()
elif step == 1: step1_info()
elif step == 2: step2_understand()
elif step == 3: step3_financials()
elif step == 4: step4_decision()
elif step == 5: step5_monitor()
