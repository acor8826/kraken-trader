"""
FastAPI Application

HTTP interface for the trading agent.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
import logging
import time

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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
    from agents.orchestrator import Orchestrator
    from memory import InMemoryStore

    # Exchange
    if settings.features.simulation_mode:
        # Try enhanced simulation first
        try:
            from integrations.exchanges.simulation import SimulationExchange, SimulationConfig, MarketScenario
            import os

            # Get scenario from environment or default to ranging
            scenario_name = os.getenv("SIMULATION_SCENARIO", "ranging")
            try:
                scenario = MarketScenario(scenario_name)
            except ValueError:
                scenario = MarketScenario.RANGING

            sim_config = SimulationConfig(
                initial_balance=settings.trading.initial_capital,
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
            exchange = MockExchange(initial_balance=settings.trading.initial_capital)
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
    if settings.stage.value == "stage2" and settings.features.enable_postgres:
        try:
            from memory.postgres import PostgresStore
            from memory.redis_cache import RedisCache

            # Initialize Redis cache
            redis_url = settings.config.get("redis", {}).get("url", "redis://localhost:6379")
            cache_ttl = settings.config.get("redis", {}).get("cache_ttl_seconds", 300)
            cache = RedisCache(redis_url, default_ttl=cache_ttl)
            await cache.connect()
            logger.info(f"Redis cache connected (TTL={cache_ttl}s)")

            # Initialize PostgreSQL
            db_url = settings.config.get("database", {}).get("url", "postgresql://trader:trader@localhost:5432/trader")
            memory = PostgresStore(db_url)
            await memory.connect()
            logger.info("PostgreSQL storage connected")
        except Exception as e:
            logger.warning(f"Failed to initialize Phase 2 storage: {e}")
            logger.info("Falling back to in-memory storage")
            memory = InMemoryStore(initial_capital=settings.trading.initial_capital)
    else:
        memory = InMemoryStore(initial_capital=settings.trading.initial_capital)
        logger.info("Using in-memory storage (Phase 1)")

    # =========================================================================
    # Cost-Optimized Strategist
    # =========================================================================
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
        # Check if we should use Advanced Strategist for Stage 2+
        if settings.stage.value in ["stage2", "stage3"] and hasattr(settings, 'features') and getattr(settings.features, 'enable_advanced_strategies', False):
            from agents.strategist.advanced import AdvancedStrategist
            strategist = AdvancedStrategist(llm, settings, exchange)
            logger.info("Using Advanced Strategist with volatility-aware take-profits")
        else:
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

    # Analysts - Phase 2: Technical + Sentiment
    analysts = [TechnicalAnalyst()]
    logger.info("✅ Technical analyst initialized")

    if settings.stage.value == "stage2" and settings.features.enable_sentiment_analyst:
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

    # Sentinel - Phase 2: Enhanced with Circuit Breakers
    if settings.stage.value == "stage2" and settings.features.enable_circuit_breakers:
        try:
            from agents.sentinel.circuit_breakers import CircuitBreakers

            circuit_breakers = CircuitBreakers(
                max_daily_loss_pct=settings.config.get("circuit_breakers", {}).get("max_daily_loss_pct", 0.10),
                max_daily_trades=settings.config.get("circuit_breakers", {}).get("max_daily_trades", 15),
                volatility_threshold_pct=settings.config.get("circuit_breakers", {}).get("volatility_threshold_pct", 0.10),
                consecutive_loss_limit=settings.config.get("circuit_breakers", {}).get("consecutive_loss_limit", 3)
            )
            logger.info("✅ Circuit breakers initialized")

            # TODO: Create EnhancedSentinel that uses circuit_breakers
            # For now, use BasicSentinel with exchange for volatility-aware stops
            sentinel = BasicSentinel(memory, settings, exchange)
            sentinel.circuit_breakers = circuit_breakers  # Attach for manual use
        except Exception as e:
            logger.warning(f"Failed to initialize circuit breakers: {e}")
            sentinel = BasicSentinel(memory, settings, exchange)
    else:
        sentinel = BasicSentinel(memory, settings, exchange)

    # Executor
    executor = SimpleExecutor(exchange, memory, settings)

    # Orchestrator
    orch = Orchestrator(
        exchange=exchange,
        analysts=analysts,
        strategist=strategist,
        sentinel=sentinel,
        executor=executor,
        memory=memory,
        settings=settings
    )

    # Attach cache and circuit breakers for access in routes
    orch._cache = cache
    orch._circuit_breakers = getattr(sentinel, 'circuit_breakers', None)

    # =========================================================================
    # Alert Manager
    # =========================================================================
    global alert_manager
    from core.alerts import AlertManager, ConsoleChannel, FileChannel, WebhookChannel

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

    logger.info(f"🚀 Orchestrator initialized ({len(analysts)} analysts)")
    return orch


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

    @app.get("/")
    async def root():
        """Redirect to dashboard"""
        return RedirectResponse(url="/dashboard/index.html")

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
        """Get current portfolio state with enhanced risk levels (cached for 30s)"""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")

        result = await _get_cached_portfolio()
        if result is None:
            raise HTTPException(status_code=500, detail="Portfolio data unavailable")
        
        # Enhance with volatility-aware risk levels if available
        try:
            if hasattr(orchestrator, 'sentinel') and orchestrator.sentinel:
                portfolio = await orchestrator._get_portfolio_state()
                risk_levels = await orchestrator.sentinel.get_position_risk_levels(portfolio.positions)
                
                # Add risk levels to the result
                result['risk_levels'] = risk_levels
                
                logger.debug(f"[API] Enhanced portfolio with risk levels for {len(risk_levels)} positions")
            
        except Exception as e:
            logger.warning(f"[API] Failed to calculate portfolio risk levels: {e}")
            # Continue without risk levels
        
        return result
    
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
            if hasattr(orchestrator, 'llm') and orchestrator.llm and hasattr(orchestrator.llm, 'get_usage_stats'):
                result["token_usage"] = orchestrator.llm.get_usage_stats()
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
            "pairs": settings.trading.pairs,
            "volatility_enabled": settings.config.get("volatility_risk", {}).get("enabled", True)
        }

    @app.get("/api/volatility/profiles")
    async def get_volatility_profiles():
        """Get volatility profiles for all trading pairs"""
        if not orchestrator or not orchestrator.sentinel:
            raise HTTPException(status_code=503, detail="Agent not initialized")
        
        if not orchestrator.sentinel.volatility_enabled:
            return {
                "enabled": False,
                "message": "Volatility-based risk management disabled"
            }
        
        try:
            profiles = {}
            for pair in settings.trading.pairs:
                try:
                    profile = await orchestrator.sentinel.volatility_calculator.get_volatility_profile(
                        pair, orchestrator.exchange
                    )
                    profiles[pair] = {
                        "asset": profile.asset,
                        "atr_14": profile.atr_14,
                        "atr_pct": profile.atr_pct,
                        "volatility_rank": profile.volatility_rank,
                        "suggested_stop_loss_pct": profile.suggested_stop_loss_pct,
                        "suggested_take_profit_pct": profile.suggested_take_profit_pct,
                        "confidence": profile.confidence,
                        "last_updated": profile.last_updated.isoformat()
                    }
                except Exception as e:
                    logger.warning(f"Failed to get volatility profile for {pair}: {e}")
                    profiles[pair] = {"error": str(e)}
            
            return {
                "enabled": True,
                "profiles": profiles,
                "config": {
                    "atr_period": orchestrator.sentinel.volatility_calculator.config.atr_period,
                    "low_volatility_threshold": orchestrator.sentinel.volatility_calculator.config.low_volatility_threshold,
                    "high_volatility_threshold": orchestrator.sentinel.volatility_calculator.config.high_volatility_threshold
                }
            }
        except Exception as e:
            logger.error(f"Error getting volatility profiles: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/volatility/profile/{pair}")
    async def get_volatility_profile(pair: str):
        """Get volatility profile for a specific trading pair"""
        if not orchestrator or not orchestrator.sentinel:
            raise HTTPException(status_code=503, detail="Agent not initialized")
        
        if not orchestrator.sentinel.volatility_enabled:
            raise HTTPException(status_code=400, detail="Volatility-based risk management disabled")
        
        try:
            # Force refresh to get latest data
            profile = await orchestrator.sentinel.volatility_calculator.get_volatility_profile(
                pair, orchestrator.exchange, force_refresh=True
            )
            
            return {
                "pair": pair,
                "asset": profile.asset,
                "atr_14": profile.atr_14,
                "atr_pct": profile.atr_pct,
                "volatility_rank": profile.volatility_rank,
                "suggested_stop_loss_pct": profile.suggested_stop_loss_pct,
                "suggested_take_profit_pct": profile.suggested_take_profit_pct,
                "confidence": profile.confidence,
                "last_updated": profile.last_updated.isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting volatility profile for {pair}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # Serve dashboard static files
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/dashboard", StaticFiles(directory=str(static_dir), html=True), name="static")


# Create default app instance
app = create_app()
