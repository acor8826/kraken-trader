"""
Configuration System

Centralized configuration with feature flags for staged rollout.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
import yaml
import logging

logger = logging.getLogger(__name__)


class Stage(Enum):
    """Deployment stages"""
    STAGE_1_MVP = "stage1"
    STAGE_2_ENHANCED = "stage2"
    STAGE_3_FULL = "stage3"


@dataclass
class TradingConfig:
    """Trading parameters"""
    pairs: List[str] = field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    quote_currency: str = "USDT"
    initial_capital: float = 1000.0
    target_capital: float = 5000.0
    check_interval_minutes: int = 60


@dataclass
class RiskConfig:
    """Risk management parameters"""
    max_position_pct: float = 0.20       # Max 20% per position
    max_total_exposure_pct: float = 0.80  # Max 80% total exposure
    stop_loss_pct: float = 0.025         # 2.5% stop loss
    take_profit_multiplier: float = 2.0  # Take profit at stop_loss * multiplier
    min_confidence: float = 0.55         # Min confidence to trade
    max_daily_trades: int = 10
    max_daily_loss_pct: float = 0.10     # Pause if down 10% in a day


@dataclass
class FeatureFlags:
    """Feature flags for staged rollout"""
    # Analysts
    enable_technical_analyst: bool = True
    enable_sentiment_analyst: bool = False
    enable_onchain_analyst: bool = False
    enable_macro_analyst: bool = False
    enable_orderbook_analyst: bool = False
    
    # Intelligence
    enable_intel_fusion: bool = False    # Stage 2+
    enable_regime_detection: bool = False  # Stage 3
    
    # Execution
    enable_limit_orders: bool = False    # Stage 2+
    enable_smart_routing: bool = False   # Stage 3
    
    # Risk
    enable_circuit_breakers: bool = False  # Stage 2+
    enable_anomaly_detection: bool = False  # Stage 3
    
    # Memory
    enable_postgres: bool = False        # Stage 2+
    enable_learning: bool = False        # Stage 3
    
    # Other
    enable_event_bus: bool = False       # Stage 2+
    simulation_mode: bool = False        # Paper trading
    enable_meme_trading: bool = False  # Meme coin trading module
    
    @classmethod
    def for_stage(cls, stage: Stage) -> "FeatureFlags":
        """Get feature flags for a specific stage"""
        if stage == Stage.STAGE_1_MVP:
            return cls(
                enable_technical_analyst=True,
                simulation_mode=os.getenv("SIMULATION_MODE", "false").lower() == "true"
            )
        elif stage == Stage.STAGE_2_ENHANCED:
            return cls(
                enable_technical_analyst=True,
                enable_sentiment_analyst=True,
                enable_intel_fusion=True,
                enable_limit_orders=True,
                enable_circuit_breakers=True,
                enable_postgres=True,
                enable_event_bus=True,
                simulation_mode=os.getenv("SIMULATION_MODE", "false").lower() == "true"
            )
        else:  # STAGE_3_FULL
            return cls(
                enable_technical_analyst=True,
                enable_sentiment_analyst=True,
                enable_onchain_analyst=True,
                enable_macro_analyst=True,
                enable_orderbook_analyst=True,
                enable_intel_fusion=True,
                enable_regime_detection=True,
                enable_limit_orders=True,
                enable_smart_routing=True,
                enable_circuit_breakers=True,
                enable_anomaly_detection=True,
                enable_postgres=True,
                enable_learning=True,
                enable_event_bus=True,
                simulation_mode=os.getenv("SIMULATION_MODE", "false").lower() == "true"
            )


@dataclass
class ExchangeConfig:
    """Exchange configuration"""
    name: str = "binance"
    api_key: str = ""
    api_secret: str = ""

    @classmethod
    def from_env(cls) -> "ExchangeConfig":
        exchange_name = os.getenv("EXCHANGE", "binance")
        if exchange_name == "kraken":
            return cls(
                name="kraken",
                api_key=os.getenv("KRAKEN_API_KEY", ""),
                api_secret=os.getenv("KRAKEN_API_SECRET", "")
            )
        else:
            testnet = os.getenv("BINANCE_TESTNET", "").lower() in ("1", "true", "yes")
            if testnet:
                api_key = os.getenv("BINANCE_TESTNET_KEY") or os.getenv("BINANCE_API_KEY", "")
                api_secret = os.getenv("BINANCE_TESTNET_SECRET") or os.getenv("BINANCE_API_SECRET", "")
            else:
                api_key = os.getenv("BINANCE_API_KEY", "")
                api_secret = os.getenv("BINANCE_API_SECRET", "")
            return cls(
                name="binance",
                api_key=api_key,
                api_secret=api_secret
            )


@dataclass
class LLMConfig:
    """LLM configuration"""
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    validation_model: str = "claude-haiku-3-5-20241022"
    api_key: str = ""
    max_tokens: int = 1000

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            api_key=os.getenv("ANTHROPIC_API_KEY", "")
        )


@dataclass
class HybridThresholds:
    """Thresholds for hybrid strategist (rules vs Claude)"""
    direction_clear: float = 0.4       # |direction| > this = clear signal
    confidence_clear: float = 0.60     # confidence > this = clear signal
    disagreement_max: float = 0.3      # disagreement < this = clear signal


@dataclass
class AdaptiveTier:
    """Portfolio tier for adaptive scheduling"""
    max_value: float
    interval_minutes: int


@dataclass
class CostOptimizationConfig:
    """
    Cost optimization settings.

    Reduces API costs through:
    - Batch analysis (multiple pairs in one call)
    - Hybrid mode (rules for clear signals)
    - Adaptive scheduling (less frequent for small portfolios)
    - Decision caching (reuse decisions if market stable)
    """
    # Feature toggles
    enable_batch_analysis: bool = True
    enable_hybrid_mode: bool = True
    enable_adaptive_schedule: bool = True
    enable_decision_cache: bool = True  # Falls back to in-memory if no Redis

    # Hybrid mode settings
    hybrid: HybridThresholds = field(default_factory=HybridThresholds)

    # Adaptive scheduling tiers
    tiers: Dict[str, AdaptiveTier] = field(default_factory=lambda: {
        "micro": AdaptiveTier(max_value=500, interval_minutes=120),    # 2 hours
        "small": AdaptiveTier(max_value=2000, interval_minutes=60),    # 1 hour
        "medium": AdaptiveTier(max_value=10000, interval_minutes=30),  # 30 min
        "large": AdaptiveTier(max_value=float('inf'), interval_minutes=15)  # 15 min
    })

    # Decision caching
    cache_ttl_seconds: int = 1800       # 30 min default
    cache_price_deviation: float = 0.02  # Invalidate if price moves > 2%

    # Batch settings
    max_pairs_per_batch: int = 10


@dataclass
class AlertConfig:
    """
    Alert configuration settings.

    Supports multiple channels: console, file, webhook (Discord/Slack).
    """
    enabled: bool = True
    console_enabled: bool = True
    file_enabled: bool = True
    file_path: str = "alerts.log"
    file_max_size_mb: int = 10

    # Webhook configuration (Discord/Slack)
    webhook_enabled: bool = False
    webhook_url: str = ""
    webhook_platform: str = "discord"  # "discord" or "slack"

    # Alert retention
    max_history: int = 1000

    @classmethod
    def from_env(cls) -> "AlertConfig":
        """Load alert config from environment variables"""
        return cls(
            enabled=os.getenv("ALERTS_ENABLED", "true").lower() == "true",
            console_enabled=os.getenv("ALERTS_CONSOLE", "true").lower() == "true",
            file_enabled=os.getenv("ALERTS_FILE", "true").lower() == "true",
            file_path=os.getenv("ALERTS_FILE_PATH", "alerts.log"),
            webhook_enabled=os.getenv("ALERTS_WEBHOOK_ENABLED", "false").lower() == "true",
            webhook_url=os.getenv("ALERTS_WEBHOOK_URL", ""),
            webhook_platform=os.getenv("ALERTS_WEBHOOK_PLATFORM", "discord"),
        )


@dataclass
class TrailingStopConfig:
    """Trailing stop configuration"""
    activation_pct: float = 0.01    # Activate when 1% in profit
    distance_pct: float = 0.007     # Trail 0.7% below peak


@dataclass
class BreakevenConfig:
    """Breakeven stop configuration"""
    activation_pct: float = 0.005   # Move to BE at +0.5% gain
    buffer_pct: float = 0.001       # 0.1% buffer above entry for fees


@dataclass
class ExitManagementConfig:
    """Exit management settings for trailing stop, breakeven, etc."""
    enable_trailing_stop: bool = True
    enable_breakeven_stop: bool = True
    trailing_stop: TrailingStopConfig = field(default_factory=TrailingStopConfig)
    breakeven: BreakevenConfig = field(default_factory=BreakevenConfig)


@dataclass
class AggressiveRiskConfig:
    """
    Aggressive risk parameters for small portfolios seeking higher returns.

    WARNING: Higher risk of drawdown. Use with caution.
    """
    max_position_pct: float = 0.35       # 35% per position (vs 20% default)
    max_total_exposure_pct: float = 0.95  # 95% total exposure (vs 80%)
    stop_loss_pct: float = 0.015         # 1.5% stop loss (vs 2.5% standard)
    take_profit_multiplier: float = 2.0  # Keep 1:2 risk-reward by default
    min_confidence: float = 0.50         # 50% min confidence (vs 70%)
    max_daily_trades: int = 30           # 30 trades (vs 10)
    max_daily_loss_pct: float = 0.15     # 15% daily loss limit (vs 10%)

    # Per-pair stop losses (volatility-adjusted)
    pair_stop_losses: Dict[str, float] = field(default_factory=lambda: {
        "BTC/USDT": 0.015,  # 1.5% - lower volatility
        "ETH/USDT": 0.02,   # 2%
        "SOL/USDT": 0.025,  # 2.5% - higher volatility
        "DOGE/USDT": 0.03,  # 3% - very volatile
        "AVAX/USDT": 0.025, # 2.5%
        "ARB/USDT": 0.03,   # 3%
    })

    def get_stop_loss_for_pair(self, pair: str) -> float:
        """Get volatility-adjusted stop loss for a specific pair."""
        return self.pair_stop_losses.get(pair, self.stop_loss_pct)


@dataclass
class Settings:
    """
    Master settings object.
    Combines all configuration into one place.
    """
    stage: Stage = Stage.STAGE_1_MVP
    trading: TradingConfig = field(default_factory=TradingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    features: FeatureFlags = field(default_factory=FeatureFlags)
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)

    # Cost optimization settings
    cost_optimization: CostOptimizationConfig = field(default_factory=CostOptimizationConfig)

    # Alert configuration
    alerts: AlertConfig = field(default_factory=AlertConfig)

    # Exit management (trailing stop, breakeven stop)
    exit_management: ExitManagementConfig = field(default_factory=ExitManagementConfig)

    # Aggressive risk profile (optional, overrides risk when enabled)
    aggressive_risk: Optional[AggressiveRiskConfig] = None

    # Risk profile selector
    risk_profile: str = "standard"  # "standard" or "aggressive"

    # Adaptive risk management
    enable_adaptive_risk: bool = False
    adaptive_risk_config: Optional[Dict[str, Any]] = None

    # Logging
    log_level: str = "INFO"

    def get_effective_risk(self) -> RiskConfig:
        """Get the effective risk config based on profile."""
        if self.risk_profile == "aggressive" and self.aggressive_risk:
            # Convert AggressiveRiskConfig to RiskConfig
            return RiskConfig(
                max_position_pct=self.aggressive_risk.max_position_pct,
                max_total_exposure_pct=self.aggressive_risk.max_total_exposure_pct,
                stop_loss_pct=self.aggressive_risk.stop_loss_pct,
                take_profit_multiplier=self.aggressive_risk.take_profit_multiplier,
                min_confidence=self.aggressive_risk.min_confidence,
                max_daily_trades=self.aggressive_risk.max_daily_trades,
                max_daily_loss_pct=self.aggressive_risk.max_daily_loss_pct
            )
        return self.risk
    
    @classmethod
    def load(cls, stage: Stage = None) -> "Settings":
        """Load settings for a stage"""
        stage = stage or Stage(os.getenv("STAGE", "stage1"))
        risk_profile = os.getenv("RISK_PROFILE", "standard").lower()

        # Build aggressive risk config if profile is aggressive
        aggressive_risk = None
        if risk_profile == "aggressive":
            aggressive_risk = AggressiveRiskConfig()
            logger.info("Loaded AGGRESSIVE risk profile")

        return cls(
            stage=stage,
            trading=TradingConfig(),
            risk=RiskConfig(),
            features=FeatureFlags.for_stage(stage),
            exchange=ExchangeConfig.from_env(),
            llm=LLMConfig.from_env(),
            cost_optimization=CostOptimizationConfig(),
            alerts=AlertConfig.from_env(),
            aggressive_risk=aggressive_risk,
            risk_profile=risk_profile,
            enable_adaptive_risk=os.getenv("ENABLE_ADAPTIVE_RISK", "false").lower() == "true",
            log_level=os.getenv("LOG_LEVEL", "INFO")
        )
    
    @classmethod
    def from_yaml(cls, path: str) -> "Settings":
        """Load settings from YAML file"""
        with open(path) as f:
            data = yaml.safe_load(f)

        stage = Stage(data.get("stage", "stage1"))
        risk_profile = data.get("risk_profile", os.getenv("RISK_PROFILE", "standard")).lower()

        # Parse cost optimization if present
        cost_opt_data = data.get("cost_optimization", {})
        cost_optimization = CostOptimizationConfig(
            enable_batch_analysis=cost_opt_data.get("enable_batch_analysis", True),
            enable_hybrid_mode=cost_opt_data.get("enable_hybrid_mode", True),
            enable_adaptive_schedule=cost_opt_data.get("enable_adaptive_schedule", True),
            enable_decision_cache=cost_opt_data.get("enable_decision_cache", False),
            cache_ttl_seconds=cost_opt_data.get("cache_ttl_seconds", 1800),
            cache_price_deviation=cost_opt_data.get("cache_price_deviation", 0.02),
        )

        # Parse hybrid thresholds if present
        if "hybrid" in cost_opt_data:
            hybrid_data = cost_opt_data["hybrid"]
            cost_optimization.hybrid = HybridThresholds(
                direction_clear=hybrid_data.get("direction_threshold", 0.6),
                confidence_clear=hybrid_data.get("confidence_threshold", 0.75),
                disagreement_max=hybrid_data.get("disagreement_threshold", 0.2),
            )

        # Parse aggressive risk if profile is aggressive
        aggressive_risk = None
        if risk_profile == "aggressive":
            agg_data = data.get("aggressive_risk", {})
            # Use AggressiveRiskConfig dataclass defaults as fallbacks
            _agg_defaults = AggressiveRiskConfig()
            aggressive_risk = AggressiveRiskConfig(
                max_position_pct=agg_data.get("max_position_pct", _agg_defaults.max_position_pct),
                max_total_exposure_pct=agg_data.get("max_total_exposure_pct", _agg_defaults.max_total_exposure_pct),
                stop_loss_pct=agg_data.get("stop_loss_pct", _agg_defaults.stop_loss_pct),
                take_profit_multiplier=agg_data.get("take_profit_multiplier", _agg_defaults.take_profit_multiplier),
                min_confidence=agg_data.get("min_confidence", _agg_defaults.min_confidence),
                max_daily_trades=agg_data.get("max_daily_trades", _agg_defaults.max_daily_trades),
                max_daily_loss_pct=agg_data.get("max_daily_loss_pct", _agg_defaults.max_daily_loss_pct),
            )
            logger.info("Loaded AGGRESSIVE risk profile from YAML")

        # Parse alerts config if present
        alerts_data = data.get("alerts", {})
        alerts = AlertConfig(
            enabled=alerts_data.get("enabled", True),
            console_enabled=alerts_data.get("console_enabled", True),
            file_enabled=alerts_data.get("file_enabled", True),
            file_path=alerts_data.get("file_path", "alerts.log"),
            file_max_size_mb=alerts_data.get("file_max_size_mb", 10),
            webhook_enabled=alerts_data.get("webhook_enabled", False),
            webhook_url=os.getenv("ALERTS_WEBHOOK_URL", alerts_data.get("webhook_url", "")),
            webhook_platform=alerts_data.get("webhook_platform", "discord"),
            max_history=alerts_data.get("max_history", 1000),
        )

        # Parse exit management config
        exit_data = data.get("exit_management", {})
        trailing_data = exit_data.get("trailing_stop", {})
        breakeven_data = exit_data.get("breakeven", {})
        exit_management = ExitManagementConfig(
            enable_trailing_stop=exit_data.get("enable_trailing_stop", True),
            enable_breakeven_stop=exit_data.get("enable_breakeven_stop", True),
            trailing_stop=TrailingStopConfig(
                activation_pct=trailing_data.get("activation_pct", 0.01),
                distance_pct=trailing_data.get("distance_pct", 0.007),
            ),
            breakeven=BreakevenConfig(
                activation_pct=breakeven_data.get("activation_pct", 0.005),
                buffer_pct=breakeven_data.get("buffer_pct", 0.001),
            ),
        )

        # Parse adaptive risk config
        adaptive_data = data.get("adaptive_risk", {})
        enable_adaptive = adaptive_data.get("enabled", False) or os.getenv("ENABLE_ADAPTIVE_RISK", "false").lower() == "true"

        return cls(
            stage=stage,
            trading=TradingConfig(**data.get("trading", {})),
            risk=RiskConfig(**data.get("risk", {})),
            features=FeatureFlags(**data.get("features", {})),
            exchange=ExchangeConfig.from_env(),  # Always from env for security
            llm=LLMConfig.from_env(),
            cost_optimization=cost_optimization,
            alerts=alerts,
            exit_management=exit_management,
            aggressive_risk=aggressive_risk,
            risk_profile=risk_profile,
            enable_adaptive_risk=enable_adaptive,
            adaptive_risk_config=adaptive_data if adaptive_data else None,
            log_level=data.get("log_level", "INFO")
        )


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create global settings"""
    global _settings
    if _settings is None:
        _settings = Settings.load()
    return _settings


def init_settings(stage: Stage = None, config_path: str = None) -> Settings:
    """Initialize settings from stage or config file"""
    global _settings
    if config_path:
        _settings = Settings.from_yaml(config_path)
    else:
        # Auto-discover YAML config based on stage
        stage = stage or Stage(os.getenv("STAGE", "stage1"))
        yaml_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "config",
            f"{stage.value}.yaml"
        )
        if os.path.exists(yaml_path):
            logger.info(f"Loading config from {yaml_path}")
            _settings = Settings.from_yaml(yaml_path)
        else:
            logger.info(f"No YAML config found at {yaml_path}, using defaults")
            _settings = Settings.load(stage)
    return _settings
