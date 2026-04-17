"""
ValueLens — 股票监控 App (Streamlit Mobile)
============================================
核心功能：
  Tab 1  持仓监控   每次打开自动运行基本面健康评分，检测结构性恶化
  Tab 2  财报提醒   倒计时卡片，7天内变红预警
  Tab 3  新闻聚合   每日持仓相关新闻，按时间排序
  Tab 4  财报分析   最近4季度营收/利润/FCF同比对比 + 关键指标
  Tab 5  设置       管理持仓列表

安装依赖：
  pip install streamlit yfinance pandas requests

运行：
  streamlit run valuelens_app.py

手机访问：部署到 Streamlit Cloud（免费）或本地运行后用手机浏览器打开
"""

import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import time

# ─── 必须最先设置 ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ValueLens",
    page_icon="◆",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ─── 全局样式：白色系 · 移动端优先 ──────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap');

/* ── 基础重置 ── */
html, body, [class*="css"], .stApp {
    font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
    background-color: #f5f5f7 !important;
}
#MainMenu, footer, header { display: none !important; }
.stDeployButton { display: none !important; }

/* ── 内容宽度限制为手机宽 ── */
.block-container {
    max-width: 480px !important;
    padding: 0 !important;
    margin: 0 auto !important;
}

/* ── Tab 样式 ── */
.stTabs [data-baseweb="tab-list"] {
    background: #ffffff;
    border-bottom: 1px solid #e5e5ea;
    padding: 0 12px;
    gap: 0;
    overflow-x: auto;
}
.stTabs [data-baseweb="tab"] {
    font-size: 13px !important;
    font-weight: 500 !important;
    color: #8e8e93 !important;
    padding: 12px 14px !important;
    border-bottom: 2px solid transparent !important;
    white-space: nowrap;
}
.stTabs [aria-selected="true"] {
    color: #1c1c1e !important;
    border-bottom-color: #1c1c1e !important;
    background: transparent !important;
}
.stTabs [data-baseweb="tab-panel"] {
    padding: 12px 14px 80px !important;
    background: #f5f5f7 !important;
}

/* ── 按钮 ── */
.stButton > button {
    font-family: 'DM Sans', sans-serif !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    border-radius: 10px !important;
    border: 1px solid #e5e5ea !important;
    background: #ffffff !important;
    color: #1c1c1e !important;
    padding: 8px 14px !important;
    transition: background 0.15s !important;
}
.stButton > button:hover {
    background: #f5f5f7 !important;
}
.stButton > button:active {
    transform: scale(0.98);
}

/* ── 输入框 ── */
.stTextInput > div > div > input {
    font-family: 'DM Mono', monospace !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    border-radius: 10px !important;
    border: 1px solid #e5e5ea !important;
    background: #ffffff !important;
    padding: 10px 12px !important;
}
.stSelectbox > div > div {
    border-radius: 10px !important;
    border: 1px solid #e5e5ea !important;
    font-size: 13px !important;
}

/* ── 展开器 ── */
.streamlit-expanderHeader {
    font-size: 13px !important;
    font-weight: 500 !important;
    color: #1c1c1e !important;
}

/* ── Spinner ── */
.stSpinner { color: #1c1c1e !important; }

/* ── 自定义组件样式 ── */

/* 顶栏 */
.vl-topbar {
    background: #ffffff;
    border-bottom: 1px solid #e5e5ea;
    padding: 13px 16px 12px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: 0 -14px;
}
.vl-logo {
    font-size: 17px;
    font-weight: 600;
    letter-spacing: -0.03em;
    color: #1c1c1e;
}
.vl-logo-dot {
    display: inline-block;
    width: 7px; height: 7px;
    background: #0071e3;
    border-radius: 50%;
    margin-right: 5px;
    vertical-align: middle;
    margin-bottom: 1px;
}
.vl-time {
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    color: #8e8e93;
}

/* 卡片 */
.vcard {
    background: #ffffff;
    border-radius: 14px;
    padding: 15px 16px;
    margin-bottom: 10px;
    border: 1px solid #e5e5ea;
}
.vcard-sm {
    background: #f8f8fa;
    border-radius: 10px;
    padding: 11px 13px;
    margin-bottom: 8px;
    border: 1px solid #ebebef;
}

/* 标签 */
.vlabel {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #8e8e93;
    margin-bottom: 5px;
}

/* 徽章 */
.badge {
    display: inline-flex;
    align-items: center;
    padding: 3px 9px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 600;
}
.badge-green  { background:#f0fdf4; color:#15803d; border:1px solid #bbf7d0; }
.badge-amber  { background:#fffbeb; color:#a16207; border:1px solid #fde68a; }
.badge-red    { background:#fef2f2; color:#b91c1c; border:1px solid #fecaca; }
.badge-blue   { background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe; }
.badge-gray   { background:#f4f4f5; color:#52525b; border:1px solid #e4e4e7; }

/* 指标网格 */
.mgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 10px 0; }
.mgrid-3 { grid-template-columns: 1fr 1fr 1fr; }
.mcell { background:#f8f8fa; border-radius:10px; padding:11px 13px; }
.mc-l { font-size:10.5px; color:#8e8e93; margin-bottom:4px; }
.mc-v { font-family:'DM Mono',monospace; font-size:20px; font-weight:500; line-height:1; color:#1c1c1e; }
.mc-v.pos { color:#15803d; }
.mc-v.neg { color:#b91c1c; }
.mc-v.warn{ color:#a16207; }
.mc-n { font-size:10px; color:#8e8e93; margin-top:2px; }

/* 分割线 */
.vdivider { height:1px; background:#ebebef; margin:10px 0; }

/* 信号行 */
.sig-row {
    display:flex; justify-content:space-between; align-items:flex-start;
    padding:11px 0; border-bottom:1px solid #f0f0f5; gap:10px;
}
.sig-row:last-child { border-bottom:none; }
.sig-title { font-size:13px; font-weight:500; color:#1c1c1e; margin-bottom:3px; }
.sig-body  { font-size:12px; color:#636366; line-height:1.55; }
.sig-meta  { font-size:10.5px; color:#8e8e93; margin-top:4px; }

/* 新闻卡 */
.news-card {
    background:#ffffff; border-radius:12px;
    padding:12px 14px; margin-bottom:8px;
    border:1px solid #e5e5ea; display:block;
}
.news-title { font-size:13px; font-weight:500; color:#1c1c1e; margin-bottom:5px; line-height:1.45; }
.news-meta  { font-size:11px; color:#8e8e93; }
.news-src   { color:#0071e3; font-weight:500; }

/* 财报倒计时 */
.earn-card {
    border-radius:13px; padding:14px 15px;
    margin-bottom:9px; border:1px solid;
    display:flex; align-items:center; gap:14px;
}
.earn-days { font-family:'DM Mono',monospace; font-size:32px; font-weight:500; line-height:1; }
.earn-unit { font-size:11px; margin-top:2px; }
.earn-sep  { width:1px; height:44px; opacity:0.25; background:currentColor; }
.earn-ticker { font-size:15px; font-weight:600; margin-bottom:2px; }
.earn-name   { font-size:12px; opacity:0.75; }
.earn-date   { font-size:12px; font-weight:500; margin-left:auto; }

/* 健康评分圈 */
.hcircle {
    width:54px; height:54px; border-radius:50%;
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    flex-shrink:0; font-weight:600;
}
.hc-num { font-family:'DM Mono',monospace; font-size:16px; line-height:1; }
.hc-sub { font-size:9px; margin-top:1px; }

/* 持仓行 */
.holding-row {
    display:flex; align-items:center; gap:10px;
    padding:11px 0; border-bottom:1px solid #f0f0f5; cursor:pointer;
}
.holding-row:last-child { border-bottom:none; }
.hr-ticker { font-family:'DM Mono',monospace; font-size:14px; font-weight:500; min-width:50px; color:#1c1c1e; }
.hr-name   { font-size:12px; color:#636366; flex:1; }
.hr-price  { font-family:'DM Mono',monospace; font-size:14px; font-weight:500; color:#1c1c1e; }
.hr-chg    { font-size:12px; font-weight:600; min-width:52px; text-align:right; }

/* 警告横幅 */
.warn-banner {
    background:#fffbeb; border:1px solid #fde68a; border-radius:11px;
    padding:11px 13px; margin-bottom:9px; display:flex; gap:10px;
}
.warn-banner.danger { background:#fef2f2; border-color:#fecaca; }
.wb-icon  { font-size:15px; flex-shrink:0; padding-top:1px; }
.wb-title { font-size:13px; font-weight:600; color:#92400e; margin-bottom:2px; }
.wb-body  { font-size:12px; color:#a16207; line-height:1.5; }
.warn-banner.danger .wb-title { color:#991b1b; }
.warn-banner.danger .wb-body  { color:#b91c1c; }

/* 空状态 */
.empty {
    text-align:center; padding:40px 20px; color:#8e8e93; font-size:14px;
}
.empty-icon { font-size:30px; margin-bottom:10px; }

/* 季度条 */
.qbar {
    flex:1; border-radius:8px; padding:9px 8px; text-align:center;
}
.qbar-q  { font-size:10px; color:#8e8e93; margin-bottom:3px; }
.qbar-v  { font-family:'DM Mono',monospace; font-size:13px; font-weight:500; }
.qbar-ch { font-size:10px; font-weight:600; margin-top:2px; }
</style>
""", unsafe_allow_html=True)


# ─── 工具函数 ────────────────────────────────────────────────────────────────

def fmt_big(n):
    """格式化大数字 → 1.2B / 340M"""
    if n is None: return "—"
    try:
        n = float(n)
        if pd.isna(n): return "—"
        if abs(n) >= 1e12: return f"{n/1e12:.2f}T"
        if abs(n) >= 1e9:  return f"{n/1e9:.2f}B"
        if abs(n) >= 1e6:  return f"{n/1e6:.1f}M"
        return f"{n:,.0f}"
    except: return "—"

def fmt_pct(n, multiply=True):
    if n is None: return "—"
    try:
        v = float(n)
        if pd.isna(v): return "—"
        if multiply: v *= 100
        return f"{v:+.1f}%" if v != 0 else "0.0%"
    except: return "—"

def fmt_x(n, suffix="x"):
    if n is None: return "—"
    try:
        v = float(n)
        if pd.isna(v) or v <= 0: return "—"
        return f"{v:.1f}{suffix}"
    except: return "—"

def pct_sign_class(val):
    try:
        return "pos" if float(val) >= 0 else "neg"
    except: return ""

def days_to(d):
    if d is None: return 9999
    try:
        return max(0, (pd.to_datetime(d).date() - datetime.today().date()).days)
    except: return 9999

def health_color(score):
    if score >= 72: return "#15803d"
    if score >= 52: return "#a16207"
    return "#b91c1c"

def health_badge(status):
    m = {"健康": "green", "关注": "amber", "预警": "red"}
    return f'<span class="badge badge-{m.get(status,"gray")}">{status}</span>'

def badge(text, style="gray"):
    return f'<span class="badge badge-{style}">{text}</span>'


# ─── 数据获取（全部带缓存）────────────────────────────────────────────────────

@st.cache_data(ttl=120)
def get_price(ticker):
    """当前价格 + 涨跌幅，2分钟缓存"""
    try:
        h = yf.Ticker(ticker).history(period="2d")
        if len(h) >= 2:
            c, p = float(h["Close"].iloc[-1]), float(h["Close"].iloc[-2])
            return round(c, 2), round((c-p)/p, 4)
        elif len(h) == 1:
            return round(float(h["Close"].iloc[-1]), 2), 0.0
    except: pass
    return None, None

@st.cache_data(ttl=300)
def get_info(ticker):
    """公司基本信息，5分钟缓存"""
    try:
        return yf.Ticker(ticker).info or {}
    except: return {}

@st.cache_data(ttl=600)
def get_earnings_date(ticker):
    """下次财报日期，10分钟缓存"""
    try:
        cal = yf.Ticker(ticker).calendar
        if cal is not None and not cal.empty and "Earnings Date" in cal.index:
            raw = cal.loc["Earnings Date"]
            candidates = raw if hasattr(raw, '__iter__') and not isinstance(raw, str) else [raw]
            today = datetime.today().date()
            for d in candidates:
                try:
                    dt = pd.to_datetime(d).date()
                    if dt >= today:
                        return dt
                except: pass
    except: pass
    return None

@st.cache_data(ttl=600)
def get_financials(ticker):
    """季度财务数据，10分钟缓存"""
    try:
        t = yf.Ticker(ticker)
        return t.quarterly_financials, t.quarterly_cashflow, t.quarterly_balance_sheet
    except: return None, None, None

@st.cache_data(ttl=900)
def get_news(ticker, n=10):
    """新闻，15分钟缓存"""
    try:
        items = yf.Ticker(ticker).news
        return (items or [])[:n]
    except: return []

@st.cache_data(ttl=300)
def get_historical(ticker, period="1y"):
    """历史价格"""
    try:
        return yf.Ticker(ticker).history(period=period)
    except: return pd.DataFrame()


# ─── 健康评分引擎 ─────────────────────────────────────────────────────────────

def compute_health(info: dict) -> tuple:
    """
    六维健康评分 (0-100)
    返回 (score, warnings, status)
    结构性恶化 = 多项同时出问题
    """
    score = 68
    warns = []
    detail = {}

    try:
        # 1. 盈利能力
        gm = info.get("grossMargins")
        om = info.get("operatingMargins")
        if gm is not None and not pd.isna(gm):
            detail["毛利率"] = fmt_pct(gm)
            if gm < 0.10:
                score -= 18; warns.append(f"毛利率极低 {fmt_pct(gm)}")
            elif gm < 0.20:
                score -= 8;  warns.append(f"毛利率偏低 {fmt_pct(gm)}")
        if om is not None and not pd.isna(om):
            detail["营业利润率"] = fmt_pct(om)
            if om < 0:
                score -= 22; warns.append(f"营业亏损 {fmt_pct(om)}")
            elif om < 0.05:
                score -= 10; warns.append(f"营业利润率偏薄 {fmt_pct(om)}")

        # 2. 成长性
        rg = info.get("revenueGrowth")
        eg = info.get("earningsGrowth")
        if rg is not None and not pd.isna(rg):
            detail["营收增速"] = fmt_pct(rg)
            if rg < -0.10:
                score -= 18; warns.append(f"营收同比大幅下滑 {fmt_pct(rg)}")
            elif rg < -0.03:
                score -= 8;  warns.append(f"营收同比下滑 {fmt_pct(rg)}")
            elif rg > 0.15:
                score += 5
        if eg is not None and not pd.isna(eg):
            detail["盈利增速"] = fmt_pct(eg)
            if eg < -0.25:
                score -= 12; warns.append(f"盈利同比大幅下滑 {fmt_pct(eg)}")
            elif eg < -0.10:
                score -= 6;  warns.append(f"盈利同比下滑 {fmt_pct(eg)}")

        # 3. 财务稳健性
        de = info.get("debtToEquity")
        cr = info.get("currentRatio")
        if de is not None and not pd.isna(de):
            detail["D/E"] = f"{de:.0f}%"
            if de > 300:
                score -= 14; warns.append(f"杠杆过高 D/E={de:.0f}%")
            elif de > 150:
                score -= 6;  warns.append(f"杠杆偏高 D/E={de:.0f}%")
        if cr is not None and not pd.isna(cr):
            detail["流动比率"] = f"{cr:.2f}x"
            if cr < 0.8:
                score -= 12; warns.append(f"流动性偏紧 {cr:.2f}x")
            elif cr < 1.2:
                score -= 5;  warns.append(f"流动比率偏低 {cr:.2f}x")

        # 4. 现金流质量
        fcf = info.get("freeCashflow")
        ni  = info.get("netIncomeToCommon")
        if fcf is not None and ni is not None and not pd.isna(fcf) and not pd.isna(ni):
            detail["FCF"] = fmt_big(fcf)
            if ni > 0 and fcf < 0:
                score -= 10; warns.append("利润为正但FCF为负，盈利质量存疑")
            elif ni > 0 and fcf > ni * 1.1:
                score += 5  # FCF > 净利润，高质量

        # 5. 估值（不扣分，仅提示）
        pe = info.get("trailingPE")
        if pe is not None and not pd.isna(pe) and pe > 80:
            warns.append(f"估值偏高 PE={pe:.0f}x")

        # 6. ROE 加分
        roe = info.get("returnOnEquity")
        if roe is not None and not pd.isna(roe) and roe > 0.20:
            score += 4

    except Exception as e:
        pass

    score = max(0, min(100, score))

    if score >= 72:
        status = "健康"
    elif score >= 52:
        status = "关注"
    else:
        status = "预警"

    return score, warns, status, detail


# ─── Session state 初始化 ─────────────────────────────────────────────────────

if "watchlist" not in st.session_state:
    st.session_state.watchlist = ["AAPL", "NVDA", "MSFT", "PDD"]
if "sel" not in st.session_state:
    st.session_state.sel = st.session_state.watchlist[0]
if "detail_ticker" not in st.session_state:
    st.session_state.detail_ticker = st.session_state.watchlist[0]


# ─── 顶栏 ────────────────────────────────────────────────────────────────────

now_str = datetime.now().strftime("%H:%M")
date_str = datetime.now().strftime("%m月%d日")

st.markdown(f"""
<div class="vl-topbar">
  <div class="vl-logo">
    <span class="vl-logo-dot"></span>ValueLens
  </div>
  <div class="vl-time">{date_str} &nbsp;{now_str}</div>
</div>
<div style="height:8px"></div>
""", unsafe_allow_html=True)


# ─── 全局紧急提醒（财报7天内 or 健康预警） ───────────────────────────────────
urgent_banners = []
for tk in st.session_state.watchlist:
    # 财报提醒
    edate = get_earnings_date(tk)
    d = days_to(edate)
    if d <= 7:
        date_fmt = pd.to_datetime(edate).strftime("%m/%d") if edate else "?"
        urgent_banners.append(("danger", f"财报即将发布 — {tk}", f"{date_fmt} 发布，还有 {d} 天，提前做好准备"))
    # 健康预警
    info = get_info(tk)
    score, warns, status, _ = compute_health(info)
    if score < 52 and warns:
        urgent_banners.append(("danger", f"基本面预警 — {tk}", warns[0]))

for style, title, body in urgent_banners[:3]:  # 最多显示3条
    st.markdown(f"""
    <div class="warn-banner {style}">
      <div class="wb-icon">{'⚠' if style=='danger' else 'ℹ'}</div>
      <div>
        <div class="wb-title">{title}</div>
        <div class="wb-body">{body}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)


# ─── 主 Tab ──────────────────────────────────────────────────────────────────

t1, t2, t3, t4, t5 = st.tabs(["持仓", "提醒", "新闻", "财报", "设置"])


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — 持仓监控  ·  每日健康评分
# ══════════════════════════════════════════════════════════════════════════════

with t1:
    col_r, col_f = st.columns([3, 1])
    with col_r:
        st.markdown('<div class="vlabel">持仓监控</div>', unsafe_allow_html=True)
    with col_f:
        if st.button("↻", key="r1", help="刷新"):
            st.cache_data.clear(); st.rerun()

    st.markdown('<div class="vcard">', unsafe_allow_html=True)
    for idx, tk in enumerate(st.session_state.watchlist):
        info  = get_info(tk)
        price, chg = get_price(tk)
        score, warns, status, detail = compute_health(info)
        name  = (info.get("shortName") or tk)[:22]
        hc    = health_color(score)

        price_str = f"${price:.2f}" if price else "—"
        chg_str   = f"{chg*100:+.1f}%" if chg is not None else "—"
        chg_cls   = "pos" if (chg and chg >= 0) else "neg"

        warn_text = " · ".join(warns[:2]) if warns else ""

        bmap = {"健康": "green", "关注": "amber", "预警": "red"}
        bc   = bmap.get(status, "gray")

        # 点击切换到详情
        if st.button(f"  {tk}   {price_str}   {chg_str}  ", key=f"w_{tk}",
                     use_container_width=True):
            st.session_state.detail_ticker = tk
            st.session_state.sel = tk

        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:10px;margin:-6px 0 10px;padding:0 2px">
          <div style="flex:1">
            <div style="font-size:11.5px;color:#636366">{name}</div>
            {'<div style="font-size:11px;color:#a16207;margin-top:2px">⚠ ' + warn_text + '</div>' if warn_text else ''}
          </div>
          <span class="badge badge-{bc}">{status}</span>
          <div class="hcircle" style="background:{hc}18;border:2px solid {hc}55;color:{hc}">
            <div class="hc-num">{score}</div>
            <div class="hc-sub">分</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        if idx < len(st.session_state.watchlist) - 1:
            st.markdown('<div class="vdivider"></div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)

    # 评分说明
    st.markdown("""
    <div class="vcard-sm">
      <div class="vlabel">评分维度（0-100分）</div>
      <div style="font-size:12px;color:#636366;line-height:1.8">
        盈利能力（毛利率 · 营业利润率）&nbsp;·&nbsp;
        成长性（营收/盈利同比）&nbsp;·&nbsp;
        财务稳健（D/E · 流动比率）&nbsp;·&nbsp;
        现金流质量（FCF vs 净利润）<br>
        <span style="color:#15803d;font-weight:600">72+ 健康</span>
        &nbsp;&nbsp;
        <span style="color:#a16207;font-weight:600">52-71 关注</span>
        &nbsp;&nbsp;
        <span style="color:#b91c1c;font-weight:600">&lt;52 预警</span>
      </div>
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — 财报提醒  ·  倒计时
# ══════════════════════════════════════════════════════════════════════════════

with t2:
    col_r2, col_f2 = st.columns([3, 1])
    with col_r2:
        st.markdown('<div class="vlabel">财报倒计时</div>', unsafe_allow_html=True)
    with col_f2:
        if st.button("↻", key="r2"):
            st.cache_data.clear(); st.rerun()

    items = []
    for tk in st.session_state.watchlist:
        ed   = get_earnings_date(tk)
        info = get_info(tk)
        items.append({
            "tk": tk,
            "name": (info.get("shortName") or tk)[:20],
            "date": ed,
            "days": days_to(ed),
        })
    items.sort(key=lambda x: x["days"])

    for item in items:
        d = item["days"]
        date_str2 = pd.to_datetime(item["date"]).strftime("%Y-%m-%d") if item["date"] else "日期未知"

        if d <= 7:
            bg, bd, tc = "#fef2f2", "#fecaca", "#b91c1c"
            urgency = badge("紧急", "red")
        elif d <= 14:
            bg, bd, tc = "#fffbeb", "#fde68a", "#a16207"
            urgency = badge("临近", "amber")
        elif d <= 60:
            bg, bd, tc = "#eff6ff", "#bfdbfe", "#1d4ed8"
            urgency = badge("正常", "blue")
        else:
            bg, bd, tc = "#f4f4f5", "#e4e4e7", "#52525b"
            urgency = badge("远期", "gray")

        days_label = str(d) if d < 200 else "90+"

        st.markdown(f"""
        <div class="earn-card" style="background:{bg};border-color:{bd};color:{tc}">
          <div style="text-align:center;min-width:48px">
            <div class="earn-days">{days_label}</div>
            <div class="earn-unit">天后</div>
          </div>
          <div class="earn-sep"></div>
          <div style="flex:1">
            <div class="earn-ticker">{item['tk']}</div>
            <div class="earn-name">{item['name']}</div>
          </div>
          <div style="text-align:right">
            <div class="earn-date">{date_str2}</div>
            <div style="margin-top:4px">{urgency}</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("""
    <div class="vcard-sm" style="margin-top:6px">
      <div class="vlabel">提醒规则</div>
      <div style="font-size:12px;color:#636366;line-height:1.8">
        🔴 7天内 → 顶部红色横幅弹出<br>
        🟡 14天内 → 提前关注<br>
        🔵 60天内 → 正常跟踪<br>
        数据来自 Yahoo Finance 财报日历
      </div>
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — 新闻  ·  持仓相关新闻聚合
# ══════════════════════════════════════════════════════════════════════════════

with t3:
    c1, c2 = st.columns([3, 1])
    with c1:
        sel_tk = st.selectbox("股票", st.session_state.watchlist,
                               key="news_sel", label_visibility="collapsed")
    with c2:
        if st.button("↻", key="r3"):
            st.cache_data.clear(); st.rerun()

    with st.spinner("拉取新闻…"):
        news = get_news(sel_tk, 12)

    if news:
        for item in news:
            title = item.get("title", "（无标题）")
            pub   = item.get("publisher", "")
            ts    = item.get("providerPublishTime", 0)
            link  = item.get("link", "#")

            if ts:
                dt = datetime.fromtimestamp(ts)
                diff = datetime.now() - dt
                if diff.days == 0:
                    t_str = f"{diff.seconds//3600}小时前" if diff.seconds >= 3600 else f"{diff.seconds//60}分钟前"
                elif diff.days == 1:
                    t_str = "昨天"
                else:
                    t_str = dt.strftime("%m-%d")
            else:
                t_str = ""

            st.markdown(f"""
            <a href="{link}" target="_blank" style="text-decoration:none">
              <div class="news-card">
                <div class="news-title">{title}</div>
                <div class="news-meta">
                  <span class="news-src">{pub}</span>
                  {"&nbsp;·&nbsp;" + t_str if t_str else ""}
                </div>
              </div>
            </a>
            """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="empty">
          <div class="empty-icon">◎</div>
          暂无新闻，稍后再试
        </div>
        """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 4 — 财报分析  ·  核心数据 + 季度对比
# ══════════════════════════════════════════════════════════════════════════════

with t4:
    c1, c2 = st.columns([3, 1])
    with c1:
        init_idx = st.session_state.watchlist.index(st.session_state.detail_ticker) \
                   if st.session_state.detail_ticker in st.session_state.watchlist else 0
        sel = st.selectbox("股票", st.session_state.watchlist,
                            index=init_idx, key="det_sel",
                            label_visibility="collapsed")
        st.session_state.detail_ticker = sel
    with c2:
        if st.button("↻", key="r4"):
            st.cache_data.clear(); st.rerun()

    with st.spinner("加载财务数据…"):
        info = get_info(sel)
        inc, cf, bal = get_financials(sel)
        price, chg = get_price(sel)

    if not info:
        st.error("无法获取数据，请检查股票代码")
        st.stop()

    name    = info.get("longName") or sel
    sector  = info.get("sector", "")
    mktcap  = info.get("marketCap")
    price_s = f"${price:.2f}" if price else "—"
    chg_s   = f"{chg*100:+.1f}%" if chg else "—"
    chg_cls = "pos" if (chg and chg >= 0) else "neg"

    score, warns, status, detail_d = compute_health(info)
    hc = health_color(score)
    bmap = {"健康": "green", "关注": "amber", "预警": "red"}

    # 公司头部卡片
    st.markdown(f"""
    <div class="vcard">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px">
        <div style="flex:1">
          <div style="font-size:11px;color:#8e8e93;margin-bottom:3px">{sector}</div>
          <div style="font-size:17px;font-weight:600;letter-spacing:-0.02em;line-height:1.2">{name}</div>
        </div>
        <div class="hcircle" style="background:{hc}18;border:2px solid {hc}55;color:{hc}">
          <div class="hc-num">{score}</div>
          <div class="hc-sub">健康</div>
        </div>
      </div>
      <div style="display:flex;align-items:baseline;gap:10px;margin-bottom:4px">
        <div style="font-family:'DM Mono',monospace;font-size:30px;font-weight:500;color:#1c1c1e">{price_s}</div>
        <div style="font-size:17px;font-weight:600" class="{chg_cls}">{chg_s}</div>
      </div>
      <div style="display:flex;align-items:center;gap:8px">
        <div style="font-size:12px;color:#8e8e93">市值 {fmt_big(mktcap)}</div>
        <span class="badge badge-{bmap.get(status,'gray')}">{status}</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # 警告列表
    if warns:
        for w in warns[:4]:
            is_danger = any(k in w for k in ["亏损", "大幅", "极低", "过高", "紧", "负"])
            sty = "danger" if is_danger else ""
            icon = "⚠" if is_danger else "ℹ"
            st.markdown(f"""
            <div class="warn-banner {sty}">
              <div class="wb-icon">{icon}</div>
              <div><div class="wb-body">{w}</div></div>
            </div>
            """, unsafe_allow_html=True)

    # ── 核心指标网格 ──────────────────────────────────────────────────────────
    st.markdown('<div class="vlabel" style="margin:14px 0 8px">核心指标</div>',
                unsafe_allow_html=True)

    def mcell(label, value, sub="", cls=""):
        return (f'<div class="mcell"><div class="mc-l">{label}</div>'
                f'<div class="mc-v {cls}">{value}</div>'
                + (f'<div class="mc-n">{sub}</div>' if sub else '')
                + '</div>')

    gm   = info.get("grossMargins")
    om   = info.get("operatingMargins")
    npm  = info.get("profitMargins")
    rg   = info.get("revenueGrowth")
    eg   = info.get("earningsGrowth")
    roe  = info.get("returnOnEquity")
    pe_t = info.get("trailingPE")
    pe_f = info.get("forwardPE")
    peg  = info.get("pegRatio")
    de   = info.get("debtToEquity")
    cr   = info.get("currentRatio")
    fcf  = info.get("freeCashflow")
    rev  = info.get("totalRevenue")
    ni   = info.get("netIncomeToCommon")
    eps_t= info.get("trailingEps")
    eps_f= info.get("forwardEps")
    beta = info.get("beta")
    div  = info.get("dividendYield")

    rg_cls  = pct_sign_class(rg)  if rg  is not None else ""
    eg_cls  = pct_sign_class(eg)  if eg  is not None else ""

    # 行1：增速
    st.markdown(f"""
    <div class="mgrid">
      {mcell("营收增速", fmt_pct(rg), "YoY", rg_cls)}
      {mcell("盈利增速", fmt_pct(eg), "YoY", eg_cls)}
    </div>""", unsafe_allow_html=True)

    # 行2：利润率
    st.markdown(f"""
    <div class="mgrid" style="margin-top:8px">
      {mcell("毛利率", fmt_pct(gm, False) if gm else "—", "Gross margin")}
      {mcell("营业利润率", fmt_pct(om, False) if om else "—", "Op margin")}
    </div>""", unsafe_allow_html=True)

    # 行3：估值
    st.markdown(f"""
    <div class="mgrid" style="margin-top:8px">
      {mcell("PE (TTM)", fmt_x(pe_t), "Trailing P/E")}
      {mcell("PE (远期)", fmt_x(pe_f), "Forward P/E")}
    </div>""", unsafe_allow_html=True)

    # 行4：质量
    st.markdown(f"""
    <div class="mgrid" style="margin-top:8px">
      {mcell("ROE", fmt_pct(roe, False) if roe else "—", "Return on equity")}
      {mcell("D/E", f"{de:.0f}%" if de else "—", "Debt/equity")}
    </div>""", unsafe_allow_html=True)

    # 行5：EPS
    st.markdown(f"""
    <div class="mgrid" style="margin-top:8px">
      {mcell("EPS (TTM)", f"${eps_t:.2f}" if eps_t else "—", "Trailing EPS")}
      {mcell("EPS (远期)", f"${eps_f:.2f}" if eps_f else "—", "Forward EPS")}
    </div>""", unsafe_allow_html=True)

    # 行6：现金
    st.markdown(f"""
    <div class="mgrid" style="margin-top:8px">
      {mcell("自由现金流", fmt_big(fcf), "Free cash flow")}
      {mcell("营收 TTM", fmt_big(rev), "Total revenue")}
    </div>""", unsafe_allow_html=True)

    # ── 季度财报对比 ──────────────────────────────────────────────────────────
    st.markdown('<div class="vlabel" style="margin:16px 0 10px">最近4季度财报</div>',
                unsafe_allow_html=True)

    show_rows = [
        ("Total Revenue",    "营收"),
        ("Gross Profit",     "毛利润"),
        ("Operating Income", "营业利润"),
        ("Net Income",       "净利润"),
    ]

    if inc is not None and not inc.empty:
        qtrs = inc.columns[:4]

        for row_key, row_label in show_rows:
            if row_key not in inc.index:
                continue

            row = inc.loc[row_key, qtrs]
            html = f'<div class="vcard-sm"><div style="font-size:12.5px;font-weight:500;margin-bottom:9px">{row_label}</div>'
            html += '<div style="display:flex;gap:7px">'

            for i, (col_dt, val) in enumerate(row.items()):
                q_label = col_dt.strftime("%y Q%m") if hasattr(col_dt, 'strftime') else str(col_dt)[:7]
                val_fmt = fmt_big(val)
                is_latest = (i == 0)

                # 环比变化
                ch_html = ""
                if i < len(row) - 1:
                    nv = row.iloc[i + 1]
                    try:
                        pct = (float(val) - float(nv)) / abs(float(nv))
                        cls = "pos" if pct >= 0 else "neg"
                        ch_html = f'<div style="font-size:10px;font-weight:600" class="{cls}">{pct*100:+.0f}%</div>'
                    except: pass

                bg = "#1c1c1e" if is_latest else "#f8f8fa"
                tc = "#ffffff" if is_latest else "#1c1c1e"
                sc = "#aaa"    if is_latest else "#8e8e93"

                html += f"""
                <div class="qbar" style="background:{bg}">
                  <div class="qbar-q" style="color:{sc}">{q_label}</div>
                  <div class="qbar-v" style="color:{tc}">{val_fmt}</div>
                  {ch_html}
                </div>"""

            html += '</div></div>'
            st.markdown(html, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="vcard-sm">
          <div style="font-size:12px;color:#8e8e93;text-align:center;padding:16px 0">
            暂无季度财务数据
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ── 公司业务简介 ──────────────────────────────────────────────────────────
    bio = info.get("longBusinessSummary", "")
    if bio:
        with st.expander("公司业务简介"):
            st.markdown(f'<div style="font-size:13px;color:#444;line-height:1.75">'
                        f'{bio[:500]}{"…" if len(bio)>500 else ""}</div>',
                        unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 5 — 设置  ·  管理持仓 + 说明
# ══════════════════════════════════════════════════════════════════════════════

with t5:
    st.markdown('<div class="vlabel">管理持仓</div>', unsafe_allow_html=True)

    # 现有持仓
    st.markdown('<div class="vcard">', unsafe_allow_html=True)
    for i, tk in enumerate(st.session_state.watchlist):
        c1, c2 = st.columns([4, 1])
        with c1:
            info_q = get_info(tk)
            n = (info_q.get("shortName") or tk)[:24]
            st.markdown(f"""
            <div style="padding:8px 0">
              <div style="font-family:'DM Mono',monospace;font-size:14px;font-weight:500">{tk}</div>
              <div style="font-size:11.5px;color:#636366;margin-top:1px">{n}</div>
            </div>
            """, unsafe_allow_html=True)
        with c2:
            if st.button("删除", key=f"del_{tk}_{i}"):
                st.session_state.watchlist.remove(tk)
                if st.session_state.detail_ticker == tk:
                    st.session_state.detail_ticker = st.session_state.watchlist[0] if st.session_state.watchlist else ""
                st.rerun()
        if i < len(st.session_state.watchlist) - 1:
            st.markdown('<div class="vdivider"></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # 添加新股票
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
    new_tk = st.text_input("添加股票代码（如 TSLA）",
                            placeholder="TSLA", key="add_inp",
                            label_visibility="collapsed")
    if st.button("添加持仓 →", use_container_width=True, key="add_btn"):
        nt = new_tk.strip().upper()
        if not nt:
            st.warning("请输入股票代码")
        elif nt in st.session_state.watchlist:
            st.warning(f"{nt} 已在持仓中")
        else:
            with st.spinner(f"验证 {nt}…"):
                test = get_info(nt)
            if test and test.get("regularMarketPrice"):
                st.session_state.watchlist.append(nt)
                st.success(f"已添加 {nt}")
                time.sleep(0.4)
                st.rerun()
            else:
                st.error(f"找不到 {nt}，请检查代码（需使用美股/港股代码）")

    # 使用说明
    st.markdown("""
    <div class="vcard-sm" style="margin-top:14px">
      <div class="vlabel">使用说明</div>
      <div style="font-size:12px;color:#636366;line-height:1.9">
        📊 <b>持仓</b> — 打开即自动评分，检测结构性恶化<br>
        🔔 <b>提醒</b> — 财报日期倒计时，7天内顶部红色弹出<br>
        📰 <b>新闻</b> — 每日最新相关新闻（15分钟缓存）<br>
        📈 <b>财报</b> — 核心数据 + 最近4季度同比分析<br><br>
        <b>数据来源</b>：Yahoo Finance (yfinance)<br>
        <b>缓存策略</b>：价格2分钟 · 财务5分钟 · 新闻15分钟<br><br>
        <b>部署方式</b>：<br>
        1. <code>pip install streamlit yfinance pandas</code><br>
        2. <code>streamlit run valuelens_app.py</code><br>
        3. 部署到 streamlit.io/cloud（免费，手机可直接访问）
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)
    if st.button("清除缓存 · 全部刷新", use_container_width=True, key="clr"):
        st.cache_data.clear()
        st.success("缓存已清除")
        time.sleep(0.4)
        st.rerun()
