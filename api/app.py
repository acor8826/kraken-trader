"""
FastAPI Application

HTTP interface for the trading agent.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
import logging
import os
import time

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pathlib import Path

from core.config import Settings, init_settings, Stage

logger = logging.getLogger(__name__)

# Global components (initialized on startup)
orchestrator = None
scheduler = None
settings = None
alert_manager = None
seed_improver = None
dgm_service = None
autoresearch_service = None

# Portfolio cache (avoid hammering Binance on every dashboard poll)
_portfolio_cache = None
_portfolio_cache_ts = 0.0
_PORTFOLIO_CACHE_TTL = 30  # seconds


async def _get_cached_portfolio() -> dict | None:
    """Return cached portfolio dict, refreshing from exchange if stale.

    Returns None when orchestrator is not initialised and no cache exists.
    """
    global _portfolio_cache, _portfolio_cache_ts

    now = time.time()
    if _portfolio_cache is not None and (now - _portfolio_cache_ts) < _PORTFOLIO_CACHE_TTL:
        return _portfolio_cache

    if not orchestrator:
        return _portfolio_cache  # may be None

    try:
        portfolio = await orchestrator._get_portfolio_state()
        _portfolio_cache = portfolio.to_dict()
        _portfolio_cache_ts = now
        return _portfolio_cache
    except Exception as e:
        logger.warning("Portfolio fetch failed, returning stale cache: %s", e)
        return _portfolio_cache  # may be None


def create_app(stage: Stage = None) -> FastAPI:
    """
    Application factory.
    Creates and configures the FastAPI app.
    """
    global settings
    settings = init_settings(stage)
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Startup and shutdown events"""
        global orchestrator, scheduler
        
        # Startup
        logger.info(f"Starting Trading Agent (Stage: {settings.stage.value})")
        logger.info(f"Target: ${settings.trading.initial_capital} → ${settings.trading.target_capital}")
        logger.info(f"Pairs: {settings.trading.pairs}")
        
        # Initialize components
        orchestrator = await _create_orchestrator(settings)

        # Run pending database migrations (idempotent, uses IF NOT EXISTS)
        await _run_migrations_on_startup()

        # Start scheduler
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            _run_trading_cycle,
            'interval',
            minutes=settings.trading.check_interval_minutes,
            id='trading_cycle',
            next_run_time=datetime.now(timezone.utc)  # Run immediately
        )
        # Meme trading scheduler (if enabled)
        if hasattr(orchestrator, '_meme_orchestrator') and orchestrator._meme_orchestrator:
            meme_config = orchestrator._meme_orchestrator.config
            scheduler.add_job(
                _run_meme_cycle,
                'interval',
                seconds=meme_config.cycle_interval_seconds,
                id='meme_trading_cycle',
                next_run_time=datetime.now(timezone.utc)
            )
            logger.info(f"Meme scheduler started: every {meme_config.cycle_interval_seconds}s")

        # Daily profit snapshot: 5:30 PM AEST — captures portfolio value for daily P&L
        scheduler.add_job(
            _run_daily_profit_snapshot,
            'cron',
            hour=17,
            minute=30,
            timezone='Australia/Sydney',
            id='daily_profit_snapshot',
            replace_existing=True,
        )

        # Seed improver + daily profit review: 5:45 PM Australia/Sydney
        # Runs after snapshot so it can evaluate today's P&L and optimise
        scheduler.add_job(
            _run_seed_improver_daily,
            'cron',
            hour=17,
            minute=45,
            timezone='Australia/Sydney',
            id='seed_improver_daily',
            replace_existing=True,
        )

        # Meme bot daily review: 6:15 PM Australia/Sydney
        scheduler.add_job(
            _run_meme_daily_review,
            'cron',
            hour=18,
            minute=15,
            timezone='Australia/Sydney',
            id='meme_daily_review',
            replace_existing=True,
        )

        # Autoresearch code improvement: 6:30 PM Australia/Sydney
        scheduler.add_job(
            _run_autoresearch_daily,
            'cron',
            hour=18,
            minute=30,
            timezone='Australia/Sydney',
            id='autoresearch_daily',
            replace_existing=True,
        )

        # Autoresearch next-day evaluation: 10:00 AM Australia/Sydney
        scheduler.add_job(
            _evaluate_autoresearch_experiments,
            'cron',
            hour=10,
            minute=0,
            timezone='Australia/Sydney',
            id='autoresearch_evaluation',
            replace_existing=True,
        )

        scheduler.start()

        logger.info(f"Scheduler started: every {settings.trading.check_interval_minutes} minutes")
        
        yield
        
        # Shutdown
        if scheduler:
            scheduler.shutdown()
        logger.info("Trading agent stopped")
    
    app = FastAPI(
        title="Crypto Trading Agent",
        description="Claude-powered autonomous crypto trading",
        version="1.0.0",
        lifespan=lifespan
    )

    # Add CORS middleware for dashboard
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    _register_routes(app)
    
    return app


async def _create_orchestrator(settings: Settings):
    """Create and wire up all components"""
    from integrations.exchanges import KrakenExchange, MockExchange, BinanceExchange, create_exchange
    from integrations.llm import ClaudeLLM, MockLLM
    from agents.analysts.technical import TechnicalAnalyst
    from agents.strategist import SimpleStrategist, RuleBasedStrategist
    from agents.strategist.cost_optimized import CostOptimizedStrategist
    from agents.sentinel import BasicSentinel
    from agents.executor import SimpleExecutor
    from agents.orchestrator import Orchestrator, Phase3Orchestrator
    from memory import InMemoryStore

    # Exchange
    if settings.features.simulation_mode:
        # Try enhanced simulation first
        try:
            from integrations.exchanges.simulation import SimulationExchange, SimulationConfig, MarketScenario
            import os

            # Get scenario from environment or default to volatile
            scenario_name = os.getenv("SIMULATION_SCENARIO", "volatile")
            try:
                scenario = MarketScenario(scenario_name)
            except ValueError:
                scenario = MarketScenario.RANGING

            sim_config = SimulationConfig(
                initial_balance=settings.trading.initial_capital,
                quote_currency=settings.trading.quote_currency,
                scenario=scenario,
                slippage_pct=float(os.getenv("SIMULATION_SLIPPAGE", "0.001")),
                failure_rate=float(os.getenv("SIMULATION_FAILURE_RATE", "0.02")),
            )
            exchange = SimulationExchange(config=sim_config)
            logger.info(f"Using ENHANCED simulation exchange (scenario: {scenario.value})")

            # Set up simulation routes
            from api.routes.simulation import set_simulation_exchange
            set_simulation_exchange(exchange)
        except ImportError:
            exchange = MockExchange(initial_balance=settings.trading.initial_capital,
                                    quote_currency=settings.trading.quote_currency)
            logger.info("Using MOCK exchange (paper trading)")
    else:
        exchange = create_exchange(settings.exchange.name)
        logger.info(f"Using LIVE {settings.exchange.name.capitalize()} exchange")

    # LLM
    llm = None
    if settings.llm.api_key:
        llm = ClaudeLLM(model=settings.llm.model)
        logger.info("Using Claude LLM for decisions")
    else:
        logger.info("No LLM configured - will use rule-based strategist")

    # Memory - Phase 2: PostgreSQL or Phase 1: In-Memory
    cache = None
    if settings.stage.value in ("stage2", "stage3") and settings.features.enable_postgres:
        # Redis cache (optional — failure doesn't block PostgreSQL)
        try:
            from memory.redis_cache import RedisCache
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            cache_ttl = int(os.getenv("REDIS_CACHE_TTL_SECONDS", "300"))
            cache = RedisCache(redis_url, default_ttl=cache_ttl)
            await cache.connect()
            logger.info(f"Redis cache connected (TTL={cache_ttl}s)")
        except Exception as e:
            logger.warning(f"Redis cache unavailable: {e}")
            cache = None

        # PostgreSQL (required for Phase 2)
        try:
            from memory.postgres import PostgresStore
            db_url = os.getenv("DATABASE_URL", "postgresql://trader:trader@localhost:5432/trader")
            memory = PostgresStore(db_url)
            await memory.connect()
            logger.info("PostgreSQL storage connected")
        except Exception as e:
            logger.warning(f"Failed to initialize PostgreSQL: {e}")
            logger.info("Falling back to in-memory storage")
            memory = InMemoryStore(initial_capital=settings.trading.initial_capital)
    else:
        memory = InMemoryStore(initial_capital=settings.trading.initial_capital)
        logger.info("Using in-memory storage (Phase 1)")

    # =========================================================================
    # Strategist / Sentinel / Executor (Stage 1/2 only — Phase3 creates its own)
    # =========================================================================
    strategist = None
    sentinel = None
    executor = None

    if settings.stage != Stage.STAGE_3_FULL:
        cost_opt = settings.cost_optimization
        if cost_opt.enable_batch_analysis or cost_opt.enable_hybrid_mode:
            # Use cost-optimized strategist
            strategist = CostOptimizedStrategist(
                llm=llm,
                cache=cache if cost_opt.enable_decision_cache else None,
                settings=settings
            )
            opt_features = []
            if cost_opt.enable_batch_analysis:
                opt_features.append("batch")
            if cost_opt.enable_hybrid_mode:
                opt_features.append("hybrid")
            if cost_opt.enable_decision_cache and cache:
                opt_features.append("cache")
            logger.info(f"[COST_OPT] Using cost-optimized strategist: {', '.join(opt_features)}")
        elif llm:
            # Standard LLM strategist
            strategist = SimpleStrategist(llm, settings)
            logger.info("Using standard Claude strategist")
        else:
            # No LLM - rules only
            strategist = RuleBasedStrategist(settings)
            logger.info("Using rule-based strategist (no LLM)")

    # Log risk profile
    if settings.risk_profile == "aggressive":
        logger.info(f"[RISK] AGGRESSIVE profile active: "
                   f"position={settings.aggressive_risk.max_position_pct:.0%}, "
                   f"confidence={settings.aggressive_risk.min_confidence:.0%}")

    # Analysts - Technical always, Sentiment for Stage 2+, full set for Stage 3
    analysts = [TechnicalAnalyst()]
    logger.info("✅ Technical analyst initialized")

    if settings.stage.value in ("stage2", "stage3") and settings.features.enable_sentiment_analyst:
        try:
            from integrations.data import FearGreedAPI, CryptoNewsAPI
            from agents.analysts.sentiment import SentimentAnalyst

            fear_greed_api = FearGreedAPI(cache=cache)
            news_api = CryptoNewsAPI(cache=cache)
            sentiment_analyst = SentimentAnalyst(fear_greed_api, news_api, llm=llm if settings.llm.api_key else None)
            analysts.append(sentiment_analyst)
            logger.info("✅ Sentiment analyst initialized (Fear & Greed + News)")
        except Exception as e:
            logger.warning(f"Failed to initialize sentiment analyst: {e}")

    # Stage 3: Additional analysts
    if settings.stage == Stage.STAGE_3_FULL:
        if settings.features.enable_onchain_analyst:
            try:
                from agents.analysts.onchain import OnChainAnalyst
                analysts.append(OnChainAnalyst(cache=cache))
                logger.info("✅ OnChainAnalyst initialized (Glassnode)")
            except Exception as e:
                logger.warning(f"Failed to init on-chain analyst: {e}")

        if settings.features.enable_macro_analyst:
            try:
                from agents.analysts.macro import MacroAnalyst
                analysts.append(MacroAnalyst(cache=cache))
                logger.info("✅ MacroAnalyst initialized (FRED)")
            except Exception as e:
                logger.warning(f"Failed to init macro analyst: {e}")

        if settings.features.enable_orderbook_analyst:
            try:
                from agents.analysts.orderbook import OrderBookAnalyst
                analysts.append(OrderBookAnalyst(exchange=exchange))
                logger.info("✅ OrderBookAnalyst initialized")
            except Exception as e:
                logger.warning(f"Failed to init orderbook analyst: {e}")

    # Sentinel - Phase 2: Enhanced with Circuit Breakers (Stage 1/2 only)
    if settings.stage != Stage.STAGE_3_FULL:
        if settings.stage.value == "stage2" and settings.features.enable_circuit_breakers:
            try:
                from agents.sentinel.circuit_breakers import CircuitBreakers

                circuit_breakers = CircuitBreakers(
                    max_daily_loss_pct=settings.risk.max_daily_loss_pct,
                    max_daily_trades=settings.risk.max_daily_trades,
                    volatility_threshold_pct=0.10,
                    consecutive_loss_limit=3
                )
                logger.info("✅ Circuit breakers initialized")

                sentinel = BasicSentinel(memory, settings)
                sentinel.circuit_breakers = circuit_breakers
            except Exception as e:
                logger.warning(f"Failed to initialize circuit breakers: {e}")
                sentinel = BasicSentinel(memory, settings)
        else:
            sentinel = BasicSentinel(memory, settings)

        # Executor
        executor = SimpleExecutor(exchange, memory, settings)

    # Orchestrator
    if settings.stage == Stage.STAGE_3_FULL:
        from core.events import get_event_bus
        event_bus = get_event_bus()

        orch = Phase3Orchestrator(
            exchange=exchange,
            analysts=analysts,
            memory=memory,
            settings=settings,
            event_bus=event_bus,
            llm=llm
        )
        logger.info(f"🚀 Phase3Orchestrator created with {len(analysts)} analysts")
    else:
        orch = Orchestrator(
            exchange=exchange,
            analysts=analysts,
            strategist=strategist,
            sentinel=sentinel,
            executor=executor,
            memory=memory,
            settings=settings
        )

    # Attach cache, circuit breakers, and LLM for access in routes
    orch._cache = cache
    orch._llm = llm
    if settings.stage == Stage.STAGE_3_FULL:
        orch._circuit_breakers = orch.sentinel.circuit_breakers
    else:
        orch._circuit_breakers = getattr(sentinel, 'circuit_breakers', None)

    # =========================================================================
    # Alert Manager
    # =========================================================================
    global alert_manager
    from core.alerts import AlertManager, ConsoleChannel, FileChannel, WebhookChannel, TelegramChannel

    alert_channels = []

    # Console channel
    if settings.alerts.console_enabled:
        alert_channels.append(ConsoleChannel(enabled=True))
        logger.info("✅ Alert channel: Console")

    # File channel
    if settings.alerts.file_enabled:
        alert_channels.append(FileChannel(
            file_path=settings.alerts.file_path,
            enabled=True,
            max_size_mb=settings.alerts.file_max_size_mb
        ))
        logger.info(f"✅ Alert channel: File ({settings.alerts.file_path})")

    # Webhook channel (Discord/Slack)
    if settings.alerts.webhook_enabled and settings.alerts.webhook_url:
        alert_channels.append(WebhookChannel(
            url=settings.alerts.webhook_url,
            platform=settings.alerts.webhook_platform,
            enabled=True
        ))
        logger.info(f"✅ Alert channel: Webhook ({settings.alerts.webhook_platform})")

    # Telegram channel
    if settings.alerts.telegram_enabled and settings.alerts.telegram_bot_token:
        alert_channels.append(TelegramChannel(
            bot_token=settings.alerts.telegram_bot_token,
            chat_id=settings.alerts.telegram_chat_id,
            enabled=True
        ))
        logger.info("✅ Alert channel: Telegram")

    alert_manager = AlertManager(
        channels=alert_channels,
        max_history=settings.alerts.max_history
    )
    orch._alert_manager = alert_manager

    # Set up alerts routes
    from api.routes.alerts import set_alert_manager
    set_alert_manager(alert_manager)

    # Set up analytics routes
    from api.routes.analytics import set_memory as set_analytics_memory
    set_analytics_memory(memory)

    # =========================================================================
    # Adaptive Risk Manager
    # =========================================================================
    if settings.enable_adaptive_risk:
        from core.risk import AdaptiveRiskManager
        from core.risk.adaptive import AdaptiveRiskConfig

        # Build config from settings
        adaptive_config_data = settings.adaptive_risk_config or {}
        adaptive_config = AdaptiveRiskConfig(
            enabled=True,
            cautious_after_losses=adaptive_config_data.get("cautious_after_losses", 2),
            defensive_after_losses=adaptive_config_data.get("defensive_after_losses", 3),
            cautious_multiplier=adaptive_config_data.get("cautious_multiplier", 0.75),
            defensive_multiplier=adaptive_config_data.get("defensive_multiplier", 0.50),
            drawdown_confidence_increase=adaptive_config_data.get("drawdown_confidence_increase", 0.10),
            drawdown_threshold=adaptive_config_data.get("drawdown_threshold", 0.05),
            recovery_steps=adaptive_config_data.get("recovery_steps", 3),
            lookback_hours=adaptive_config_data.get("lookback_hours", 24),
        )

        risk_manager = AdaptiveRiskManager(config=adaptive_config)
        orch._risk_manager = risk_manager

        # Set up risk routes
        from api.routes.risk import set_risk_manager
        set_risk_manager(risk_manager)

        logger.info("✅ Adaptive risk manager initialized")
    else:
        logger.info("Adaptive risk manager disabled (set ENABLE_ADAPTIVE_RISK=true to enable)")

    # =========================================================================
    # Meme Trading Module (behind feature flag)
    # =========================================================================
    import os
    enable_meme = os.getenv("ENABLE_MEME_TRADING", "false").lower() == "true"

    if enable_meme:
        try:
            from agents.memetrader import MemeOrchestrator, MemeConfig
            from agents.memetrader.listing_detector import ListingDetector
            from agents.memetrader.twitter_analyst import TwitterSentimentAnalyst
            from agents.memetrader.volume_analyst import VolumeMomentumAnalyst
            from agents.memetrader.meme_strategist import MemeStrategist
            from agents.memetrader.meme_sentinel import MemeSentinel
            from agents.memetrader.models import MemeBudgetState
            from integrations.data.twitter_client import TwitterClient
            from integrations.llm import ClaudeLLM

            meme_config = MemeConfig()

            # Separate Haiku LLM for meme decisions (cheaper model)
            meme_llm = None
            if settings.llm.api_key:
                meme_llm = ClaudeLLM(model=meme_config.haiku_model)
                logger.info(f"Meme LLM: {meme_config.haiku_model}")

            # Twitter client
            twitter_bearer = os.getenv("TWITTER_BEARER_TOKEN", "")
            twitter_client = TwitterClient(bearer_token=twitter_bearer, cache=cache)

            # Budget tracker
            budget = MemeBudgetState(
                daily_reads_limit=meme_config.daily_api_reads,
                monthly_reads_limit=meme_config.monthly_api_reads,
            )

            # Create meme components
            listing_detector = ListingDetector(config=meme_config)
            twitter_analyst = TwitterSentimentAnalyst(twitter_client, meme_llm, budget=budget)
            volume_analyst = VolumeMomentumAnalyst()
            meme_strategist = MemeStrategist(llm=meme_llm, config=meme_config)
            meme_sentinel = MemeSentinel(config=meme_config)

            meme_orchestrator = MemeOrchestrator(
                exchange=exchange,
                executor=SimpleExecutor(exchange, memory, settings),
                twitter_analyst=twitter_analyst,
                volume_analyst=volume_analyst,
                strategist=meme_strategist,
                sentinel=meme_sentinel,
                listing_detector=listing_detector,
                config=meme_config,
            )

            # Wire up API routes
            from api.routes.meme import set_meme_orchestrator
            set_meme_orchestrator(meme_orchestrator)

            # Add scheduler job for meme cycles
            # Note: scheduler is set up in lifespan, so we store on orch for later
            orch._meme_orchestrator = meme_orchestrator

            logger.info("✅ Meme trading module initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize meme trading module: {e}")
            import traceback
            traceback.print_exc()
    else:
        logger.info("Meme trading module disabled (set ENABLE_MEME_TRADING=true to enable)")

    # Seed improver service (Phase 0 + Phase 1 + Phase 2 auto-apply)
    global seed_improver
    try:
        from agents.seed_improver import SeedImproverService

        # Load seed_improver config from YAML if available
        auto_apply_config = {}
        try:
            import yaml as _yaml
            _cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", f"{settings.stage.value}.yaml")
            if os.path.exists(_cfg_path):
                with open(_cfg_path) as _f:
                    _raw = _yaml.safe_load(_f)
                    auto_apply_config = _raw.get("seed_improver", {})
        except Exception:
            pass

        seed_improver = SeedImproverService(
            memory=memory,
            llm=llm,
            alert_manager=alert_manager,
            auto_apply_config=auto_apply_config,
        )
        phase = "Phase 0 + 1" if llm else "Phase 0 only (no LLM)"
        if auto_apply_config.get("auto_apply"):
            phase += " + Phase 2 (auto-apply)"
        logger.info(f"SeedImprover initialized ({phase})")

        from api.routes.seed_improver import set_seed_improver
        set_seed_improver(seed_improver, memory)

        # DGM (Darwinian Godel Machine) initialization
        global dgm_service
        dgm_config = auto_apply_config.get("dgm", {})
        db_pool = getattr(memory, "_pool", None)
        if dgm_config.get("enabled") and db_pool:
            try:
                from agents.seed_improver.dgm_service import DGMService as _DGMService
                from agents.seed_improver.deployer import SelfDeployer
                from api.routes.seed_improver import set_dgm_service

                deployer = SelfDeployer(
                    gcs_bucket=auto_apply_config.get("gcs_config_bucket", ""),
                )
                dgm_service = _DGMService(
                    db_pool=db_pool,
                    seed_improver_service=seed_improver,
                    deployer=deployer,
                    dgm_config=dgm_config,
                )
                set_dgm_service(dgm_service, db_pool)
                logger.info("DGM (Darwinian Godel Machine) initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize DGM: {e}")
        elif dgm_config.get("enabled"):
            logger.warning("DGM enabled but no DB pool available, skipping")

    except Exception as e:
        logger.warning(f"Failed to initialize SeedImprover: {e}")

    # Autoresearch service — LLM-powered code improvement
    global autoresearch_service
    try:
        from agents.autoresearch.service import AutoresearchService

        autoresearch_service = AutoresearchService(
            store=memory,
            llm=llm,
        )
        logger.info("Autoresearch service initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize Autoresearch: {e}")

    logger.info(f"🚀 Orchestrator initialized ({len(analysts)} analysts)")
    return orch


async def _run_migrations_on_startup():
    """Run pending DB migrations on startup (idempotent)."""
    if not seed_improver or not hasattr(seed_improver, 'memory'):
        return
    memory = seed_improver.memory
    if not hasattr(memory, '_connection'):
        return

    migration_dir = Path(__file__).resolve().parents[1] / "migrations"
    migration_files = [
        "006_dgm_population_archive.sql",
        "008_daily_portfolio_ledger.sql",
        "009_autoresearch_experiments.sql",
    ]
    for filename in migration_files:
        try:
            migration_file = migration_dir / filename
            if migration_file.exists():
                sql = migration_file.read_text(encoding='utf-8')
                async with memory._connection() as conn:
                    await conn.execute(sql)
                logger.info("Migration %s applied successfully", filename)
        except Exception as e:
            logger.warning("Migration %s skipped or already applied: %s", filename, e)


async def _run_trading_cycle():
    """Wrapper for scheduled trading cycle"""
    global orchestrator
    if orchestrator:
        try:
            await orchestrator.run_cycle()
        except Exception as e:
            logger.error(f"Trading cycle error: {e}", exc_info=True)


async def _run_meme_cycle():
    """Wrapper for scheduled meme trading cycle"""
    global orchestrator
    if orchestrator and hasattr(orchestrator, '_meme_orchestrator') and orchestrator._meme_orchestrator:
        try:
            await orchestrator._meme_orchestrator.run_cycle()
        except Exception as e:
            logger.error(f"Meme trading cycle error: {e}", exc_info=True)


# Profit tracker paths — override with PROFIT_TRACKER_DIR env var at runtime
_PROFIT_TRACKER_DIR = "/tmp/memory/daily"
_PROFIT_STATE_FILE = _PROFIT_TRACKER_DIR + "/profit-state.json"
_PROFIT_TABLE_FILE = _PROFIT_TRACKER_DIR + "/profit-tracker.md"
_STAGNANT_THRESHOLD_PCT = 0.10


async def _run_daily_profit_snapshot() -> dict:
    """5:30 PM AEST — capture daily P&L vs yesterday, save to DB ledger."""
    global orchestrator
    import json as _json
    import os as _os
    from datetime import date as _date, datetime as _dt, timezone as _tz

    logger.info("[PROFIT_SNAPSHOT] 5:30 PM snapshot starting")
    _os.makedirs(_PROFIT_TRACKER_DIR, exist_ok=True)

    today = _date.today()
    today_iso = today.isoformat()
    now_ts = _dt.now(_tz.utc).isoformat()
    portfolio_value = 0.0
    total_trades = 0
    wins = 0
    losses = 0
    win_rate = 0.0
    main_pnl = 0.0
    meme_pnl = 0.0
    realized_pnl = 0.0
    unrealized_pnl = 0.0
    fees_total = 0.0

    if orchestrator:
        try:
            pf = await orchestrator._get_portfolio_state()
            portfolio_value = pf.total_value
            # Calculate unrealized P&L from open positions
            for pos in pf.positions.values():
                if pos.entry_price and pos.current_price and pos.amount:
                    unrealized_pnl += (pos.current_price - pos.entry_price) * pos.amount
        except Exception as exc:
            logger.error("[PROFIT_SNAPSHOT] Portfolio fetch failed: %s", exc)
        try:
            perf = await orchestrator.memory.get_performance_summary()
            total_trades = perf.get("total_trades", 0)
            wins = perf.get("wins_7d", 0)
            losses = perf.get("losses_7d", 0)
            win_rate = perf.get("win_rate", 0.0)
            main_pnl = perf.get("total_pnl", 0.0)
            realized_pnl = main_pnl
        except Exception as exc:
            logger.warning("[PROFIT_SNAPSHOT] Trade stats failed: %s", exc)
        try:
            fees_total = await orchestrator.memory.get_daily_fees_today()
        except Exception as exc:
            logger.warning("[PROFIT_SNAPSHOT] Fee fetch failed: %s", exc)

    if (orchestrator and hasattr(orchestrator, "_meme_orchestrator")
            and orchestrator._meme_orchestrator):
        for pos in getattr(orchestrator._meme_orchestrator, "_positions", {}).values():
            entry = getattr(pos, "entry_price", None)
            current = getattr(pos, "_current_price", None) or getattr(pos, "current_price", None)
            qty = getattr(pos, "amount", None) or getattr(pos, "quantity", None)
            if entry and current and qty:
                meme_pnl += (current - entry) * qty

    # Determine start value: previous day's end_value from DB, else flat file, else current
    start_value = portfolio_value
    if orchestrator and hasattr(orchestrator.memory, "get_previous_day_end_value"):
        try:
            prev = await orchestrator.memory.get_previous_day_end_value(today)
            if prev is not None:
                start_value = prev
        except Exception:
            pass

    # Fallback to flat file state if no DB entry yet
    state: dict = {}
    if start_value == portfolio_value and _os.path.exists(_PROFIT_STATE_FILE):
        try:
            with open(_PROFIT_STATE_FILE, "r", encoding="utf-8") as fh:
                state = _json.load(fh)
            start_value = state.get("last_snapshot_value", portfolio_value)
        except Exception:
            pass

    baseline_value = state.get("baseline_value", start_value)
    daily_pnl = portfolio_value - start_value
    daily_pnl_pct = (daily_pnl / start_value * 100) if start_value > 0 else 0.0
    total_pnl = portfolio_value - baseline_value
    total_pnl_pct = (total_pnl / baseline_value * 100) if baseline_value > 0 else 0.0

    if abs(daily_pnl_pct) < _STAGNANT_THRESHOLD_PCT:
        day_status = "STAGNANT"
    elif daily_pnl > 0:
        day_status = "PROFIT"
    else:
        day_status = "LOSS"

    # Save to database ledger
    if orchestrator and hasattr(orchestrator.memory, "save_daily_ledger_entry"):
        try:
            await orchestrator.memory.save_daily_ledger_entry({
                "date": today,
                "start_value": start_value,
                "end_value": portfolio_value,
                "daily_pnl": daily_pnl,
                "daily_pnl_pct": daily_pnl_pct,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "total_trades": total_trades,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate / 100 if win_rate > 1 else win_rate,
                "main_pnl": main_pnl,
                "meme_pnl": meme_pnl,
                "fees_total": fees_total,
                "status": day_status,
            })
        except Exception as exc:
            logger.error("[PROFIT_SNAPSHOT] DB ledger save failed: %s", exc)

    # Also write flat file state for backward compatibility
    win_pct_str = f"{win_rate:.0f}%" if total_trades > 0 else "—"
    recent = state.get("recent_daily_results", [])
    recent = [r for r in recent if r.get("date") != today_iso]
    recent.append({"date": today_iso, "pnl": daily_pnl, "pnl_pct": daily_pnl_pct})
    recent = recent[-7:]

    last_3 = recent[-3:]
    stagnant_streak = (len(last_3) >= 3
                       and all(abs(r["pnl_pct"]) < _STAGNANT_THRESHOLD_PCT for r in last_3))
    consecutive_losses = 0
    for r in reversed(recent):
        if r["pnl"] < 0:
            consecutive_losses += 1
        else:
            break

    # Flat file table (kept for compatibility)
    table_header = (
        "# Daily Profit Tracker\n\n"
        "| Date | Start $ | End $ | Daily P&L | Daily % | Trades | Win% | Main PnL | Meme PnL | Status |\n"
        "|------|---------|-------|-----------|---------|--------|------|----------|----------|--------|\n"
    )
    day_status_emoji = {"PROFIT": "✅ PROFIT", "LOSS": "🔴 LOSS", "STAGNANT": "🟡 STAGNANT"}.get(day_status, day_status)
    row = (f"| {today_iso} | ${start_value:,.2f} | ${portfolio_value:,.2f} | "
           f"${daily_pnl:+,.2f} | {daily_pnl_pct:+.2f}% | {total_trades} | {win_pct_str} | "
           f"${main_pnl:+.2f} | ${meme_pnl:+.2f} | {day_status_emoji} |\n")

    if not _os.path.exists(_PROFIT_TABLE_FILE):
        with open(_PROFIT_TABLE_FILE, "w", encoding="utf-8") as fh:
            fh.write(table_header)
    with open(_PROFIT_TABLE_FILE, "a", encoding="utf-8") as fh:
        fh.write(row)

    new_state = {
        "last_snapshot_date": today_iso, "last_snapshot_ts": now_ts,
        "last_snapshot_value": portfolio_value, "baseline_value": baseline_value,
        "recent_daily_results": recent, "today_pnl": daily_pnl,
        "today_pnl_pct": daily_pnl_pct, "today_status": day_status,
        "today_trades": total_trades, "today_win_rate": win_rate,
        "today_main_pnl": main_pnl, "today_meme_pnl": meme_pnl,
        "stagnant_streak": stagnant_streak, "consecutive_losses": consecutive_losses,
        "total_pnl": total_pnl, "total_pnl_pct": total_pnl_pct,
    }
    with open(_PROFIT_STATE_FILE, "w", encoding="utf-8") as fh:
        _json.dump(new_state, fh, indent=2)

    logger.info("[PROFIT_SNAPSHOT] %s | $%.2f→$%.2f | %s | stagnant=%s | losses=%d",
                today_iso, start_value, portfolio_value, day_status, stagnant_streak, consecutive_losses)
    return new_state


async def _run_meme_daily_review():
    """6:15 PM AEST — log meme bot positions + circuit breaker state."""
    global orchestrator
    if not (orchestrator and hasattr(orchestrator, "_meme_orchestrator")
            and orchestrator._meme_orchestrator):
        logger.info("[MEME_REVIEW] Meme orchestrator inactive")
        return
    try:
        import os as _os
        from datetime import date as _date
        meme_orch = orchestrator._meme_orchestrator
        positions = getattr(meme_orch, "_positions", {})
        cycle_count = getattr(meme_orch, "_cycle_count", 0)
        sentinel = getattr(meme_orch, "sentinel", None)
        cb_active = getattr(sentinel, "_circuit_breaker_active", False) if sentinel else False

        open_pnl = 0.0
        pos_lines = []
        for symbol, pos in positions.items():
            entry = getattr(pos, "entry_price", None)
            current = getattr(pos, "_current_price", None) or getattr(pos, "current_price", None)
            qty = getattr(pos, "amount", None)
            if entry and current and qty:
                p = (current - entry) * qty
                open_pnl += p
                pos_lines.append(f"  - {symbol}: ${p:+.2f}")

        _os.makedirs(_PROFIT_TRACKER_DIR, exist_ok=True)
        today = _date.today().isoformat()
        log_path = _os.path.join(_PROFIT_TRACKER_DIR, f"{today}.md")
        pos_section = "\n".join(pos_lines) if pos_lines else "  - No open positions"
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"\n### Meme Bot Daily Review — {today} 18:15 AEST\n"
                     f"- Positions: {len(positions)} | Open P&L: ${open_pnl:+.2f}\n"
                     f"- Circuit breaker: {'🔴 ACTIVE' if cb_active else '🟢 OFF'}\n"
                     f"- Cycles today: {cycle_count}\n{pos_section}\n")
        logger.info("[MEME_REVIEW] Review written — positions=%d open_pnl=$%.2f cb=%s",
                    len(positions), open_pnl, cb_active)
    except Exception as exc:
        logger.error("[MEME_REVIEW] Error: %s", exc, exc_info=True)


async def _run_seed_improver_daily():
    """Daily autonomous seed improver run (5:45 PM Australia/Sydney).

    Evaluates today's daily P&L from the ledger. If the day was a loss or
    stagnant, runs an aggressive improvement cycle targeting the specific
    issues. When DGM is enabled, runs a full evolutionary cycle.
    """
    global seed_improver, dgm_service, orchestrator
    from datetime import date as _date

    today = _date.today()
    daily_context = {}

    # Pull today's daily ledger entry to inform the improvement cycle
    if orchestrator and hasattr(orchestrator.memory, "get_daily_ledger_entry"):
        try:
            entry = await orchestrator.memory.get_daily_ledger_entry(today)
            if entry:
                daily_context = {
                    "daily_pnl": float(entry.get("daily_pnl", 0)),
                    "daily_pnl_pct": float(entry.get("daily_pnl_pct", 0)),
                    "daily_status": entry.get("status", "NO_DATA"),
                    "start_value": float(entry.get("start_value", 0)),
                    "end_value": float(entry.get("end_value", 0)),
                    "total_trades": entry.get("total_trades", 0),
                    "wins": entry.get("wins", 0),
                    "losses": entry.get("losses", 0),
                    "win_rate": float(entry.get("win_rate", 0)),
                    "main_pnl": float(entry.get("main_pnl", 0)),
                    "meme_pnl": float(entry.get("meme_pnl", 0)),
                    "fees_total": float(entry.get("fees_total", 0)),
                }
                logger.info("[IMPROVER] Today's P&L: $%.4f (%s)", daily_context["daily_pnl"], daily_context["daily_status"])
        except Exception as exc:
            logger.warning("[IMPROVER] Failed to read daily ledger: %s", exc)

    # Also pull streak data
    if orchestrator and hasattr(orchestrator.memory, "get_daily_profit_streak"):
        try:
            streak = await orchestrator.memory.get_daily_profit_streak()
            daily_context["streak_type"] = streak.get("streak_type", "none")
            daily_context["streak_days"] = streak.get("streak_days", 0)
            daily_context["profit_days_14d"] = streak.get("profit_days", 0)
            daily_context["loss_days_14d"] = streak.get("loss_days", 0)
        except Exception:
            pass

    improvement_action = "scheduled_review"
    is_loss_day = daily_context.get("daily_status") in ("LOSS", "STAGNANT")

    if is_loss_day:
        improvement_action = "loss_recovery_optimization"
        logger.info("[IMPROVER] LOSS/STAGNANT day detected — running aggressive optimization")

    # DGM mode: run evolutionary cycle with daily profit context
    if dgm_service:
        try:
            result = await dgm_service.run_cycle()
            outcome = result.get("outcome", "unknown")
            logger.info("DGM cycle completed: %s", outcome)

            # Record improvement action in ledger
            if orchestrator and hasattr(orchestrator.memory, "update_daily_ledger_improvement"):
                action_desc = f"DGM {improvement_action}: {outcome}"
                result_desc = _summarize_dgm_result(result)
                try:
                    await orchestrator.memory.update_daily_ledger_improvement(today, action_desc, result_desc)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"DGM cycle error: {e}", exc_info=True)
        return

    # Legacy mode: standard seed improver with daily profit context
    if seed_improver:
        try:
            context = {"source": "apscheduler", "daily_profit": daily_context}
            if is_loss_day:
                context["priority"] = "high"
                context["focus"] = "daily_profit_recovery"
                context["instruction"] = (
                    f"TODAY WAS A {daily_context.get('daily_status', 'LOSS')} DAY. "
                    f"Portfolio went from ${daily_context.get('start_value', 0):.2f} to "
                    f"${daily_context.get('end_value', 0):.2f} "
                    f"(P&L: ${daily_context.get('daily_pnl', 0):+.4f}). "
                    f"Analyse ALL trading strategies (main pairs, meme coins, charts) and "
                    f"recommend specific config changes to return a daily profit tomorrow. "
                    f"Focus on: entry/exit timing, position sizing, stop-loss levels, "
                    f"confidence thresholds, and pair selection."
                )
            result = await seed_improver.run("scheduled", context)
            from api.routes.seed_improver import _store_run_in_memory
            _store_run_in_memory(result)

            # Record improvement action in ledger
            if orchestrator and hasattr(orchestrator.memory, "update_daily_ledger_improvement"):
                action_desc = f"seed_improver {improvement_action}"
                result_desc = getattr(result, "summary", str(result)) if result else "no result"
                try:
                    await orchestrator.memory.update_daily_ledger_improvement(today, action_desc, result_desc[:500])
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Seed improver daily run error: {e}", exc_info=True)


def _summarize_dgm_result(result: dict) -> str:
    """Create a short summary of a DGM cycle result for the ledger."""
    parts = [f"outcome={result.get('outcome', '?')}"]
    phases = result.get("phases", {})
    if "evaluate" in phases:
        ev = phases["evaluate"]
        parts.append(f"eval={ev.get('verdict', ev.get('status', '?'))}")
    if "mutate" in phases:
        mt = phases["mutate"]
        parts.append(f"patches={mt.get('patches_count', 0)}")
    if "deploy" in phases:
        dp = phases["deploy"]
        parts.append(f"deploy={dp.get('status', '?')}")
    return " | ".join(parts)


async def _run_autoresearch_daily():
    """6:30 PM AEST — run autoresearch code improvement session."""
    global autoresearch_service, orchestrator
    if not autoresearch_service:
        logger.info("[AUTORESEARCH] Service not initialized")
        return

    from datetime import date as _date

    today = _date.today()
    daily_context = {}

    if orchestrator and hasattr(orchestrator.memory, "get_daily_ledger_entry"):
        try:
            entry = await orchestrator.memory.get_daily_ledger_entry(today)
            if entry:
                daily_context = {
                    "daily_pnl": float(entry.get("daily_pnl", 0)),
                    "daily_pnl_pct": float(entry.get("daily_pnl_pct", 0)),
                    "daily_status": entry.get("status", "NO_DATA"),
                    "total_trades": entry.get("total_trades", 0),
                    "wins": entry.get("wins", 0),
                    "losses": entry.get("losses", 0),
                    "win_rate": float(entry.get("win_rate", 0)),
                }
        except Exception as exc:
            logger.warning("[AUTORESEARCH] Failed to read daily ledger: %s", exc)

    try:
        result = await autoresearch_service.run(daily_context)
        n_exp = len(result.get("experiments", []))
        n_eval = len(result.get("evaluations", []))
        logger.info(
            "[AUTORESEARCH] Session complete: %d experiments, %d evaluations",
            n_exp, n_eval,
        )
    except Exception as e:
        logger.error("[AUTORESEARCH] Session error: %s", e, exc_info=True)


async def _evaluate_autoresearch_experiments():
    """10:00 AM AEST — evaluate yesterday's autoresearch experiments."""
    global autoresearch_service
    if not autoresearch_service:
        return

    try:
        evals = await autoresearch_service._evaluate_pending_experiments()
        logger.info("[AUTORESEARCH] Morning evaluation: %d experiments evaluated", len(evals))
    except Exception as e:
        logger.error("[AUTORESEARCH] Evaluation error: %s", e, exc_info=True)


def _register_routes(app: FastAPI):
    """Register API routes"""

    # Register alerts router
    from api.routes.alerts import router as alerts_router
    app.include_router(alerts_router)

    # Register analytics router
    from api.routes.analytics import router as analytics_router
    app.include_router(analytics_router)

    # Register risk management router
    from api.routes.risk import router as risk_router
    app.include_router(risk_router)

    # Register simulation router
    from api.routes.simulation import router as simulation_router
    app.include_router(simulation_router)

    # Register meme trading router
    from api.routes.meme import router as meme_router
    app.include_router(meme_router)

    # Register seed improver router
    from api.routes.seed_improver import router as seed_improver_router
    app.include_router(seed_improver_router)

    # Autoresearch API endpoints
    @app.get("/api/autoresearch/experiments")
    async def get_autoresearch_experiments(days: int = 30):
        """Get recent autoresearch experiments."""
        if not autoresearch_service:
            return {"experiments": [], "error": "Autoresearch service not initialized"}
        experiments = await autoresearch_service.get_experiments(days)
        return {"experiments": experiments}

    @app.get("/api/autoresearch/latest")
    async def get_autoresearch_latest():
        """Get the most recent autoresearch experiment."""
        if not autoresearch_service:
            return {"experiment": None, "error": "Autoresearch service not initialized"}
        experiment = await autoresearch_service.get_latest_experiment()
        return {"experiment": experiment}

    @app.post("/api/autoresearch/trigger")
    async def trigger_autoresearch():
        """Manually trigger an autoresearch session."""
        if not autoresearch_service:
            raise HTTPException(status_code=503, detail="Autoresearch service not initialized")
        from datetime import date as _date
        daily_context = {}
        if orchestrator and hasattr(orchestrator.memory, "get_daily_ledger_entry"):
            try:
                entry = await orchestrator.memory.get_daily_ledger_entry(_date.today())
                if entry:
                    daily_context = {
                        "daily_pnl": float(entry.get("daily_pnl", 0)),
                        "daily_status": entry.get("status", "NO_DATA"),
                    }
            except Exception:
                pass
        result = await autoresearch_service.run(daily_context)
        return result

    @app.get("/")
    async def root():
        """Redirect to dashboard"""
        return RedirectResponse(url="/dashboard/")

    @app.get("/api/status")
    async def api_status():
        """Agent status (moved from root to /api/status)"""
        return {
            "status": "running",
            "stage": settings.stage.value,
            "target": f"${settings.trading.initial_capital} → ${settings.trading.target_capital}",
            "pairs": settings.trading.pairs,
            "interval_minutes": settings.trading.check_interval_minutes,
            "simulation_mode": settings.features.simulation_mode
        }
    
    @app.get("/api/agents")
    async def get_agents():
        """Return all agents with their runtime active status"""
        # Metadata not available from the analyst objects themselves
        agent_meta = {
            "technical": {
                "display_name": "Technical Analyst", "type": "analyst",
                "description": "Analyzes price action using SMA crossovers and RSI indicators to identify trend direction and momentum.",
                "accuracy": 0.72, "stage": 1, "icon": "candlestick-chart",
            },
            "sentiment": {
                "display_name": "Sentiment Analyst", "type": "analyst",
                "description": "Monitors Fear & Greed Index and crypto news headlines for market sentiment signals with contrarian logic.",
                "accuracy": 0.68, "stage": 2, "icon": "heart-pulse",
            },
            "onchain": {
                "display_name": "On-Chain Analyst", "type": "analyst",
                "description": "Analyzes blockchain metrics including exchange flows, active addresses, and whale activity.",
                "accuracy": 0.65, "stage": 3, "icon": "link",
            },
            "macro": {
                "display_name": "Macro Analyst", "type": "analyst",
                "description": "Evaluates macroeconomic factors like DXY, interest rates, and global M2 money supply.",
                "accuracy": 0.60, "stage": 3, "icon": "globe",
            },
            "orderbook": {
                "display_name": "Order Book Analyst", "type": "analyst",
                "description": "Analyzes market microstructure including bid/ask imbalance and order book depth.",
                "accuracy": 0.62, "stage": 3, "icon": "book-open",
            },
        }

        agents_list = []
        active_names = set()

        # Build list from live orchestrator analysts
        if orchestrator:
            for analyst in orchestrator.analysts:
                name = analyst.name
                active_names.add(name)
                meta = agent_meta.get(name, {})
                agents_list.append({
                    "name": name,
                    "display_name": meta.get("display_name", name.title()),
                    "type": meta.get("type", "analyst"),
                    "description": meta.get("description", ""),
                    "weight": analyst.weight,
                    "accuracy": meta.get("accuracy", 0.0),
                    "stage": meta.get("stage", 1),
                    "active": True,
                    "icon": meta.get("icon", "cpu"),
                })

        # Add any agents that exist in metadata but weren't initialized
        for name, meta in agent_meta.items():
            if name not in active_names:
                agents_list.append({
                    "name": name,
                    "active": False,
                    **meta,
                    "weight": 0.0,
                })

        # Always include strategist and sentinel (non-analyst agents)
        agents_list.append({
            "name": "strategist",
            "display_name": "Claude Strategist",
            "type": "strategist",
            "description": "LLM-powered decision engine that synthesizes all analyst signals into trading plans.",
            "weight": 1.0, "accuracy": 0.70, "stage": 1,
            "active": orchestrator is not None,
            "icon": "sparkles",
        })
        agents_list.append({
            "name": "sentinel",
            "display_name": "Risk Sentinel",
            "type": "sentinel",
            "description": "Validates all trading decisions against risk parameters, position limits, and circuit breakers.",
            "weight": 1.0, "accuracy": 0.95, "stage": 1,
            "active": orchestrator is not None,
            "icon": "shield",
        })
        agents_list.append({
            "name": "fusion",
            "display_name": "Intelligence Fusion",
            "type": "analyst",
            "description": "Combines signals from multiple analysts using weighted averaging and disagreement detection.",
            "weight": 1.0, "accuracy": 0.73, "stage": 2,
            "active": orchestrator is not None,
            "icon": "merge",
        })

        return {"agents": agents_list}

    @app.get("/health")
    async def health():
        """Health check"""
        return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

    @app.get("/metrics")
    async def metrics():
        """Prometheus metrics endpoint"""
        from api.metrics import get_metrics_response, metrics_collector

        # Update metrics from cached portfolio (no extra Binance API calls)
        cached = await _get_cached_portfolio()
        if cached:
            try:
                metrics_collector.update_portfolio(
                    value=cached.get("total_value", 0),
                    pnl=cached.get("total_pnl", 0),
                    pnl_pct=cached.get("total_pnl_pct", 0),
                    progress=cached.get("progress_to_target", 0),
                    position_count=len(cached.get("positions", {}))
                )
            except Exception as e:
                logger.debug(f"Metrics portfolio update failed: {e}")

        return get_metrics_response()
    
    @app.get("/portfolio")
    async def get_portfolio():
        """Get current portfolio state (cached for 30s)"""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")

        result = await _get_cached_portfolio()
        if result is None:
            raise HTTPException(status_code=500, detail="Portfolio data unavailable")
        return result
    
    @app.get("/api/portfolio/history")
    async def get_portfolio_history(range: str = "7D"):
        """Get portfolio value history for charting"""
        if not orchestrator:
            return {"snapshots": [], "range": range, "count": 0}

        range_map = {"1H": 0.04, "1D": 1, "24H": 1, "7D": 7, "30D": 30, "90D": 90, "ALL": 365}
        days = range_map.get(range, 7)

        try:
            db = orchestrator.memory
            # Try PostgreSQL first
            if hasattr(db, '_connection'):
                async with db._connection() as conn:
                    rows = await conn.fetch("""
                        SELECT total_value, created_at
                        FROM portfolio_snapshots
                        WHERE created_at >= NOW() - ($1 || ' days')::INTERVAL
                        ORDER BY created_at ASC
                    """, str(int(days) if days >= 1 else 1))

                snapshots = [
                    {"timestamp": row["created_at"].isoformat(), "total_value": float(row["total_value"])}
                    for row in rows
                ]
            else:
                # In-memory fallback: build from trade history
                snapshots = []
                trades = await orchestrator.memory.get_trade_history(1000)
                initial_capital = settings.trading.initial_capital

                # Get current portfolio value safely
                try:
                    portfolio = await orchestrator._get_portfolio_state()
                    current_value = portfolio.total_value
                except Exception:
                    p = await orchestrator.memory.get_portfolio()
                    current_value = p.total_value if p else initial_capital

                if trades:
                    # Create snapshots from trade timestamps
                    running_value = initial_capital
                    for trade in reversed(trades):
                        pnl = getattr(trade, 'realized_pnl', 0) or 0
                        running_value += pnl
                        ts = trade.timestamp.isoformat() if trade.timestamp else datetime.now(timezone.utc).isoformat()
                        snapshots.append({"timestamp": ts, "total_value": round(running_value, 2)})

                    # Add initial capital as first point
                    first_ts = trades[-1].timestamp if trades[-1].timestamp else datetime.now(timezone.utc)
                    snapshots.insert(0, {
                        "timestamp": (first_ts.replace(second=0, microsecond=0)).isoformat(),
                        "total_value": initial_capital
                    })

                # Always add current value as latest point
                snapshots.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "total_value": round(current_value, 2)
                })

            return {"snapshots": snapshots, "range": range, "count": len(snapshots)}
        except Exception as e:
            logger.error(f"Portfolio history error: {e}")
            return {"snapshots": [], "range": range, "count": 0}

    @app.get("/status")
    async def get_status():
        """Get detailed agent status"""
        global scheduler
        
        jobs = scheduler.get_jobs() if scheduler else []
        next_run = jobs[0].next_run_time if jobs else None
        
        return {
            "scheduler_running": scheduler.running if scheduler else False,
            "next_cycle": next_run.isoformat() if next_run else None,
            "cycle_count": orchestrator._cycle_count if orchestrator else 0,
            "sentinel_paused": orchestrator.sentinel.is_paused if orchestrator else False
        }
    
    @app.get("/history")
    async def get_trade_history(limit: int = 20):
        """Get trade history"""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")
        
        trades = await orchestrator.memory.get_trade_history(limit)
        return {"trades": [t.to_dict() for t in trades]}
    
    @app.get("/performance")
    async def get_performance():
        """Get performance summary"""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")
        
        return await orchestrator.memory.get_performance_summary()
    
    @app.post("/trigger")
    async def trigger_cycle():
        """Manually trigger a trading cycle"""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")
        
        result = await orchestrator.run_cycle()
        return {"status": "completed", "result": result}

    @app.post("/pause")
    async def pause_trading():
        """Pause trading"""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")
        
        orchestrator.sentinel.pause()
        return {"status": "paused"}
    
    @app.post("/resume")
    async def resume_trading():
        """Resume trading"""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")
        
        orchestrator.sentinel.resume()
        return {"status": "resumed"}
    
    @app.post("/emergency-stop")
    async def emergency_stop():
        """Emergency stop - close all positions and pause"""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")

        await orchestrator.sentinel.emergency_stop()
        # TODO: Close all positions
        return {"status": "emergency_stop_activated"}

    # WebSocket endpoint for portfolio updates
    from api.websocket_manager import connection_manager

    @app.websocket("/ws/portfolio")
    async def websocket_portfolio(websocket: WebSocket):
        """WebSocket endpoint for real-time portfolio updates"""
        connection_id = await connection_manager.connect(websocket)

        try:
            # Send initial portfolio state (from cache to avoid extra API calls)
            cached = await _get_cached_portfolio()
            await websocket.send_json({
                "type": "connection",
                "message": "Connected to portfolio stream",
                "connection_id": connection_id,
                "initial_portfolio": cached
            })

            # Keep connection alive and handle ping/pong
            while True:
                try:
                    data = await websocket.receive_text()
                    # Handle both plain text "ping" and JSON {"type":"ping"}
                    if data == "ping":
                        await websocket.send_text("pong")
                    else:
                        try:
                            import json
                            msg = json.loads(data)
                            if isinstance(msg, dict) and msg.get("type") == "ping":
                                await websocket.send_json({"type": "pong"})
                        except (json.JSONDecodeError, TypeError):
                            pass
                except WebSocketDisconnect:
                    break
        except Exception as e:
            logger.error(f"WebSocket error for {connection_id}: {e}")
        finally:
            await connection_manager.disconnect(connection_id)

    @app.get("/ws/connections")
    async def get_websocket_connections():
        """Get number of active WebSocket connections"""
        return {
            "active_connections": connection_manager.connection_count
        }

    # =========================================================================
    # Phase 2 Endpoints
    # =========================================================================

    @app.get("/api/phase2/breakers")
    async def get_circuit_breakers():
        """Get circuit breaker status (Phase 2)"""
        if not orchestrator or not hasattr(orchestrator, '_circuit_breakers') or not orchestrator._circuit_breakers:
            return {
                "enabled": False,
                "message": "Circuit breakers not available (Phase 1 or disabled)"
            }

        return {
            "enabled": True,
            "status": orchestrator._circuit_breakers.get_status()
        }

    @app.post("/api/phase2/breakers/reset/{breaker_name}")
    async def reset_circuit_breaker(breaker_name: str):
        """Manually reset a circuit breaker (Phase 2)"""
        if not orchestrator or not hasattr(orchestrator, '_circuit_breakers') or not orchestrator._circuit_breakers:
            raise HTTPException(status_code=404, detail="Circuit breakers not available")

        success = orchestrator._circuit_breakers.reset_breaker(breaker_name)
        if success:
            return {"status": "reset", "breaker": breaker_name}
        else:
            raise HTTPException(status_code=404, detail=f"Breaker '{breaker_name}' not found")

    @app.get("/api/phase2/cache")
    async def get_cache_stats():
        """Get Redis cache statistics (Phase 2)"""
        if not orchestrator or not hasattr(orchestrator, '_cache') or not orchestrator._cache:
            return {
                "enabled": False,
                "message": "Redis cache not available (Phase 1 or disabled)"
            }

        try:
            stats = await orchestrator._cache.get_stats()
            return {
                "enabled": True,
                "stats": stats
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/phase2/sentiment")
    async def get_sentiment_preview():
        """Get current sentiment data preview (Phase 2)"""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")

        # Check if sentiment analyst is available
        sentiment_analyst = None
        for analyst in orchestrator.analysts:
            if analyst.name == "sentiment":
                sentiment_analyst = analyst
                break

        if not sentiment_analyst:
            return {
                "enabled": False,
                "message": "Sentiment analyst not available (Phase 1 or disabled)"
            }

        try:
            # Get current sentiment data
            fear_greed_data = await sentiment_analyst.fear_greed.get_current()

            return {
                "enabled": True,
                "fear_greed": fear_greed_data,
                "note": "News sentiment is asset-specific, trigger a cycle to see full analysis"
            }
        except Exception as e:
            logger.error(f"Error fetching sentiment preview: {e}")
            return {
                "enabled": True,
                "error": str(e)
            }

    @app.get("/api/phase2/info")
    async def get_phase2_info():
        """Get Phase 2 feature status"""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")

        is_phase2 = settings.stage.value == "stage2"

        features = {
            "stage": settings.stage.value,
            "is_phase2": is_phase2,
            "features": {
                "postgres": settings.features.enable_postgres if is_phase2 else False,
                "redis_cache": hasattr(orchestrator, '_cache') and orchestrator._cache is not None,
                "sentiment_analyst": any(a.name == "sentiment" for a in orchestrator.analysts),
                "circuit_breakers": hasattr(orchestrator, '_circuit_breakers') and orchestrator._circuit_breakers is not None,
                "analyst_count": len(orchestrator.analysts)
            }
        }

        return features

    @app.get("/api/phase2/fusion")
    async def get_fusion_status():
        """Get latest intelligence fusion results (Phase 2)"""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")

        # Check if we have fusion data from the last cycle
        latest_fusion = getattr(orchestrator, '_latest_fusion', None)

        if not latest_fusion:
            return {
                "enabled": len(orchestrator.analysts) > 1,
                "latest": None,
                "message": "No fusion data yet - run a trading cycle first"
            }

        # Convert to serializable format
        fusion_data = {
            "fused_direction": latest_fusion.fused_direction,
            "fused_confidence": latest_fusion.fused_confidence,
            "disagreement": latest_fusion.disagreement,
            "regime": latest_fusion.regime.value if hasattr(latest_fusion, 'regime') and latest_fusion.regime else None,
            "signals": []
        }

        # Add individual analyst signals
        for signal in latest_fusion.signals:
            fusion_data["signals"].append({
                "source": signal.source,
                "direction": signal.direction,
                "confidence": signal.confidence,
                "reasoning": signal.reasoning
            })

        return {
            "enabled": True,
            "latest": fusion_data
        }

    @app.get("/api/phase2/execution")
    async def get_execution_stats():
        """Get limit order execution statistics (Phase 2)"""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")

        # Check if enhanced executor is being used
        executor = orchestrator.executor
        is_enhanced = hasattr(executor, 'get_stats')

        if not is_enhanced:
            return {
                "enabled": False,
                "message": "Using basic executor (market orders only)"
            }

        try:
            stats = executor.get_stats()
            return {
                "enabled": True,
                "stats": stats
            }
        except Exception as e:
            logger.error(f"Error getting execution stats: {e}")
            return {
                "enabled": True,
                "stats": {
                    "limit_orders": 0,
                    "fill_rate": None,
                    "avg_slippage": None,
                    "market_fallbacks": 0
                }
            }

    # =========================================================================
    # Cost Optimization Endpoints
    # =========================================================================

    @app.get("/api/cost/stats")
    async def get_cost_optimization_stats():
        """Get cost optimization statistics"""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")

        # Check if cost-optimized strategist is being used
        strategist = orchestrator.strategist
        has_stats = hasattr(strategist, 'get_stats')

        if not has_stats:
            return {
                "enabled": False,
                "message": "Standard strategist in use (no cost optimization)",
                "config": {
                    "batch_analysis": settings.cost_optimization.enable_batch_analysis,
                    "hybrid_mode": settings.cost_optimization.enable_hybrid_mode,
                    "decision_cache": settings.cost_optimization.enable_decision_cache,
                    "adaptive_schedule": settings.cost_optimization.enable_adaptive_schedule
                }
            }

        try:
            stats = strategist.get_stats()
            result = {
                "enabled": True,
                "stats": stats,
                "config": {
                    "batch_analysis": settings.cost_optimization.enable_batch_analysis,
                    "hybrid_mode": settings.cost_optimization.enable_hybrid_mode,
                    "decision_cache": settings.cost_optimization.enable_decision_cache,
                    "adaptive_schedule": settings.cost_optimization.enable_adaptive_schedule
                }
            }
            # Include LLM token usage if available
            if orchestrator and getattr(orchestrator, '_llm', None) and hasattr(orchestrator._llm, 'get_usage_stats'):
                result["token_usage"] = orchestrator._llm.get_usage_stats()
            return result
        except Exception as e:
            logger.error(f"Error getting cost optimization stats: {e}")
            return {
                "enabled": True,
                "error": str(e)
            }

    @app.get("/api/cost/config")
    async def get_cost_config():
        """Get cost optimization configuration"""
        cost_opt = settings.cost_optimization

        return {
            "batch_analysis": cost_opt.enable_batch_analysis,
            "hybrid_mode": cost_opt.enable_hybrid_mode,
            "adaptive_schedule": cost_opt.enable_adaptive_schedule,
            "decision_cache": cost_opt.enable_decision_cache,
            "hybrid_thresholds": {
                "direction": cost_opt.hybrid.direction_clear,
                "confidence": cost_opt.hybrid.confidence_clear,
                "disagreement": cost_opt.hybrid.disagreement_max
            },
            "cache_settings": {
                "ttl_seconds": cost_opt.cache_ttl_seconds,
                "price_deviation": cost_opt.cache_price_deviation
            },
            "risk_profile": settings.risk_profile,
            "estimated_monthly_cost": _estimate_monthly_cost(cost_opt)
        }

    @app.post("/api/cost/hybrid/toggle")
    async def toggle_hybrid_mode(request: Request):
        """Toggle hybrid mode (rule-based vs Claude LLM) at runtime."""
        global settings
        body = await request.json()
        enabled = body.get("enabled", False)

        # Update settings
        settings.cost_optimization.enable_hybrid_mode = enabled

        # Rebuild strategist stack if cost-optimized
        strategist = orchestrator.strategist if orchestrator else None
        if strategist and hasattr(strategist, '_build_stack'):
            strategist.config.enable_hybrid_mode = enabled
            strategist._build_stack()
            mode = "HYBRID (rule-based for clear signals)" if enabled else "CLAUDE LLM (all signals)"
            logger.info(f"[COST_OPT] Hybrid mode toggled: {mode}")

        return {
            "status": "ok",
            "hybrid_enabled": enabled,
            "mode": "hybrid" if enabled else "llm"
        }

    @app.get("/api/cost/hybrid/status")
    async def get_hybrid_status():
        """Get current hybrid mode status."""
        return {
            "hybrid_enabled": settings.cost_optimization.enable_hybrid_mode,
            "mode": "hybrid" if settings.cost_optimization.enable_hybrid_mode else "llm"
        }

    def _estimate_monthly_cost(cost_opt) -> str:
        """Estimate monthly API cost based on configuration."""
        base_cost = 12.0  # Base cost without optimization
        multiplier = 1.0

        if cost_opt.enable_batch_analysis:
            multiplier *= 0.34  # 66% savings
        if cost_opt.enable_hybrid_mode:
            multiplier *= 0.5   # 50% savings
        if cost_opt.enable_adaptive_schedule:
            multiplier *= 0.5   # 50% savings for small portfolios
        if cost_opt.enable_decision_cache:
            multiplier *= 0.7   # 30% savings

        estimated = base_cost * multiplier
        return f"${estimated:.2f}"

    @app.get("/api/ai/cycle/current")
    async def get_current_cycle():
        """Get current cycle timing info for dashboard countdown"""
        jobs = scheduler.get_jobs() if scheduler else []
        next_run = None
        seconds_until_next = None

        for job in jobs:
            if job.id == 'trading_cycle' and job.next_run_time:
                next_run = job.next_run_time
                seconds_until_next = max(0, (job.next_run_time - datetime.now(timezone.utc)).total_seconds())
                break

        return {
            "seconds_until_next": int(seconds_until_next) if seconds_until_next is not None else None,
            "cycle_count": orchestrator._cycle_count if orchestrator else 0,
            "is_paused": orchestrator.sentinel.is_paused if orchestrator else False,
            "scheduler_running": scheduler.running if scheduler else False,
            "next_cycle": next_run.isoformat() if next_run else None
        }

    @app.get("/api/risk/profile")
    async def get_risk_profile():
        """Get current risk profile settings"""
        return {
            "profile": settings.risk_profile,
            "effective_risk": {
                "max_position_pct": settings.get_effective_risk().max_position_pct,
                "max_total_exposure_pct": settings.get_effective_risk().max_total_exposure_pct,
                "stop_loss_pct": settings.get_effective_risk().stop_loss_pct,
                "min_confidence": settings.get_effective_risk().min_confidence,
                "max_daily_trades": settings.get_effective_risk().max_daily_trades,
                "max_daily_loss_pct": settings.get_effective_risk().max_daily_loss_pct
            },
            "aggressive_available": settings.aggressive_risk is not None,
            "pairs": settings.trading.pairs
        }

    # =========================================================================
    # Missing endpoints (required by dashboard frontend)
    # =========================================================================

    @app.get("/api/positions/detailed")
    async def get_detailed_positions():
        """Get detailed position information including stop-loss levels."""
        try:
            portfolio = await orchestrator.memory.get_portfolio()
            quote = settings.trading.quote_currency
            positions = []

            for symbol, position in portfolio.positions.items():
                stop_loss_pct = orchestrator.sentinel.stop_loss_pct if hasattr(orchestrator.sentinel, 'stop_loss_pct') else 0.05
                stop_loss_price = position.entry_price * (1 - stop_loss_pct) if position.entry_price else None

                positions.append({
                    "symbol": symbol,
                    "pair": f"{symbol}/{quote}",
                    "amount": position.amount,
                    "entry_price": position.entry_price,
                    "current_price": position.current_price,
                    "stop_loss_price": stop_loss_price,
                    "stop_loss_pct": stop_loss_pct * 100,
                    "unrealized_pnl": position.unrealized_pnl,
                    "unrealized_pnl_pct": position.unrealized_pnl_pct,
                    "value_quote": position.amount * position.current_price if position.current_price else 0
                })

            return {
                "positions": positions,
                "total_positions": len(positions),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            logger.error(f"Error fetching detailed positions: {e}")
            return {"positions": [], "error": str(e)}

    @app.get("/api/costs/usage")
    async def get_api_usage():
        """Get API token usage and costs."""
        try:
            from integrations.llm.claude import ClaudeLLM
            usage_stats = ClaudeLLM.get_usage_stats()
            return {"enabled": True, "usage": usage_stats}
        except Exception:
            return {"enabled": False, "usage": {
                "total_calls": 0, "total_input_tokens": 0, "total_output_tokens": 0,
                "total_cost_usd": 0, "input_cost_usd": 0, "output_cost_usd": 0
            }}

    @app.get("/api/costs/breakdown")
    async def get_cost_breakdown():
        """Get cost breakdown analysis."""
        try:
            from integrations.llm.claude import ClaudeLLM
            usage = ClaudeLLM.get_usage_stats()
            total_api_cost = usage.get("total_cost_usd", 0)
        except Exception:
            usage = {}
            total_api_cost = 0

        trading_pnl = 0
        if orchestrator and orchestrator.memory:
            try:
                summary = await orchestrator.memory.get_performance_summary()
                trading_pnl = summary.get("total_pnl", 0)
            except Exception:
                pass

        return {
            "api_costs_total_usd": round(total_api_cost, 4),
            "trading_pnl_usd": round(trading_pnl, 2),
            "net_profit_usd": round(trading_pnl - total_api_cost, 2),
            "efficiency": {
                "total_calls": usage.get("total_calls", 0),
                "total_tokens": usage.get("total_input_tokens", 0) + usage.get("total_output_tokens", 0),
            }
        }

    @app.get("/api/pnl/summary")
    async def get_pnl_summary():
        """Get comprehensive P&L summary."""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")

        try:
            portfolio = await orchestrator._get_portfolio_state()
            performance = await orchestrator.memory.get_performance_summary()

            realized_pnl = performance.get("total_pnl", 0)
            unrealized_pnl = sum(
                pos.current_price * pos.amount - pos.entry_price * pos.amount
                for pos in portfolio.positions.values()
                if pos.entry_price and pos.entry_price > 0
            )

            try:
                from integrations.llm.claude import ClaudeLLM
                api_cost = ClaudeLLM.get_usage_stats().get("total_cost_usd", 0)
            except Exception:
                api_cost = 0

            return {
                "realized_pnl": round(realized_pnl, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "total_pnl": round(realized_pnl + unrealized_pnl, 2),
                "api_costs": {"total_usd": round(api_cost, 4)},
                "net_profit": round(realized_pnl + unrealized_pnl - api_cost, 2),
                "portfolio_value": round(portfolio.total_value, 2),
                "initial_capital": settings.trading.initial_capital,
                "target_value": settings.trading.target_capital,
                "progress_pct": round(portfolio.progress_to_target, 2),
                "win_rate": performance.get("win_rate", 0),
                "profit_factor": performance.get("profit_factor", 0),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting P&L summary: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/pnl/by-pair")
    async def get_pnl_by_pair():
        """Get P&L breakdown by trading pair."""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")

        try:
            trades = await orchestrator.memory.get_trade_history(1000)
            by_pair = {}
            for trade in trades:
                pair = trade.pair
                if pair not in by_pair:
                    by_pair[pair] = {"realized_pnl": 0, "trade_count": 0, "wins": 0, "losses": 0}

                pnl = getattr(trade, 'realized_pnl', 0) or 0
                by_pair[pair]["realized_pnl"] += pnl
                by_pair[pair]["trade_count"] += 1
                if pnl > 0:
                    by_pair[pair]["wins"] += 1
                elif pnl < 0:
                    by_pair[pair]["losses"] += 1

            for pair in by_pair:
                total = by_pair[pair]["trade_count"]
                wins = by_pair[pair]["wins"]
                by_pair[pair]["win_rate"] = wins / total if total > 0 else 0

            return {"pairs": by_pair}
        except Exception as e:
            logger.error(f"Error getting P&L by pair: {e}")
            return {"pairs": {}}

    @app.get("/api/trades/rejected")
    async def get_rejected_trades(limit: int = 100):
        """Get rejected trade signals."""
        try:
            if hasattr(orchestrator.memory, 'get_rejected_trades'):
                rejected = await orchestrator.memory.get_rejected_trades(limit)
                return {"trades": [r.to_dict() if hasattr(r, 'to_dict') else r for r in rejected]}
            return {"trades": []}
        except Exception as e:
            logger.error(f"Error getting rejected trades: {e}")
            return {"trades": []}

    @app.get("/api/settings")
    async def get_settings_api():
        """Get current settings for the settings page."""
        effective = settings.get_effective_risk()
        return {
            "risk": {
                "max_position_pct": effective.max_position_pct,
                "max_exposure_pct": effective.max_total_exposure_pct,
                "stop_loss_pct": effective.stop_loss_pct,
                "min_confidence": effective.min_confidence,
                "max_daily_trades": effective.max_daily_trades,
                "max_daily_loss_pct": effective.max_daily_loss_pct
            },
            "circuit_breakers": {
                "max_daily_loss_pct": effective.max_daily_loss_pct,
                "max_daily_trades": effective.max_daily_trades,
                "volatility_threshold_pct": 0.10,
                "consecutive_loss_limit": 3
            },
            "analyst_weights": {
                "technical": 0.45, "sentiment": 0.35, "onchain": 0.15, "macro": 0.05
            },
            "trading": {
                "pairs": settings.trading.pairs,
                "quote_currency": settings.trading.quote_currency,
                "initial_capital": settings.trading.initial_capital,
                "target_capital": settings.trading.target_capital,
                "check_interval_minutes": settings.trading.check_interval_minutes
            },
            "risk_profile": settings.risk_profile,
            "stage": settings.stage.value,
            "simulation_mode": settings.features.simulation_mode
        }

    @app.put("/api/settings")
    async def update_settings_api(body: dict):
        """Update runtime settings."""
        section = body.get("section", "")
        updates = body.get("updates", {})

        if not section or not updates:
            raise HTTPException(status_code=400, detail="Missing section or updates")

        applied = {}

        if section == "risk":
            effective = settings.get_effective_risk()
            for key, value in updates.items():
                if hasattr(effective, key):
                    setattr(effective, key, value)
                    applied[key] = value

        elif section == "trading":
            for key, value in updates.items():
                if hasattr(settings.trading, key):
                    setattr(settings.trading, key, value)
                    applied[key] = value

        elif section == "cost_optimization":
            # Store cost optimization config in-memory (no persistent model for this)
            applied = updates

        elif section == "analyst_weights":
            if orchestrator:
                for analyst in orchestrator.analysts:
                    if analyst.name in updates:
                        analyst.weight = float(updates[analyst.name])
                        applied[analyst.name] = analyst.weight

        else:
            raise HTTPException(status_code=400, detail=f"Unknown section: {section}")

        logger.info(f"Settings updated [{section}]: {applied}")
        return {"status": "ok", "section": section, "applied": applied}

    # ------------------------------------------------------------------
    # AI Activity / Intel / Patterns endpoints (for Charts page)
    # ------------------------------------------------------------------

    @app.get("/api/ai/activity")
    async def get_ai_activity(limit: int = 20):
        """Return recent trading activity events from the event bus."""
        from core.events import get_event_bus, EventType
        bus = get_event_bus()

        activities = []
        for et in (EventType.TRADE_EXECUTED, EventType.INTEL_FUSED, EventType.STOP_LOSS_TRIGGERED):
            for ev in bus.get_history(event_type=et, limit=limit):
                activities.append({
                    "type": et.value,
                    "data": ev.data,
                    "timestamp": ev.timestamp.isoformat(),
                    "source": ev.source,
                })

        # Sort newest-first, cap to limit
        activities.sort(key=lambda a: a["timestamp"], reverse=True)
        return {"activities": activities[:limit]}

    @app.get("/api/ai/intel")
    async def get_ai_intel():
        """Return latest fused intel for all pairs."""
        if not orchestrator:
            return {"intel": {}}

        intel_data = {}
        latest = getattr(orchestrator, "_latest_intel", {})
        for pair, intel in latest.items():
            intel_data[pair] = {
                "pair": pair,
                "direction": intel.fused_direction,
                "confidence": intel.fused_confidence,
                "regime": intel.regime.value if hasattr(intel.regime, "value") else str(intel.regime),
                "disagreement": getattr(intel, "disagreement", 0),
                "signal_count": len(intel.signals) if intel.signals else 0,
                "timestamp": intel.timestamp.isoformat() if hasattr(intel, "timestamp") and intel.timestamp else None,
            }
        return {"intel": intel_data}

    @app.get("/api/ai/patterns/{pair:path}")
    async def get_ai_patterns(pair: str):
        """Return detected candlestick patterns from latest analysis."""
        pair = pair.replace("-", "/").upper()
        if "/" not in pair and len(pair) >= 6:
            pair = f"{pair[:-4]}/{pair[-4:]}"

        patterns = []

        # Pull pattern data from latest intel signals
        if orchestrator:
            latest = getattr(orchestrator, "_latest_intel", {})
            intel = latest.get(pair)
            if intel and intel.signals:
                for sig in intel.signals:
                    meta = getattr(sig, "metadata", {}) or {}

                    # Check for "patterns" list (structured format)
                    if meta.get("patterns"):
                        for p in meta["patterns"]:
                            patterns.append(p)

                    # Extract from per-timeframe keys: {tf}_candle_pattern / {tf}_candle_signal
                    seen_tf = set()
                    for key, val in meta.items():
                        if key.endswith("_candle_pattern") and val:
                            tf = key.replace("_candle_pattern", "")
                            if tf in seen_tf:
                                continue
                            seen_tf.add(tf)
                            signal_val = meta.get(f"{tf}_candle_signal", 0)
                            patterns.append({
                                "name": val,
                                "timeframe": tf,
                                "signal": signal_val,
                                "direction": "bullish" if signal_val > 0 else "bearish",
                                "strength": abs(signal_val),
                                "timestamp": (intel.timestamp.isoformat()
                                              if hasattr(intel, "timestamp") and intel.timestamp
                                              else None),
                            })

        # Also check event bus for pattern events
        from core.events import get_event_bus, EventType
        bus = get_event_bus()
        for ev in bus.get_history(event_type=EventType.ANALYST_SIGNAL, limit=50):
            if ev.data.get("pair") == pair and ev.data.get("patterns"):
                for p in ev.data["patterns"]:
                    patterns.append({
                        **p,
                        "timestamp": ev.timestamp.isoformat(),
                    })

        return {"pair": pair, "patterns": patterns}

    @app.get("/api/market/ohlcv/{pair:path}")
    async def get_market_ohlcv(pair: str, interval: int = 60, limit: int = 100):
        """Get OHLCV data for a trading pair."""
        try:
            pair = pair.replace("-", "/").upper()
            if "/" not in pair and len(pair) >= 6:
                pair = f"{pair[:-4]}/{pair[-4:]}"

            ohlcv = await orchestrator.exchange.get_ohlcv(pair, interval=interval, limit=limit)
            return {
                "pair": pair,
                "interval": interval,
                "candles": ohlcv if ohlcv else [],
                "count": len(ohlcv) if ohlcv else 0
            }
        except Exception as e:
            logger.error(f"Error fetching OHLCV for {pair}: {e}")
            return {"candles": [], "pair": pair, "error": str(e)}

    @app.get("/api/profit-tracker")
    async def get_profit_tracker():
        """Daily profit tracking: latest snapshot state + recent table rows.
        Used by the Kraken Expander at 7 PM to assess profit/stagnation."""
        import json as _json
        state: dict = {}
        table_rows: list = []
        if os.path.exists(_PROFIT_STATE_FILE):
            try:
                with open(_PROFIT_STATE_FILE, "r", encoding="utf-8") as fh:
                    state = _json.load(fh)
            except Exception as exc:
                logger.warning("/api/profit-tracker state read error: %s", exc)
        if os.path.exists(_PROFIT_TABLE_FILE):
            try:
                with open(_PROFIT_TABLE_FILE, "r", encoding="utf-8") as fh:
                    lines = fh.readlines()
                table_rows = [
                    l.strip() for l in lines
                    if l.startswith("|") and "Date" not in l and "---" not in l
                ][-14:]
            except Exception as exc:
                logger.warning("/api/profit-tracker table read error: %s", exc)
        return {
            "today_status": state.get("today_status", "NO_DATA"),
            "today_pnl": state.get("today_pnl", 0),
            "today_pnl_pct": state.get("today_pnl_pct", 0),
            "stagnant_streak": state.get("stagnant_streak", False),
            "consecutive_losses": state.get("consecutive_losses", 0),
            "last_snapshot_date": state.get("last_snapshot_date"),
            "last_snapshot_ts": state.get("last_snapshot_ts"),
            "portfolio_value": state.get("last_snapshot_value", 0),
            "total_pnl": state.get("total_pnl", 0),
            "total_pnl_pct": state.get("total_pnl_pct", 0),
            "recent_daily_results": state.get("recent_daily_results", []),
            "table_rows": table_rows,
        }

    @app.post("/api/profit-tracker/snapshot")
    async def trigger_profit_snapshot():
        """Manually trigger the 5:59 PM profit snapshot (testing / backfill)."""
        result = await _run_daily_profit_snapshot()
        return {
            "status": "ok",
            "today_status": result.get("today_status"),
            "today_pnl": result.get("today_pnl"),
            "today_pnl_pct": result.get("today_pnl_pct"),
            "stagnant_streak": result.get("stagnant_streak"),
            "consecutive_losses": result.get("consecutive_losses"),
        }

    # =========================================================================
    # Daily Profit Ledger Endpoints
    # =========================================================================

    @app.get("/api/daily-profit")
    async def get_daily_profit(days: int = 30):
        """Daily profit ledger — portfolio start/end values and P&L for each day."""
        from datetime import date as _date

        entries = []
        streak = {"streak_type": "none", "streak_days": 0, "profit_days": 0, "loss_days": 0}

        if orchestrator and hasattr(orchestrator.memory, "get_daily_ledger"):
            try:
                rows = await orchestrator.memory.get_daily_ledger(days)
                for r in rows:
                    entries.append({
                        "date": r["date"].isoformat() if hasattr(r["date"], "isoformat") else str(r["date"]),
                        "start_value": float(r.get("start_value", 0)),
                        "end_value": float(r.get("end_value", 0)),
                        "daily_pnl": float(r.get("daily_pnl", 0)),
                        "daily_pnl_pct": float(r.get("daily_pnl_pct", 0)),
                        "realized_pnl": float(r.get("realized_pnl", 0)),
                        "unrealized_pnl": float(r.get("unrealized_pnl", 0)),
                        "total_trades": r.get("total_trades", 0),
                        "wins": r.get("wins", 0),
                        "losses": r.get("losses", 0),
                        "win_rate": float(r.get("win_rate", 0)),
                        "main_pnl": float(r.get("main_pnl", 0)),
                        "meme_pnl": float(r.get("meme_pnl", 0)),
                        "fees_total": float(r.get("fees_total", 0)),
                        "status": r.get("status", "NO_DATA"),
                        "improvement_action": r.get("improvement_action"),
                        "improvement_result": r.get("improvement_result"),
                    })
            except Exception as exc:
                logger.warning("/api/daily-profit ledger read error: %s", exc)

        if orchestrator and hasattr(orchestrator.memory, "get_daily_profit_streak"):
            try:
                streak = await orchestrator.memory.get_daily_profit_streak()
            except Exception:
                pass

        # Calculate cumulative P&L from entries
        cumulative_pnl = 0.0
        for entry in reversed(entries):
            cumulative_pnl += entry["daily_pnl"]
            entry["cumulative_pnl"] = round(cumulative_pnl, 8)

        return {
            "entries": entries,
            "streak": streak,
            "total_days": len(entries),
            "profit_days": sum(1 for e in entries if e["status"] == "PROFIT"),
            "loss_days": sum(1 for e in entries if e["status"] == "LOSS"),
            "stagnant_days": sum(1 for e in entries if e["status"] == "STAGNANT"),
            "cumulative_pnl": cumulative_pnl,
        }

    @app.get("/api/daily-profit/today")
    async def get_daily_profit_today():
        """Today's daily profit status — real-time before snapshot."""
        from datetime import date as _date
        today = _date.today()

        # Check if snapshot already taken
        entry = None
        if orchestrator and hasattr(orchestrator.memory, "get_daily_ledger_entry"):
            try:
                entry = await orchestrator.memory.get_daily_ledger_entry(today)
            except Exception:
                pass

        if entry:
            return {
                "snapshot_taken": True,
                "date": today.isoformat(),
                "start_value": float(entry.get("start_value", 0)),
                "end_value": float(entry.get("end_value", 0)),
                "daily_pnl": float(entry.get("daily_pnl", 0)),
                "daily_pnl_pct": float(entry.get("daily_pnl_pct", 0)),
                "status": entry.get("status", "NO_DATA"),
                "total_trades": entry.get("total_trades", 0),
                "improvement_action": entry.get("improvement_action"),
            }

        # No snapshot yet — provide a live estimate
        portfolio_value = 0.0
        start_value = 0.0
        if orchestrator:
            try:
                pf = await orchestrator._get_portfolio_state()
                portfolio_value = pf.total_value
            except Exception:
                pass
            if hasattr(orchestrator.memory, "get_previous_day_end_value"):
                try:
                    prev = await orchestrator.memory.get_previous_day_end_value(today)
                    if prev is not None:
                        start_value = prev
                except Exception:
                    pass
            if start_value == 0:
                start_value = portfolio_value

        live_pnl = portfolio_value - start_value
        live_pnl_pct = (live_pnl / start_value * 100) if start_value > 0 else 0.0

        return {
            "snapshot_taken": False,
            "date": today.isoformat(),
            "start_value": start_value,
            "current_value": portfolio_value,
            "live_pnl": live_pnl,
            "live_pnl_pct": live_pnl_pct,
            "status": "LIVE",
        }

    # Cache-control: prevent stale JS/CSS/HTML
    @app.middleware("http")
    async def add_cache_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/dashboard"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

    # Serve dashboard static files
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/dashboard", StaticFiles(directory=str(static_dir), html=True), name="static")


# Create default app instance
app = create_app()

