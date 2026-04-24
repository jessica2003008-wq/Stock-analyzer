"""Buffett Analyzer v2.0 — Streamlit UI (升级版)

升级：
  - 融合估值展示（市场锚点 + 模型）
  - 置信度标签
  - 回报结构分析
  - 三句话摘要（普通人可读）
  - 偏差警告自动展示
  - 动态折现率/增长率展示
"""

from __future__ import annotations

import os
import sys
import json
from datetime import datetime
import streamlit as st
import markdown

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from data.yfinance_client import YFinanceClient, YFinanceError
from data.edgar_client import EdgarClient
from llm.claude_client import ClaudeClient, LLMError
from reports.company_report import run_company_analysis, report_to_json, report_to_markdown
from reports.industry_report_gen import run_industry_analysis, industry_report_to_markdown

anthropic_key = st.secrets.get("ANTHROPIC_API_KEY", "")

if "cache_version" not in st.session_state or st.session_state.cache_version != "v2.2.0":
    st.cache_data.clear()
    st.session_state.cache_version = "v2.2.0"


def md_to_styled_html(md_text: str, title: str = "Buffett Analyzer Report") -> str:
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    css = """
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial;
      margin: 40px; color: #111; line-height: 1.55; max-width: 980px;
    }
    h1, h2, h3 { margin-top: 28px; }
    h1 { font-size: 28px; } h2 { font-size: 22px; } h3 { font-size: 18px; }
    code { background: #f6f8fa; padding: 2px 5px; border-radius: 4px; }
    pre { background: #f6f8fa; padding: 12px; border-radius: 8px; overflow-x: auto; }
    pre code { background: transparent; padding: 0; }
    table { border-collapse: collapse; width: 100%; margin: 14px 0; }
    th, td { border: 1px solid #d0d7de; padding: 8px; text-align: left; vertical-align: top; }
    th { background: #f6f8fa; }
    hr { border: none; border-top: 1px solid #d0d7de; margin: 24px 0; }
    blockquote { border-left: 4px solid #0969da; padding-left: 12px; color: #333; margin-left: 0; background: #f0f7ff; padding: 8px 12px; border-radius: 0 4px 4px 0; }
    strong { font-weight: 700; }
    """
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>{css}</style>
</head>
<body>{body}</body>
</html>"""


# ── Page config ──
st.set_page_config(
    page_title="Buffett Analyzer v2",
    page_icon="🔬",
    layout="wide",
)

st.title("🔬 Buffett Analyzer v2.0")
st.caption("市场锚点 + DCF 融合估值 | 动态折现率 | 回报结构分析 | 置信度系统")

# ── Sidebar ──
with st.sidebar:
    st.header("⚙️ 配置参数")
    st.divider()

    st.subheader("估值参数（Fallback）")
    st.caption("实际折现率/增长率由市场数据动态计算，以下为无数据时的后备值")
    projection_years = st.slider("预测年数", 5, 15, config.PROJECTION_YEARS)
    discount_rate = st.slider("折现率 Fallback (%)", 5, 20, int(config.DISCOUNT_RATE * 100)) / 100
    terminal_growth = st.slider("终端增长率 (%)", 1, 6, int(config.TERMINAL_GROWTH_RATE * 100)) / 100

    st.divider()
    st.subheader("行业分析参数")
    universe_size = st.slider("Universe 规模 (N)", 5, 50, config.DEFAULT_UNIVERSE_SIZE)
    sort_method = st.selectbox("排序方式", ["market_cap", "revenue"])
    min_mcap = (
        st.number_input("最小市值 ($B)", value=config.MIN_MARKET_CAP / 1e9, min_value=0.1, step=0.5) * 1e9
    )

    st.divider()
    st.subheader("硬过滤阈值")
    min_moat = st.slider("最低护城河分", 0, 100, config.MIN_MOAT_SCORE)
    min_fq = st.slider("最低财务质量分", 0, 100, config.MIN_FINANCIAL_SCORE)
    min_stab = st.slider("最低稳定性分", 0, 100, config.MIN_STABILITY_SCORE)

    use_edgar = st.checkbox("获取 SEC EDGAR 文件", value=True)

    st.divider()
    st.subheader("ℹ️ v2.0 新功能")
    st.markdown("""
    - 📡 **市场锚点**：自动抓取 Analyst 目标价
    - 🔄 **融合估值**：市场×N% + 模型×M%（动态权重）
    - 📉 **动态折现率**：从市场 PE 反推，不再拍脑袋
    - 📈 **增长四源融合**：历史+analyst+市场隐含+质量调整
    - 💰 **回报结构**：增长+回购+股息 = 预期年化回报
    - 🎯 **置信度系统**：High/Medium/Low
    - ⚠️ **偏差自检**：模型IV与市价偏差>50%自动警告
    """)


# ── Main Tabs ──
tab_company, tab_industry = st.tabs(["📊 公司分析", "🏭 行业分析"])

# ════════════════════════════════════════════════════════════════
# TAB 1: 公司分析
# ════════════════════════════════════════════════════════════════
with tab_company:
    st.subheader("单公司深度分析")
    col1, col2 = st.columns([3, 1])
    with col1:
        ticker = st.text_input("输入股票代码", placeholder="AAPL", key="company_ticker")
    with col2:
        st.write("")
        st.write("")
        run_company = st.button("🔍 开始分析", key="run_company", type="primary")

    if run_company and ticker:
        config.MIN_MOAT_SCORE = min_moat
        config.MIN_FINANCIAL_SCORE = min_fq
        config.MIN_STABILITY_SCORE = min_stab

        progress = st.empty()

        def company_progress(msg: str):
            progress.info(msg)

        try:
            data_client = YFinanceClient()
            llm = None
            if anthropic_key:
                try:
                    llm = ClaudeClient(api_key=anthropic_key)
                except LLMError:
                    st.warning("⚠️ Anthropic Key 无效，仅使用确定性评分")

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

            rec = report.recommendation
            progress.success(
                f"✅ 分析完成：{rec['action']} / {rec['position_size']} 仓位"
            )

            # ── 三句话摘要（突出展示）──
            if report.three_sentence_summary:
                ts = report.three_sentence_summary
                st.info("📌 **三句话摘要（普通人版）**")
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    st.markdown(ts["sentence1_what"])
                with col_b:
                    st.markdown(ts["sentence2_return"])
                with col_c:
                    st.markdown(ts["sentence3_verdict"])
                st.divider()

            # ── 融合估值 + 置信度（新增卡片）──
            if report.fusion_summary:
                fs = report.fusion_summary
                col1, col2, col3, col4 = st.columns(4)

                with col1:
                    st.metric(
                        "融合 IV",
                        f"${fs.get('fusion_iv', 0):.0f}",
                        delta=f"区间 ${fs.get('fusion_iv_low',0):.0f}–${fs.get('fusion_iv_high',0):.0f}",
                    )
                with col2:
                    conf = fs.get("confidence_level", "N/A")
                    conf_score = fs.get("confidence_score", 0)
                    conf_color = "🟢" if conf == "High" else ("🟡" if conf == "Medium" else "🔴")
                    st.metric("置信度", f"{conf_color} {conf}", delta=f"{conf_score:.0f}/100")
                with col3:
                    mw = fs.get("market_weight_pct", 0)
                    dw = fs.get("model_weight_pct", 100)
                    st.metric("权重分配", f"市场{mw:.0f}% / 模型{dw:.0f}%", delta=fs.get("company_type",""))
                with col4:
                    dr = fs.get("dynamic_discount_rate_pct")
                    gr = fs.get("dynamic_growth_rate_pct")
                    if dr:
                        st.metric("动态折现率", f"{dr:.2f}%", delta="市场校准")
                    else:
                        st.metric("增长率", f"{gr:.2f}%" if gr else "N/A")

                # 偏差警告
                if fs.get("sanity_triggered"):
                    st.error(f"⚠️ **偏差警告**：{fs.get('sanity_note','')}")

                st.divider()

            # ── 回报结构（新增）──
            if report.return_structure:
                rs = report.return_structure
                st.markdown("### 💰 预期年化回报结构")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("预期总回报", f"{rs['expected_annual_return_pct']:.1f}%")
                with col2:
                    st.metric("📈 增长贡献", f"{rs['from_growth_pct']:.1f}%")
                with col3:
                    st.metric("🔄 回购贡献", f"{rs['from_buyback_pct']:.1f}%")
                with col4:
                    st.metric("💵 股息贡献", f"{rs['from_dividend_pct']:.1f}%")
                st.caption(rs.get("note", ""))
                st.divider()

            # ── 市场快照（新增）──
            if report.market_snapshot:
                ms = report.market_snapshot
                with st.expander("📊 市场快照（Analyst数据）", expanded=False):
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        if ms.get("trailing_pe"):
                            st.metric("TTM PE", f"{ms['trailing_pe']:.1f}x")
                        if ms.get("forward_pe"):
                            st.metric("Forward PE", f"{ms['forward_pe']:.1f}x")
                    with col2:
                        if ms.get("analyst_target_mean"):
                            st.metric(
                                f"Analyst 目标价（{ms['analyst_count']}位）",
                                f"${ms['analyst_target_mean']:.0f}",
                                delta=f"区间 ${ms.get('analyst_target_low','?')}–${ms.get('analyst_target_high','?')}",
                            )
                    with col3:
                        if ms.get("dividend_yield_pct"):
                            st.metric("股息率", f"{ms['dividend_yield_pct']:.2f}%")
                        if ms.get("buyback_yield_pct"):
                            st.metric("回购率（估算）", f"{ms['buyback_yield_pct']:.2f}%")

            # ── 完整 Markdown 报告 ──
            st.divider()
            md = report_to_markdown(report)
            st.markdown(md)

            # ── 下载按钮 ──
            col_dl1, col_dl2, col_dl3 = st.columns(3)
            with col_dl1:
                st.download_button(
                    "📥 下载 JSON",
                    data=report_to_json(report),
                    file_name=f"{ticker.upper()}_report_v2.json",
                    mime="application/json",
                )
            with col_dl2:
                st.download_button(
                    "📥 下载 Markdown",
                    data=md,
                    file_name=f"{ticker.upper()}_report_v2.md",
                    mime="text/markdown",
                )
            with col_dl3:
                html_doc = md_to_styled_html(md, title=f"{ticker.upper()} Buffett Report v2")
                st.download_button(
                    "🌐 下载 HTML",
                    data=html_doc,
                    file_name=f"{ticker.upper()}_report_v2.html",
                    mime="text/html",
                )

            # 保存到 output/
            output_dir = os.path.join(os.path.dirname(__file__), "output")
            os.makedirs(output_dir, exist_ok=True)
            for ext, content, mode in [
                ("json", report_to_json(report), "w"),
                ("md", md, "w"),
                ("html", html_doc, "w"),
            ]:
                with open(os.path.join(output_dir, f"{ticker.upper()}_report_v2.{ext}"), mode, encoding="utf-8") as f:
                    f.write(content)

        except YFinanceError as e:
            st.error(f"❌ 数据错误：{e}")
        except RuntimeError as e:
            st.error(f"❌ {e}")
        except Exception as e:
            st.error(f"❌ 未知错误：{e}")
            st.exception(e)


# ════════════════════════════════════════════════════════════════
# TAB 2: 行业分析（保持原有逻辑，轻微UI升级）
# ════════════════════════════════════════════════════════════════
with tab_industry:
    st.subheader("行业分析（Top N）")
    col1, col2 = st.columns([3, 1])
    with col1:
        industry = st.text_input("输入行业名称", placeholder="Semiconductors", key="industry_name")
    with col2:
        st.write("")
        st.write("")
        run_industry = st.button("🔍 分析行业", key="run_industry", type="primary")

    if run_industry and industry:
        config.MIN_MOAT_SCORE = min_moat
        config.MIN_FINANCIAL_SCORE = min_fq
        config.MIN_STABILITY_SCORE = min_stab

        progress = st.empty()

        def industry_progress(msg: str):
            progress.info(msg)

        try:
            data_client = YFinanceClient()
            llm = None
            if anthropic_key:
                try:
                    llm = ClaudeClient(api_key=anthropic_key)
                except LLMError:
                    st.warning("⚠️ Anthropic Key 无效")

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

            progress.success(
                f"✅ 行业分析完成：{len(report.all_reports)} 家公司，Top {len(report.top_5)} 家上榜"
            )

            md = industry_report_to_markdown(report)
            st.markdown(md)

            col_dl1, col_dl2, col_dl3 = st.columns(3)
            json_data = report.model_dump_json(indent=2)
            safe_name = industry.replace(" ", "_").replace("/", "_")

            with col_dl1:
                st.download_button("📥 JSON", data=json_data, file_name=f"{safe_name}_industry.json", mime="application/json")
            with col_dl2:
                st.download_button("📥 Markdown", data=md, file_name=f"{safe_name}_industry.md", mime="text/markdown")
            with col_dl3:
                html_doc = md_to_styled_html(md, title=f"{safe_name} Industry Report")
                st.download_button("🌐 HTML", data=html_doc, file_name=f"{safe_name}_industry.html", mime="text/html")

            output_dir = os.path.join(os.path.dirname(__file__), "output")
            os.makedirs(output_dir, exist_ok=True)
            for ext, content in [("json", json_data), ("md", md), ("html", html_doc)]:
                with open(os.path.join(output_dir, f"{safe_name}_industry.{ext}"), "w", encoding="utf-8") as f:
                    f.write(content)

        except YFinanceError as e:
            st.error(f"❌ 数据错误：{e}")
        except Exception as e:
            st.error(f"❌ 未知错误：{e}")
            st.exception(e)

# Footer
st.divider()
st.caption(
    "Buffett Analyzer v2.0 — 融合估值 | 动态折现率 | 回报结构 | 置信度系统 | "
    "仅供研究，不构成投资建议。"
)
