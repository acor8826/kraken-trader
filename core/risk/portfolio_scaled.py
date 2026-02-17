"""
Portfolio-Scaled Risk Module

Provides adaptive risk parameters based on portfolio size.
Smaller portfolios can afford more aggressive settings for growth.
Larger portfolios use conservative settings for preservation.
"""

import logging
from typing import Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScaledRiskConfig:
    """Risk configuration that scales with portfolio value."""
    min_confidence: float          # Minimum signal confidence to trade
    max_position_pct: float        # Maximum position size as % of available
    max_total_exposure_pct: float  # Maximum total portfolio exposure
    direction_threshold: float      # Minimum direction strength
    max_daily_trades: int          # Maximum trades per day
    stop_loss_pct: float           # Default stop-loss percentage
    description: str               # Human-readable description

    def to_dict(self) -> Dict:
        return {
            "min_confidence": self.min_confidence,
            "max_position_pct": self.max_position_pct,
            "max_total_exposure_pct": self.max_total_exposure_pct,
            "direction_threshold": self.direction_threshold,
            "max_daily_trades": self.max_daily_trades,
            "stop_loss_pct": self.stop_loss_pct,
            "description": self.description
        }


# Portfolio size tiers with corresponding risk profiles
PORTFOLIO_TIERS = {
    "micro": {
        "max_value": 500,
        "config": ScaledRiskConfig(
            min_confidence=0.45,
            max_position_pct=0.40,
            max_total_exposure_pct=0.95,
            direction_threshold=0.15,
            max_daily_trades=30,
            stop_loss_pct=0.03,
            description="Micro portfolio (<$500): Very aggressive for growth"
        )
    },
    "small": {
        "max_value": 2000,
        "config": ScaledRiskConfig(
            min_confidence=0.55,
            max_position_pct=0.30,
            max_total_exposure_pct=0.90,
            direction_threshold=0.20,
            max_daily_trades=20,
            stop_loss_pct=0.04,
            description="Small portfolio ($500-$2K): Aggressive with some caution"
        )
    },
    "medium": {
        "max_value": 10000,
        "config": ScaledRiskConfig(
            min_confidence=0.65,
            max_position_pct=0.20,
            max_total_exposure_pct=0.85,
            direction_threshold=0.25,
            max_daily_trades=15,
            stop_loss_pct=0.05,
            description="Medium portfolio ($2K-$10K): Balanced risk/reward"
        )
    },
    "large": {
        "max_value": float("inf"),
        "config": ScaledRiskConfig(
            min_confidence=0.70,
            max_position_pct=0.15,
            max_total_exposure_pct=0.80,
            direction_threshold=0.30,
            max_daily_trades=10,
            stop_loss_pct=0.05,
            description="Large portfolio (>$10K): Conservative, capital preservation"
        )
    }
}


def get_tier_for_portfolio(portfolio_value: float) -> str:
    """Determine the tier for a given portfolio value."""
    for tier_name, tier_data in PORTFOLIO_TIERS.items():
        if portfolio_value < tier_data["max_value"]:
            return tier_name
    return "large"


def get_scaled_config(portfolio_value: float) -> ScaledRiskConfig:
    """
    Get risk configuration scaled to portfolio size.

    Smaller portfolios get more aggressive settings to enable growth.
    Larger portfolios get conservative settings to preserve capital.

    Args:
        portfolio_value: Current portfolio value in quote currency (e.g., AUD)

    Returns:
        ScaledRiskConfig appropriate for the portfolio size
    """
    tier = get_tier_for_portfolio(portfolio_value)
    config = PORTFOLIO_TIERS[tier]["config"]

    logger.debug(f"[RISK] Portfolio ${portfolio_value:.2f} -> {tier} tier: "
                f"min_conf={config.min_confidence:.0%}, "
                f"max_pos={config.max_position_pct:.0%}")

    return config


def get_scaled_config_dict(portfolio_value: float) -> Dict:
    """Get risk configuration as a dictionary."""
    config = get_scaled_config(portfolio_value)
    result = config.to_dict()
    result["tier"] = get_tier_for_portfolio(portfolio_value)
    result["portfolio_value"] = portfolio_value
    return result


class PortfolioScaledRisk:
    """
    Risk manager that automatically adjusts parameters based on portfolio size.

    Usage:
        risk = PortfolioScaledRisk(portfolio_value=1500)
        if signal.confidence >= risk.min_confidence:
            # Trade is allowed
    """

    def __init__(self, portfolio_value: float = 1000):
        self._portfolio_value = portfolio_value
        self._config = get_scaled_config(portfolio_value)
        self._tier = get_tier_for_portfolio(portfolio_value)

    def update_portfolio_value(self, value: float) -> None:
        """Update portfolio value and recalculate risk parameters."""
        if value != self._portfolio_value:
            self._portfolio_value = value
            new_tier = get_tier_for_portfolio(value)

            if new_tier != self._tier:
                logger.info(f"[RISK] Portfolio tier changed: {self._tier} -> {new_tier}")
                self._tier = new_tier
                self._config = get_scaled_config(value)

    @property
    def min_confidence(self) -> float:
        """Minimum confidence threshold to execute trades."""
        return self._config.min_confidence

    @property
    def max_position_pct(self) -> float:
        """Maximum position size as percentage of available capital."""
        return self._config.max_position_pct

    @property
    def max_total_exposure_pct(self) -> float:
        """Maximum total portfolio exposure."""
        return self._config.max_total_exposure_pct

    @property
    def direction_threshold(self) -> float:
        """Minimum direction strength to consider a signal actionable."""
        return self._config.direction_threshold

    @property
    def max_daily_trades(self) -> int:
        """Maximum number of trades allowed per day."""
        return self._config.max_daily_trades

    @property
    def stop_loss_pct(self) -> float:
        """Default stop-loss percentage."""
        return self._config.stop_loss_pct

    @property
    def tier(self) -> str:
        """Current portfolio tier."""
        return self._tier

    @property
    def description(self) -> str:
        """Human-readable description of current risk profile."""
        return self._config.description

    def should_trade(
        self,
        confidence: float,
        direction: float
    ) -> bool:
        """
        Check if a signal meets minimum requirements for trading.

        Args:
            confidence: Signal confidence (0-1)
            direction: Signal direction (-1 to +1)

        Returns:
            True if signal meets thresholds
        """
        if confidence < self.min_confidence:
            logger.debug(f"[RISK] Signal rejected: confidence {confidence:.0%} < {self.min_confidence:.0%}")
            return False

        if abs(direction) < self.direction_threshold:
            logger.debug(f"[RISK] Signal rejected: direction {direction:+.2f} < {self.direction_threshold:.2f}")
            return False

        return True

    def calculate_position_size(
        self,
        available: float,
        confidence: float
    ) -> float:
        """
        Calculate position size based on confidence and limits.

        Higher confidence = larger position (up to max_position_pct).

        Args:
            available: Available capital in quote currency
            confidence: Signal confidence (0-1)

        Returns:
            Position size in quote currency
        """
        # Base size is max_position_pct of available
        base_size = available * self.max_position_pct

        # Scale by confidence (50% to 100% of base size)
        # Low confidence = smaller position, high confidence = full position
        confidence_multiplier = 0.5 + (confidence * 0.5)
        position_size = base_size * confidence_multiplier

        logger.debug(f"[RISK] Position size: ${position_size:.2f} "
                    f"(confidence={confidence:.0%}, max={self.max_position_pct:.0%})")

        return position_size

    def get_status(self) -> Dict:
        """Get current risk configuration status."""
        return {
            "portfolio_value": self._portfolio_value,
            "tier": self._tier,
            "config": self._config.to_dict()
        }


# Convenience function for quick access
def get_risk_for_portfolio(portfolio_value: float) -> PortfolioScaledRisk:
    """Create a PortfolioScaledRisk instance for the given portfolio value."""
    return PortfolioScaledRisk(portfolio_value)
