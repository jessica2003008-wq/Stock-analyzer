"""
valuation_engine.py — Per-Company Valuation Engine (v3)
=========================================================

核心思想（借鉴 ai-hedge-fund）：
  不同公司 → 完全不同的估值方法和参数，不是一套参数套所有

公司类型 → 估值方法映射：
  mature_quality  → 三阶段 DCF（保守，Buffett风格）
  growth          → 高增长 DCF + FCF倍数（Cathie Wood风格）
  value_trap      → Graham Number + Net-Net（Ben Graham风格）
  cyclical        → 标准化盈利 + EV/EBITDA（周期均值回归）
  distressed      → 资产清算价值（悲观为主）

每种类型有独立的：
  - 增长率计算逻辑
  - 折现率区间
  - 终端价值方法
  - 置信度调整
  - LLM prompt 人格
"""

from __future__ import annotations
import math
from typing import Optional, List, Literal
from pydantic import BaseModel

# ── 公司画像（升级版，更细粒度） ──────────────────────────────────────────────

CompanyType = Literal[
    "mature_quality",   # 苹果、可口可乐：稳定现金流，宽护城河
    "growth",           # Nvidia、Salesforce：高增长，高R&D，高倍数
    "value_deep",       # 被低估的传统公司：Graham Number有效
    "cyclical",         # 钢铁、汽车、能源：用标准化盈利
    "distressed",       # 高杠杆、持续亏损：以资产价值为主
]

class CompanyProfile(BaseModel):
    """从数据自动判断的公司画像"""
    company_type: CompanyType
    # 判断依据
    revenue_cagr_5yr: float
    gross_margin_avg: float
    roe_avg: float
    debt_to_equity: float
    fcf_positive_years: int          # 近5年FCF为正的年数
    rd_to_revenue: float             # R&D / Revenue（成长型公司关键指标）
    revenue_volatility_cov: float    # 营收变异系数（越高越周期）
    # 分类理由
    classification_rationale: str
    # 建议估值方法
    recommended_method: str


class ValuationParams(BaseModel):
    """每种公司类型的专属估值参数"""
    company_type: CompanyType
    method_name: str

    # DCF 参数
    stage1_years: int = 5
    stage2_years: int = 5
    stage1_growth: float = 0.06
    stage2_growth: float = 0.03
    terminal_growth: float = 0.025
    discount_rate: float = 0.10

    # 倍数法参数（成长型/周期型）
    use_multiple_method: bool = False
    terminal_fcf_multiple: float = 15.0     # 终端FCF倍数
    normalized_earnings_years: int = 5      # 周期股标准化盈利用几年均值

    # 保守性调整
    growth_haircut: float = 0.0             # 历史增长打折
    iv_haircut: float = 0.0                 # 最终IV额外保守折扣

    # 参数来源说明
    params_rationale: List[str] = []


# ── 公司分类器（核心函数） ─────────────────────────────────────────────────────

def classify_company(
    revenue_cagr_5yr: float,
    gross_margin_avg: float,
    roe_avg: float,
    debt_to_equity: float,
    fcf_positive_years: int,
    rd_to_revenue: float,
    revenue_volatility_cov: float,
    net_income_positive_years: int,
) -> CompanyProfile:
    """
    根据财务指标自动分类公司类型。
    逻辑：先排除极端情况（distressed），再看增长特征。
    """
    reasons = []

    # 1. 财务困境判断（优先级最高）
    if net_income_positive_years <= 2 or debt_to_equity > 3.0 or fcf_positive_years <= 1:
        reasons.append(f"财务困境信号：盈利年数={net_income_positive_years}，D/E={debt_to_equity:.1f}，FCF正年数={fcf_positive_years}")
        return CompanyProfile(
            company_type="distressed",
            revenue_cagr_5yr=revenue_cagr_5yr,
            gross_margin_avg=gross_margin_avg,
            roe_avg=roe_avg,
            debt_to_equity=debt_to_equity,
            fcf_positive_years=fcf_positive_years,
            rd_to_revenue=rd_to_revenue,
            revenue_volatility_cov=revenue_volatility_cov,
            classification_rationale="; ".join(reasons),
            recommended_method="资产清算价值 + 悲观DCF",
        )

    # 2. 成长型判断：高增速 + 高R&D + 可接受亏损
    if revenue_cagr_5yr >= 0.15 and rd_to_revenue >= 0.08:
        reasons.append(f"成长型：营收CAGR={revenue_cagr_5yr:.1%}（≥15%），R&D占比={rd_to_revenue:.1%}（≥8%）")
        return CompanyProfile(
            company_type="growth",
            revenue_cagr_5yr=revenue_cagr_5yr,
            gross_margin_avg=gross_margin_avg,
            roe_avg=roe_avg,
            debt_to_equity=debt_to_equity,
            fcf_positive_years=fcf_positive_years,
            rd_to_revenue=rd_to_revenue,
            revenue_volatility_cov=revenue_volatility_cov,
            classification_rationale="; ".join(reasons),
            recommended_method="高增长DCF（20%增速）+ 终端FCF倍数法",
        )

    # 仅高增速无高R&D也算成长（如平台公司）
    if revenue_cagr_5yr >= 0.20:
        reasons.append(f"高速成长：营收CAGR={revenue_cagr_5yr:.1%}（≥20%），暂无高R&D但增速主导")
        return CompanyProfile(
            company_type="growth",
            revenue_cagr_5yr=revenue_cagr_5yr,
            gross_margin_avg=gross_margin_avg,
            roe_avg=roe_avg,
            debt_to_equity=debt_to_equity,
            fcf_positive_years=fcf_positive_years,
            rd_to_revenue=rd_to_revenue,
            revenue_volatility_cov=revenue_volatility_cov,
            classification_rationale="; ".join(reasons),
            recommended_method="高增长DCF + 终端倍数法",
        )

    # 3. 周期型：营收波动大
    if revenue_volatility_cov >= 0.20:
        reasons.append(f"周期型：营收波动CoV={revenue_volatility_cov:.2f}（≥0.20）")
        return CompanyProfile(
            company_type="cyclical",
            revenue_cagr_5yr=revenue_cagr_5yr,
            gross_margin_avg=gross_margin_avg,
            roe_avg=roe_avg,
            debt_to_equity=debt_to_equity,
            fcf_positive_years=fcf_positive_years,
            rd_to_revenue=rd_to_revenue,
            revenue_volatility_cov=revenue_volatility_cov,
            classification_rationale="; ".join(reasons),
            recommended_method="标准化盈利DCF（5年均值） + EV/EBITDA多倍数",
        )

    # 4. 深度价值：低增长但低估
    if revenue_cagr_5yr < 0.05 and gross_margin_avg < 0.30 and roe_avg < 0.12:
        reasons.append(f"深度价值型：增长={revenue_cagr_5yr:.1%}，毛利={gross_margin_avg:.1%}，ROE={roe_avg:.1%}")
        return CompanyProfile(
            company_type="value_deep",
            revenue_cagr_5yr=revenue_cagr_5yr,
            gross_margin_avg=gross_margin_avg,
            roe_avg=roe_avg,
            debt_to_equity=debt_to_equity,
            fcf_positive_years=fcf_positive_years,
            rd_to_revenue=rd_to_revenue,
            revenue_volatility_cov=revenue_volatility_cov,
            classification_rationale="; ".join(reasons),
            recommended_method="Graham Number + NCAV + 保守DCF",
        )

    # 5. 默认：成熟优质
    reasons.append(
        f"成熟优质：CAGR={revenue_cagr_5yr:.1%}，毛利={gross_margin_avg:.1%}，"
        f"ROE={roe_avg:.1%}，D/E={debt_to_equity:.1f}，FCF正={fcf_positive_years}/5年"
    )
    return CompanyProfile(
        company_type="mature_quality",
        revenue_cagr_5yr=revenue_cagr_5yr,
        gross_margin_avg=gross_margin_avg,
        roe_avg=roe_avg,
        debt_to_equity=debt_to_equity,
        fcf_positive_years=fcf_positive_years,
        rd_to_revenue=rd_to_revenue,
        revenue_volatility_cov=revenue_volatility_cov,
        classification_rationale="; ".join(reasons),
        recommended_method="三阶段保守DCF（Buffett风格）",
    )


# ── 每种公司类型的专属估值参数 ────────────────────────────────────────────────

def get_valuation_params(
    profile: CompanyProfile,
    market_implied_growth: Optional[float] = None,
    analyst_forward_growth: Optional[float] = None,
    market_pe: Optional[float] = None,
) -> ValuationParams:
    """
    根据公司画像返回专属估值参数。
    这是整个升级的核心：不同公司 → 完全不同的参数，不是一套套所有。
    """
    hist_g = profile.revenue_cagr_5yr
    reasons = [f"公司类型: {profile.company_type}"]

    # ════════════════════════════════════════
    # 成熟优质：苹果、可口可乐、强生
    # 来源：Buffett三阶段DCF
    # ════════════════════════════════════════
    if profile.company_type == "mature_quality":
        # 增长：历史CAGR × 0.7（保守），再考虑analyst预期
        g1 = _blend_growth(hist_g * 0.70, analyst_forward_growth, weight_analyst=0.35)
        g1 = min(g1, 0.12)   # 成熟公司cap 12%
        g2 = g1 * 0.50        # 第二阶段减速一半
        tg = 0.025            # 终端：接近GDP增速

        # 折现率：从PE反推，保守区间 8-10%
        dr = _dr_from_pe(market_pe, lo=0.08, hi=0.10, default=0.10)
        reasons += [
            f"增长Stage1={g1:.1%}（历史×0.7 + analyst融合），Stage2={g2:.1%}，终端={tg:.1%}",
            f"折现率={dr:.1%}（PE反推，区间8-10%）",
            "终端价值：Gordon增长模型",
            "额外保守：最终IV × 0.85（Buffett安全边际）",
        ]
        return ValuationParams(
            company_type="mature_quality",
            method_name="三阶段保守DCF（Buffett）",
            stage1_years=5, stage2_years=5,
            stage1_growth=g1, stage2_growth=g2,
            terminal_growth=tg, discount_rate=dr,
            use_multiple_method=False,
            growth_haircut=0.0,
            iv_haircut=0.15,   # 额外15%保守折扣
            params_rationale=reasons,
        )

    # ════════════════════════════════════════
    # 成长型：Nvidia、Salesforce、Shopify
    # 来源：Cathie Wood高增长DCF + 终端倍数
    # ════════════════════════════════════════
    elif profile.company_type == "growth":
        # 增长：analyst预期权重更高（成长公司analyst更准），但打折避免过度乐观
        g1 = _blend_growth(hist_g * 0.80, analyst_forward_growth, weight_analyst=0.50)
        g1 = min(g1, 0.35)   # 成长公司可以允许35%

        # 重要：成长公司用两阶段而非三阶段
        # 第一阶段（5年）：高速增长
        # 直接用终端FCF倍数，不做第二阶段
        g2 = g1 * 0.40        # 急速减速
        tg = 0.04             # 成长公司终端增速略高

        # 折现率更高：成长公司风险溢价更大
        dr = _dr_from_pe(market_pe, lo=0.10, hi=0.15, default=0.12)
        # 终端用倍数：25x FCF（成长公司接近市场给的倍数）
        terminal_mult = _growth_terminal_multiple(g1)

        reasons += [
            f"增长Stage1={g1:.1%}（analyst权重50%，历史×0.8权重50%，cap35%）",
            f"折现率={dr:.1%}（成长溢价，区间10-15%）",
            f"终端倍数={terminal_mult:.0f}x FCF（基于增速自动计算）",
            "注意：成长公司DCF高度依赖终端假设，结果区间宽",
            "市场锚点权重更低（50%），模型权重50%",
        ]
        return ValuationParams(
            company_type="growth",
            method_name="高增长DCF + 终端FCF倍数（Cathie Wood风格）",
            stage1_years=5, stage2_years=5,
            stage1_growth=g1, stage2_growth=g2,
            terminal_growth=tg, discount_rate=dr,
            use_multiple_method=True,
            terminal_fcf_multiple=terminal_mult,
            growth_haircut=0.0,
            iv_haircut=0.0,   # 成长公司不额外打折（已在DR中体现）
            params_rationale=reasons,
        )

    # ════════════════════════════════════════
    # 深度价值：传统制造、银行、零售
    # 来源：Ben Graham - Graham Number + 保守DCF
    # ════════════════════════════════════════
    elif profile.company_type == "value_deep":
        # 增长：保守，不信历史（价值型公司历史增长不代表未来）
        g1 = min(hist_g * 0.50, 0.05)   # cap 5%，极度保守
        g2 = g1 * 0.50
        tg = 0.02            # 几乎零实际增长
        dr = 0.11            # 价值公司风险溢价中等

        reasons += [
            f"增长Stage1={g1:.1%}（历史×0.5，cap5%，Ben Graham极度保守）",
            f"折现率={dr:.1%}（固定，价值公司不用PE反推）",
            "同时计算 Graham Number = √(22.5 × EPS × BVPS)",
            "同时计算 NCAV = 流动资产 - 总负债",
            "最终IV取 DCF 和 Graham Number 的保守值",
        ]
        return ValuationParams(
            company_type="value_deep",
            method_name="Graham Number + 保守DCF（Ben Graham）",
            stage1_years=5, stage2_years=5,
            stage1_growth=g1, stage2_growth=g2,
            terminal_growth=tg, discount_rate=dr,
            use_multiple_method=False,
            growth_haircut=0.0,
            iv_haircut=0.20,   # 额外20%保守（Graham强调安全边际）
            params_rationale=reasons,
        )

    # ════════════════════════════════════════
    # 周期型：钢铁、汽车、油气、航运
    # 来源：标准化盈利（避免周期顶点高估）
    # ════════════════════════════════════════
    elif profile.company_type == "cyclical":
        # 关键：用5-7年平均盈利，不用当年盈利！
        # 当年可能处于周期顶点或谷底，都会扭曲估值
        g1 = min(max(hist_g * 0.40, 0.0), 0.06)  # 周期公司增长cap 6%
        g2 = g1 * 0.30        # 周期公司长期增长很低
        tg = 0.015            # 接近通胀
        dr = 0.115            # 周期公司风险溢价较高

        reasons += [
            f"增长Stage1={g1:.1%}（历史×0.4，cap6%，周期公司不能信历史高点）",
            f"折现率={dr:.1%}（周期溢价）",
            f"关键：用{5}年平均OE代替最新OE（避免周期顶点高估）",
            "终端增长接近通胀（1.5%），周期公司无法持续增长",
        ]
        return ValuationParams(
            company_type="cyclical",
            method_name="标准化盈利DCF（周期均值回归）",
            stage1_years=5, stage2_years=5,
            stage1_growth=g1, stage2_growth=g2,
            terminal_growth=tg, discount_rate=dr,
            use_multiple_method=False,
            normalized_earnings_years=5,   # 用5年均值
            growth_haircut=0.0,
            iv_haircut=0.10,
            params_rationale=reasons,
        )

    # ════════════════════════════════════════
    # 财务困境：高杠杆、持续亏损
    # ════════════════════════════════════════
    else:  # distressed
        g1 = max(hist_g * 0.20, -0.05)  # 困境公司增长可能负
        g2 = 0.0
        tg = 0.01
        dr = 0.15  # 高风险溢价

        reasons += [
            f"困境公司：折现率15%，增长极度保守",
            "主要看资产清算价值（NCAV）",
            "DCF结果仅作参考，高度不确定",
        ]
        return ValuationParams(
            company_type="distressed",
            method_name="资产清算价值优先",
            stage1_years=5, stage2_years=5,
            stage1_growth=g1, stage2_growth=g2,
            terminal_growth=tg, discount_rate=dr,
            use_multiple_method=False,
            iv_haircut=0.30,   # 困境公司额外30%折扣
            params_rationale=reasons,
        )


# ── 核心估值计算 ───────────────────────────────────────────────────────────────

class SingleScenario(BaseModel):
    scenario_name: str
    owner_earnings_used: float
    params: ValuationParams
    projected_cash_flows: List[float]
    terminal_value: float
    total_pv: float
    per_share_value: float
    method_note: str


class ValuationOutput(BaseModel):
    ticker: str
    company_profile: CompanyProfile
    params_used: ValuationParams

    # 三场景
    bull: SingleScenario
    base: SingleScenario
    bear: SingleScenario

    # Graham Number（如果适用）
    graham_number: Optional[float] = None
    ncav_per_share: Optional[float] = None

    # 标准化OE（周期型）
    normalized_oe: Optional[float] = None

    # 最终推荐区间
    iv_low: float          # = bear × (1 - iv_haircut)
    iv_base: float         # = base × (1 - iv_haircut)
    iv_high: float         # = bull × (1 - iv_haircut)
    current_price: float
    margin_of_safety_pct: float

    evidence: List[str]


def run_per_company_valuation(
    ticker: str,
    financial_history,          # FinancialHistory
    market_data,                # MarketAnchorData（可为None）
) -> ValuationOutput:
    """
    主入口：根据公司特征自动选择估值方法。
    """
    stmts = financial_history.statements
    if not stmts or len(stmts) < 2:
        raise RuntimeError(f"财务数据不足，无法估值：{ticker}")

    price = financial_history.current_price
    shares = financial_history.shares_outstanding
    evidence = []

    # ── 1. 计算基础指标 ────────────────────────────────────────────────────────
    rev_cagr = _cagr([s.revenue for s in stmts], years=min(5, len(stmts)-1))
    earn_cagr = _cagr([s.net_income for s in stmts], years=min(5, len(stmts)-1))
    gross_margins = [s.gross_profit / s.revenue for s in stmts if s.revenue > 0]
    gm_avg = sum(gross_margins) / len(gross_margins) if gross_margins else 0
    roes = [s.net_income / s.total_equity for s in stmts if s.total_equity > 0]
    roe_avg = sum(roes) / len(roes) if roes else 0
    latest = stmts[-1]
    de_ratio = latest.total_debt / max(latest.total_equity, 1)
    fcf_pos = sum(1 for s in stmts[-5:] if s.free_cash_flow > 0)
    ni_pos = sum(1 for s in stmts[-5:] if s.net_income > 0)

    # R&D 占比
    rd_vals = [s.research_and_development for s in stmts if s.research_and_development]
    rev_vals = [s.revenue for s in stmts if s.revenue > 0]
    rd_ratio = (sum(rd_vals[-3:]) / 3) / (sum(rev_vals[-3:]) / 3) if rd_vals and rev_vals else 0

    # 营收波动
    revs = [s.revenue for s in stmts if s.revenue > 0]
    rev_cov = _cov(revs) if len(revs) >= 3 else 0

    evidence.append(f"营收CAGR5yr={rev_cagr:.1%}，毛利均值={gm_avg:.1%}，ROE均值={roe_avg:.1%}")
    evidence.append(f"D/E={de_ratio:.2f}，FCF正年数={fcf_pos}/5，R&D占比={rd_ratio:.1%}，营收波动CoV={rev_cov:.2f}")

    # ── 2. 公司分类 ────────────────────────────────────────────────────────────
    profile = classify_company(
        revenue_cagr_5yr=rev_cagr,
        gross_margin_avg=gm_avg,
        roe_avg=roe_avg,
        debt_to_equity=de_ratio,
        fcf_positive_years=fcf_pos,
        rd_to_revenue=rd_ratio,
        revenue_volatility_cov=rev_cov,
        net_income_positive_years=ni_pos,
    )
    evidence.append(f"公司分类：{profile.company_type} — {profile.classification_rationale}")

    # ── 3. 市场数据提取 ────────────────────────────────────────────────────────
    market_pe = None
    analyst_fwd_growth = None
    market_implied_growth = None

    if market_data:
        market_pe = market_data.trailing_pe or market_data.forward_pe
        analyst_fwd_growth = market_data.forward_eps_growth
        # Reverse DCF 反推隐含增长（简化）
        if market_pe and market_pe > 0:
            # implied growth ≈ PE/(PE+1) 粗略，更精确版在 market_anchor.py
            market_implied_growth = min(1 / market_pe * 1.5, 0.30)

    # ── 4. 获取专属估值参数 ────────────────────────────────────────────────────
    params = get_valuation_params(
        profile=profile,
        market_implied_growth=market_implied_growth,
        analyst_forward_growth=analyst_fwd_growth,
        market_pe=market_pe,
    )
    for r in params.params_rationale:
        evidence.append(r)

    # ── 5. 计算 Owner Earnings（或标准化版本） ──────────────────────────────────
    raw_oe, maint_capex, maint_note = _compute_oe(latest)
    evidence.append(f"最新OE={raw_oe/1e9:.2f}B，维护CapEx={maint_capex/1e9:.2f}B（{maint_note}）")

    # 周期型：用标准化OE（多年均值）
    if profile.company_type == "cyclical":
        norm_oe = _normalized_oe(stmts, maint_capex, years=params.normalized_earnings_years)
        base_oe = norm_oe
        evidence.append(f"标准化OE（{params.normalized_earnings_years}年均值）={norm_oe/1e9:.2f}B（替代最新OE）")
    else:
        norm_oe = None
        base_oe = raw_oe

    # ── 6. Graham Number（深度价值型） ────────────────────────────────────────
    graham_number = None
    ncav_ps = None
    if profile.company_type in ("value_deep", "distressed"):
        eps = latest.net_income / shares if shares > 0 else 0
        bvps = latest.total_equity / shares if shares > 0 else 0
        if eps > 0 and bvps > 0:
            graham_number = math.sqrt(22.5 * eps * bvps)
            evidence.append(f"Graham Number = √(22.5 × EPS{eps:.2f} × BVPS{bvps:.2f}) = ${graham_number:.2f}")
        ncav = latest.total_assets - latest.total_liabilities  # 简化版
        ncav_ps = ncav / shares if shares > 0 else 0
        evidence.append(f"NCAV/股 = ${ncav_ps:.2f}（流动资产 - 总负债估算）")

    # ── 7. 三场景估值 ─────────────────────────────────────────────────────────
    bull_scenario = _run_single_scenario(
        name="bull", base_oe=base_oe,
        g1=params.stage1_growth * 1.35,
        g2=params.stage2_growth * 1.35,
        tg=params.terminal_growth + 0.005,
        dr=params.discount_rate * 0.92,
        years1=params.stage1_years, years2=params.stage2_years,
        shares=shares,
        use_multiple=params.use_multiple_method,
        terminal_multiple=params.terminal_fcf_multiple * 1.2,
        margin_compression=0.0,
    )

    base_scenario = _run_single_scenario(
        name="base", base_oe=base_oe,
        g1=params.stage1_growth,
        g2=params.stage2_growth,
        tg=params.terminal_growth,
        dr=params.discount_rate,
        years1=params.stage1_years, years2=params.stage2_years,
        shares=shares,
        use_multiple=params.use_multiple_method,
        terminal_multiple=params.terminal_fcf_multiple,
        margin_compression=0.03,
    )

    bear_scenario = _run_single_scenario(
        name="bear", base_oe=base_oe,
        g1=params.stage1_growth * 0.40,
        g2=params.stage2_growth * 0.30,
        tg=max(params.terminal_growth - 0.01, 0.005),
        dr=params.discount_rate * 1.15,
        years1=params.stage1_years, years2=params.stage2_years,
        shares=shares,
        use_multiple=params.use_multiple_method,
        terminal_multiple=params.terminal_fcf_multiple * 0.6,
        margin_compression=0.15,
    )

    # ── 8. 应用 IV haircut + Graham Number 对比 ────────────────────────────────
    h = params.iv_haircut
    iv_bull = bull_scenario.per_share_value * (1 - h)
    iv_base = base_scenario.per_share_value * (1 - h)
    iv_bear = bear_scenario.per_share_value * (1 - h)

    # 深度价值：取 DCF 和 Graham Number 的更低值（更保守）
    if graham_number and profile.company_type == "value_deep":
        iv_base = min(iv_base, graham_number)
        evidence.append(f"深度价值：取 DCF({base_scenario.per_share_value:.0f}×{1-h}) 和 Graham Number(${graham_number:.0f}) 的较低值 → ${iv_base:.0f}")

    mos = (iv_base - price) / iv_base * 100 if iv_base > 0 else 0
    evidence.append(f"最终估值区间：${iv_bear:.0f}–${iv_base:.0f}–${iv_bull:.0f}，安全边际={mos:.1f}%")

    # ── 9. 组装输出 ────────────────────────────────────────────────────────────
    bull_scenario.params = params
    base_scenario.params = params
    bear_scenario.params = params

    return ValuationOutput(
        ticker=ticker,
        company_profile=profile,
        params_used=params,
        bull=bull_scenario,
        base=base_scenario,
        bear=bear_scenario,
        graham_number=round(graham_number, 2) if graham_number else None,
        ncav_per_share=round(ncav_ps, 2) if ncav_ps else None,
        normalized_oe=round(norm_oe, 2) if norm_oe else None,
        iv_low=round(iv_bear, 2),
        iv_base=round(iv_base, 2),
        iv_high=round(iv_bull, 2),
        current_price=round(price, 2),
        margin_of_safety_pct=round(mos, 2),
        evidence=evidence,
    )


# ── 辅助函数 ───────────────────────────────────────────────────────────────────

def _run_single_scenario(
    name: str,
    base_oe: float,
    g1: float, g2: float, tg: float, dr: float,
    years1: int, years2: int,
    shares: float,
    use_multiple: bool,
    terminal_multiple: float,
    margin_compression: float,
) -> SingleScenario:
    g1 = min(max(g1, -0.05), 0.40)
    g2 = min(max(g2, -0.03), 0.30)

    oe = base_oe * (1 - margin_compression)
    cfs = []
    pv = 0.0
    cur = oe

    # Stage 1
    for t in range(1, years1 + 1):
        cur *= (1 + g1)
        pv += cur / (1 + dr) ** t
        cfs.append(round(cur, 2))

    # Stage 2
    for t in range(1, years2 + 1):
        cur *= (1 + g2)
        tt = years1 + t
        pv += cur / (1 + dr) ** tt
        cfs.append(round(cur, 2))

    # Terminal
    if use_multiple:
        terminal = cur * terminal_multiple
    else:
        terminal = cur * (1 + tg) / max(dr - tg, 0.001)

    total_years = years1 + years2
    pv_terminal = terminal / (1 + dr) ** total_years
    total_pv = pv + pv_terminal
    per_share = total_pv / shares if shares > 0 else 0

    return SingleScenario(
        scenario_name=name,
        owner_earnings_used=round(oe, 2),
        params=ValuationParams(company_type="mature_quality", method_name="temp",
                               stage1_growth=g1, stage2_growth=g2,
                               terminal_growth=tg, discount_rate=dr),
        projected_cash_flows=cfs,
        terminal_value=round(terminal, 2),
        total_pv=round(total_pv, 2),
        per_share_value=round(per_share, 2),
        method_note=f"{'倍数法' if use_multiple else 'Gordon增长'}, DR={dr:.1%}, g1={g1:.1%}, g2={g2:.1%}, TV×{terminal_multiple:.0f}" if use_multiple else f"DR={dr:.1%}, g1={g1:.1%}, g2={g2:.1%}, tg={tg:.1%}",
    )


def _compute_oe(stmt) -> tuple[float, float, str]:
    ni = stmt.net_income
    da = stmt.depreciation_amortization
    capex = abs(stmt.capital_expenditure)
    maint = da * 1.0  # 保守：D&A = 维护CapEx
    wc = getattr(stmt, 'change_in_working_capital', 0) or 0
    oe = max(ni + da - maint - wc, 0)
    return oe, maint, f"D&A法({da/1e6:.0f}M)"


def _normalized_oe(stmts, maint_capex: float, years: int) -> float:
    """周期型公司：用多年均值OE"""
    recent = stmts[-years:] if len(stmts) >= years else stmts
    vals = []
    for s in recent:
        oe = max(s.net_income + s.depreciation_amortization - maint_capex, 0)
        vals.append(oe)
    return sum(vals) / len(vals) if vals else 0


def _cagr(values: list, years: int) -> float:
    if years <= 0 or len(values) < 2:
        return 0.0
    start = values[max(0, len(values)-years-1)]
    end = values[-1]
    if start <= 0 or end <= 0:
        return 0.0
    try:
        return (end / start) ** (1 / years) - 1
    except Exception:
        return 0.0


def _cov(values: list) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance) / abs(mean)


def _dr_from_pe(pe: Optional[float], lo: float, hi: float, default: float) -> float:
    """从市场PE反推折现率，约束在合理区间"""
    if not pe or pe <= 0:
        return default
    implied = 1.0 / pe + 0.025  # earnings yield + terminal growth
    return round(min(max(implied, lo), hi), 4)


def _blend_growth(hist_g: float, analyst_g: Optional[float], weight_analyst: float) -> float:
    """融合历史增长和analyst预期"""
    if analyst_g is None:
        return hist_g
    w_hist = 1.0 - weight_analyst
    return hist_g * w_hist + analyst_g * weight_analyst


def _growth_terminal_multiple(g1: float) -> float:
    """
    成长公司终端倍数：根据增速动态计算
    g1 >= 30%: 35x（超高增长）
    g1 >= 20%: 28x
    g1 >= 15%: 22x
    g1 < 15%: 18x
    """
    if g1 >= 0.30:
        return 35.0
    elif g1 >= 0.20:
        return 28.0
    elif g1 >= 0.15:
        return 22.0
    else:
        return 18.0
