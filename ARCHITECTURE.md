# Buffett Analyzer — Architecture Document

**Version:** 1.0  
**Date:** 2026-03-05  
**Status:** AWAITING CONFIRMATION  

---

## 1. Directory Structure

```
buffett-analyzer/
├── app.py                          # Streamlit UI entry point
├── config.py                       # All configurable parameters
├── requirements.txt
├── README.md
│
├── data/
│   ├── __init__.py
│   ├── fmp_client.py               # Financial Modeling Prep API client
│   ├── edgar_client.py             # SEC EDGAR 10-K/10-Q text fetcher
│   ├── yfinance_fallback.py        # Price fallback only
│   └── schemas.py                  # Pydantic data models for all API responses
│
├── analysis/
│   ├── __init__.py
│   ├── circle_of_competence.py     # Step 1
│   ├── moat_proxy.py               # Step 2
│   ├── financial_quality.py        # Step 3
│   ├── stability.py                # Step 4
│   ├── valuation.py                # Step 5 (Owner Earnings + DCF, 3 scenarios)
│   ├── margin_of_safety.py         # Step 6
│   └── recommendation.py           # Final recommendation
│
├── industry/
│   ├── __init__.py
│   ├── universe.py                 # Top N company identification
│   ├── ranking.py                  # Composite scoring + hard filters
│   └── industry_report.py          # Industry-level report assembly
│
├── llm/
│   ├── __init__.py
│   └── claude_client.py            # Claude API wrapper for qualitative analysis
│
├── reports/
│   ├── __init__.py
│   ├── company_report.py           # Assembles single-company report (JSON + MD)
│   └── industry_report_gen.py      # Assembles industry comparison report
│
├── output/                         # Generated reports land here
│   └── .gitkeep
│
└── tests/
    ├── __init__.py
    ├── test_data_clients.py
    ├── test_valuation.py
    ├── test_financial_quality.py
    ├── test_stability.py
    ├── test_scoring.py
    ├── test_ranking.py
    ├── test_e2e_company.py         # End-to-end: AAPL
    └── test_e2e_industry.py        # End-to-end: Semiconductors
```

---

## 2. Data Schemas (Inputs/Outputs Per Module)

### 2.1 Shared Data Models (data/schemas.py)

```python
# All models use Pydantic BaseModel

class CompanyProfile:
    ticker: str
    name: str
    sector: str
    industry: str
    market_cap: float
    description: str             # Business description
    num_employees: int | None
    exchange: str

class FinancialStatement:
    """One year of financials."""
    fiscal_year: int
    revenue: float
    cost_of_revenue: float
    gross_profit: float
    operating_income: float
    net_income: float
    eps: float
    shares_outstanding: float
    total_assets: float
    total_liabilities: float
    total_equity: float
    long_term_debt: float
    total_debt: float
    cash_and_equivalents: float
    depreciation_amortization: float
    capital_expenditure: float       # Negative in cash flow; stored as positive
    operating_cash_flow: float
    free_cash_flow: float
    dividends_paid: float
    change_in_working_capital: float
    research_and_development: float | None
    sga_expense: float | None

class FinancialHistory:
    ticker: str
    statements: list[FinancialStatement]   # Ordered oldest → newest, 10 years
    current_price: float
    current_market_cap: float
    shares_outstanding: float

class FilingText:
    ticker: str
    filing_type: str                # "10-K" or "10-Q"
    fiscal_year: int
    sections: dict[str, str]        # e.g. {"business": "...", "risk_factors": "...", "mda": "..."}
```

### 2.2 Module Inputs → Outputs

| Module | Input | Output (JSON model) |
|--------|-------|---------------------|
| **Step 1: Circle of Competence** | `CompanyProfile`, `FilingText`, `FinancialHistory` | `CompetenceResult` |
| **Step 2: Moat Proxy** | `CompanyProfile`, `FilingText`, `FinancialHistory` | `MoatResult` |
| **Step 3: Financial Quality** | `FinancialHistory` | `FinancialQualityResult` |
| **Step 4: Stability** | `FinancialHistory` | `StabilityResult` |
| **Step 5: Intrinsic Value** | `FinancialHistory`, valuation params | `ValuationResult` |
| **Step 6: Margin of Safety** | `ValuationResult`, current price | `MarginOfSafetyResult` |
| **Final Recommendation** | All prior results | `RecommendationResult` |

### 2.3 Output Schemas (per module)

```python
class CompetenceResult:
    score: int                    # 0-100
    business_model_summary: str   # 2-3 sentence plain-English explanation
    revenue_segments: list[dict]  # [{"segment": "iPhone", "pct_revenue": 52.3}, ...]
    predictability: str           # "High" | "Medium" | "Low"
    complexity_flags: list[str]   # e.g. ["complex derivatives exposure", "multi-segment conglomerate"]
    evidence: list[str]           # Filing excerpts or data points backing the score
    rationale: str                # Paragraph explaining score

class MoatResult:
    score: int                    # 0-100
    moat_type: str                # "Wide" | "Narrow" | "None"
    moat_sources: list[dict]      # [{"source": "brand", "strength": 85, "evidence": "..."}, ...]
    durability_assessment: str    # "Durable" | "Eroding" | "Strengthening"
    margin_trend: dict            # {"gross_margin_5yr_trend": ..., "operating_margin_5yr_trend": ...}
    evidence: list[str]
    rationale: str

class FinancialQualityResult:
    score: int                    # 0-100
    metrics: dict                 # All computed metrics with values + years
    # metrics includes:
    #   roe_avg_5yr, roe_trend
    #   roic_avg_5yr, roic_trend
    #   debt_to_equity_current, debt_to_equity_trend
    #   interest_coverage
    #   current_ratio
    #   fcf_to_net_income_avg  (earnings quality check)
    #   gross_margin_avg, gross_margin_stability
    #   operating_margin_avg
    #   capex_to_revenue_avg
    flags: list[str]              # e.g. ["high debt load", "declining ROE"]
    evidence: list[str]           # Data field references: "ROE 2024: 28.3% (net_income/total_equity)"
    rationale: str

class StabilityResult:
    score: int                    # 0-100
    revenue_cagr_5yr: float
    revenue_cagr_10yr: float | None
    earnings_cagr_5yr: float
    revenue_volatility: float     # Coefficient of variation
    earnings_volatility: float    # Coefficient of variation
    consecutive_profit_years: int
    dividend_consistency: str     # "Consistent" | "Irregular" | "None"
    regression_r_squared: float   # Linear fit on revenue — measures trend reliability
    evidence: list[str]
    rationale: str

class ScenarioValuation:
    owner_earnings: float
    growth_rate: float
    discount_rate: float
    terminal_growth_rate: float
    maintenance_capex: float
    maintenance_capex_method: str  # How we estimated it
    projected_cash_flows: list[float]  # Year 1-10
    terminal_value: float
    present_value: float          # Total PV of cash flows + terminal
    per_share_value: float
    assumptions: list[str]        # Every assumption stated explicitly

class ValuationResult:
    bull: ScenarioValuation
    base: ScenarioValuation
    bear: ScenarioValuation
    epv: float                    # Earnings Power Value as sanity check
    epv_per_share: float
    current_price: float
    sensitivity_table: list[dict] # Discount rate vs growth rate matrix
    evidence: list[str]
    rationale: str

class MarginOfSafetyResult:
    score: int                    # 0-100
    current_price: float
    base_intrinsic_value: float
    bull_intrinsic_value: float
    bear_intrinsic_value: float
    margin_of_safety_pct: float   # (base_IV - price) / base_IV
    bull_upside_pct: float
    bear_downside_pct: float
    verdict: str                  # "Undervalued" | "Fairly Valued" | "Overvalued"
    evidence: list[str]
    rationale: str

class RecommendationResult:
    action: str                   # "Buy" | "Watch" | "Avoid"
    position_size: str            # "Full" | "Half" | "Starter" | "None"
    composite_score: float        # 0-100 weighted composite
    score_breakdown: dict         # {module_name: score} for each step
    bull_case: str                # 2-3 sentences
    bear_case: str                # 2-3 sentences
    monitoring_metrics: list[str] # What to watch: e.g. ["gross margin < 38%", "debt/equity > 1.5"]
    evidence: list[str]
    rationale: str
```

Every result model includes `evidence` (traceable data references) and `rationale` (human-readable explanation). The JSON is the source of truth; the Markdown is generated from it.

---

## 3. Scoring Rubric Definitions

### Step 1: Circle of Competence (0-100)

| Score Range | Meaning | Criteria |
|-------------|---------|----------|
| 80-100 | Highly understandable | Simple business model, ≤3 major revenue segments, predictable demand drivers, no complex financial instruments |
| 60-79 | Reasonably understandable | Moderate complexity, ≤5 segments, some cyclicality or regulatory complexity |
| 40-59 | Somewhat complex | Multi-segment, some opaque revenue drivers, moderate financial engineering |
| 20-39 | Complex | Conglomerate, heavy financial engineering, or highly technical product with unclear moats |
| 0-19 | Opaque | Unable to clearly explain how the company makes money from public filings |

**Inputs used:** business description, revenue segment breakdown, filing MD&A section.

### Step 2: Moat Proxy (0-100)

Five moat sources scored independently (each 0-100), then weighted:

| Moat Source | Weight | How Scored |
|-------------|--------|------------|
| Brand / Pricing Power | 25% | Gross margin level + trend, brand mentions in filings |
| Switching Costs | 25% | Revenue retention patterns, contract length, R&D integration |
| Network Effects | 20% | User/revenue growth correlation, platform dynamics |
| Cost Advantages | 15% | Operating margin vs industry peers, scale indicators |
| Intangible Assets | 15% | Patents, licenses, regulatory barriers in filings |

**Moat classification:**
- Wide: score ≥ 75
- Narrow: score 50-74
- None: score < 50

**Durability:** Assessed by 5-year margin trend direction. Expanding = Strengthening, flat = Durable, contracting = Eroding.

### Step 3: Financial Quality (0-100)

Deterministic scoring. Each metric scored 0-100, then weighted:

| Metric | Weight | Scoring |
|--------|--------|---------|
| ROE (5yr avg) | 20% | ≥20% → 100, ≥15% → 80, ≥10% → 60, ≥5% → 40, <5% → 20 |
| ROIC (5yr avg) | 20% | ≥15% → 100, ≥12% → 80, ≥8% → 60, ≥5% → 40, <5% → 20 |
| Debt-to-Equity | 15% | ≤0.3 → 100, ≤0.5 → 85, ≤1.0 → 65, ≤2.0 → 40, >2.0 → 15 |
| Interest Coverage | 10% | ≥15x → 100, ≥8x → 80, ≥4x → 60, ≥2x → 40, <2x → 15 |
| FCF/Net Income (avg) | 15% | ≥1.0 → 100, ≥0.8 → 80, ≥0.6 → 60, ≥0.4 → 40, <0.4 → 20 |
| Gross Margin Stability | 10% | CoV <0.05 → 100, <0.10 → 75, <0.20 → 50, ≥0.20 → 25 |
| Current Ratio | 10% | ≥2.0 → 100, ≥1.5 → 80, ≥1.0 → 60, ≥0.7 → 40, <0.7 → 15 |

### Step 4: Stability (0-100)

| Metric | Weight | Scoring |
|--------|--------|---------|
| Revenue CAGR 5yr | 20% | ≥15% → 100, ≥10% → 85, ≥5% → 70, ≥0% → 50, <0% → 20 |
| Earnings CAGR 5yr | 20% | Same scale as revenue |
| Revenue Volatility (CoV) | 20% | <0.05 → 100, <0.10 → 80, <0.15 → 60, <0.25 → 40, ≥0.25 → 20 |
| Earnings Volatility (CoV) | 20% | <0.10 → 100, <0.15 → 80, <0.25 → 60, <0.40 → 40, ≥0.40 → 20 |
| Consecutive Profit Years | 10% | 10 → 100, 8-9 → 85, 5-7 → 65, 3-4 → 40, <3 → 15 |
| Revenue R² (linear trend) | 10% | ≥0.95 → 100, ≥0.85 → 80, ≥0.70 → 60, ≥0.50 → 40, <0.50 → 20 |

### Step 5: Intrinsic Value — Valuation Parameters

**Owner Earnings formula:**
```
Owner Earnings = Net Income + D&A - Maintenance CapEx ± ΔWorking Capital
```

**Maintenance CapEx heuristic:**
- Primary method: `Maintenance CapEx = D&A × 1.0` (assumption: D&A approximates maintenance spending)
- Cross-check: `CapEx × (1 - revenue_growth_rate)` — the logic being that a portion of CapEx proportional to growth is growth CapEx
- If the two methods diverge by >30%, flag it and use the more conservative (higher) estimate
- Sensitivity table tests Maintenance CapEx at 80%, 100%, and 120% of D&A

**Three scenarios:**

| Parameter | Bull | Base | Bear |
|-----------|------|------|------|
| Growth rate | Historical CAGR × 0.9 (cap 20%) | Historical CAGR × 0.6 (cap 12%) | Max(historical CAGR × 0.3, 0%) (cap 5%) |
| Discount rate | 9% | 10% | 12% |
| Terminal growth | 4% (configurable) | 3% | 2% |
| Margin assumption | Current margins hold | Slight compression (5%) | 15% compression |

**DCF:**
```
PV = Σ_{t=1}^{10} OE_t / (1 + r)^t  +  TV / (1 + r)^10
TV = OE_10 × (1 + g_terminal) / (r - g_terminal)
```

**EPV (sanity check):**
```
EPV = Adjusted Earnings / WACC
Adjusted Earnings = avg(Owner Earnings, last 3 years)  # smoothed
WACC simplified to discount rate for this model
```

### Step 6: Margin of Safety (0-100)

| Margin of Safety % | Score |
|---------------------|-------|
| ≥ 50% | 100 |
| 40-49% | 90 |
| 30-39% | 75 |
| 20-29% | 60 |
| 10-19% | 45 |
| 0-9% | 25 |
| Negative (overvalued) | 0-15 (scaled by how overvalued) |

`Margin of Safety % = (Base Intrinsic Value - Price) / Base Intrinsic Value × 100`

### Final Recommendation

| Composite Score | Action | Position Size |
|-----------------|--------|---------------|
| ≥ 80 | Buy | Full |
| 70-79 | Buy | Half |
| 60-69 | Buy | Starter |
| 50-59 | Watch | None |
| < 50 | Avoid | None |

**Composite Score Weights (same as ranking):**

| Factor | Weight |
|--------|--------|
| Margin of Safety (Step 6) | 30% |
| Moat Proxy (Step 2) | 25% |
| Financial Quality (Step 3) | 20% |
| Stability (Step 4) | 15% |
| Circle of Competence (Step 1) | 10% |

---

## 4. Industry Universe Method

### Identifying Top N Companies

1. **Input:** Industry name (e.g., "Semiconductors") + N (default 20) + sort method (default: market_cap, optional: revenue)
2. **Process:**
   - Query FMP's stock screener API with sector/industry filter
   - Filter: US exchanges only (NYSE, NASDAQ), market cap > $1B (configurable floor)
   - Sort by market cap (or revenue if selected)
   - Take top N
3. **Output:** Universe list with: ticker, name, market cap, inclusion rationale

```python
class UniverseCompany:
    ticker: str
    name: str
    market_cap: float
    revenue_ttm: float | None
    sector: str
    industry: str
    exchange: str
    inclusion_rationale: str   # e.g. "Ranked #3 by market cap in Semiconductors ($542B)"

class UniverseResult:
    industry: str
    sort_method: str           # "market_cap" or "revenue"
    min_market_cap: float
    total_found: int           # How many matched before truncation
    companies: list[UniverseCompany]
```

### Industry Pipeline Flow

```
Industry Input ("Semiconductors", N=20)
    │
    ▼
universe.py → UniverseResult (20 companies)
    │
    ▼
For each company → Full Company Pipeline (Steps 1-6 + Recommendation)
    │
    ▼
ranking.py → Apply hard filters → Score survivors → Sort → Top 5
    │
    ▼
industry_report_gen.py → Combined report
```

---

## 5. Ranking Algorithm

### Hard Filters (must ALL pass to be ranked)

| Filter | Threshold | On Failure |
|--------|-----------|------------|
| Moat score | ≥ 70 | Eliminated |
| Financial Quality score | ≥ 70 | Eliminated |
| Stability score | ≥ 60 | Eliminated |
| Price vs Base IV | Price ≤ Base IV × 0.85 | Eliminated |
| Bear-case downside | ≤ 25% OR explicit justification | Flagged as "Higher Risk" but NOT eliminated; included with ⚠️ flag |

**Bear-case downside** = `(Price - Bear IV) / Price × 100`. If bear IV is below current price, this is positive (you lose money). If > 25%, the company stays in ranking but gets a risk flag and must include a justification paragraph.

### Composite Score (for ranking survivors)

Same weights as Final Recommendation composite:

| Factor | Weight |
|--------|--------|
| Margin of Safety | 30% |
| Moat Proxy | 25% |
| Financial Quality | 20% |
| Stability | 15% |
| Circle of Competence | 10% |

Sort descending. Output top 5.

---

## 6. Error Handling Strategy

### Data Layer Errors

| Error | Handling |
|-------|----------|
| FMP API rate limit | Exponential backoff, max 3 retries, 2s/4s/8s |
| FMP returns no data for ticker | Return clear error: "No financial data found for {ticker}" |
| FMP returns partial data (<5 years) | Proceed with warning: "Only {n} years of data available; scores may be less reliable" |
| EDGAR filing not found | Skip filing text; LLM modules use business description from FMP instead; flag in report |
| yfinance fallback triggered | Log: "Primary price source unavailable, using yfinance fallback" |
| Invalid ticker | Fail fast with "Ticker {ticker} not found on US exchanges" |
| Network timeout | 30s timeout, retry once, then fail with clear message |

### Analysis Layer Errors

| Error | Handling |
|-------|----------|
| Division by zero (e.g., zero equity for ROE) | Return `None` for that metric, exclude from scoring, note in evidence |
| Negative equity | Flag as "negative equity — financial distress indicator", set financial quality sub-score to 0 for D/E metric |
| LLM call fails | Retry once; on second failure, produce a "LLM analysis unavailable" stub with deterministic-only scoring |
| LLM returns unparseable JSON | Retry with stricter prompt; on failure, flag module as degraded |
| Unreasonable valuation (IV > 10× or < 0.1× current price) | Flag as "valuation outlier — review assumptions", still include but mark |

### Industry Pipeline Errors

| Error | Handling |
|-------|----------|
| <5 companies pass hard filters | Produce report with available companies + note: "Only {n} of {N} companies passed all filters" |
| 0 companies pass hard filters | Report: "No companies in {industry} currently meet all investment criteria" with the closest misses listed |
| Individual company analysis fails | Skip that company, note in report, continue with remaining |

### General Principles

- **Never silently drop data.** Every omission, fallback, or degradation is noted in the report's evidence trail.
- **Fail loud, not wrong.** Better to say "I couldn't compute this" than to output a bad number.
- **Every number has a source.** If a data field is missing, the downstream score says why.

---

## 7. Self-Test Plan

### Unit Tests

| Test File | What It Covers |
|-----------|----------------|
| `test_data_clients.py` | FMP client returns valid `FinancialHistory` for AAPL; EDGAR returns filing text; handles invalid ticker gracefully |
| `test_valuation.py` | Owner Earnings calculation with known inputs; DCF produces expected PV; sensitivity table generates; maintenance capex heuristic cross-check; all 3 scenarios produce different values with bull > base > bear |
| `test_financial_quality.py` | Each metric scorer returns correct score for known values; composite weighting is correct; handles `None` metrics |
| `test_stability.py` | CAGR calculation; CoV calculation; R² calculation; handles short history (<10yr) |
| `test_scoring.py` | Composite score calculation; position size mapping; action mapping |
| `test_ranking.py` | Hard filter eliminates correctly; bear-case flag works; ranking order is correct; handles edge case of 0 survivors |

### End-to-End Tests

**E2E #1: Single Company — AAPL**
- Input: ticker="AAPL"
- Verify: All 6 steps produce valid JSON matching schema + non-empty evidence
- Verify: Markdown report generates and contains all sections
- Verify: Valuation has bull > base > bear
- Verify: Recommendation is one of Buy/Watch/Avoid with valid position size
- Output: Save report to `output/AAPL_report.json` + `output/AAPL_report.md`

**E2E #2: Industry — Semiconductors**
- Input: industry="Semiconductors", N=20
- Verify: Universe contains ≤20 companies with tickers + market caps + rationale
- Verify: Each company in universe gets analyzed (or has documented skip reason)
- Verify: Hard filters applied correctly
- Verify: Top 5 output is sorted by composite score descending
- Verify: Any bear-case flag >25% has justification text
- Output: Save to `output/Semiconductors_industry.json` + `output/Semiconductors_industry.md`

---

## 8. Configuration (config.py)

```python
# All defaults, all overridable via Streamlit UI

FMP_API_KEY = ""                    # Required — set via env var or UI
CLAUDE_API_KEY = ""                 # Required — set via env var or UI

# Valuation defaults
PROJECTION_YEARS = 10
DISCOUNT_RATE = 0.10
TERMINAL_GROWTH_RATE = 0.04
MAINTENANCE_CAPEX_RATIO = 1.0       # Multiplier on D&A

# Industry defaults
DEFAULT_UNIVERSE_SIZE = 20
MIN_MARKET_CAP = 1_000_000_000      # $1B floor
UNIVERSE_SORT = "market_cap"        # or "revenue"

# Hard filter thresholds
MIN_MOAT_SCORE = 70
MIN_FINANCIAL_SCORE = 70
MIN_STABILITY_SCORE = 60
MAX_PRICE_TO_IV_RATIO = 0.85        # Price must be ≤ 85% of base IV
MAX_BEAR_DOWNSIDE_PCT = 25          # Flag threshold

# Scoring weights
WEIGHTS = {
    "margin_of_safety": 0.30,
    "moat_proxy": 0.25,
    "financial_quality": 0.20,
    "stability": 0.15,
    "circle_of_competence": 0.10,
}

# API settings
FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
FMP_TIMEOUT = 30
FMP_MAX_RETRIES = 3
EDGAR_USER_AGENT = "BuffettAnalyzer/1.0 (contact@example.com)"
```

---

## Checkpoint

**This document covers:**
- ✅ Modules + directory structure
- ✅ Data schemas (inputs/outputs per module)
- ✅ Scoring rubric definitions (all 6 steps + final recommendation)
- ✅ Industry universe method
- ✅ Ranking algorithm (hard filters + composite scoring)
- ✅ Error-handling strategy
- ✅ Self-test plan (unit + 2 E2E tests)
- ✅ Configuration defaults

**Awaiting your confirmation to begin implementation.**
