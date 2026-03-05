"""Claude API wrapper for qualitative analysis."""
from __future__ import annotations
import json
import logging
from anthropic import Anthropic
import config

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


class ClaudeClient:
    """Wrapper around Anthropic Claude API for structured analysis."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or config.ANTHROPIC_API_KEY
        if not self.api_key:
            raise LLMError(
                "ANTHROPIC_API_KEY is required. Set it via environment variable "
                "or enter it in the Streamlit sidebar."
            )
        self.client = Anthropic(api_key=self.api_key)
        self.model = config.LLM_MODEL
        self.max_tokens = config.LLM_MAX_TOKENS

    def analyze(self, system_prompt: str, user_prompt: str) -> dict:
        """Send a prompt to Claude and parse JSON response."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = response.content[0].text

            # Extract JSON from response (handle markdown code blocks)
            text = text.strip()
            if text.startswith("```"):
                # Remove markdown code block
                lines = text.split("\n")
                text = "\n".join(lines[1:])
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            return json.loads(text)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM JSON response: {e}")
            logger.debug(f"Raw response: {text[:500]}")
            # Retry with stricter prompt
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system_prompt + "\n\nCRITICAL: Your response must be ONLY valid JSON. No markdown, no explanation, no code blocks. Start with { and end with }.",
                    messages=[{"role": "user", "content": user_prompt}],
                )
                text = response.content[0].text.strip()
                if text.startswith("```"):
                    lines = text.split("\n")
                    text = "\n".join(lines[1:])
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()
                return json.loads(text)
            except Exception as e2:
                raise LLMError(f"LLM returned unparseable response after retry: {e2}")

        except Exception as e:
            raise LLMError(f"LLM API call failed: {e}")

    def analyze_text(self, system_prompt: str, user_prompt: str) -> str:
        """Send a prompt and return raw text response."""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text
        except Exception as e:
            raise LLMError(f"LLM API call failed: {e}")
