"""Pydantic data models for all data and analysis results."""
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional


# ── Data Models ──────────────────────────────────────────────────────────────

class CompanyProfile(BaseModel):
    ticker: str
    name: str
    sector: str = ""
    industry: str = ""
    market_cap: float = 0.0
    description: str = ""
    num_employees: Optional[int] = None
    exchange: str = ""


class FinancialStatement(BaseModel):
    """One fiscal year of financials."""
    fiscal_year: int
    revenue: float = 0.0
    cost_of_revenue: float = 0.0
    gross_profit: float = 0.0
    operating_income: float = 0.0
    net_income: float = 0.0
    eps: float = 0.0
    shares_outstanding: float = 0.0
    total_assets: float = 0.0
    total_liabilities: float = 0.0
    total_equity: float = 0.0
    long_term_debt: float = 0.0
    total_debt: float = 0.0
    cash_and_equivalents: float = 0.0
    depreciation_amortization: float = 0.0
    capital_expenditure: float = 0.0  # stored as positive
    operating_cash_flow: float = 0.0
    free_cash_flow: float = 0.0
    dividends_paid: float = 0.0
    change_in_working_capital: float = 0.0
    research_and_development: Optional[float] = None
    sga_expense: Optional[float] = None


class FinancialHistory(BaseModel):
    ticker: str
    profile: CompanyProfile
    statements: list[FinancialStatement] = Field(default_factory=list)  # oldest → newest
    current_price: float = 0.0
    current_market_cap: float = 0.0
    shares_outstanding: float = 0.0


class FilingText(BaseModel):
    ticker: str
    filing_type: str = "10-K"
    fiscal_year: int = 0
    sections: dict[str, str] = Field(default_factory=dict)


# ── Analysis Result Models ───────────────────────────────────────────────────

class CompetenceResult(BaseModel):
    score: int = 0  # 0-100
    business_model_summary: str = ""
    revenue_segments: list[dict] = Field(default_factory=list)
    predictability: str = "Medium"  # High | Medium | Low
    complexity_flags: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    rationale: str = ""


class MoatSource(BaseModel):
    source: str = ""
    strength: int = 0  # 0-100
    evidence: str = ""


class MoatResult(BaseModel):
    score: int = 0  # 0-100
    moat_type: str = "None"  # Wide | Narrow | None
    moat_sources: list[MoatSource] = Field(default_factory=list)
    durability_assessment: str = "Durable"  # Durable | Eroding | Strengthening
    margin_trend: dict = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    rationale: str = ""


class FinancialQualityResult(BaseModel):
    score: int = 0  # 0-100
    metrics: dict = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    rationale: str = ""


class StabilityResult(BaseModel):
    score: int = 0  # 0-100
    revenue_cagr_5yr: Optional[float] = None
    revenue_cagr_10yr: Optional[float] = None
    earnings_cagr_5yr: Optional[float] = None
    revenue_volatility: Optional[float] = None  # CoV
    earnings_volatility: Optional[float] = None  # CoV
    consecutive_profit_years: int = 0
    dividend_consistency: str = "None"  # Consistent | Irregular | None
    regression_r_squared: Optional[float] = None
    evidence: list[str] = Field(default_factory=list)
    rationale: str = ""


class ScenarioValuation(BaseModel):
    label: str = ""  # bull | base | bear
    owner_earnings: float = 0.0
    growth_rate: float = 0.0
    discount_rate: float = 0.0
    terminal_growth_rate: float = 0.0
    maintenance_capex: float = 0.0
    maintenance_capex_method: str = ""
    projected_cash_flows: list[float] = Field(default_factory=list)
    terminal_value: float = 0.0
    present_value: float = 0.0
    per_share_value: float = 0.0
    assumptions: list[str] = Field(default_factory=list)


class ValuationResult(BaseModel):
    bull: ScenarioValuation = Field(default_factory=ScenarioValuation)
    base: ScenarioValuation = Field(default_factory=ScenarioValuation)
    bear: ScenarioValuation = Field(default_factory=ScenarioValuation)
    epv: float = 0.0
    epv_per_share: float = 0.0
    current_price: float = 0.0
    sensitivity_table: list[dict] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    rationale: str = ""


class MarginOfSafetyResult(BaseModel):
    score: int = 0  # 0-100
    current_price: float = 0.0
    base_intrinsic_value: float = 0.0
    bull_intrinsic_value: float = 0.0
    bear_intrinsic_value: float = 0.0
    margin_of_safety_pct: float = 0.0
    bull_upside_pct: float = 0.0
    bear_downside_pct: float = 0.0
    verdict: str = "Fairly Valued"  # Undervalued | Fairly Valued | Overvalued
    evidence: list[str] = Field(default_factory=list)
    rationale: str = ""


class RecommendationResult(BaseModel):
    action: str = "Watch"  # Buy | Watch | Avoid
    position_size: str = "None"  # Full | Half | Starter | None
    composite_score: float = 0.0
    score_breakdown: dict = Field(default_factory=dict)
    bull_case: str = ""
    bear_case: str = ""
    monitoring_metrics: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    rationale: str = ""


# ── Full Company Report ──────────────────────────────────────────────────────

class CompanyReport(BaseModel):
    ticker: str
    name: str
    analysis_date: str = ""
    currency: str = "USD"
    currency_note: str = ""
    competence: CompetenceResult = Field(default_factory=CompetenceResult)
    moat: MoatResult = Field(default_factory=MoatResult)
    financial_quality: FinancialQualityResult = Field(default_factory=FinancialQualityResult)
    stability: StabilityResult = Field(default_factory=StabilityResult)
    valuation: ValuationResult = Field(default_factory=ValuationResult)
    margin_of_safety: MarginOfSafetyResult = Field(default_factory=MarginOfSafetyResult)
    recommendation: RecommendationResult = Field(default_factory=RecommendationResult)
    warnings: list[str] = Field(default_factory=list)
    validation_summary: str = ""
    validation_issues: list[dict] = Field(default_factory=list)


# ── Industry Models ──────────────────────────────────────────────────────────

class UniverseCompany(BaseModel):
    ticker: str
    name: str
    market_cap: float = 0.0
    revenue_ttm: Optional[float] = None
    sector: str = ""
    industry: str = ""
    exchange: str = ""
    inclusion_rationale: str = ""


class UniverseResult(BaseModel):
    industry: str
    sort_method: str = "market_cap"
    min_market_cap: float = 1_000_000_000
    total_found: int = 0
    companies: list[UniverseCompany] = Field(default_factory=list)


class RankedCompany(BaseModel):
    ticker: str
    name: str
    composite_score: float = 0.0
    score_breakdown: dict = Field(default_factory=dict)
    action: str = "Watch"
    margin_of_safety_pct: float = 0.0
    bear_downside_pct: float = 0.0
    bear_risk_flag: bool = False
    bear_justification: str = ""
    passed_all_filters: bool = False
    filter_failures: list[str] = Field(default_factory=list)


class IndustryReport(BaseModel):
    industry: str
    analysis_date: str = ""
    universe: UniverseResult = Field(default_factory=lambda: UniverseResult(industry=""))
    all_reports: list[CompanyReport] = Field(default_factory=list)
    ranked: list[RankedCompany] = Field(default_factory=list)
    top_5: list[RankedCompany] = Field(default_factory=list)
    skipped: list[dict] = Field(default_factory=list)  # {ticker, reason}
    warnings: list[str] = Field(default_factory=list)
