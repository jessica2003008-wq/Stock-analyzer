"""yfinance-based data client — replaces FMP for all financial data.

Goals:
- Be resilient against Yahoo/yfinance rate limits (429) via caching + retry + jitter.
- Keep changes small and compatible with your existing schemas and app.
- Make industry screening return something useful even when Yahoo screeners/search are flaky.
"""
from __future__ import annotations

import logging
import time
import random
from typing import Any, Dict, Tuple, List

import pandas as pd
import streamlit as st
import yfinance as yf

from data.schemas import (
    CompanyProfile,
    FinancialStatement,
    FinancialHistory,
    UniverseCompany,
)

logger = logging.getLogger(__name__)


class YFinanceError(Exception):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Rate-limit protection: cache + retry + jitter
# ──────────────────────────────────────────────────────────────────────────────

def _sleep_backoff(attempt: int) -> None:
    """Exponential backoff with jitter."""
    # 0.8s, 1.6s, 3.2s, 6.4s + jitter
    time.sleep((2 ** attempt) * 0.8 + random.uniform(0, 0.4))


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)  # cache 24h per ticker
def _cached_info(ticker: str) -> Dict[str, Any]:
    t = yf.Ticker(ticker)
    return t.info or {}


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)  # cache 24h per ticker
def _cached_history_last_close(ticker: str) -> float:
    t = yf.Ticker(ticker)
    hist = t.history(period="5d")
    if hist is None or hist.empty:
        return 0.0
    return float(hist["Close"].iloc[-1])


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)  # cache 24h per ticker
def _cached_financial_frames(ticker: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    t = yf.Ticker(ticker)
    # These each trigger requests under the hood; caching here saves a lot.
    return t.financials, t.balance_sheet, t.cashflow


def _get_info_with_retry(ticker: str, max_retries: int = 5) -> Dict[str, Any]:
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            info = _cached_info(ticker)
            if info:
                return info
            # Sometimes yfinance returns empty dict transiently.
            last_err = ValueError("Empty info payload")
            _sleep_backoff(attempt)
        except Exception as e:
            last_err = e
            _sleep_backoff(attempt)
    raise YFinanceError(f"Failed to fetch info for {ticker}: {last_err}")


def _get_financials_with_retry(ticker: str, max_retries: int = 5) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            frames = _cached_financial_frames(ticker)
            return frames
        except Exception as e:
            last_err = e
            _sleep_backoff(attempt)
    raise YFinanceError(f"Failed to fetch financials for {ticker}: {last_err}")


# ──────────────────────────────────────────────────────────────────────────────
# Seed universes: ensures industry analysis returns tickers even when
# Yahoo screeners/search are flaky.
# ──────────────────────────────────────────────────────────────────────────────

SEED_INDUSTRIES: Dict[str, List[str]] = {
    "healthcare": [
        "UNH", "ELV", "CVS", "CI", "HUM",
        "JNJ", "PFE", "MRK", "ABBV", "LLY",
        "BMY", "AMGN", "TMO", "DHR", "SYK",
        "MDT", "BSX", "ISRG", "GILD", "REGN",
        "VRTX", "BIIB", "HCA", "UHS", "CNC",
    ],
    "semiconductors": [
        "NVDA", "AMD", "AVGO", "INTC", "TSM",
        "ASML", "TXN", "QCOM", "MU", "AMAT",
        "LRCX", "KLAC",
    ],
    "banks": [
        "JPM", "BAC", "WFC", "C", "GS",
        "MS", "USB", "PNC", "TFC",
    ],
    "software": [
        "MSFT", "ORCL", "ADBE", "CRM", "NOW",
        "SNOW", "DDOG", "INTU", "WDAY",
    ],
}


def _seed_universe(industry: str, limit: int) -> List[UniverseCompany]:
    """Return seed tickers for common industries (no network calls)."""
    key = (industry or "").strip().lower()
    tickers = SEED_INDUSTRIES.get(key, [])
    if not tickers:
        return []
    out: List[UniverseCompany] = []
    for t in tickers[:limit]:
        out.append(UniverseCompany(
            ticker=t,
            name=t,
            market_cap=0,
            revenue_ttm=None,
            sector="",
            industry=industry,
            exchange="",
            inclusion_rationale="Seed universe (fallback)",
        ))
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Client
# ──────────────────────────────────────────────────────────────────────────────

class YFinanceClient:
    """Full data client using yfinance — free, no API key needed."""

    def __init__(self):
        pass

    def get_profile(self, ticker: str) -> CompanyProfile:
        ticker = ticker.upper().strip()
        try:
            info = _get_info_with_retry(ticker)
        except Exception as e:
            raise YFinanceError(f"Failed to fetch info for {ticker}: {e}")

        if not info or info.get("quoteType") is None:
            raise YFinanceError(f"No data found for ticker {ticker}")

        return CompanyProfile(
            ticker=ticker,
            name=info.get("longName") or info.get("shortName") or ticker,
            sector=info.get("sector") or "",
            industry=info.get("industry") or "",
            market_cap=info.get("marketCap") or 0,
            description=info.get("longBusinessSummary") or "",
            num_employees=info.get("fullTimeEmployees"),
            exchange=info.get("exchange") or "",
        )

    def get_financial_history(self, ticker: str) -> FinancialHistory:
        ticker = ticker.upper().strip()

        # Info (cached + retry)
        try:
            info = _get_info_with_retry(ticker)
        except Exception as e:
            raise YFinanceError(f"Failed to fetch info for {ticker}: {e}")

        if not info or info.get("quoteType") is None:
            raise YFinanceError(f"No data found for ticker {ticker}")

        profile = CompanyProfile(
            ticker=ticker,
            name=info.get("longName") or info.get("shortName") or ticker,
            sector=info.get("sector") or "",
            industry=info.get("industry") or "",
            market_cap=info.get("marketCap") or 0,
            description=info.get("longBusinessSummary") or "",
            num_employees=info.get("fullTimeEmployees"),
            exchange=info.get("exchange") or "",
        )

        # Financial statements (cached + retry)
        try:
            income_annual, balance_annual, cashflow_annual = _get_financials_with_retry(ticker)
        except Exception as e:
            raise YFinanceError(f"Failed to fetch financials for {ticker}: {e}")

        if income_annual is None or getattr(income_annual, "empty", True):
            raise YFinanceError(f"No financial statements found for {ticker}")

        statements: List[FinancialStatement] = []

        def _get(series: pd.Series, *keys: str, default: float = 0.0) -> float:
            for key in keys:
                try:
                    val = series.get(key)
                    if val is not None and not pd.isna(val):
                        return float(val)
                except Exception:
                    continue
            return default

        # yfinance returns DataFrames with dates as columns (newest first)
        for col in income_annual.columns:
            year = col.year if hasattr(col, "year") else int(str(col)[:4])

            inc = income_annual[col] if col in income_annual.columns else pd.Series(dtype=float)
            bs = (
                balance_annual[col]
                if balance_annual is not None and hasattr(balance_annual, "columns") and col in balance_annual.columns
                else pd.Series(dtype=float)
            )
            cf = (
                cashflow_annual[col]
                if cashflow_annual is not None and hasattr(cashflow_annual, "columns") and col in cashflow_annual.columns
                else pd.Series(dtype=float)
            )

            revenue = _get(inc, "Total Revenue", "Operating Revenue")
            cost_of_revenue = _get(inc, "Cost Of Revenue")
            gross_profit = _get(inc, "Gross Profit")
            operating_income = _get(inc, "Operating Income", "EBIT")
            net_income = _get(inc, "Net Income", "Net Income Common Stockholders")
            eps = _get(inc, "Basic EPS", "Diluted EPS")
            shares = _get(inc, "Basic Average Shares", "Diluted Average Shares")
            rd = _get(inc, "Research And Development", "Research Development")
            sga = _get(inc, "Selling General And Administration", "Selling And Marketing Expense")

            total_assets = _get(bs, "Total Assets")
            total_liabilities = _get(bs, "Total Liabilities Net Minority Interest", "Total Liab")
            total_equity = _get(bs, "Stockholders Equity", "Total Stockholder Equity", "Common Stock Equity")
            long_term_debt = _get(bs, "Long Term Debt", "Long Term Debt And Capital Lease Obligation")
            total_debt = _get(bs, "Total Debt", "Net Debt")
            cash = _get(bs, "Cash And Cash Equivalents",
                        "Cash Cash Equivalents And Short Term Investments",
                        "Cash")

            dep = _get(cf, "Depreciation And Amortization", "Depreciation & Amortization")
            capex_raw = _get(cf, "Capital Expenditure", "Capital Expenditures")
            capex = abs(capex_raw)
            ocf = _get(cf,
                       "Operating Cash Flow",
                       "Cash Flow From Continuing Operating Activities",
                       "Total Cash From Operating Activities")
            fcf = _get(cf, "Free Cash Flow")
            if fcf == 0 and ocf != 0:
                fcf = ocf - capex

            dividends_raw = _get(cf,
                                 "Common Stock Dividend Paid",
                                 "Cash Dividends Paid",
                                 "Payment Of Dividends And Other Cash Distributions")
            dividends = abs(dividends_raw)

            wc_change = _get(cf, "Change In Working Capital", "Changes In Account Receivables")

            # Compute missing gross profit
            if gross_profit == 0 and revenue > 0 and cost_of_revenue > 0:
                gross_profit = revenue - cost_of_revenue

            # shares fallback
            if shares == 0:
                shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding") or 0

            # EPS fallback
            if eps == 0 and net_income != 0 and shares > 0:
                eps = net_income / shares

            stmt = FinancialStatement(
                fiscal_year=year,
                revenue=revenue,
                cost_of_revenue=cost_of_revenue,
                gross_profit=gross_profit,
                operating_income=operating_income,
                net_income=net_income,
                eps=eps,
                shares_outstanding=shares,
                total_assets=total_assets,
                total_liabilities=total_liabilities,
                total_equity=total_equity,
                long_term_debt=long_term_debt,
                total_debt=total_debt,
                cash_and_equivalents=cash,
                depreciation_amortization=dep,
                capital_expenditure=capex,
                operating_cash_flow=ocf,
                free_cash_flow=fcf,
                dividends_paid=dividends,
                change_in_working_capital=wc_change,
                research_and_development=rd if rd != 0 else None,
                sga_expense=sga if sga != 0 else None,
            )
            statements.append(stmt)

        # Sort oldest to newest and filter out junk years
        statements.sort(key=lambda s: s.fiscal_year)
        statements = [s for s in statements if s.revenue > 0 or s.net_income != 0]

        # Current price
        current_price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        current_mcap = info.get("marketCap") or 0
        shares_out = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding") or 0

        if current_price == 0:
            try:
                current_price = _cached_history_last_close(ticker)
            except Exception:
                pass

        return FinancialHistory(
            ticker=ticker,
            profile=profile,
            statements=statements,
            current_price=current_price,
            current_market_cap=current_mcap,
            shares_outstanding=shares_out,
        )

    def screen_by_industry(
        self,
        industry: str,
        sort_by: str = "market_cap",
        limit: int = 20,
        min_market_cap: float = 1_000_000_000,
    ) -> List[UniverseCompany]:
        """Screen for companies in an industry using yfinance screener.

        If screener fails or returns empty, fallback to:
        1) seed universe (fast, no network)
        2) yfinance search + cached info lookup (network, but cached)
        """
        # 1) seed universe first (fast + reliable) for common labels
        seeded = _seed_universe(industry, limit)
        if seeded:
            return seeded[:limit]

        # 2) try Yahoo screener (best effort)
        try:
            from yfinance import Screener

            s = Screener()
            results: List[Dict[str, Any]] = []

            quotes: List[Dict[str, Any]] = []
            try:
                s.set_predefined_body("most_actives")
                data = s.response
                quotes = data.get("quotes", []) if isinstance(data, dict) else []
            except Exception:
                quotes = []

            for screen_name in ["day_gainers", "day_losers", "most_actives"]:
                try:
                    s2 = Screener()
                    s2.set_predefined_body(screen_name)
                    d = s2.response
                    if isinstance(d, dict):
                        quotes.extend(d.get("quotes", []))
                except Exception:
                    continue

            # Deduplicate
            seen = set()
            unique_quotes: List[Dict[str, Any]] = []
            for q in quotes:
                sym = q.get("symbol", "")
                if sym and sym not in seen:
                    seen.add(sym)
                    unique_quotes.append(q)

            industry_lower = (industry or "").lower()
            for q in unique_quotes:
                q_industry = (q.get("industry") or "").lower()
                q_sector = (q.get("sector") or "").lower()
                mcap = q.get("marketCap", 0) or 0
                if mcap < min_market_cap:
                    continue
                if industry_lower and (industry_lower in q_industry or industry_lower in q_sector):
                    results.append(q)

            if results:
                if sort_by == "revenue":
                    results.sort(key=lambda x: x.get("revenue", 0) or 0, reverse=True)
                else:
                    results.sort(key=lambda x: x.get("marketCap", 0) or 0, reverse=True)

                companies: List[UniverseCompany] = []
                for i, item in enumerate(results[:limit]):
                    mcap = item.get("marketCap", 0) or 0
                    companies.append(UniverseCompany(
                        ticker=item.get("symbol", ""),
                        name=item.get("longName") or item.get("shortName") or "",
                        market_cap=mcap,
                        revenue_ttm=item.get("revenue"),
                        sector=item.get("sector") or "",
                        industry=item.get("industry") or "",
                        exchange=item.get("exchange") or "",
                        inclusion_rationale=(
                            f"Ranked #{i + 1} by {sort_by.replace('_', ' ')} in {industry} "
                            f"(${mcap / 1e9:.1f}B market cap)"
                        ),
                    ))
                return companies

        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Screener failed: {e}")

        # 3) fallback search (cached info; slowest)
        return self._fallback_industry_search(industry, min_market_cap)[:limit]

    def _fallback_industry_search(
        self,
        industry: str,
        min_market_cap: float = 1_000_000_000,
    ) -> List[UniverseCompany]:
        """Fallback: search for companies using yfinance search + cached info lookup."""
        try:
            search_results = yf.Search(industry, max_results=30)
            quotes = search_results.quotes if hasattr(search_results, "quotes") else []
        except Exception:
            quotes = []

        if not quotes:
            return []

        companies: List[UniverseCompany] = []
        for q in quotes:
            sym = (q.get("symbol", "") or "").upper()
            if not sym or "." in sym:  # Skip many non-US tickers
                continue
            try:
                info = _get_info_with_retry(sym)
                mcap = info.get("marketCap") or 0
                if mcap < min_market_cap:
                    continue
                companies.append(UniverseCompany(
                    ticker=sym,
                    name=info.get("longName") or info.get("shortName") or sym,
                    market_cap=mcap,
                    revenue_ttm=info.get("totalRevenue"),
                    sector=info.get("sector") or "",
                    industry=info.get("industry") or "",
                    exchange=info.get("exchange") or "",
                    inclusion_rationale=f"Found via search for '{industry}'",
                ))
            except Exception:
                continue

        companies.sort(key=lambda c: c.market_cap, reverse=True)
        return companies
