"""Unit tests for data clients (mocked — no API calls)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock
from data.fmp_client import FMPClient, FMPError
from data.schemas import CompanyProfile


class TestFMPClient:
    def test_missing_api_key_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            import config
            old_key = config.FMP_API_KEY
            config.FMP_API_KEY = ""
            try:
                with pytest.raises(FMPError, match="FMP_API_KEY is required"):
                    FMPClient(api_key="")
            finally:
                config.FMP_API_KEY = old_key

    def test_get_profile_no_data(self):
        client = FMPClient(api_key="test_key")
        with patch.object(client, '_get', return_value=[]):
            with pytest.raises(FMPError, match="No profile data"):
                client.get_profile("INVALID")

    def test_get_profile_success(self):
        client = FMPClient(api_key="test_key")
        mock_data = [{
            "companyName": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "mktCap": 3000000000000,
            "description": "Apple designs iPhones.",
            "fullTimeEmployees": 164000,
            "exchangeShortName": "NASDAQ",
        }]
        with patch.object(client, '_get', return_value=mock_data):
            profile = client.get_profile("AAPL")
            assert profile.ticker == "AAPL"
            assert profile.name == "Apple Inc."
            assert profile.market_cap == 3000000000000

    def test_get_financial_history_success(self):
        client = FMPClient(api_key="test_key")

        profile_data = [{
            "companyName": "Test", "sector": "Tech", "industry": "Software",
            "mktCap": 1e9, "description": "Test co", "exchangeShortName": "NYSE",
        }]
        income_data = [{
            "calendarYear": "2024", "revenue": 1000000, "netIncome": 150000,
            "grossProfit": 400000, "operatingIncome": 200000,
            "costOfRevenue": 600000, "eps": 1.5,
            "weightedAverageShsOut": 100000,
        }]
        balance_data = [{
            "calendarYear": "2024", "totalAssets": 2000000,
            "totalLiabilities": 800000, "totalStockholdersEquity": 1200000,
            "longTermDebt": 300000, "totalDebt": 400000,
            "cashAndCashEquivalents": 100000,
        }]
        cf_data = [{
            "calendarYear": "2024", "operatingCashFlow": 200000,
            "capitalExpenditure": -70000, "freeCashFlow": 130000,
            "depreciationAndAmortization": 50000, "dividendsPaid": -30000,
            "changeInWorkingCapital": -10000,
        }]
        quote_data = [{"price": 50, "marketCap": 5000000, "sharesOutstanding": 100000}]

        def mock_get(endpoint, params=None):
            if "profile" in endpoint:
                return profile_data
            elif "income" in endpoint:
                return income_data
            elif "balance" in endpoint:
                return balance_data
            elif "cash-flow" in endpoint:
                return cf_data
            elif "quote" in endpoint:
                return quote_data
            return []

        with patch.object(client, '_get', side_effect=mock_get):
            history = client.get_financial_history("TEST")
            assert history.ticker == "TEST"
            assert len(history.statements) == 1
            assert history.statements[0].revenue == 1000000
            assert history.current_price == 50

    def test_screen_by_industry(self):
        client = FMPClient(api_key="test_key")
        mock_data = [
            {"symbol": "NVDA", "companyName": "NVIDIA", "marketCap": 3e12,
             "sector": "Technology", "industry": "Semiconductors",
             "exchangeShortName": "NASDAQ"},
            {"symbol": "AMD", "companyName": "AMD", "marketCap": 2e11,
             "sector": "Technology", "industry": "Semiconductors",
             "exchangeShortName": "NASDAQ"},
        ]
        with patch.object(client, '_get', return_value=mock_data):
            results = client.screen_by_industry("Semiconductors", limit=5)
            assert len(results) == 2
            assert results[0].ticker == "NVDA"
            assert results[0].market_cap > results[1].market_cap
