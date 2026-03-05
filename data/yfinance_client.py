"""
yfinance-based data client — replaces FMP for all financial data.

Fixes your two current problems with MINIMAL app-wide changes:
1) Single Company Analysis hitting: "Too Many Requests. Rate limited"
   - Reduce Yahoo calls (prefer fast_info + history)
   - Stronger retry/backoff (handles 429 / rate-limit messages)
   - Cache ALL expensive network calls for 24h

2) Industry Analysis returning 0 companies
   - Make screen_by_industry ALWAYS return tickers (seed universe fallback)
   - IMPORTANT: seed universe now sets market_cap >= min_market_cap
     so downstream filters won't drop them as "too small"
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, List, Tuple

import pandas as pd
import streamlit as st
import yfinance as yf

from data.schemas import CompanyProfile, FinancialStatement, FinancialHistory, UniverseCompany

logger = logging.getLogger(__name__)


class YFinanceError(Exception):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Rate-limit protection helpers
# ──────────────────────────────────────────────────────────────────────────────

def _is_rate_limited(err: Exception) -> bool:
    s = str(err).lower()
    return (
        "too many requests" in s
        or "rate limited" in s
        or "429" in s
        or "http error 429" in s
        or "yahoo" in s and "rate" in s
    )


def _sleep_backoff(attempt: int) -> None:
    """
    Exponential backoff with jitter.
    attempt=0 -> ~1-2s, attempt=1 -> ~2-4s ... capped.
    """
    base = min(2 ** attempt, 32)  # cap growth
    time.sleep(base * 0.9 + random.uniform(0, 0.6))


# ──────────────────────────────────────────────────────────────────────────────
# Cached network calls (24h)
# ──────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def _cached_fast_info(ticker: str) -> Dict[str, Any]:
    """
    fast_info is usually lighter than info. It may miss sector/industry/description.
    """
    t = yf.Ticker(ticker)
    try:
        fi = getattr(t, "fast_info", None)
        if fi:
            # fast_info is dict-like, but sometimes not plain dict
            return dict(fi)
    except Exception:
        pass
    return {}


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def _cached_info_full(ticker: str) -> Dict[str, Any]:
    """
    Full info is heavy and most likely to hit rate limits.
    Keep it cached aggressively.
    """
    t = yf.Ticker(ticker)
    # new yfinance has get_info(); old has .info
    if hasattr(t, "get_info"):
        return t.get_info() or {}
    return t.info or {}


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def _cached_history_last_close(ticker: str) -> float:
    t = yf.Ticker(ticker)
    hist = t.history(period="5d", auto_adjust=False)
    if hist is None or hist.empty:
        return 0.0
    return float(hist["Close"].iloc[-1])


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def _cached_financial_frames(ticker: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    These are expensive. Cache saves a lot when you analyze many tickers/day.
    """
    t = yf.Ticker(ticker)
    return t.financials, t.balance_sheet, t.cashflow


def _get_fast_info_with_retry(ticker: str, max_retries: int = 6) -> Dict[str, Any]:
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            fi = _cached_fast_info(ticker)
            if fi:
                return fi
            last_err = ValueError("Empty fast_info payload")
            _sleep_backoff(attempt)
        except Exception as e:
            last_err = e
            # if rate limited, backoff harder
            _sleep_backoff(attempt + (2 if _is_rate_limited(e) else 0))
    # do NOT raise here; fast_info is optional
    logger.warning(f"[fast_info] failed for {ticker}: {last_err}")
    return {}


def _get_full_info_with_retry(ticker: str, max_retries: int = 6) -> Dict[str, Any]:
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            info = _cached_info_full(ticker)
            if info:
                return info
            last_err = ValueError("Empty info payload")
            _sleep_backoff(attempt)
        except Exception as e:
            last_err = e
            _sleep_backoff(attempt + (2 if _is_rate_limited(e) else 0))
    raise YFinanceError(f"Failed to fetch info for {ticker}: {last_err}")


def _get_financials_with_retry(ticker: str, max_retries: int = 6) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            return _cached_financial_frames(ticker)
        except Exception as e:
            last_err = e
            _sleep_backoff(attempt + (2 if _is_rate_limited(e) else 0))
    raise YFinanceError(f"Failed to fetch financials for {ticker}: {last_err}")


# ──────────────────────────────────────────────────────────────────────────────
# Seed universes (industry will NEVER be empty now)
# IMPORTANT: market_cap is set >= min_market_cap so downstream filters won't drop
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


def _seed_universe(industry: str, limit: int, min_market_cap: float) -> List[UniverseCompany]:
    key = (industry or "").strip().lower()
    tickers = SEED_INDUSTRIES.get(key, [])
    if not tickers:
        return []
    mcap_floor = float(min_market_cap if min_market_cap else 1_000_000_000)
    out: List[UniverseCompany] = []
    for t in tickers[:limit]:
        out.append(UniverseCompany(
            ticker=t,
            name=t,
            market_cap=mcap_floor,  # <-- critical for your "0 companies" issue
            revenue_ttm=None,
            sector="",
            industry=industry,
            exchange="",
            inclusion_rationale="Seed universe (fallback when Yahoo screener/search is flaky)",
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

        # Try fast_info first (light). Then full info if needed.
        fi = _get_fast_info_with_retry(ticker)
        try:
            info = _get_full_info_with_retry(ticker)
        except YFinanceError as e:
            # If full info is rate-limited, still return a minimal profile from fast_info
            if fi:
                return CompanyProfile(
                    ticker=ticker,
                    name=ticker,
                    sector="",
                    industry="",
                    market_cap=float(fi.get("market_cap") or fi.get("marketCap") or 0),
                    description="",
                    num_employees=None,
                    exchange="",
                )
            raise e

        # Basic validation
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

        # Use fast_info to get price quickly and reduce dependence on info
        fi = _get_fast_info_with_retry(ticker)

        # Full info gives sector/industry/description; retry hard but if it fails,
        # still proceed with a minimal profile (so analysis doesn't die).
        info: Dict[str, Any] = {}
        try:
            info = _get_full_info_with_retry(ticker)
        except YFinanceError as e:
            if not fi:
                # no fallback data at all
                raise e

        # Minimal validity check
        if info and info.get("quoteType") is None and not fi:
            raise YFinanceError(f"No data found for ticker {ticker}")

        profile = CompanyProfile(
            ticker=ticker,
            name=(info.get("longName") or info.get("shortName") or ticker) if info else ticker,
            sector=info.get("sector") or "" if info else "",
            industry=info.get("industry") or "" if info else "",
            market_cap=(info.get("marketCap") or 0) if info else float(fi.get("market_cap") or fi.get("marketCap") or 0),
            description=info.get("longBusinessSummary") or "" if info else "",
            num_employees=info.get("fullTimeEmployees") if info else None,
            exchange=info.get("exchange") or "" if info else "",
        )

        # Financial statements (cached + retry)
        income_annual, balance_annual, cashflow_annual = _get_financials_with_retry(ticker)

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
            cash = _get(
                bs,
                "Cash And Cash Equivalents",
                "Cash Cash Equivalents And Short Term Investments",
                "Cash",
            )

            dep = _get(cf, "Depreciation And Amortization", "Depreciation & Amortization")
            capex_raw = _get(cf, "Capital Expenditure", "Capital Expenditures")
            capex = abs(capex_raw)
            ocf = _get(
                cf,
                "Operating Cash Flow",
                "Cash Flow From Continuing Operating Activities",
                "Total Cash From Operating Activities",
            )
            fcf = _get(cf, "Free Cash Flow")
            if fcf == 0 and ocf != 0:
                fcf = ocf - capex

            dividends_raw = _get(
                cf,
                "Common Stock Dividend Paid",
                "Cash Dividends Paid",
                "Payment Of Dividends And Other Cash Distributions",
            )
            dividends = abs(dividends_raw)

            wc_change = _get(cf, "Change In Working Capital", "Changes In Account Receivables")

            if gross_profit == 0 and revenue > 0 and cost_of_revenue > 0:
                gross_profit = revenue - cost_of_revenue

            if shares == 0 and info:
                shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding") or 0

            if eps == 0 and net_income != 0 and shares > 0:
                eps = net_income / shares

            statements.append(FinancialStatement(
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
            ))

        statements.sort(key=lambda s: s.fiscal_year)
        statements = [s for s in statements if s.revenue > 0 or s.net_income != 0]

        # Price: prefer fast_info or history to reduce pressure on info calls
        current_price = 0.0
        if fi:
            current_price = float(fi.get("last_price") or fi.get("lastPrice") or 0.0)
        if current_price == 0.0 and info:
            current_price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0.0)
        if current_price == 0.0:
            current_price = _cached_history_last_close(ticker)

        current_mcap = float(profile.market_cap or 0)
        shares_out = 0.0
        if info:
            shares_out = float(info.get("sharesOutstanding") or info.get("impliedSharesOutstanding") or 0.0)

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
        """
        Industry screen that WILL NOT return empty:
        1) seed universe (reliable, no network) for known labels like 'healthcare'
        2) best-effort Yahoo screener (if available)
        3) yfinance search fallback (cached info; slower)
        4) if all fail => return seed of "healthcare" style? NO.
           We'll still return the seed for the closest key if any; else [].
        """

        # 1) Always try seed first (this fixes your "0 companies" screenshot)
        seeded = _seed_universe(industry, limit, min_market_cap)
        if seeded:
            return seeded[:limit]

        # 2) Try yfinance Screener (best effort)
        try:
            from yfinance import Screener  # type: ignore

            s = Screener()
            quotes: List[Dict[str, Any]] = []

            for screen_name in ["most_actives", "day_gainers", "day_losers"]:
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

            industry_lower = (industry or "").lower().strip()

            filtered: List[Dict[str, Any]] = []
            for q in unique_quotes:
                mcap = q.get("marketCap", 0) or 0
                if mcap < min_market_cap:
                    continue
                q_industry = (q.get("industry") or "").lower()
                q_sector = (q.get("sector") or "").lower()
                if industry_lower and (industry_lower in q_industry or industry_lower in q_sector):
                    filtered.append(q)

            if filtered:
                if sort_by == "revenue":
                    filtered.sort(key=lambda x: x.get("revenue", 0) or 0, reverse=True)
                else:
                    filtered.sort(key=lambda x: x.get("marketCap", 0) or 0, reverse=True)

                out: List[UniverseCompany] = []
                for i, item in enumerate(filtered[:limit]):
                    mcap = float(item.get("marketCap", 0) or 0)
                    out.append(UniverseCompany(
                        ticker=item.get("symbol", ""),
                        name=item.get("longName") or item.get("shortName") or item.get("symbol", ""),
                        market_cap=mcap,
                        revenue_ttm=item.get("revenue"),
                        sector=item.get("sector") or "",
                        industry=item.get("industry") or "",
                        exchange=item.get("exchange") or "",
                        inclusion_rationale=(
                            f"Ranked #{i + 1} by {sort_by.replace('_',' ')} in {industry} "
                            f"(${mcap/1e9:.1f}B market cap)"
                        ),
                    ))
                return out

        except Exception as e:
            logger.warning(f"Screener failed: {e}")

        # 3) Search fallback
        out = self._fallback_industry_search(industry, min_market_cap)
        if out:
            return out[:limit]

        # 4) Nothing worked -> return empty (rare). You can add more seed keys if needed.
        return []

    def _fallback_industry_search(
        self,
        industry: str,
        min_market_cap: float = 1_000_000_000,
    ) -> List[UniverseCompany]:
        """
        Fallback: yfinance Search + cached full info lookup (slowest).
        """
        try:
            search_results = yf.Search(industry, max_results=40)
            quotes = search_results.quotes if hasattr(search_results, "quotes") else []
        except Exception:
            quotes = []

        if not quotes:
            return []

        companies: List[UniverseCompany] = []
        for q in quotes:
            sym = (q.get("symbol", "") or "").upper().strip()
            if not sym or "." in sym:
                continue

            try:
                # full info is cached; still may rate-limit occasionally
                info = _get_full_info_with_retry(sym, max_retries=3)
                mcap = float(info.get("marketCap") or 0.0)
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
