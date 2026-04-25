"""
ValueLens — Koyfin 风格 · Buffett Analyzer 完整功能
=====================================================
三个页面（左侧导航）：
  财报分析  — 上传 PDF / 搜索股票，AI 结构化解读
  市场新闻  — 自选股新闻聚合 + 大跌 / 财报预警
  深度研究  — 原版 Buffett Analyzer（公司 + 行业分析，逻辑完全不变）

放到原 Stock-analyzer 项目根目录，与 config.py / data / llm / reports 同级运行：
  pip install streamlit yfinance pandas anthropic markdown
  streamlit run valuelens_app.py
"""

from __future__ import annotations
import os, sys, json
from datetime import datetime
import streamlit as st
import yfinance as yf
import pandas as pd

# ── page config（必须最先）──────────────────────────────────────────────────
st.set_page_config(
    page_title="ValueLens",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 导入 Buffett Analyzer 模块 ──────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from data.yfinance_client import YFinanceClient, YFinanceError
from data.edgar_client import EdgarClient
from llm.claude_client import ClaudeClient, LLMError
from reports.company_report import run_company_analysis, report_to_json, report_to_markdown
from reports.industry_report_gen import run_industry_analysis, industry_report_to_markdown
import markdown as _markdown

# cache 版本刷新
if "cache_version" not in st.session_state or st.session_state.cache_version != "v3.0.0":
    st.cache_data.clear()
    st.session_state.cache_version = "v3.0.0"

anthropic_key = ""
try:
    anthropic_key = st.secrets.get("ANTHROPIC_API_KEY", "")
except Exception:
    pass

# ── CSS ─────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"], .stApp {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    background: #ffffff !important;
}
#MainMenu, footer, header, .stDeployButton { display: none !important; }
.block-container { padding: 0 !important; max-width: 100% !important; }

/* ── Sidebar ── */
section[data-testid="stSidebar"] {
    background: #f8f8f9 !important;
    border-right: 1px solid #e8e8ec !important;
    min-width: 220px !important;
    max-width: 220px !important;
}
section[data-testid="stSidebar"] .stButton > button {
    width: 100% !important;
    text-align: left !important;
    padding: 9px 12px !important;
    border-radius: 8px !important;
    border: none !important;
    background: transparent !important;
    color: #636366 !important;
    font-size: 13px !important;
    font-weight: 400 !important;
    justify-content: flex-start !important;
    box-shadow: none !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background: #ededf0 !important;
    color: #111 !important;
}
section[data-testid="stSidebar"] .stSlider > div { padding: 0 !important; }
section[data-testid="stSidebar"] .stSelectbox > div > div,
section[data-testid="stSidebar"] .stNumberInput > div > div > input {
    font-size: 12px !important;
    border-radius: 7px !important;
    border: 1px solid #e8e8ec !important;
    background: #fff !important;
}

/* ── Top header ── */
.vl-hd {
    padding: 13px 28px;
    border-bottom: 1px solid #e8e8ec;
    display: flex; align-items: center;
    background: #fff;
}
.vl-ticker { font-family: 'JetBrains Mono', monospace; font-size: 17px; font-weight: 500; color: #111; margin-right: 8px; }
.vl-tag    { font-size: 11px; color: #8e8e93; background: #f4f4f5; padding: 3px 8px; border-radius: 5px; margin-right: 10px; border: 1px solid #e8e8ec; }
.vl-name   { font-size: 14px; color: #636366; margin-right: 14px; }
.vl-sep    { width: 1px; height: 20px; background: #e8e8ec; margin: 0 14px; }
.vl-price  { font-family: 'JetBrains Mono', monospace; font-size: 17px; font-weight: 500; color: #111; margin-right: 8px; }
.vl-pos    { font-size: 14px; font-weight: 500; color: #15803d; }
.vl-neg    { font-size: 14px; font-weight: 500; color: #b91c1c; }
.vl-date   { font-size: 12px; color: #8e8e93; font-family: 'JetBrains Mono', monospace; margin-left: auto; }

/* ── Alert bar ── */
.vl-alerts { display: flex; gap: 8px; padding: 9px 28px; border-bottom: 1px solid #e8e8ec; flex-wrap: wrap; background: #fff; }
.ac-r { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 8px; font-size: 12px; font-weight: 500; background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }
.ac-a { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 8px; font-size: 12px; font-weight: 500; background: #fffbeb; color: #a16207; border: 1px solid #fde68a; }

/* ── Page head ── */
.pg-hd    { padding: 16px 28px 10px; }
.pg-title { font-size: 18px; font-weight: 600; letter-spacing: -.03em; color: #111; margin-bottom: 2px; }
.pg-sub   { font-size: 12px; color: #8e8e93; }
.pg-body  { padding: 0 28px 40px; }

/* ── KPI strip ── */
.kpi-strip { display: grid; gap: 1px; background: #e8e8ec; border: 1px solid #e8e8ec; border-radius: 12px; overflow: hidden; margin-bottom: 16px; }
.kpi-cell  { background: #fff; padding: 14px 18px; }
.kpi-l     { font-size: 11px; color: #8e8e93; margin-bottom: 5px; }
.kpi-v     { font-family: 'JetBrains Mono', monospace; font-size: 20px; font-weight: 500; line-height: 1; margin-bottom: 3px; }
.kpi-c     { font-size: 11px; font-weight: 500; }
.kpi-v.pos, .kpi-c.pos { color: #15803d; }
.kpi-v.neg, .kpi-c.neg { color: #b91c1c; }

/* ── Generic card ── */
.vc     { border: 1px solid #e8e8ec; border-radius: 12px; overflow: hidden; margin-bottom: 14px; background: #fff; }
.vc-hd  { padding: 12px 18px; border-bottom: 1px solid #e8e8ec; display: flex; align-items: center; justify-content: space-between; }
.vc-lbl { font-size: 12px; font-weight: 500; color: #636366; }
.vc-bd  { padding: 0 18px; }
.vc-ft  { padding: 10px 18px; background: #f8f8f9; border-top: 1px solid #e8e8ec; font-size: 11px; color: #8e8e93; }

/* ── Insight row ── */
.ir       { padding: 13px 0; border-bottom: 1px solid #f0f0f4; display: grid; grid-template-columns: 88px 1fr; gap: 14px; align-items: start; }
.ir:last-child { border-bottom: none; padding-bottom: 0; }
.ir-tag   { padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; text-align: center; line-height: 1.4; }
.ir-title { font-size: 13px; font-weight: 500; margin-bottom: 4px; color: #111; }
.ir-body  { font-size: 12px; color: #636366; line-height: 1.65; }

/* ── News card ── */
.nc        { border: 1px solid #e8e8ec; border-radius: 11px; padding: 13px 15px; margin-bottom: 8px; display: block; text-decoration: none; transition: border-color .15s; }
.nc:hover  { border-color: #c8c8ce; }
.nc-meta   { display: flex; align-items: center; justify-content: space-between; margin-bottom: 7px; }
.nc-cat    { font-size: 10px; font-weight: 600; padding: 3px 8px; border-radius: 5px; }
.nc-time   { font-size: 11px; color: #8e8e93; }
.nc-title  { font-size: 13px; font-weight: 500; line-height: 1.5; margin-bottom: 6px; color: #111; }
.nc-src    { font-size: 11px; color: #8e8e93; }
.nc-src b  { color: #1d4ed8; }
.nc.danger { border-color: #fecaca; }
.nc.danger .nc-title { color: #b91c1c; }

/* ── Earnings card grid ── */
.earn-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px; }
.ec        { border: 1px solid #e8e8ec; border-radius: 11px; padding: 14px; text-align: center; background: #fff; }
.ec-days   { font-family: 'JetBrains Mono', monospace; font-size: 28px; font-weight: 500; line-height: 1; margin-bottom: 3px; }
.ec-unit   { font-size: 10px; color: #8e8e93; margin-bottom: 8px; }
.ec-tk     { font-size: 13px; font-weight: 500; color: #111; margin-bottom: 2px; }
.ec-date   { font-size: 11px; color: #8e8e93; margin-bottom: 7px; }

/* ── Section label ── */
.sec-lbl { font-size: 10px; font-weight: 500; letter-spacing: .09em; text-transform: uppercase; color: #8e8e93; margin: 16px 0 8px; }

/* ── Company strip ── */
.co-strip  { padding: 12px 0 14px; border-bottom: 1px solid #e8e8ec; margin-bottom: 14px; display: flex; align-items: flex-start; justify-content: space-between; }
.co-code   { font-size: 11px; color: #8e8e93; margin-bottom: 3px; font-family: 'JetBrains Mono', monospace; }
.co-name   { font-size: 20px; font-weight: 600; letter-spacing: -.03em; color: #111; margin-bottom: 7px; }
.co-tags   { display: flex; gap: 6px; flex-wrap: wrap; }
.co-tag    { font-size: 11px; padding: 3px 9px; border-radius: 5px; border: 1px solid; }

/* ── Watchlist row ── */
.wl-row { display: flex; justify-content: space-between; align-items: center; padding: 6px 8px; border-radius: 7px; }
.wl-row:hover { background: #ededf0; cursor: pointer; }
.wl-tk  { font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 500; color: #111; }

/* ── Sub-tabs (inside pages) ── */
.stTabs [data-baseweb="tab-list"]    { background: transparent; border-bottom: 1px solid #e8e8ec; gap: 0; padding: 0; }
.stTabs [data-baseweb="tab"]         { font-size: 13px !important; font-weight: 500 !important; color: #8e8e93 !important; padding: 10px 18px !important; border-bottom: 2px solid transparent !important; }
.stTabs [aria-selected="true"]       { color: #111 !important; border-bottom-color: #111 !important; }
.stTabs [data-baseweb="tab-panel"]   { padding: 0 !important; }

/* ── Inputs / buttons ── */
.stTextInput > div > div > input,
.stSelectbox > div > div {
    font-family: 'Inter', sans-serif !important;
    border-radius: 9px !important; border: 1px solid #e8e8ec !important;
    font-size: 13px !important; background: #fff !important;
}
.stButton > button {
    font-family: 'Inter', sans-serif !important;
    font-size: 13px !important; font-weight: 500 !important;
    border-radius: 9px !important; padding: 9px 18px !important;
}
.stButton > button[kind="primary"]   { background: #111 !important; color: #fff !important; border: none !important; }
.stButton > button[kind="secondary"] { border: 1px solid #e8e8ec !important; background: #fff !important; color: #111 !important; }
div[data-testid="stFileUploadDropzone"] {
    border-radius: 12px !important; border: 1.5px dashed #d1d1d8 !important; background: #f8f8f9 !important;
}

/* ── Deep research area: restore normal st spacing ── */
.research-body .stMetric label { font-size: 11px !important; color: #8e8e93 !important; }
.research-body .stMetric [data-testid="stMetricValue"] { font-family: 'JetBrains Mono', monospace !important; font-size: 22px !important; font-weight: 500 !important; }
</style>
""", unsafe_allow_html=True)


# ── Shared data helpers ──────────────────────────────────────────────────────

@st.cache_data(ttl=120)
def _price(tk):
    try:
        h = yf.Ticker(tk).history(period="2d")
        if len(h) >= 2:
            c, p = float(h["Close"].iloc[-1]), float(h["Close"].iloc[-2])
            return round(c, 2), round((c - p) / p, 4)
        if len(h) == 1:
            return round(float(h["Close"].iloc[-1]), 2), 0.0
    except:
        pass
    return None, None

@st.cache_data(ttl=300)
def _info(tk):
    try: return yf.Ticker(tk).info or {}
    except: return {}

@st.cache_data(ttl=600)
def _earnings(tk):
    try:
        cal = yf.Ticker(tk).calendar
        if cal is not None and not cal.empty and "Earnings Date" in cal.index:
            raw = cal.loc["Earnings Date"]
            items = raw if (hasattr(raw, "__iter__") and not isinstance(raw, str)) else [raw]
            today = datetime.today().date()
            for d in items:
                dt = pd.to_datetime(d).date()
                if dt >= today: return dt
    except: pass
    return None

@st.cache_data(ttl=900)
def _news(tk, n=12):
    try:
        items = yf.Ticker(tk).news
        return (items or [])[:n]
    except: return []

def days_until(d):
    if d is None: return 9999
    try: return max(0, (pd.to_datetime(d).date() - datetime.today().date()).days)
    except: return 9999


def md_to_html(md_text: str, title: str = "Report") -> str:
    body = _markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    css = """
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:40px;color:#111;line-height:1.55;max-width:980px}
    h1,h2,h3{margin-top:28px} h1{font-size:28px} h2{font-size:22px} h3{font-size:18px}
    code{background:#f6f8fa;padding:2px 5px;border-radius:4px}
    pre{background:#f6f8fa;padding:12px;border-radius:8px;overflow-x:auto} pre code{background:transparent;padding:0}
    table{border-collapse:collapse;width:100%;margin:14px 0}
    th,td{border:1px solid #d0d7de;padding:8px;text-align:left;vertical-align:top} th{background:#f6f8fa}
    hr{border:none;border-top:1px solid #d0d7de;margin:24px 0}
    blockquote{border-left:4px solid #0969da;margin-left:0;background:#f0f7ff;padding:8px 12px;border-radius:0 4px 4px 0}
    """
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title><style>{css}</style></head><body>{body}</body></html>"


# ── Session state ────────────────────────────────────────────────────────────
if "watchlist" not in st.session_state:
    st.session_state.watchlist = ["AAPL", "NVDA", "MSFT", "PDD"]
if "pane" not in st.session_state:
    st.session_state.pane = "report"
if "focus" not in st.session_state:
    st.session_state.focus = st.session_state.watchlist[0]


# ══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:

    # Wordmark
    st.markdown("""
    <div style="display:flex;align-items:center;gap:8px;padding:4px 0 20px">
      <div style="width:22px;height:22px;border-radius:6px;background:#111;display:grid;place-items:center;flex-shrink:0">
        <svg width="12" height="12" fill="white" viewBox="0 0 12 12">
          <rect x="1" y="1" width="4" height="4" rx="1"/>
          <rect x="7" y="1" width="4" height="4" rx="1"/>
          <rect x="1" y="7" width="4" height="4" rx="1"/>
          <rect x="7" y="7" width="4" height="4" rx="1"/>
        </svg>
      </div>
      <span style="font-size:15px;font-weight:600;letter-spacing:-.03em;color:#111">ValueLens</span>
    </div>
    """, unsafe_allow_html=True)

    # Navigation
    st.markdown('<div style="font-size:10px;font-weight:500;letter-spacing:.09em;text-transform:uppercase;color:#8e8e93;padding:2px 4px 8px">功能</div>', unsafe_allow_html=True)

    for pid, icon, label in [("report","◉","财报分析"), ("news","◈","市场新闻"), ("research","◆","深度研究")]:
        if st.session_state.pane == pid:
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:9px;padding:9px 12px;border-radius:8px;
                        background:#fff;border:1px solid #e8e8ec;box-shadow:0 1px 3px rgba(0,0,0,.06);
                        margin-bottom:2px">
              <span style="font-size:12px;color:#111">{icon}</span>
              <span style="font-size:13px;font-weight:500;color:#111">{label}</span>
            </div>""", unsafe_allow_html=True)
        else:
            if st.button(f"{icon}  {label}", key=f"nav_{pid}", use_container_width=True):
                st.session_state.pane = pid
                st.rerun()

    # Watchlist
    st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:10px;font-weight:500;letter-spacing:.09em;text-transform:uppercase;color:#8e8e93;padding:2px 4px 8px">自选股</div>', unsafe_allow_html=True)
    for tk in st.session_state.watchlist:
        p, c = _price(tk)
        cc = "#15803d" if (c and c >= 0) else "#b91c1c"
        cs = f"{c*100:+.2f}%" if c is not None else "—"
        ps = f"${p:.2f}" if p else "—"
        st.markdown(f"""
        <div class="wl-row">
          <div>
            <span class="wl-tk">{tk}</span>
            <span style="font-size:11px;color:#8e8e93;margin-left:6px;font-family:'JetBrains Mono',monospace">{ps}</span>
          </div>
          <span style="font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:500;color:{cc}">{cs}</span>
        </div>""", unsafe_allow_html=True)

    # Deep research params (only shown on that pane)
    if st.session_state.pane == "research":
        st.markdown('<div style="height:14px"></div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size:10px;font-weight:500;letter-spacing:.09em;text-transform:uppercase;color:#8e8e93;padding:2px 4px 8px">估值参数（Fallback）</div>', unsafe_allow_html=True)
        st.caption("实际值由市场数据动态计算，以下为无数据时后备值")
        projection_years = st.slider("预测年数", 5, 15, config.PROJECTION_YEARS)
        discount_rate    = st.slider("折现率 (%)", 5, 20, int(config.DISCOUNT_RATE * 100)) / 100
        terminal_growth  = st.slider("终端增长率 (%)", 1, 6, int(config.TERMINAL_GROWTH_RATE * 100)) / 100

        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size:10px;font-weight:500;letter-spacing:.09em;text-transform:uppercase;color:#8e8e93;padding:2px 4px 8px">行业分析参数</div>', unsafe_allow_html=True)
        universe_size = st.slider("Universe 规模 (N)", 5, 50, config.DEFAULT_UNIVERSE_SIZE)
        sort_method   = st.selectbox("排序方式", ["market_cap", "revenue"])
        min_mcap      = st.number_input("最小市值 ($B)", value=config.MIN_MARKET_CAP / 1e9, min_value=0.1, step=0.5) * 1e9

        st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
        st.markdown('<div style="font-size:10px;font-weight:500;letter-spacing:.09em;text-transform:uppercase;color:#8e8e93;padding:2px 4px 8px">硬过滤阈值</div>', unsafe_allow_html=True)
        min_moat = st.slider("最低护城河分", 0, 100, config.MIN_MOAT_SCORE)
        min_fq   = st.slider("最低财务质量分", 0, 100, config.MIN_FINANCIAL_SCORE)
        min_stab = st.slider("最低稳定性分", 0, 100, config.MIN_STABILITY_SCORE)
        use_edgar = st.checkbox("获取 SEC EDGAR 文件", value=True)
    else:
        # defaults when not on research pane
        projection_years = config.PROJECTION_YEARS
        discount_rate    = config.DISCOUNT_RATE
        terminal_growth  = config.TERMINAL_GROWTH_RATE
        universe_size    = config.DEFAULT_UNIVERSE_SIZE
        sort_method      = "market_cap"
        min_mcap         = config.MIN_MARKET_CAP
        min_moat         = config.MIN_MOAT_SCORE
        min_fq           = config.MIN_FINANCIAL_SCORE
        min_stab         = config.MIN_STABILITY_SCORE
        use_edgar        = True


# ══════════════════════════════════════════════════════════════════════════════
#  TOP HEADER BAR  (共用，所有 pane 都显示)
# ══════════════════════════════════════════════════════════════════════════════
ftk = st.session_state.focus
fp, fc  = _price(ftk)
fi      = _info(ftk)
fn      = (fi.get("shortName") or ftk)[:24]
ps_hd   = f"${fp:.2f}" if fp else "—"
cs_hd   = f"{fc*100:+.2f}%" if fc is not None else "—"
cc_hd   = "vl-neg" if (fc and fc < 0) else "vl-pos"
tag_hd  = "A股" if (ftk.isdigit() and len(ftk) == 6) else "US"

st.markdown(f"""
<div class="vl-hd">
  <span class="vl-ticker">{ftk}</span>
  <span class="vl-tag">{tag_hd}</span>
  <span class="vl-name">{fn}</span>
  <div class="vl-sep"></div>
  <span class="vl-price">{ps_hd}</span>
  <span class="{cc_hd}">{cs_hd}</span>
  <span class="vl-date">{datetime.now().strftime("%m/%d  %H:%M")}</span>
</div>
""", unsafe_allow_html=True)

# Alert bar
_ab = ""
for tk in st.session_state.watchlist:
    p, c = _price(tk)
    if c is not None and c <= -0.05:
        _ab += f'<span class="ac-r">↓ {tk} 大跌 {c*100:.1f}%，关注负面消息</span>'
    ed = _earnings(tk)
    d  = days_until(ed)
    if d <= 7:
        ds = pd.to_datetime(ed).strftime("%m/%d") if ed else "?"
        _ab += f'<span class="ac-a">◷ {tk} 财报还有 {d} 天（{ds}）</span>'
if _ab:
    st.markdown(f'<div class="vl-alerts">{_ab}</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  PANE 1 — 财报分析
# ══════════════════════════════════════════════════════════════════════════════
if st.session_state.pane == "report":
    st.markdown('<div class="pg-hd"><div class="pg-title">财报分析</div><div class="pg-sub">上传 PDF 或输入股票代码，AI 自动生成结构化解读</div></div>', unsafe_allow_html=True)
    st.markdown('<div class="pg-body">', unsafe_allow_html=True)

    c1, c2 = st.columns([4, 1])
    with c1:
        st.text_input("", placeholder="输入股票代码或公司名，如 002176 / 江特电机…",
                      key="rpt_search", label_visibility="collapsed")
    with c2:
        st.file_uploader("上传 PDF", type=["pdf"], key="pdf_up", label_visibility="collapsed")

    st.button("分析", type="primary", key="rpt_run")

    # Static demo report (江特电机 from uploaded PDF)
    st.markdown("""
    <div class="co-strip">
      <div>
        <div class="co-code">002176.SZ &nbsp;·&nbsp; 电力设备 · 电机</div>
        <div class="co-name">江特电机 · 2025年三季度报告</div>
        <div class="co-tags">
          <span class="co-tag" style="background:#fef2f2;color:#b91c1c;border-color:#fecaca">净利润亏损扩大</span>
          <span class="co-tag" style="background:#fffbeb;color:#a16207;border-color:#fde68a">毛利率断崖下滑</span>
          <span class="co-tag" style="background:#fffbeb;color:#a16207;border-color:#fde68a">短期偿债承压</span>
        </div>
      </div>
      <div style="text-align:right">
        <div style="font-size:11px;color:#8e8e93">ValueLens AI 解读</div>
        <div style="font-size:12px;color:#636366;margin-top:2px">2025-10-31</div>
      </div>
    </div>
    <div class="kpi-strip" style="grid-template-columns:repeat(5,1fr)">
      <div class="kpi-cell"><div class="kpi-l">营业总收入</div><div class="kpi-v">14.32亿</div><div class="kpi-c pos">+14.6% YoY</div></div>
      <div class="kpi-cell"><div class="kpi-l">归母净利润</div><div class="kpi-v neg">−1.13亿</div><div class="kpi-c neg">−37.3% YoY</div></div>
      <div class="kpi-cell"><div class="kpi-l">毛利率</div><div class="kpi-v neg">2.63%</div><div class="kpi-c neg">vs 4.45% 上年</div></div>
      <div class="kpi-cell"><div class="kpi-l">经营现金流</div><div class="kpi-v neg">−3.38亿</div><div class="kpi-c pos">改善 +37.4%</div></div>
      <div class="kpi-cell"><div class="kpi-l">总资产</div><div class="kpi-v">60.08亿</div><div class="kpi-c neg">−7.8% YoY</div></div>
    </div>
    """, unsafe_allow_html=True)

    t1, t2, t3 = st.tabs(["核心洞察", "季度趋势", "风险预警"])

    with t1:
        st.markdown("""
        <div class="vc" style="margin-top:12px">
          <div class="vc-bd">
            <div class="ir">
              <span class="ir-tag" style="background:#fef2f2;color:#b91c1c">利润背离</span>
              <div><div class="ir-title">收入增长 +14.6%，但亏损反而扩大 37% — 毛利率才是核心矛盾</div>
              <div class="ir-body">碳酸锂市场价格较高位回落超 50%，固定成本无法摊薄，毛利率从 4.45% 骤降至 2.63%。这是结构性问题，不是季节性波动。</div></div>
            </div>
            <div class="ir">
              <span class="ir-tag" style="background:#fffbeb;color:#a16207">盈利质量</span>
              <div><div class="ir-title">Q3 账面扭亏，但扣非后仍亏 6690 万 — 主要依赖期货收益</div>
              <div class="ir-body">单季净利润账面转正，主要靠公允价值变动收益 4383 万（碳酸锂期货）。扣非后依然亏损，主营业务未见改善。</div></div>
            </div>
            <div class="ir">
              <span class="ir-tag" style="background:#fef2f2;color:#b91c1c">流动性</span>
              <div><div class="ir-title">短期借款暴增 615%，货币资金 5.25 亿勉强覆盖到期负债 5.34 亿</div>
              <div class="ir-body">长期借款重分类至一年内到期，若 Q4 无法获得新增融资，年末现金或跌破 2 亿，违约风险上升。</div></div>
            </div>
          </div>
          <div class="vc-ft">AI 基于财报原文生成 · 不构成投资建议</div>
        </div>
        """, unsafe_allow_html=True)

    with t2:
        st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({
            "指标":      ["单季营收（亿）","单季净利润（亿）","毛利率","经营现金流（亿）","短期借款（亿）"],
            "2025 Q3":  ["4.57","+0.01","−0.93%","−0.42","7.15"],
            "2025 Q2":  ["4.74","−0.71","2.85%","−1.55","—"],
            "2025 Q1":  ["5.01","−0.43","5.68%","−1.41","—"],
            "2024 Q4":  ["—","—","—","—","—"],
            "2024 Q3":  ["3.12","−0.21","4.45%","−1.35","1.00"],
        }).set_index("指标"), use_container_width=True)
        st.caption("毛利率从 Q1 的 5.68% 断崖式跌至 Q3 的 −0.93%，单季营收连续两季环比下滑")

    with t3:
        st.markdown("""
        <div class="vc" style="margin-top:12px">
          <div class="vc-hd">
            <span class="vc-lbl">风险预警</span>
            <span style="background:#fef2f2;color:#b91c1c;border:1px solid #fecaca;padding:3px 9px;border-radius:5px;font-size:11px;font-weight:500">高风险</span>
          </div>
          <div class="vc-bd">
            <div class="ir">
              <span class="ir-tag" style="background:#fef2f2;color:#b91c1c">高风险</span>
              <div><div class="ir-title">偿债缺口：货币资金 5.25亿 vs 一年内到期负债 5.34亿，覆盖率不足</div>
              <div class="ir-body">若银行不予续贷，违约风险将在 2026 年 Q1-Q2 集中暴露。</div></div>
            </div>
            <div class="ir">
              <span class="ir-tag" style="background:#fef2f2;color:#b91c1c">高风险</span>
              <div><div class="ir-title">Q3 单季毛利率转负（−0.93%）— 卖越多亏越多</div>
              <div class="ir-body">碳酸锂仍处下行通道，电机业务毛利率仅 2–3%，双业务同时承压。</div></div>
            </div>
            <div class="ir">
              <span class="ir-tag" style="background:#fffbeb;color:#a16207">中风险</span>
              <div><div class="ir-title">全年预计亏损 1.5–1.8亿，同比扩大 40–60%</div>
              <div class="ir-body">Q4 锂盐淡季，非经常性损益贡献减弱，全年亏损大概率进一步扩大。</div></div>
            </div>
          </div>
          <div class="vc-ft">风险评级：高 · 建议跟踪 Q4 债务滚动能力与锂价走势</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  PANE 2 — 市场新闻
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.pane == "news":
    st.markdown('<div class="pg-hd"><div class="pg-title">市场新闻</div><div class="pg-sub">自选股相关新闻 · 大跌预警 · 财报日历</div></div>', unsafe_allow_html=True)
    st.markdown('<div class="pg-body">', unsafe_allow_html=True)

    c1, c2 = st.columns([4, 1])
    with c1:
        sel_tk = st.selectbox("", st.session_state.watchlist, key="news_sel", label_visibility="collapsed")
    with c2:
        if st.button("↻ 刷新", key="ref_news"):
            st.cache_data.clear(); st.rerun()

    # Earnings countdown
    st.markdown('<div class="sec-lbl">财报倒计时</div>', unsafe_allow_html=True)
    earn_html = '<div class="earn-grid">'
    for tk in st.session_state.watchlist:
        ed = _earnings(tk); d = days_until(ed)
        ds = pd.to_datetime(ed).strftime("%Y-%m-%d") if ed else "未知"
        dn = str(d) if d < 999 else "90+"
        if d <= 7:    bc, tc, lb = "#fef2f2","#b91c1c","紧急"
        elif d <= 14: bc, tc, lb = "#fffbeb","#a16207","临近"
        elif d <= 60: bc, tc, lb = "#eff6ff","#1d4ed8","正常"
        else:         bc, tc, lb = "#f4f4f5","#52525b","远期"
        earn_html += f"""
        <div class="ec">
          <div class="ec-days" style="color:{tc}">{dn}</div>
          <div class="ec-unit">天后</div>
          <div class="ec-tk">{tk}</div>
          <div class="ec-date">{ds}</div>
          <span style="background:{bc};color:{tc};border:1px solid;padding:3px 9px;border-radius:5px;font-size:11px;font-weight:500">{lb}</span>
        </div>"""
    earn_html += "</div>"
    st.markdown(earn_html, unsafe_allow_html=True)

    # News feed
    st.markdown(f'<div class="sec-lbl">{sel_tk} 相关新闻</div>', unsafe_allow_html=True)
    with st.spinner("拉取新闻…"):
        news_items = _news(sel_tk, 12)

    neg_kw = ["跌","亏","下滑","警告","制裁","限制","违约","fall","drop","restrict",
              "ban","warning","loss","decline","tariff","sanction","penalty","crash","plunge"]
    if news_items:
        ca, cb = st.columns(2)
        for i, item in enumerate(news_items):
            title = item.get("title","（无标题）")
            pub   = item.get("publisher","")
            ts    = item.get("providerPublishTime", 0)
            link  = item.get("link","#")
            if ts:
                dt = datetime.fromtimestamp(ts); diff = datetime.now() - dt
                t_s = (f"{diff.seconds//3600}小时前" if diff.seconds >= 3600 else f"{diff.seconds//60}分钟前") \
                      if diff.days == 0 else ("昨天" if diff.days == 1 else dt.strftime("%m-%d"))
            else: t_s = ""
            is_neg = any(w.lower() in title.lower() for w in neg_kw)
            nc_cls  = "danger" if is_neg else ""
            cat_bg  = "background:#fef2f2;color:#b91c1c" if is_neg else "background:#f4f4f5;color:#52525b"
            cat_txt = "利空" if is_neg else "新闻"
            html = f"""
            <a href="{link}" target="_blank" style="text-decoration:none">
              <div class="nc {nc_cls}">
                <div class="nc-meta">
                  <span class="nc-cat" style="{cat_bg};padding:3px 8px;border-radius:5px">{cat_txt}</span>
                  <span class="nc-time">{t_s}</span>
                </div>
                <div class="nc-title">{title}</div>
                <div class="nc-src"><b>{pub}</b></div>
              </div>
            </a>"""
            (ca if i % 2 == 0 else cb).markdown(html, unsafe_allow_html=True)
    else:
        st.markdown('<div style="text-align:center;padding:40px;color:#8e8e93">暂无新闻</div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  PANE 3 — 深度研究  (原版 Buffett Analyzer，逻辑完全保留)
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.pane == "research":
    st.markdown('<div class="pg-hd"><div class="pg-title">深度研究</div><div class="pg-sub">DCF 融合估值 · 护城河分析 · 回报结构 · 行业对比 | Buffett Analyzer v2.0</div></div>', unsafe_allow_html=True)
    st.markdown('<div class="pg-body research-body">', unsafe_allow_html=True)

    tab_company, tab_industry = st.tabs(["公司分析", "行业分析"])

    # ──────────────────────────────────────────────────────────────────────────
    #  公司分析  (原版逻辑，完整保留)
    # ──────────────────────────────────────────────────────────────────────────
    with tab_company:
        st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)
        col1, col2 = st.columns([3, 1])
        with col1:
            ticker = st.text_input("输入股票代码", placeholder="AAPL", key="company_ticker")
        with col2:
            st.write(""); st.write("")
            run_company = st.button("开始分析", key="run_company", type="primary")

        if run_company and ticker:
            st.session_state.focus = ticker.upper()
            config.MIN_MOAT_SCORE       = min_moat
            config.MIN_FINANCIAL_SCORE  = min_fq
            config.MIN_STABILITY_SCORE  = min_stab

            progress = st.empty()
            def company_progress(msg: str): progress.info(msg)

            try:
                data_client = YFinanceClient()
                llm = None
                if anthropic_key:
                    try: llm = ClaudeClient(api_key=anthropic_key)
                    except LLMError: st.warning("⚠️ Anthropic Key 无效，仅使用确定性评分")

                edgar = EdgarClient() if use_edgar else None

                report = run_company_analysis(
                    ticker=ticker, data_client=data_client, llm=llm, edgar=edgar,
                    discount_rate=discount_rate, terminal_growth=terminal_growth,
                    projection_years=projection_years, progress_callback=company_progress,
                )

                rec = report.recommendation
                progress.success(f"✅ 分析完成：{rec['action']} / {rec['position_size']} 仓位")

                # 三句话摘要
                if report.three_sentence_summary:
                    ts = report.three_sentence_summary
                    st.info("📌 **三句话摘要（普通人版）**")
                    col_a, col_b, col_c = st.columns(3)
                    with col_a: st.markdown(ts["sentence1_what"])
                    with col_b: st.markdown(ts["sentence2_return"])
                    with col_c: st.markdown(ts["sentence3_verdict"])
                    st.divider()

                # 融合估值 + 置信度
                if report.fusion_summary:
                    fs = report.fusion_summary
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("融合 IV", f"${fs.get('fusion_iv', 0):.0f}",
                                  delta=f"区间 ${fs.get('fusion_iv_low',0):.0f}–${fs.get('fusion_iv_high',0):.0f}")
                    with col2:
                        conf = fs.get("confidence_level", "N/A")
                        conf_color = "🟢" if conf == "High" else ("🟡" if conf == "Medium" else "🔴")
                        st.metric("置信度", f"{conf_color} {conf}", delta=f"{fs.get('confidence_score',0):.0f}/100")
                    with col3:
                        mw = fs.get("market_weight_pct", 0)
                        dw = fs.get("model_weight_pct", 100)
                        st.metric("权重分配", f"市场{mw:.0f}% / 模型{dw:.0f}%", delta=fs.get("company_type",""))
                    with col4:
                        dr = fs.get("dynamic_discount_rate_pct")
                        gr = fs.get("dynamic_growth_rate_pct")
                        if dr: st.metric("动态折现率", f"{dr:.2f}%", delta="市场校准")
                        else:  st.metric("增长率", f"{gr:.2f}%" if gr else "N/A")
                    if fs.get("sanity_triggered"):
                        st.error(f"⚠️ **偏差警告**：{fs.get('sanity_note','')}")
                    st.divider()

                # 回报结构
                if report.return_structure:
                    rs = report.return_structure
                    st.markdown("### 💰 预期年化回报结构")
                    col1, col2, col3, col4 = st.columns(4)
                    with col1: st.metric("预期总回报", f"{rs['expected_annual_return_pct']:.1f}%")
                    with col2: st.metric("📈 增长贡献", f"{rs['from_growth_pct']:.1f}%")
                    with col3: st.metric("🔄 回购贡献", f"{rs['from_buyback_pct']:.1f}%")
                    with col4: st.metric("💵 股息贡献", f"{rs['from_dividend_pct']:.1f}%")
                    st.caption(rs.get("note", ""))
                    st.divider()

                # 市场快照
                if report.market_snapshot:
                    ms = report.market_snapshot
                    with st.expander("📊 市场快照（Analyst 数据）", expanded=False):
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            if ms.get("trailing_pe"): st.metric("TTM PE", f"{ms['trailing_pe']:.1f}x")
                            if ms.get("forward_pe"):  st.metric("Forward PE", f"{ms['forward_pe']:.1f}x")
                        with col2:
                            if ms.get("analyst_target_mean"):
                                st.metric(f"Analyst 目标价（{ms['analyst_count']}位）",
                                          f"${ms['analyst_target_mean']:.0f}",
                                          delta=f"区间 ${ms.get('analyst_target_low','?')}–${ms.get('analyst_target_high','?')}")
                        with col3:
                            if ms.get("dividend_yield_pct"): st.metric("股息率", f"{ms['dividend_yield_pct']:.2f}%")
                            if ms.get("buyback_yield_pct"):  st.metric("回购率（估算）", f"{ms['buyback_yield_pct']:.2f}%")

                # 完整 Markdown 报告
                st.divider()
                md = report_to_markdown(report)
                st.markdown(md)

                # 下载
                html_doc = md_to_html(md, title=f"{ticker.upper()} Buffett Report v2")
                col_dl1, col_dl2, col_dl3 = st.columns(3)
                with col_dl1:
                    st.download_button("📥 下载 JSON", data=report_to_json(report),
                                       file_name=f"{ticker.upper()}_report_v2.json", mime="application/json")
                with col_dl2:
                    st.download_button("📥 下载 Markdown", data=md,
                                       file_name=f"{ticker.upper()}_report_v2.md", mime="text/markdown")
                with col_dl3:
                    st.download_button("🌐 下载 HTML", data=html_doc,
                                       file_name=f"{ticker.upper()}_report_v2.html", mime="text/html")

                # 保存到 output/
                output_dir = os.path.join(os.path.dirname(__file__), "output")
                os.makedirs(output_dir, exist_ok=True)
                for ext, content in [("json", report_to_json(report)), ("md", md), ("html", html_doc)]:
                    with open(os.path.join(output_dir, f"{ticker.upper()}_report_v2.{ext}"), "w", encoding="utf-8") as f:
                        f.write(content)

            except YFinanceError as e:
                st.error(f"❌ 数据错误：{e}")
            except RuntimeError as e:
                st.error(f"❌ {e}")
            except Exception as e:
                st.error(f"❌ 未知错误：{e}"); st.exception(e)

    # ──────────────────────────────────────────────────────────────────────────
    #  行业分析  (原版逻辑，完整保留)
    # ──────────────────────────────────────────────────────────────────────────
    with tab_industry:
        st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)
        col1, col2 = st.columns([3, 1])
        with col1:
            industry = st.text_input("输入行业名称", placeholder="Semiconductors", key="industry_name")
        with col2:
            st.write(""); st.write("")
            run_industry = st.button("分析行业", key="run_industry", type="primary")

        if run_industry and industry:
            config.MIN_MOAT_SCORE      = min_moat
            config.MIN_FINANCIAL_SCORE = min_fq
            config.MIN_STABILITY_SCORE = min_stab

            progress = st.empty()
            def industry_progress(msg: str): progress.info(msg)

            try:
                data_client = YFinanceClient()
                llm = None
                if anthropic_key:
                    try: llm = ClaudeClient(api_key=anthropic_key)
                    except LLMError: st.warning("⚠️ Anthropic Key 无效")

                edgar = EdgarClient() if use_edgar else None

                report = run_industry_analysis(
                    industry=industry, data_client=data_client, llm=llm, edgar=edgar,
                    n=universe_size, sort_by=sort_method, min_market_cap=min_mcap,
                    discount_rate=discount_rate, terminal_growth=terminal_growth,
                    projection_years=projection_years, progress_callback=industry_progress,
                )

                progress.success(
                    f"✅ 行业分析完成：{len(report.all_reports)} 家公司，Top {len(report.top_5)} 家上榜"
                )

                md = industry_report_to_markdown(report)
                st.markdown(md)

                json_data = report.model_dump_json(indent=2)
                safe_name = industry.replace(" ", "_").replace("/", "_")
                html_doc  = md_to_html(md, title=f"{safe_name} Industry Report")

                col_dl1, col_dl2, col_dl3 = st.columns(3)
                with col_dl1: st.download_button("📥 JSON", data=json_data, file_name=f"{safe_name}_industry.json", mime="application/json")
                with col_dl2: st.download_button("📥 Markdown", data=md, file_name=f"{safe_name}_industry.md", mime="text/markdown")
                with col_dl3: st.download_button("🌐 HTML", data=html_doc, file_name=f"{safe_name}_industry.html", mime="text/html")

                output_dir = os.path.join(os.path.dirname(__file__), "output")
                os.makedirs(output_dir, exist_ok=True)
                for ext, content in [("json", json_data), ("md", md), ("html", html_doc)]:
                    with open(os.path.join(output_dir, f"{safe_name}_industry.{ext}"), "w", encoding="utf-8") as f:
                        f.write(content)

            except YFinanceError as e: st.error(f"❌ 数据错误：{e}")
            except Exception as e: st.error(f"❌ 未知错误：{e}"); st.exception(e)

    st.markdown('</div>', unsafe_allow_html=True)


# ── Footer ───────────────────────────────────────────────────────────────────
st.markdown(
    '<div style="text-align:center;font-size:11px;color:#8e8e93;padding:20px 28px">'
    'ValueLens · Buffett Analyzer v2.0 · 融合估值 | 动态折现率 | 回报结构 | 置信度系统 &nbsp;·&nbsp; 仅供研究，不构成投资建议'
    '</div>',
    unsafe_allow_html=True,
)
