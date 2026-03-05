"""yfinance-based data client — replaces FMP for all financial data."""
from __future__ import annotations
import logging
import yfinance as yf
import pandas as pd
from data.schemas import (
    CompanyProfile, FinancialStatement, FinancialHistory, UniverseCompany,
)

logger = logging.getLogger(__name__)


class YFinanceError(Exception):
    pass


class YFinanceClient:
    """Full data client using yfinance — free, no API key needed."""

    def __init__(self):
        pass  # No API key required

    def get_profile(self, ticker: str) -> CompanyProfile:
        """Fetch company profile via yfinance."""
        ticker = ticker.upper()
        t = yf.Ticker(ticker)
        try:
            info = t.info
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
        """Fetch complete financial history for a ticker using yfinance."""
        ticker = ticker.upper()
        t = yf.Ticker(ticker)

        try:
            info = t.info
        except Exception as e:
            raise YFinanceError(f"Failed to fetch info for {ticker}: {e}")

        if not info or info.get("quoteType") is None:
            raise YFinanceError(f"No data found for ticker {ticker}")

        # Build profile
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

        # Fetch financial statements
        try:
            income_annual = t.financials  # columns = dates, rows = line items
            balance_annual = t.balance_sheet
            cashflow_annual = t.cashflow
        except Exception as e:
            raise YFinanceError(f"Failed to fetch financials for {ticker}: {e}")

        if income_annual is None or income_annual.empty:
            raise YFinanceError(f"No financial statements found for {ticker}")

        statements = []

        # yfinance returns DataFrames with dates as columns (newest first)
        for col in income_annual.columns:
            year = col.year if hasattr(col, 'year') else int(str(col)[:4])

            inc = income_annual[col] if col in income_annual.columns else pd.Series(dtype=float)
            bs = balance_annual[col] if balance_annual is not None and col in balance_annual.columns else pd.Series(dtype=float)
            cf = cashflow_annual[col] if cashflow_annual is not None and col in cashflow_annual.columns else pd.Series(dtype=float)

            def _get(series, *keys, default=0):
                """Try multiple possible key names, return first found."""
                for key in keys:
                    try:
                        val = series.get(key)
                        if val is not None and not pd.isna(val):
                            return float(val)
                    except (KeyError, TypeError):
                        continue
                return default

            revenue = _get(inc, 'Total Revenue', 'Operating Revenue')
            cost_of_revenue = _get(inc, 'Cost Of Revenue')
            gross_profit = _get(inc, 'Gross Profit')
            operating_income = _get(inc, 'Operating Income', 'EBIT')
            net_income = _get(inc, 'Net Income', 'Net Income Common Stockholders')
            eps = _get(inc, 'Basic EPS', 'Diluted EPS')
            shares = _get(inc, 'Basic Average Shares', 'Diluted Average Shares')
            rd = _get(inc, 'Research And Development', 'Research Development')
            sga = _get(inc, 'Selling General And Administration',
                       'Selling And Marketing Expense')

            total_assets = _get(bs, 'Total Assets')
            total_liabilities = _get(bs, 'Total Liabilities Net Minority Interest',
                                     'Total Liab')
            total_equity = _get(bs, 'Stockholders Equity',
                               'Total Stockholder Equity',
                               'Common Stock Equity')
            long_term_debt = _get(bs, 'Long Term Debt', 'Long Term Debt And Capital Lease Obligation')
            total_debt = _get(bs, 'Total Debt', 'Net Debt')
            cash = _get(bs, 'Cash And Cash Equivalents',
                       'Cash Cash Equivalents And Short Term Investments',
                       'Cash')

            dep = _get(cf, 'Depreciation And Amortization',
                      'Depreciation & Amortization')
            capex_raw = _get(cf, 'Capital Expenditure', 'Capital Expenditures')
            capex = abs(capex_raw)
            ocf = _get(cf, 'Operating Cash Flow', 'Cash Flow From Continuing Operating Activities',
                      'Total Cash From Operating Activities')
            fcf = _get(cf, 'Free Cash Flow')
            if fcf == 0 and ocf != 0:
                fcf = ocf - capex

            dividends_raw = _get(cf, 'Common Stock Dividend Paid',
                                'Cash Dividends Paid',
                                'Payment Of Dividends And Other Cash Distributions')
            dividends = abs(dividends_raw)

            wc_change = _get(cf, 'Change In Working Capital',
                            'Changes In Account Receivables')

            # If gross profit not available, compute it
            if gross_profit == 0 and revenue > 0 and cost_of_revenue > 0:
                gross_profit = revenue - cost_of_revenue

            # If shares not available from income, try info
            if shares == 0:
                shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding") or 0

            # If EPS not available, compute it
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

        # Sort oldest to newest
        statements.sort(key=lambda s: s.fiscal_year)

        # Filter out years with no meaningful data (e.g. partial/future years)
        statements = [s for s in statements if s.revenue > 0 or s.net_income != 0]

        # Current price
        current_price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        current_mcap = info.get("marketCap") or 0
        shares_out = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding") or 0

        if current_price == 0:
            # Try fast_info or history as fallback
            try:
                hist = t.history(period="5d")
                if not hist.empty:
                    current_price = float(hist['Close'].iloc[-1])
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
    ) -> list[UniverseCompany]:
        """Screen for companies in an industry using yfinance screener."""
        try:
            # Use yfinance screener
            from yfinance import Screener

            s = Screener()
            # Try to find a matching predefined screen, or use custom query
            # yfinance screener has limited options; we'll use sector-based approach
            results = []

            # Use the most_actives as a broad starting point and filter
            try:
                s.set_predefined_body("most_actives")
                data = s.response
                quotes = data.get("quotes", []) if isinstance(data, dict) else []
            except Exception:
                quotes = []

            # Also try day_gainers and day_losers for broader coverage
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
            unique_quotes = []
            for q in quotes:
                sym = q.get("symbol", "")
                if sym and sym not in seen:
                    seen.add(sym)
                    unique_quotes.append(q)

            # Filter by industry
            industry_lower = industry.lower()
            for q in unique_quotes:
                q_industry = (q.get("industry") or "").lower()
                q_sector = (q.get("sector") or "").lower()
                mcap = q.get("marketCap", 0) or 0

                if mcap < min_market_cap:
                    continue

                if industry_lower in q_industry or industry_lower in q_sector:
                    results.append(q)

            if not results:
                # Fallback: use a curated list of well-known tickers per industry
                results = self._fallback_industry_search(industry, min_market_cap)
                return results[:limit]

            # Sort
            if sort_by == "revenue":
                results.sort(key=lambda x: x.get("revenue", 0) or 0, reverse=True)
            else:
                results.sort(key=lambda x: x.get("marketCap", 0) or 0, reverse=True)

            companies = []
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
                        f"Ranked #{i+1} by {sort_by.replace('_', ' ')} in {industry} "
                        f"(${mcap/1e9:.1f}B market cap)"
                    ),
                ))

            return companies

        except ImportError:
            # Screener not available in this yfinance version
            return self._fallback_industry_search(industry, min_market_cap)[:limit]
        except Exception as e:
            logger.warning(f"Screener failed: {e}, using fallback")
            return self._fallback_industry_search(industry, min_market_cap)[:limit]

    def _fallback_industry_search(
        self,
        industry: str,
        min_market_cap: float = 1_000_000_000,
    ) -> list[UniverseCompany]:
        """Fallback: search for companies using yfinance search + info lookup."""
        try:
            # Use yfinance search
            search_results = yf.Search(industry, max_results=30)
            quotes = search_results.quotes if hasattr(search_results, 'quotes') else []
        except Exception:
            quotes = []

        if not quotes:
            return []

        companies = []
        for q in quotes:
            sym = q.get("symbol", "")
            if not sym or "." in sym:  # Skip non-US tickers
                continue
            try:
                t = yf.Ticker(sym)
                info = t.info
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
