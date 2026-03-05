"""Financial Modeling Prep API client."""
from __future__ import annotations
import time
import logging
import requests
from data.schemas import (
    CompanyProfile, FinancialStatement, FinancialHistory, UniverseCompany,
)
import config

logger = logging.getLogger(__name__)


class FMPError(Exception):
    pass


class FMPClient:
    """Wrapper around Financial Modeling Prep API v3."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or config.FMP_API_KEY
        if not self.api_key:
            raise FMPError(
                "FMP_API_KEY is required. Set it via environment variable "
                "FMP_API_KEY or enter it in the Streamlit sidebar."
            )
        self.base_url = config.FMP_BASE_URL
        self.timeout = config.FMP_TIMEOUT
        self.max_retries = config.FMP_MAX_RETRIES

    def _get(self, endpoint: str, params: dict | None = None) -> list | dict:
        params = params or {}
        params["apikey"] = self.api_key
        url = f"{self.base_url}/{endpoint}"

        for attempt in range(self.max_retries):
            try:
                resp = requests.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 429:
                    wait = 2 ** (attempt + 1)
                    logger.warning(f"FMP rate limit hit, waiting {wait}s (attempt {attempt+1})")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict) and "Error Message" in data:
                    raise FMPError(f"FMP API error: {data['Error Message']}")
                return data
            except requests.exceptions.Timeout:
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise FMPError(f"FMP API timeout after {self.max_retries} attempts for {endpoint}")
            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise FMPError(f"FMP API request failed: {e}")

        raise FMPError(f"FMP API failed after {self.max_retries} retries for {endpoint}")

    def get_profile(self, ticker: str) -> CompanyProfile:
        data = self._get(f"profile/{ticker.upper()}")
        if not data:
            raise FMPError(f"No profile data found for ticker {ticker}")
        p = data[0] if isinstance(data, list) else data
        return CompanyProfile(
            ticker=ticker.upper(),
            name=p.get("companyName", ""),
            sector=p.get("sector", ""),
            industry=p.get("industry", ""),
            market_cap=p.get("mktCap", 0),
            description=p.get("description", ""),
            num_employees=p.get("fullTimeEmployees"),
            exchange=p.get("exchangeShortName", ""),
        )

    def get_income_statements(self, ticker: str, limit: int = 10) -> list[dict]:
        return self._get(f"income-statement/{ticker.upper()}", {"limit": limit, "period": "annual"})

    def get_balance_sheets(self, ticker: str, limit: int = 10) -> list[dict]:
        return self._get(f"balance-sheet-statement/{ticker.upper()}", {"limit": limit, "period": "annual"})

    def get_cash_flow(self, ticker: str, limit: int = 10) -> list[dict]:
        return self._get(f"cash-flow-statement/{ticker.upper()}", {"limit": limit, "period": "annual"})

    def get_quote(self, ticker: str) -> dict:
        data = self._get(f"quote/{ticker.upper()}")
        if not data:
            raise FMPError(f"No quote data found for ticker {ticker}")
        return data[0] if isinstance(data, list) else data

    def get_revenue_segments(self, ticker: str) -> list[dict]:
        """Get revenue by product/segment."""
        try:
            data = self._get(f"revenue-product-segmentation", {
                "symbol": ticker.upper(),
                "structure": "flat",
                "period": "annual",
            })
            return data if data else []
        except FMPError:
            return []

    def get_financial_history(self, ticker: str) -> FinancialHistory:
        """Fetch complete financial history for a ticker."""
        ticker = ticker.upper()
        profile = self.get_profile(ticker)
        income = self.get_income_statements(ticker)
        balance = self.get_balance_sheets(ticker)
        cash_flow = self.get_cash_flow(ticker)
        quote = self.get_quote(ticker)

        # Index balance sheets and cash flows by year for merging
        bs_by_year = {}
        for bs in balance:
            year = int(bs.get("calendarYear", bs.get("date", "0")[:4]))
            bs_by_year[year] = bs

        cf_by_year = {}
        for cf in cash_flow:
            year = int(cf.get("calendarYear", cf.get("date", "0")[:4]))
            cf_by_year[year] = cf

        statements = []
        for inc in income:
            year = int(inc.get("calendarYear", inc.get("date", "0")[:4]))
            bs = bs_by_year.get(year, {})
            cf = cf_by_year.get(year, {})

            capex_raw = cf.get("capitalExpenditure", 0) or 0
            capex = abs(capex_raw)  # Store as positive

            stmt = FinancialStatement(
                fiscal_year=year,
                revenue=inc.get("revenue", 0) or 0,
                cost_of_revenue=inc.get("costOfRevenue", 0) or 0,
                gross_profit=inc.get("grossProfit", 0) or 0,
                operating_income=inc.get("operatingIncome", 0) or 0,
                net_income=inc.get("netIncome", 0) or 0,
                eps=inc.get("eps", 0) or 0,
                shares_outstanding=inc.get("weightedAverageShsOut", 0) or 0,
                total_assets=bs.get("totalAssets", 0) or 0,
                total_liabilities=bs.get("totalLiabilities", 0) or 0,
                total_equity=bs.get("totalStockholdersEquity", 0) or 0,
                long_term_debt=bs.get("longTermDebt", 0) or 0,
                total_debt=bs.get("totalDebt", 0) or 0,
                cash_and_equivalents=bs.get("cashAndCashEquivalents", 0) or 0,
                depreciation_amortization=cf.get("depreciationAndAmortization", 0) or 0,
                capital_expenditure=capex,
                operating_cash_flow=cf.get("operatingCashFlow", 0) or 0,
                free_cash_flow=cf.get("freeCashFlow", 0) or 0,
                dividends_paid=abs(cf.get("dividendsPaid", 0) or 0),
                change_in_working_capital=cf.get("changeInWorkingCapital", 0) or 0,
                research_and_development=inc.get("researchAndDevelopmentExpenses"),
                sga_expense=inc.get("sellingGeneralAndAdministrativeExpenses"),
            )
            statements.append(stmt)

        # Sort oldest to newest
        statements.sort(key=lambda s: s.fiscal_year)

        return FinancialHistory(
            ticker=ticker,
            profile=profile,
            statements=statements,
            current_price=quote.get("price", 0) or 0,
            current_market_cap=quote.get("marketCap", 0) or 0,
            shares_outstanding=quote.get("sharesOutstanding", 0) or 0,
        )

    def screen_by_industry(
        self,
        industry: str,
        sort_by: str = "market_cap",
        limit: int = 20,
        min_market_cap: float = 1_000_000_000,
    ) -> list[UniverseCompany]:
        """Screen for top companies in an industry by market cap or revenue."""
        # FMP stock screener
        params = {
            "industry": industry,
            "marketCapMoreThan": int(min_market_cap),
            "exchange": "NYSE,NASDAQ",
            "limit": 200,  # get plenty, then filter/sort locally
            "isActivelyTrading": True,
        }
        try:
            data = self._get("stock-screener", params)
        except FMPError:
            # Try broader search if exact industry name doesn't match
            params.pop("industry")
            params["sector"] = industry
            data = self._get("stock-screener", params)

        if not data:
            return []

        # Sort
        if sort_by == "revenue":
            data.sort(key=lambda x: x.get("revenue", 0) or 0, reverse=True)
        else:
            data.sort(key=lambda x: x.get("marketCap", 0) or 0, reverse=True)

        results = []
        for i, item in enumerate(data[:limit]):
            mcap = item.get("marketCap", 0) or 0
            results.append(UniverseCompany(
                ticker=item.get("symbol", ""),
                name=item.get("companyName", ""),
                market_cap=mcap,
                revenue_ttm=item.get("revenue"),
                sector=item.get("sector", ""),
                industry=item.get("industry", ""),
                exchange=item.get("exchangeShortName", ""),
                inclusion_rationale=(
                    f"Ranked #{i+1} by {sort_by.replace('_', ' ')} in {industry} "
                    f"(${mcap/1e9:.1f}B market cap)"
                ),
            ))

        return results
