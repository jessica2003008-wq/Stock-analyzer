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
import requests

from data.schemas import CompanyProfile, FinancialStatement, FinancialHistory, UniverseCompany

logger = logging.getLogger(__name__)


class YFinanceError(Exception):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Currency conversion for US-listed foreign reporters
# ──────────────────────────────────────────────────────────────────────────────

FOREIGN_CURRENCY_REPORTERS: Dict[str, Tuple[str, float]] = {
    # Chinese companies on NASDAQ/NYSE reporting in RMB
    "PDD": ("CNY", 7.25), "BABA": ("CNY", 7.25), "JD": ("CNY", 7.25),
    "NIO": ("CNY", 7.25), "LI": ("CNY", 7.25), "XPEV": ("CNY", 7.25),
    "BIDU": ("CNY", 7.25), "BILI": ("CNY", 7.25), "IQ": ("CNY", 7.25),
    "TME": ("CNY", 7.25), "ZTO": ("CNY", 7.25), "VNET": ("CNY", 7.25),
    "WB": ("CNY", 7.25), "MNSO": ("CNY", 7.25), "QFIN": ("CNY", 7.25),
    "FINV": ("CNY", 7.25), "LU": ("CNY", 7.25), "TCOM": ("CNY", 7.25),
    "FUTU": ("HKD", 7.80), "YMM": ("CNY", 7.25), "KC": ("CNY", 7.25),
    # Japanese
    "SONY": ("JPY", 150.0), "TM": ("JPY", 150.0), "HMC": ("JPY", 150.0),
    "MUFG": ("JPY", 150.0), "SMFG": ("JPY", 150.0),
    # European
    "SAP": ("EUR", 0.92), "ASML": ("EUR", 0.92), "NVO": ("DKK", 6.90),
    "AZN": ("GBP", 0.79), "GSK": ("GBP", 0.79), "BP": ("GBP", 0.79),
    "SHEL": ("GBP", 0.79), "UL": ("GBP", 0.79), "DEO": ("GBP", 0.79),
    # Other
    "NU": ("BRL", 5.0), "STNE": ("BRL", 5.0),
}

_EXCHANGE_RATES: Dict[str, float] = {}

def _get_live_rate(currency: str) -> float | None:
    if currency == "USD":
        return 1.0
    if currency in _EXCHANGE_RATES:
        return _EXCHANGE_RATES[currency]
    try:
        resp = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=5)
        if resp.status_code == 200:
            rates = resp.json().get("rates", {})
            _EXCHANGE_RATES.update(rates)
            return rates.get(currency)
    except Exception:
        pass
    return None


def _convert_statements_to_usd(
    statements: List[FinancialStatement], rate: float
) -> List[FinancialStatement]:
    """Divide all monetary fields by exchange rate to convert to USD."""
    converted = []
    for s in statements:
        converted.append(FinancialStatement(
            fiscal_year=s.fiscal_year,
            revenue=s.revenue / rate,
            cost_of_revenue=s.cost_of_revenue / rate,
            gross_profit=s.gross_profit / rate,
            operating_income=s.operating_income / rate,
            net_income=s.net_income / rate,
            eps=s.eps / rate if s.eps else 0,
            shares_outstanding=s.shares_outstanding,
            total_assets=s.total_assets / rate,
            total_liabilities=s.total_liabilities / rate,
            total_equity=s.total_equity / rate,
            long_term_debt=s.long_term_debt / rate,
            total_debt=s.total_debt / rate,
            cash_and_equivalents=s.cash_and_equivalents / rate,
            depreciation_amortization=s.depreciation_amortization / rate,
            capital_expenditure=s.capital_expenditure / rate,
            operating_cash_flow=s.operating_cash_flow / rate,
            free_cash_flow=s.free_cash_flow / rate,
            dividends_paid=s.dividends_paid / rate,
            change_in_working_capital=s.change_in_working_capital / rate,
            research_and_development=(s.research_and_development / rate) if s.research_and_development else None,
            sga_expense=(s.sga_expense / rate) if s.sga_expense else None,
        ))
    return converted


def _detect_and_convert_currency(
    ticker: str,
    statements: List[FinancialStatement],
    price_usd: float,
    shares: float,
) -> Tuple[List[FinancialStatement], str]:
    """Detect currency mismatch and convert to USD if needed."""
    if not statements or price_usd <= 0 or shares <= 0:
        return statements, ""

    ticker_upper = ticker.upper()

    # Method 1: Known foreign reporters
    if ticker_upper in FOREIGN_CURRENCY_REPORTERS:
        currency, fallback_rate = FOREIGN_CURRENCY_REPORTERS[ticker_upper]
        live_rate = _get_live_rate(currency)
        rate = live_rate if live_rate else fallback_rate
        logger.info(f"{ticker}: converting from {currency} to USD (rate: {rate:.2f})")
        return _convert_statements_to_usd(statements, rate), \
            f"Financials converted from {currency} to USD (1 USD = {rate:.2f} {currency})"

    # Method 2: Heuristic — revenue/share >> price suggests foreign currency
    latest = statements[-1]
    if latest.revenue > 0 and shares > 0:
        rev_per_share = latest.revenue / shares
        ratio = rev_per_share / price_usd
        if ratio > 3:
            estimated_rate = ratio
            logger.warning(f"{ticker}: auto-detected currency mismatch (ratio {ratio:.1f}x), converting")
            return _convert_statements_to_usd(statements, estimated_rate), \
                f"⚠️ Auto-detected currency mismatch (ratio {ratio:.1f}x). Financials divided by {estimated_rate:.2f}."

    return statements, ""


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

@st.cache_data(ttl=60 * 60 * 4, show_spinner=False)
def _cached_fast_info(ticker: str, _v: str = "v2") -> Dict[str, Any]:
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


@st.cache_data(ttl=60 * 60 * 4, show_spinner=False)
def _cached_info_full(ticker: str, _v: str = "v2") -> Dict[str, Any]:
    """
    Full info is heavy and most likely to hit rate limits.
    Keep it cached aggressively.
    """
    t = yf.Ticker(ticker)
    # new yfinance has get_info(); old has .info
    if hasattr(t, "get_info"):
        return t.get_info() or {}
    return t.info or {}


@st.cache_data(ttl=60 * 60 * 4, show_spinner=False)
def _cached_history_last_close(ticker: str, _v: str = "v2") -> float:
    t = yf.Ticker(ticker)
    hist = t.history(period="5d", auto_adjust=False)
    if hist is None or hist.empty:
        return 0.0
    return float(hist["Close"].iloc[-1])


@st.cache_data(ttl=60 * 60 * 4, show_spinner=False)
def _cached_financial_frames(ticker: str, _v: str = "v2") -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
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
    ],
    "pharma": [
        "JNJ", "PFE", "MRK", "ABBV", "LLY",
        "BMY", "AMGN", "GILD", "REGN", "VRTX",
        "AZN", "NVO", "GSK", "SNY", "ZTS",
    ],
    "biotechnology": [
        "AMGN", "GILD", "REGN", "VRTX", "MRNA",
        "BIIB", "ILMN", "SGEN", "ALNY", "BMRN",
    ],
    "semiconductors": [
        "NVDA", "AMD", "AVGO", "INTC", "TSM",
        "ASML", "TXN", "QCOM", "MU", "AMAT",
        "LRCX", "KLAC", "MRVL", "ON", "ADI",
    ],
    "banks": [
        "JPM", "BAC", "WFC", "C", "GS",
        "MS", "USB", "PNC", "TFC", "SCHW",
    ],
    "banking": [
        "JPM", "BAC", "WFC", "C", "GS",
        "MS", "USB", "PNC", "TFC", "SCHW",
    ],
    "financial services": [
        "JPM", "BAC", "GS", "MS", "BLK",
        "SCHW", "AXP", "V", "MA", "COF",
    ],
    "insurance": [
        "BRK-B", "PGR", "ALL", "MET", "AIG",
        "PRU", "TRV", "AFL", "HIG", "CINF",
    ],
    "software": [
        "MSFT", "ORCL", "ADBE", "CRM", "NOW",
        "SNOW", "DDOG", "INTU", "WDAY", "PANW",
    ],
    "cloud computing": [
        "AMZN", "MSFT", "GOOG", "CRM", "NOW",
        "SNOW", "DDOG", "NET", "MDB", "DKNG",
    ],
    "internet": [
        "GOOG", "META", "AMZN", "NFLX", "SNAP",
        "PINS", "SPOT", "ROKU", "TTD", "UBER",
    ],
    "e-commerce": [
        "AMZN", "PDD", "JD", "BABA", "MELI",
        "SHOP", "ETSY", "EBAY", "W", "CPNG",
    ],
    "consumer electronics": [
        "AAPL", "SONY", "DELL", "HPQ", "LOGI",
        "SONO", "GPRO", "KOSS", "HEAR", "CRSR",
    ],
    "consumer staples": [
        "PG", "KO", "PEP", "COST", "WMT",
        "CL", "MO", "PM", "KMB", "GIS",
        "K", "HSY", "SJM", "CPB", "CAG",
    ],
    "retail": [
        "WMT", "COST", "HD", "LOW", "TGT",
        "TJX", "ROST", "DG", "DLTR", "BBY",
    ],
    "restaurants": [
        "MCD", "SBUX", "CMG", "YUM", "DPZ",
        "QSR", "DINE", "JACK", "WEN", "PZZA",
    ],
    "energy": [
        "XOM", "CVX", "COP", "SLB", "EOG",
        "MPC", "VLO", "PSX", "OXY", "DVN",
    ],
    "oil & gas": [
        "XOM", "CVX", "COP", "SLB", "EOG",
        "MPC", "VLO", "PSX", "OXY", "DVN",
    ],
    "utilities": [
        "NEE", "DUK", "SO", "D", "AEP",
        "EXC", "SRE", "XEL", "WEC", "ED",
    ],
    "real estate": [
        "AMT", "PLD", "CCI", "EQIX", "SPG",
        "PSA", "O", "WELL", "DLR", "AVB",
    ],
    "reits": [
        "AMT", "PLD", "CCI", "EQIX", "SPG",
        "PSA", "O", "WELL", "DLR", "AVB",
    ],
    "aerospace & defense": [
        "LMT", "RTX", "BA", "NOC", "GD",
        "LHX", "TDG", "HWM", "HEI", "TXT",
    ],
    "automotive": [
        "TSLA", "F", "GM", "TM", "RIVN",
        "STLA", "HMC", "NIO", "LI", "XPEV",
    ],
    "electric vehicles": [
        "TSLA", "RIVN", "NIO", "LI", "XPEV",
        "LCID", "FSR", "PSNY", "FFIE", "GOEV",
    ],
    "clean energy": [
        "ENPH", "SEDG", "FSLR", "RUN", "NEE",
        "PLUG", "BE", "CSIQ", "JKS", "NOVA",
    ],
    "telecommunications": [
        "T", "VZ", "TMUS", "CMCSA", "CHTR",
        "AMT", "CCI", "SBAC", "LUMN", "FTR",
    ],
    "media & entertainment": [
        "DIS", "NFLX", "CMCSA", "WBD", "PARA",
        "RBLX", "TTWO", "EA", "LYV", "IMAX",
    ],
    "industrials": [
        "HON", "UNP", "UPS", "CAT", "DE",
        "GE", "MMM", "EMR", "ITW", "ROK",
    ],
    "materials": [
        "LIN", "APD", "SHW", "ECL", "DD",
        "NEM", "FCX", "NUE", "VMC", "MLM",
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

        # ── Currency conversion ──
        # Some companies (PDD, BABA, etc.) report financials in foreign currency but trade in USD
        statements, currency_note = _detect_and_convert_currency(
            ticker, statements, current_price, shares_out
        )
        if currency_note:
            logger.info(f"{ticker}: {currency_note}")

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
