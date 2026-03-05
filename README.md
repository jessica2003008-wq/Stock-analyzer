# Buffett Analyzer

AI-powered investment research platform modeled on Berkshire Hathaway's analytical process.

## Setup

```bash
cd buffett-analyzer
pip install -r requirements.txt
```

## Configuration

Set environment variables:
```bash
export FMP_API_KEY="your_fmp_api_key"
export ANTHROPIC_API_KEY="your_anthropic_api_key"
```

Or enter them in the Streamlit sidebar.

## Run

```bash
streamlit run app.py
```

## Tests

```bash
python -m pytest tests/ -v
```
