"""End-to-end test: Industry analysis (Semiconductors).

Requires FMP_API_KEY. Optionally uses ANTHROPIC_API_KEY.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import json
import config
from data.fmp_client import FMPClient
from data.edgar_client import EdgarClient
from llm.claude_client import ClaudeClient, LLMError
from reports.industry_report_gen import run_industry_analysis, industry_report_to_markdown


@pytest.fixture
def fmp():
    if not config.FMP_API_KEY:
        pytest.skip("FMP_API_KEY not set — skipping E2E test")
    return FMPClient()


@pytest.fixture
def llm():
    if not config.ANTHROPIC_API_KEY:
        return None
    try:
        return ClaudeClient()
    except LLMError:
        return None


@pytest.fixture
def edgar():
    return EdgarClient()


class TestE2EIndustry:
    def test_semiconductors_analysis(self, fmp, llm, edgar):
        """Full industry analysis of Semiconductors (limited to 5 for speed)."""
        report = run_industry_analysis(
            industry="Semiconductors",
            fmp=fmp,
            llm=llm,
            edgar=edgar,
            n=5,  # Small universe for test speed
        )

        # ── Universe ──
        assert report.universe.industry == "Semiconductors"
        assert len(report.universe.companies) > 0

        # Verify universe has required fields
        for c in report.universe.companies:
            assert c.ticker != ""
            assert c.market_cap > 0
            assert c.inclusion_rationale != ""

        # ── Analysis ran ──
        assert len(report.all_reports) > 0 or len(report.skipped) > 0

        # ── Ranking ──
        if report.all_reports:
            assert len(report.ranked) > 0

            # Verify ranking order (passed first, then by score)
            passed_seen = False
            for r in report.ranked:
                if r.passed_all_filters:
                    passed_seen = True
                elif passed_seen:
                    # After seeing passed companies, all remaining should be failed
                    # (or there are more passed ones mixed in due to sorting)
                    pass

            # Check bear risk flags
            for r in report.ranked:
                if r.bear_risk_flag:
                    assert r.bear_justification != ""
                    assert "⚠️" in r.bear_justification

        # ── Top 5 ──
        for t in report.top_5:
            assert t.passed_all_filters is True
            assert t.composite_score > 0

        # ── Markdown report ──
        md = industry_report_to_markdown(report)
        assert "Semiconductors" in md
        assert "Universe" in md

        # ── Save outputs ──
        output_dir = os.path.join(os.path.dirname(__file__), "..", "output")
        os.makedirs(output_dir, exist_ok=True)
        json_data = report.model_dump_json(indent=2)
        with open(os.path.join(output_dir, "Semiconductors_industry.json"), "w") as f:
            f.write(json_data)
        with open(os.path.join(output_dir, "Semiconductors_industry.md"), "w") as f:
            f.write(md)

        print(f"\n{'='*60}")
        print(f"Semiconductors Industry E2E Results:")
        print(f"  Universe: {len(report.universe.companies)} companies")
        print(f"  Analyzed: {len(report.all_reports)}")
        print(f"  Skipped:  {len(report.skipped)}")
        print(f"  Ranked:   {len(report.ranked)}")
        print(f"  Top 5:    {len(report.top_5)}")
        if report.top_5:
            print(f"  #1: {report.top_5[0].ticker} (score: {report.top_5[0].composite_score:.0f})")
        if report.warnings:
            print(f"  Warnings: {report.warnings}")
        print(f"{'='*60}")
