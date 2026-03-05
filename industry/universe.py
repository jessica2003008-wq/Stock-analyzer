"""Industry universe identification."""
from __future__ import annotations
import logging
from data.yfinance_client import YFinanceClient
from data.schemas import UniverseResult

logger = logging.getLogger(__name__)


def build_universe(
    industry: str,
    data_client: YFinanceClient,
    n: int = 20,
    sort_by: str = "market_cap",
    min_market_cap: float = 1_000_000_000,
) -> UniverseResult:
    """Identify top N companies in an industry."""
    logger.info(f"Building universe for {industry}: top {n} by {sort_by}")

    companies = data_client.screen_by_industry(
        industry=industry,
        sort_by=sort_by,
        limit=n,
        min_market_cap=min_market_cap,
    )

    return UniverseResult(
        industry=industry,
        sort_method=sort_by,
        min_market_cap=min_market_cap,
        total_found=len(companies),
        companies=companies,
    )
