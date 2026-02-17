"""
Fed Policy Watcher

Monitors Federal Reserve monetary policy to assess risk appetite:
- Fed Funds Rate changes
- Yield curve inversions
- Rate cut/hike expectations

Rate cuts = risk-on = bullish for crypto
Rate hikes = risk-off = bearish for crypto
Inverted yield curve = recession signal = risk-off
"""

import logging
from typing import Dict, Optional
from dataclasses import dataclass

from integrations.data.fred import FREDClient

logger = logging.getLogger(__name__)


@dataclass
class FedPolicySignal:
    """Signal from Fed policy analysis"""
    direction: float  # -1 (risk-off/hawkish) to +1 (risk-on/dovish)
    confidence: float  # 0 to 1
    policy_stance: str  # "hawkish", "dovish", "neutral"
    yield_curve_status: str  # "normal", "flat", "inverted"
    rate_direction: str  # "easing", "tightening", "stable"
    reasoning: str


class FedWatcher:
    """
    Monitors Federal Reserve monetary policy for trading signals.

    Fed policy signals:
    - Rate cuts / dovish stance = risk-on = bullish
    - Rate hikes / hawkish stance = risk-off = bearish
    - Yield curve inversion = recession warning = risk-off
    """

    def __init__(self, fred_client: FREDClient):
        """
        Initialize Fed policy watcher.

        Args:
            fred_client: FRED API client for economic data
        """
        self.fred = fred_client
        logger.info("FedWatcher initialized")

    async def analyze(self) -> FedPolicySignal:
        """
        Analyze current Fed policy stance.

        Returns:
            FedPolicySignal with direction, confidence, and reasoning
        """
        # Fetch Fed data
        fed_funds = await self.fred.get_fed_funds_rate()
        yield_curve = await self.fred.get_yield_curve_spread()

        # If no data available, return neutral
        if not fed_funds and not yield_curve:
            return FedPolicySignal(
                direction=0.0,
                confidence=0.0,
                policy_stance="unknown",
                yield_curve_status="unknown",
                rate_direction="unknown",
                reasoning="No Fed policy data available"
            )

        direction = 0.0
        confidence = 0.0
        reasons = []

        # Analyze Fed Funds Rate direction
        rate_direction = "stable"
        if fed_funds:
            rate_direction = fed_funds.get("direction", "stable")
            rate_change = fed_funds.get("change_1m", 0)

            # Rate cuts are bullish for risk assets
            if rate_direction == "easing":
                direction += 0.5  # Bullish
                reasons.append(f"Fed easing: rates down {abs(rate_change):.2f}%")
            elif rate_direction == "tightening":
                direction -= 0.5  # Bearish
                reasons.append(f"Fed tightening: rates up {rate_change:.2f}%")
            else:
                reasons.append(f"Rates stable at {fed_funds.get('rate', 'N/A')}%")

            confidence += 0.4

        # Analyze yield curve
        yield_curve_status = "unknown"
        if yield_curve:
            spread = yield_curve.get("spread", 0)
            is_inverted = yield_curve.get("is_inverted", False)
            yield_curve_status = yield_curve.get("signal", "normal")

            if is_inverted:
                # Inverted curve = recession signal = risk-off
                direction -= 0.4
                if spread < -0.5:
                    reasons.append(f"Yield curve deeply inverted ({spread:+.2f}%): recession warning")
                else:
                    reasons.append(f"Yield curve inverted ({spread:+.2f}%): caution")
            elif spread < 0.3:
                # Flat curve = slowing growth
                direction -= 0.1
                reasons.append(f"Yield curve flat ({spread:+.2f}%): slowing growth")
            else:
                # Normal curve = healthy expansion
                direction += 0.2
                reasons.append(f"Yield curve normal ({spread:+.2f}%): healthy")

            confidence += 0.4

        # Determine overall policy stance
        if direction > 0.3:
            policy_stance = "dovish"
        elif direction < -0.3:
            policy_stance = "hawkish"
        else:
            policy_stance = "neutral"

        # Clamp values
        direction = max(-1.0, min(1.0, direction))
        confidence = min(1.0, confidence)

        return FedPolicySignal(
            direction=round(direction, 4),
            confidence=round(confidence, 4),
            policy_stance=policy_stance,
            yield_curve_status=yield_curve_status,
            rate_direction=rate_direction,
            reasoning="; ".join(reasons) if reasons else "Fed policy neutral"
        )

    async def get_rate_summary(self) -> Dict:
        """Get summary of current Fed rates and policy"""
        fed_funds = await self.fred.get_fed_funds_rate()
        yield_curve = await self.fred.get_yield_curve_spread()

        return {
            "fed_funds_rate": fed_funds.get("rate") if fed_funds else None,
            "rate_direction": fed_funds.get("direction") if fed_funds else None,
            "yield_curve_spread": yield_curve.get("spread") if yield_curve else None,
            "yield_curve_status": yield_curve.get("signal") if yield_curve else None,
            "is_inverted": yield_curve.get("is_inverted") if yield_curve else None,
            "yield_2y": yield_curve.get("yield_2y") if yield_curve else None,
            "yield_10y": yield_curve.get("yield_10y") if yield_curve else None
        }
