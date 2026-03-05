"""Buffett Analyzer - Configuration"""
import os
from dotenv import load_dotenv

load_dotenv()

# API Keys (from env, overridable via Streamlit sidebar)
FMP_API_KEY = os.getenv("FMP_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Valuation defaults
PROJECTION_YEARS = 10
DISCOUNT_RATE = 0.10
TERMINAL_GROWTH_RATE = 0.04
MAINTENANCE_CAPEX_RATIO = 1.0  # Multiplier on D&A

# Scenario parameters
SCENARIOS = {
    "bull": {
        "growth_multiplier": 0.9,
        "growth_cap": 0.20,
        "discount_rate": 0.09,
        "terminal_growth": 0.04,
        "margin_compression": 0.0,
    },
    "base": {
        "growth_multiplier": 0.6,
        "growth_cap": 0.12,
        "discount_rate": 0.10,
        "terminal_growth": 0.03,
        "margin_compression": 0.05,
    },
    "bear": {
        "growth_multiplier": 0.3,
        "growth_cap": 0.05,
        "discount_rate": 0.12,
        "terminal_growth": 0.02,
        "margin_compression": 0.15,
    },
}

# Industry defaults
DEFAULT_UNIVERSE_SIZE = 20
MIN_MARKET_CAP = 1_000_000_000  # $1B floor
UNIVERSE_SORT = "market_cap"  # or "revenue"

# Hard filter thresholds
MIN_MOAT_SCORE = 70
MIN_FINANCIAL_SCORE = 70
MIN_STABILITY_SCORE = 60
MAX_PRICE_TO_IV_RATIO = 0.85  # Price must be <= 85% of base IV
MAX_BEAR_DOWNSIDE_PCT = 25  # Flag threshold (not elimination)

# Scoring weights
WEIGHTS = {
    "margin_of_safety": 0.30,
    "moat_proxy": 0.25,
    "financial_quality": 0.20,
    "stability": 0.15,
    "circle_of_competence": 0.10,
}

# API settings
FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
FMP_TIMEOUT = 30
FMP_MAX_RETRIES = 3
EDGAR_USER_AGENT = "BuffettAnalyzer/1.0 (research@example.com)"

# LLM settings
LLM_MODEL = "claude-sonnet-4-20250514"
LLM_MAX_TOKENS = 4096
