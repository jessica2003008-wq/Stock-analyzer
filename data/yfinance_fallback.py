"""yfinance fallback for price data."""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def get_current_price(ticker: str) -> float | None:
    """Fallback: get current price via yfinance."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price:
            logger.info(f"yfinance fallback price for {ticker}: ${price}")
            return float(price)
        return None
    except Exception as e:
        logger.warning(f"yfinance fallback failed for {ticker}: {e}")
        return None
