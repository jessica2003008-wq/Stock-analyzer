"""End-to-end test: Single company (AAPL).

This test requires FMP_API_KEY to be set. Skip if not available.
Optionally uses ANTHROPIC_API_KEY for LLM modules.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import json
import config
from data.fmp_client import FMPClient
from data.edgar_client import EdgarClient
from llm.claude_client import ClaudeClient, LLMError
from reports.company_report import run_company_analysis, report_to_json, report_to_markdown


@pytest.fixture
def fmp():
    if not config.FMP_API_KEY:
        pytest.skip("FMP_API_KEY not set — skipping E2E test")
    return FMPClient()


@pytest.fixture
def llm():
    if not config.ANTHROPIC_API_KEY:
        return None  # Run without LLM
    try:
        return ClaudeClient()
    except LLMError:
        return None


@pytest.fixture
def edgar():
    return EdgarClient()


class TestE2ECompany:
    def test_aapl_full_analysis(self, fmp, llm, edgar):
        """Full end-to-end analysis of AAPL."""
        report = run_company_analysis(
            ticker="AAPL",
            fmp=fmp,
            llm=llm,
            edgar=edgar,
        )

        # ── Schema validation ──
        assert report.ticker == "AAPL"
        assert report.name != ""
        assert report.analysis_date != ""

        # ── All 6 steps produce valid results ──
        assert 0 <= report.competence.score <= 100
        assert report.competence.rationale != ""
        assert len(report.competence.evidence) > 0

        assert 0 <= report.moat.score <= 100
        assert report.moat.moat_type in ("Wide", "Narrow", "None")
        assert len(report.moat.evidence) > 0

        assert 0 <= report.financial_quality.score <= 100
        assert "roe_avg_5yr" in report.financial_quality.metrics
        assert len(report.financial_quality.evidence) > 0

        assert 0 <= report.stability.score <= 100
        assert report.stability.consecutive_profit_years > 0
        assert len(report.stability.evidence) > 0

        # ── Valuation: bull > base > bear ──
        v = report.valuation
        assert v.bull.per_share_value > v.base.per_share_value
        assert v.base.per_share_value > v.bear.per_share_value
        assert v.epv_per_share > 0
        assert len(v.sensitivity_table) > 0
        assert len(v.evidence) > 0

        # ── Margin of Safety ──
        m = report.margin_of_safety
        assert m.current_price > 0
        assert m.base_intrinsic_value > 0
        assert m.verdict in ("Undervalued", "Fairly Valued", "Overvalued")

        # ── Recommendation ──
        rec = report.recommendation
        assert rec.action in ("Buy", "Watch", "Avoid")
        assert rec.position_size in ("Full", "Half", "Starter", "None")
        assert rec.composite_score > 0
        assert len(rec.score_breakdown) > 0
        assert len(rec.monitoring_metrics) > 0

        # ── JSON serialization ──
        json_str = report_to_json(report)
        parsed = json.loads(json_str)
        assert parsed["ticker"] == "AAPL"

        # ── Markdown generation ──
        md = report_to_markdown(report)
        assert "AAPL" in md
        assert "Step 1" in md or "Circle of Competence" in md
        assert "Final Recommendation" in md

        # ── Save outputs ──
        output_dir = os.path.join(os.path.dirname(__file__), "..", "output")
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "AAPL_report.json"), "w") as f:
            f.write(json_str)
        with open(os.path.join(output_dir, "AAPL_report.md"), "w") as f:
            f.write(md)

        print(f"\n{'='*60}")
        print(f"AAPL E2E Results:")
        print(f"  Competence:  {report.competence.score}/100")
        print(f"  Moat:        {report.moat.score}/100 ({report.moat.moat_type})")
        print(f"  Fin Quality: {report.financial_quality.score}/100")
        print(f"  Stability:   {report.stability.score}/100")
        print(f"  MoS:         {m.margin_of_safety_pct:.1f}% ({m.verdict})")
        print(f"  Bull IV:     ${v.bull.per_share_value:,.2f}")
        print(f"  Base IV:     ${v.base.per_share_value:,.2f}")
        print(f"  Bear IV:     ${v.bear.per_share_value:,.2f}")
        print(f"  Price:       ${v.current_price:,.2f}")
        print(f"  Action:      {rec.action} ({rec.position_size})")
        print(f"  Composite:   {rec.composite_score:.0f}/100")
        print(f"{'='*60}")
