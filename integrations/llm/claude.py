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
    
    async def complete(self, prompt: str, max_tokens: int = 1000) -> str:
        """Get text completion from Claude"""
        if not self.client:
            raise Exception("Claude API not configured")

        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )
        self._track_usage(message, "complete")

        return message.content[0].text
    
    async def complete_json(self, prompt: str, max_tokens: int = 1000) -> Dict:
        """
        Get JSON completion from Claude.
        Automatically parses and validates JSON response.
        """
        if not self.client:
            raise Exception("Claude API not configured")
        
        # Add JSON instruction to prompt
        json_prompt = prompt + "\n\nRespond ONLY with valid JSON. No markdown, no explanation, just JSON."
        
        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": json_prompt}]
        )
        self._track_usage(message, "complete_json")

        response_text = message.content[0].text.strip()
        
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
        if not self.client:
            raise Exception("Claude API not configured")
        
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
