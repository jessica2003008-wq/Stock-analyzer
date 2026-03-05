"""SEC EDGAR filing text fetcher."""
from __future__ import annotations
import logging
import requests
from data.schemas import FilingText
import config

logger = logging.getLogger(__name__)


class EdgarError(Exception):
    pass


class EdgarClient:
    """Fetch 10-K/10-Q text from SEC EDGAR."""

    BASE_URL = "https://efts.sec.gov/LATEST/search-index"
    FULL_TEXT_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
    SUBMISSIONS_URL = "https://data.sec.gov/submissions"

    def __init__(self):
        self.headers = {
            "User-Agent": config.EDGAR_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        }

    def _get_cik(self, ticker: str) -> str:
        """Look up CIK for a ticker."""
        url = "https://efts.sec.gov/LATEST/search-index"
        # Use the company tickers JSON
        try:
            resp = requests.get(
                "https://www.sec.gov/files/company_tickers.json",
                headers=self.headers,
                timeout=15,
            )
            resp.raise_for_status()
            tickers = resp.json()
            for entry in tickers.values():
                if entry.get("ticker", "").upper() == ticker.upper():
                    return str(entry["cik_str"]).zfill(10)
        except Exception as e:
            logger.warning(f"Failed to look up CIK for {ticker}: {e}")
        raise EdgarError(f"Could not find CIK for ticker {ticker}")

    def get_latest_10k_text(self, ticker: str) -> FilingText:
        """Fetch the latest 10-K filing and extract key sections."""
        try:
            cik = self._get_cik(ticker)
            # Get recent filings
            url = f"{self.SUBMISSIONS_URL}/CIK{cik}.json"
            resp = requests.get(url, headers=self.headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()

            # Find latest 10-K
            recent = data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            accessions = recent.get("accessionNumber", [])
            primary_docs = recent.get("primaryDocument", [])
            dates = recent.get("filingDate", [])

            for i, form in enumerate(forms):
                if form == "10-K":
                    accession = accessions[i].replace("-", "")
                    primary = primary_docs[i]
                    filing_date = dates[i]

                    # Fetch the primary document
                    doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{accession}/{primary}"
                    doc_resp = requests.get(doc_url, headers=self.headers, timeout=30)
                    doc_resp.raise_for_status()
                    text = doc_resp.text

                    # Extract key sections (simplified — real parsing would use SEC full-text API)
                    sections = self._extract_sections(text)
                    year = int(filing_date[:4])

                    return FilingText(
                        ticker=ticker.upper(),
                        filing_type="10-K",
                        fiscal_year=year,
                        sections=sections,
                    )

            logger.warning(f"No 10-K found for {ticker}")
            return FilingText(ticker=ticker.upper())

        except EdgarError:
            raise
        except Exception as e:
            logger.warning(f"EDGAR fetch failed for {ticker}: {e}")
            return FilingText(ticker=ticker.upper())

    def _extract_sections(self, html_text: str) -> dict[str, str]:
        """Best-effort extraction of key sections from 10-K HTML/text."""
        # This is a simplified extraction — full parsing would use a dedicated HTML parser
        import re

        text = re.sub(r'<[^>]+>', ' ', html_text)  # Strip HTML tags
        text = re.sub(r'\s+', ' ', text)  # Normalize whitespace

        sections = {}

        # Try to find business section (Item 1)
        bus_match = re.search(
            r'(?:Item\s*1[.\s]*(?:Business|BUSINESS))(.*?)(?:Item\s*1A|Item\s*2)',
            text, re.IGNORECASE | re.DOTALL
        )
        if bus_match:
            sections["business"] = bus_match.group(1)[:10000].strip()

        # Risk factors (Item 1A)
        risk_match = re.search(
            r'(?:Item\s*1A[.\s]*(?:Risk\s*Factors|RISK\s*FACTORS))(.*?)(?:Item\s*1B|Item\s*2)',
            text, re.IGNORECASE | re.DOTALL
        )
        if risk_match:
            sections["risk_factors"] = risk_match.group(1)[:10000].strip()

        # MD&A (Item 7)
        mda_match = re.search(
            r'(?:Item\s*7[.\s]*(?:Management|MANAGEMENT))(.*?)(?:Item\s*7A|Item\s*8)',
            text, re.IGNORECASE | re.DOTALL
        )
        if mda_match:
            sections["mda"] = mda_match.group(1)[:10000].strip()

        return sections
