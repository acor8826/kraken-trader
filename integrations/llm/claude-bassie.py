"""
Claude LLM Integration

Implements the ILLM interface for Anthropic's Claude API.
Includes token usage tracking for cost monitoring.
"""

import os
import json
import re
import logging
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone

import anthropic

from core.interfaces import ILLM

logger = logging.getLogger(__name__)


@dataclass
class APIUsageRecord:
    """Record of a single API call with token usage."""
    timestamp: datetime
    call_type: str  # "complete", "complete_json", "analyze_market"
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "call_type": self.call_type,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd
        }


@dataclass
class UsageStats:
    """Aggregated usage statistics."""
    total_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    calls_today: int = 0
    cost_today_usd: float = 0.0
    records: list = field(default_factory=list)
    _today_date: str = ""

    def to_dict(self) -> Dict:
        return {
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "calls_today": self.calls_today,
            "cost_today_usd": round(self.cost_today_usd, 6),
            "recent_records": [r.to_dict() for r in self.records[-20:]]
        }


# Claude Sonnet 4 pricing (as of 2025)
CLAUDE_PRICING = {
    "claude-sonnet-4-20250514": {
        "input_per_1k": 0.003,   # $3 per 1M input tokens
        "output_per_1k": 0.015  # $15 per 1M output tokens
    },
    "claude-3-5-sonnet-20241022": {
        "input_per_1k": 0.003,
        "output_per_1k": 0.015
    },
    "default": {
        "input_per_1k": 0.003,
        "output_per_1k": 0.015
    }
}


class ClaudeLLM(ILLM):
    """
    Claude API integration for the decision engine.
    Tracks token usage and costs for all API calls.
    """

    # Class-level usage stats (shared across instances)
    _usage_stats: UsageStats = None

    def __init__(
        self,
        api_key: str = None,
        model: str = "claude-sonnet-4-20250514"
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model

        # Initialize shared usage stats
        if ClaudeLLM._usage_stats is None:
            ClaudeLLM._usage_stats = UsageStats()

        if self.api_key:
            self.client = anthropic.Anthropic(api_key=self.api_key)
            logger.info(f"Claude LLM initialized with model: {model}")
        else:
            self.client = None
            logger.warning("ANTHROPIC_API_KEY not set - LLM calls will fail")

    def _calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost based on token usage and model pricing."""
        pricing = CLAUDE_PRICING.get(self.model, CLAUDE_PRICING["default"])
        input_cost = (input_tokens / 1000) * pricing["input_per_1k"]
        output_cost = (output_tokens / 1000) * pricing["output_per_1k"]
        return input_cost + output_cost

    def _record_usage(self, call_type: str, input_tokens: int, output_tokens: int) -> APIUsageRecord:
        """Record API usage for tracking."""
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        cost = self._calculate_cost(input_tokens, output_tokens)

        record = APIUsageRecord(
            timestamp=now,
            call_type=call_type,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost
        )

        stats = ClaudeLLM._usage_stats

        # Reset daily counters if new day
        if stats._today_date != today:
            stats._today_date = today
            stats.calls_today = 0
            stats.cost_today_usd = 0.0

        # Update stats
        stats.total_calls += 1
        stats.total_input_tokens += input_tokens
        stats.total_output_tokens += output_tokens
        stats.total_cost_usd += cost
        stats.calls_today += 1
        stats.cost_today_usd += cost
        stats.records.append(record)

        # Keep only last 1000 records
        if len(stats.records) > 1000:
            stats.records = stats.records[-1000:]

        logger.info(f"[API_COST] {call_type}: {input_tokens} in / {output_tokens} out = ${cost:.4f} "
                   f"(today: ${stats.cost_today_usd:.4f})")

        return record

    @classmethod
    def get_usage_stats(cls) -> Dict:
        """Get current usage statistics."""
        if cls._usage_stats is None:
            cls._usage_stats = UsageStats()
        return cls._usage_stats.to_dict()

    @classmethod
    def reset_usage_stats(cls) -> None:
        """Reset usage statistics."""
        cls._usage_stats = UsageStats()
    
    async def complete(self, prompt: str, max_tokens: int = 1000) -> str:
        """Get text completion from Claude"""
        if not self.client:
            raise Exception("Claude API not configured")

        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}]
        )

        # Track token usage
        self._record_usage(
            call_type="complete",
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens
        )

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

        # Track token usage
        self._record_usage(
            call_type="complete_json",
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens
        )

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

        # Track token usage
        self._record_usage(
            call_type="analyze_market",
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens
        )

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
