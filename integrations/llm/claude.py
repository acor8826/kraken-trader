"""
Claude LLM Integration

Implements the ILLM interface for Anthropic's Claude API.
"""

import os
import json
import re
import logging
from typing import Dict, Optional

import anthropic
import httpx

from core.interfaces import ILLM

logger = logging.getLogger(__name__)


class ClaudeLLM(ILLM):
    """
    Claude API integration for the decision engine.
    """

    def __init__(
        self,
        api_key: str = None,
        model: str = "claude-sonnet-4-20250514"
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model
        self.codex_api_key = os.getenv("OPENAI_API_KEY", "")
        self.codex_model = os.getenv("OPENAI_MODEL", "gpt-5-codex")

        # Token usage tracking
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_calls = 0

        if self.api_key:
            self.client = anthropic.Anthropic(api_key=self.api_key)
            logger.info(f"Claude LLM initialized with model: {model}")
        else:
            self.client = None
            logger.warning("ANTHROPIC_API_KEY not set - LLM calls will fail")

        if self.codex_api_key:
            logger.info(f"Codex fallback enabled with model: {self.codex_model}")

    def _track_usage(self, message, caller: str = ""):
        """Track token usage from API response."""
        if hasattr(message, 'usage'):
            inp = message.usage.input_tokens
            out = message.usage.output_tokens
            self._total_input_tokens += inp
            self._total_output_tokens += out
            self._total_calls += 1
            logger.info(f"[TOKENS] {caller}: in={inp} out={out} | cumulative: in={self._total_input_tokens} out={self._total_output_tokens} calls={self._total_calls}")

    def get_usage_stats(self) -> Dict:
        """Get cumulative token usage statistics."""
        return {
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_calls": self._total_calls,
            "estimated_cost_usd": round(
                self._total_input_tokens * 3 / 1_000_000 +
                self._total_output_tokens * 15 / 1_000_000, 4
            )
        }

    def _can_use_codex_fallback(self) -> bool:
        return bool(self.codex_api_key)

    def _looks_like_connection_failure(self, error: Exception) -> bool:
        text = str(error).lower()
        markers = [
            "timeout",
            "timed out",
            "connection",
            "dns",
            "network",
            "unreachable",
            "temporarily unavailable",
            "service unavailable",
            "connection reset"
        ]
        return any(marker in text for marker in markers)

    def _extract_openai_text(self, payload: Dict) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        output = payload.get("output", [])
        if isinstance(output, list):
            text_chunks = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") in ("output_text", "text"):
                        t = block.get("text")
                        if isinstance(t, str):
                            text_chunks.append(t)
            if text_chunks:
                return "".join(text_chunks).strip()

        raise ValueError("No text content found in Codex response")

    def _complete_with_codex(self, prompt: str, max_tokens: int = 1000, system_prompt: str = None) -> str:
        if not self.codex_api_key:
            raise Exception("Codex fallback not configured (OPENAI_API_KEY missing)")

        headers = {
            "Authorization": f"Bearer {self.codex_api_key}",
            "Content-Type": "application/json"
        }

        input_payload = prompt
        if system_prompt:
            input_payload = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]

        body = {
            "model": self.codex_model,
            "input": input_payload,
            "max_output_tokens": max_tokens
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post("https://api.openai.com/v1/responses", headers=headers, json=body)
            response.raise_for_status()
            data = response.json()

        return self._extract_openai_text(data)
    
    async def complete(self, prompt: str, max_tokens: int = 1000) -> str:
        """Get text completion from Claude"""
        if self.client:
            try:
                message = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}]
                )
                self._track_usage(message, "complete")
                return message.content[0].text
            except Exception as e:
                if self._can_use_codex_fallback() and self._looks_like_connection_failure(e):
                    logger.warning(f"Claude connection failed, falling back to Codex: {e}")
                    return self._complete_with_codex(prompt, max_tokens=max_tokens)
                raise

        if self._can_use_codex_fallback():
            logger.warning("Claude not configured, falling back to Codex")
            return self._complete_with_codex(prompt, max_tokens=max_tokens)

        raise Exception("Claude API not configured")
    
    async def complete_json(self, prompt: str, max_tokens: int = 1000) -> Dict:
        """
        Get JSON completion from Claude.
        Automatically parses and validates JSON response.
        """
        # Add JSON instruction to prompt
        json_prompt = prompt + "\n\nRespond ONLY with valid JSON. No markdown, no explanation, just JSON."

        if self.client:
            try:
                message = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": json_prompt}]
                )
                self._track_usage(message, "complete_json")
                response_text = message.content[0].text.strip()
            except Exception as e:
                if self._can_use_codex_fallback() and self._looks_like_connection_failure(e):
                    logger.warning(f"Claude connection failed for JSON call, falling back to Codex: {e}")
                    response_text = self._complete_with_codex(json_prompt, max_tokens=max_tokens).strip()
                else:
                    raise
        elif self._can_use_codex_fallback():
            logger.warning("Claude not configured for JSON call, falling back to Codex")
            response_text = self._complete_with_codex(json_prompt, max_tokens=max_tokens).strip()
        else:
            raise Exception("Claude API not configured")
        
        # Try to parse JSON
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            
            logger.error(f"Failed to parse JSON from response: {response_text[:500]}")
            raise ValueError(f"Could not parse JSON from Claude response")
    
    async def analyze_market(
        self,
        prompt: str,
        system_prompt: str = None,
        max_tokens: int = 1000
    ) -> Dict:
        """
        Specialized method for market analysis with optional system prompt.
        """
        if self.client:
            try:
                messages = [{"role": "user", "content": prompt}]

                kwargs = {
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "messages": messages
                }

                if system_prompt:
                    kwargs["system"] = system_prompt

                message = self.client.messages.create(**kwargs)
                self._track_usage(message, "analyze_market")
                response_text = message.content[0].text.strip()
            except Exception as e:
                if self._can_use_codex_fallback() and self._looks_like_connection_failure(e):
                    logger.warning(f"Claude connection failed for market analysis, falling back to Codex: {e}")
                    response_text = self._complete_with_codex(
                        prompt,
                        max_tokens=max_tokens,
                        system_prompt=system_prompt
                    ).strip()
                else:
                    raise
        elif self._can_use_codex_fallback():
            logger.warning("Claude not configured for market analysis, falling back to Codex")
            response_text = self._complete_with_codex(
                prompt,
                max_tokens=max_tokens,
                system_prompt=system_prompt
            ).strip()
        else:
            raise Exception("Claude API not configured")
        
        # Parse JSON (handles both objects and arrays)
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from response (handles markdown code fences, extra text)
            # First, try to find array pattern for batch responses
            if "[" in response_text:
                start = response_text.find("[")
                bracket_count = 0
                for i, char in enumerate(response_text[start:], start):
                    if char == "[":
                        bracket_count += 1
                    elif char == "]":
                        bracket_count -= 1
                        if bracket_count == 0:
                            try:
                                return json.loads(response_text[start:i+1])
                            except json.JSONDecodeError:
                                pass
                            break

            # Fallback to object pattern
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if json_match:
                return json.loads(json_match.group())
            raise ValueError("Could not parse market analysis response")


class MockLLM(ILLM):
    """
    Mock LLM for testing without API calls.
    Returns rule-based decisions.
    """
    
    async def complete(self, prompt: str, max_tokens: int = 1000) -> str:
        return "This is a mock response for testing."
    
    async def complete_json(self, prompt: str, max_tokens: int = 1000) -> Dict:
        # Return a neutral HOLD decision
        return {
            "action": "HOLD",
            "confidence": 0.5,
            "reasoning": "Mock LLM - no real analysis performed"
        }
