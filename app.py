"""Buffett Analyzer — Streamlit UI."""
from __future__ import annotations
import os
import json
import streamlit as st
from datetime import datetime

# Add parent dir to path so imports work
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from data.fmp_client import FMPClient, FMPError
from data.edgar_client import EdgarClient
from llm.claude_client import ClaudeClient, LLMError
from reports.company_report import run_company_analysis, report_to_json, report_to_markdown
from reports.industry_report_gen import run_industry_analysis, industry_report_to_markdown

st.set_page_config(
    page_title="Buffett Analyzer",
    page_icon="🔬",
    layout="wide",
)

st.title("🔬 Buffett Analyzer")
st.caption("AI-powered investment research modeled on Berkshire Hathaway's analytical process")

# ── Sidebar: Configuration ──
with st.sidebar:
    st.header("⚙️ Configuration")

    st.subheader("API Keys")
    fmp_key = st.text_input(
        "FMP API Key",
        value=config.FMP_API_KEY,
        type="password",
        help="Financial Modeling Prep API key. Set via env var FMP_API_KEY or enter here.",
    )
    anthropic_key = st.text_input(
        "Anthropic API Key",
        value=config.ANTHROPIC_API_KEY,
        type="password",
        help="Anthropic Claude API key. Set via env var ANTHROPIC_API_KEY or enter here.",
    )

    st.divider()
    st.subheader("Valuation Parameters")
    projection_years = st.slider("Projection Years", 5, 15, config.PROJECTION_YEARS)
    discount_rate = st.slider("Discount Rate (%)", 5, 20, int(config.DISCOUNT_RATE * 100)) / 100
    terminal_growth = st.slider("Terminal Growth (%)", 1, 6, int(config.TERMINAL_GROWTH_RATE * 100)) / 100

    st.divider()
    st.subheader("Industry Settings")
    universe_size = st.slider("Universe Size (N)", 5, 50, config.DEFAULT_UNIVERSE_SIZE)
    sort_method = st.selectbox("Sort By", ["market_cap", "revenue"])
    min_mcap = st.number_input(
        "Min Market Cap ($B)", value=config.MIN_MARKET_CAP / 1e9, min_value=0.1, step=0.5
    ) * 1e9

    st.divider()
    st.subheader("Hard Filter Thresholds")
    min_moat = st.slider("Min Moat Score", 0, 100, config.MIN_MOAT_SCORE)
    min_fq = st.slider("Min Financial Quality Score", 0, 100, config.MIN_FINANCIAL_SCORE)
    min_stab = st.slider("Min Stability Score", 0, 100, config.MIN_STABILITY_SCORE)

    use_edgar = st.checkbox("Fetch SEC EDGAR filings", value=True)

# ── Validate Keys ──
if not fmp_key:
    st.error("❌ FMP API Key is required. Set it via env var `FMP_API_KEY` or enter in the sidebar.")
    st.stop()

# ── Main Interface ──
tab_company, tab_industry = st.tabs(["📊 Company Analysis", "🏭 Industry Analysis"])

with tab_company:
    st.subheader("Single Company Analysis")
    col1, col2 = st.columns([3, 1])
    with col1:
        ticker = st.text_input("Enter ticker symbol", placeholder="AAPL", key="company_ticker")
    with col2:
        st.write("")
        st.write("")
        run_company = st.button("🔍 Analyze", key="run_company", type="primary")

    if run_company and ticker:
        # Update config with sidebar values
        config.MIN_MOAT_SCORE = min_moat
        config.MIN_FINANCIAL_SCORE = min_fq
        config.MIN_STABILITY_SCORE = min_stab

        progress = st.empty()
        status_container = st.container()

        def company_progress(msg):
            progress.info(msg)

        try:
            fmp = FMPClient(api_key=fmp_key)
            llm = None
            if anthropic_key:
                try:
                    llm = ClaudeClient(api_key=anthropic_key)
                except LLMError:
                    st.warning("⚠️ Anthropic key invalid — running without LLM (deterministic scoring only)")

            edgar = EdgarClient() if use_edgar else None

            report = run_company_analysis(
                ticker=ticker,
                fmp=fmp,
                llm=llm,
                edgar=edgar,
                discount_rate=discount_rate,
                terminal_growth=terminal_growth,
                projection_years=projection_years,
                progress_callback=company_progress,
            )

            progress.success(f"✅ Analysis complete: {report.recommendation.action} ({report.recommendation.position_size})")

            # Display report
            md = report_to_markdown(report)
            st.markdown(md)

            # Downloads
            col_dl1, col_dl2 = st.columns(2)
            with col_dl1:
                st.download_button(
                    "📥 Download JSON",
                    data=report_to_json(report),
                    file_name=f"{ticker.upper()}_report.json",
                    mime="application/json",
                )
            with col_dl2:
                st.download_button(
                    "📥 Download Markdown",
                    data=md,
                    file_name=f"{ticker.upper()}_report.md",
                    mime="text/markdown",
                )

            # Save to output/
            output_dir = os.path.join(os.path.dirname(__file__), "output")
            os.makedirs(output_dir, exist_ok=True)
            with open(os.path.join(output_dir, f"{ticker.upper()}_report.json"), "w") as f:
                f.write(report_to_json(report))
            with open(os.path.join(output_dir, f"{ticker.upper()}_report.md"), "w") as f:
                f.write(md)

        except FMPError as e:
            st.error(f"❌ FMP Error: {e}")
        except RuntimeError as e:
            st.error(f"❌ {e}")
        except Exception as e:
            st.error(f"❌ Unexpected error: {e}")
            st.exception(e)

with tab_industry:
    st.subheader("Industry Analysis")
    col1, col2 = st.columns([3, 1])
    with col1:
        industry = st.text_input(
            "Enter industry name",
            placeholder="Semiconductors",
            key="industry_name",
        )
    with col2:
        st.write("")
        st.write("")
        run_industry = st.button("🔍 Analyze Industry", key="run_industry", type="primary")

    if run_industry and industry:
        config.MIN_MOAT_SCORE = min_moat
        config.MIN_FINANCIAL_SCORE = min_fq
        config.MIN_STABILITY_SCORE = min_stab

        progress = st.empty()
        status_text = st.empty()

        def industry_progress(msg):
            progress.info(msg)

        try:
            fmp = FMPClient(api_key=fmp_key)
            llm = None
            if anthropic_key:
                try:
                    llm = ClaudeClient(api_key=anthropic_key)
                except LLMError:
                    st.warning("⚠️ Anthropic key invalid — running without LLM")

            edgar = EdgarClient() if use_edgar else None

            report = run_industry_analysis(
                industry=industry,
                fmp=fmp,
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

            top_count = len(report.top_5)
            progress.success(
                f"✅ Industry analysis complete. "
                f"{len(report.all_reports)} companies analyzed, "
                f"{top_count} in top 5."
            )

            # Display
            md = industry_report_to_markdown(report)
            st.markdown(md)

            # Downloads
            col_dl1, col_dl2 = st.columns(2)
            json_data = report.model_dump_json(indent=2)
            safe_name = industry.replace(" ", "_").replace("/", "_")
            with col_dl1:
                st.download_button(
                    "📥 Download JSON",
                    data=json_data,
                    file_name=f"{safe_name}_industry.json",
                    mime="application/json",
                )
            with col_dl2:
                st.download_button(
                    "📥 Download Markdown",
                    data=md,
                    file_name=f"{safe_name}_industry.md",
                    mime="text/markdown",
                )

            # Save
            output_dir = os.path.join(os.path.dirname(__file__), "output")
            os.makedirs(output_dir, exist_ok=True)
            with open(os.path.join(output_dir, f"{safe_name}_industry.json"), "w") as f:
                f.write(json_data)
            with open(os.path.join(output_dir, f"{safe_name}_industry.md"), "w") as f:
                f.write(md)

        except FMPError as e:
            st.error(f"❌ FMP Error: {e}")
        except Exception as e:
            st.error(f"❌ Unexpected error: {e}")
            st.exception(e)


# Footer
st.divider()
st.caption(
    "Buffett Analyzer v1.0 — This tool is for research purposes only. "
    "Not financial advice. Always do your own due diligence."
)
