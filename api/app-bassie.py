"""
FastAPI Application

HTTP interface for the trading agent.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
import logging

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
        logger.info(f"Target: ${settings.trading.initial_capital} -> ${settings.trading.target_capital}")
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
        scheduler.start()
        
        logger.info(f"Scheduler started: every {settings.trading.check_interval_minutes} minutes")
        
        yield
        
        # Shutdown
        if scheduler:
            scheduler.shutdown()
        logger.info("Trading agent stopped")
    
    app = FastAPI(
        title="Kraken Trading Agent",
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
    from integrations.exchanges import KrakenExchange, MockExchange
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
        exchange = KrakenExchange()
        logger.info("Using LIVE Kraken exchange")

    # LLM
    llm = None
    if settings.llm.api_key:
        llm = ClaudeLLM(model=settings.llm.model)
        logger.info("Using Claude LLM for decisions")
    else:
        logger.info("No LLM configured - will use rule-based strategist")

    # Memory - Phase 2: PostgreSQL or Phase 1: In-Memory
    cache = None
    db_pool = None  # Database pool for auth service
    if settings.stage.value == "stage2" and settings.features.enable_postgres:
        try:
            from memory.postgres import PostgresStore
            from memory.redis_cache import RedisCache

            # Initialize Redis cache (use env vars)
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            cache_ttl = 300
            cache = RedisCache(redis_url, default_ttl=cache_ttl)
            await cache.connect()
            logger.info(f"Redis cache connected (TTL={cache_ttl}s)")

            # Initialize PostgreSQL (use env vars)
            db_url = os.getenv("DATABASE_URL", "postgresql://trader:trader@localhost:5432/trader")
            memory = PostgresStore(db_url)
            await memory.connect()
            db_pool = memory._pool  # Get pool for auth service (private attr)
            logger.info("PostgreSQL storage connected")
        except Exception as e:
            logger.warning(f"Failed to initialize Phase 2 storage: {e}")
            logger.info("Falling back to in-memory storage")
            memory = InMemoryStore(initial_capital=settings.trading.initial_capital)
    else:
        memory = InMemoryStore(initial_capital=settings.trading.initial_capital)
        logger.info("Using in-memory storage (Phase 1)")

    # Initialize auth service with database pool (if available)
    try:
        from core.auth.service import auth_service
        if db_pool:
            auth_service.set_pool(db_pool)
            logger.info("[AUTH] Auth service initialized with PostgreSQL")
        else:
            logger.info("[AUTH] Auth service running without database (limited functionality)")
    except Exception as e:
        logger.warning(f"[AUTH] Failed to initialize auth service: {e}")

    # Initialize in-memory cache for decision caching (Stage 1)
    cost_opt = settings.cost_optimization
    if cache is None and cost_opt.enable_decision_cache:
        from memory.inmemory_cache import InMemoryCache
        cache_ttl = cost_opt.cache_ttl_seconds
        cache = InMemoryCache(default_ttl=cache_ttl)
        await cache.connect()
        logger.info(f"[CACHE] In-memory decision cache enabled (TTL={cache_ttl}s)")

    # =========================================================================
    # Cost-Optimized Strategist
    # =========================================================================
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
                max_daily_loss_pct=0.10,
                max_daily_trades=15,
                volatility_threshold_pct=0.10,
                consecutive_loss_limit=3
            )
            logger.info("✅ Circuit breakers initialized")

            # TODO: Create EnhancedSentinel that uses circuit_breakers
            # For now, use BasicSentinel
            sentinel = BasicSentinel(memory, settings)
            sentinel.circuit_breakers = circuit_breakers  # Attach for manual use
        except Exception as e:
            logger.warning(f"Failed to initialize circuit breakers: {e}")
            sentinel = BasicSentinel(memory, settings)
    else:
        sentinel = BasicSentinel(memory, settings)

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

    # Register auth router
    from api.routes.auth import router as auth_router
    app.include_router(auth_router)

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

        # Update metrics from current state if orchestrator is available
        if orchestrator:
            try:
                portfolio = await orchestrator._get_portfolio_state()
                metrics_collector.update_portfolio(
                    value=portfolio.total_value,
                    pnl=portfolio.total_pnl,
                    pnl_pct=portfolio.pnl_percent,
                    progress=portfolio.progress_to_target,
                    position_count=len(portfolio.positions)
                )
            except Exception as e:
                logger.debug(f"Metrics portfolio update failed: {e}")

        return get_metrics_response()
    
    @app.get("/portfolio")
    async def get_portfolio():
        """Get current portfolio state"""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")
        
        try:
            portfolio = await orchestrator._get_portfolio_state()
            return portfolio.to_dict()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
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
            # Send initial portfolio state
            if orchestrator:
                portfolio = await orchestrator._get_portfolio_state()
                await websocket.send_json({
                    "type": "connection",
                    "message": "Connected to portfolio stream",
                    "connection_id": connection_id,
                    "initial_portfolio": portfolio.to_dict()
                })

            # Keep connection alive and handle ping/pong
            while True:
                try:
                    data = await websocket.receive_text()
                    if data == "ping":
                        await websocket.send_text("pong")
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
            return {
                "enabled": True,
                "stats": stats,
                "config": {
                    "batch_analysis": settings.cost_optimization.enable_batch_analysis,
                    "hybrid_mode": settings.cost_optimization.enable_hybrid_mode,
                    "decision_cache": settings.cost_optimization.enable_decision_cache,
                    "adaptive_schedule": settings.cost_optimization.enable_adaptive_schedule
                }
            }
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
            "pairs": settings.trading.pairs
        }

    # =========================================================================
    # API Usage & Cost Tracking Endpoints (Actual Token Usage)
    # =========================================================================

    @app.get("/api/costs/usage")
    async def get_api_usage():
        """Get actual API token usage and costs from Claude LLM."""
        try:
            from integrations.llm.claude import ClaudeLLM
            usage_stats = ClaudeLLM.get_usage_stats()
            return {
                "enabled": True,
                "usage": usage_stats,
                "pricing": {
                    "model": "claude-sonnet-4-20250514",
                    "input_per_1k": 0.003,
                    "output_per_1k": 0.015
                }
            }
        except Exception as e:
            logger.error(f"Error getting API usage: {e}")
            return {
                "enabled": False,
                "error": str(e)
            }

    @app.get("/api/costs/breakdown")
    async def get_cost_breakdown():
        """Get break-even analysis for API costs vs trading P&L."""
        try:
            from integrations.llm.claude import ClaudeLLM
            from core.analytics.cost_tracker import CostTracker

            usage = ClaudeLLM.get_usage_stats()
            total_api_cost = usage.get("total_cost_usd", 0)

            # Get trading P&L from memory
            if orchestrator and orchestrator.memory:
                summary = await orchestrator.memory.get_performance_summary()
                trading_pnl = summary.get("total_pnl", 0)
            else:
                trading_pnl = 0

            net_profit = trading_pnl - total_api_cost
            break_even = trading_pnl >= total_api_cost
            profit_margin = ((trading_pnl - total_api_cost) / total_api_cost * 100) if total_api_cost > 0 else 0

            return {
                "api_costs_total_usd": round(total_api_cost, 4),
                "trading_pnl_usd": round(trading_pnl, 2),
                "net_profit_usd": round(net_profit, 2),
                "break_even_achieved": break_even,
                "profit_margin_pct": round(profit_margin, 2),
                "efficiency": {
                    "total_calls": usage.get("total_calls", 0),
                    "total_tokens": usage.get("total_input_tokens", 0) + usage.get("total_output_tokens", 0),
                    "cost_per_call": round(total_api_cost / usage.get("total_calls", 1), 4) if usage.get("total_calls", 0) > 0 else 0
                }
            }
        except Exception as e:
            logger.error(f"Error getting cost breakdown: {e}")
            return {"error": str(e)}

    # =========================================================================
    # P&L Tracking Endpoints
    # =========================================================================

    @app.get("/api/pnl/summary")
    async def get_pnl_summary():
        """Get comprehensive P&L summary including API costs."""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")

        try:
            # Get portfolio state
            portfolio = await orchestrator._get_portfolio_state()

            # Get performance data
            performance = await orchestrator.memory.get_performance_summary()

            # Get API costs
            from integrations.llm.claude import ClaudeLLM
            usage = ClaudeLLM.get_usage_stats()
            api_cost = usage.get("total_cost_usd", 0)

            realized_pnl = performance.get("total_pnl", 0)
            unrealized_pnl = sum(
                pos.current_price * pos.amount - pos.entry_price * pos.amount
                for pos in portfolio.positions.values()
                if pos.entry_price and pos.entry_price > 0
            )

            return {
                "realized_pnl": round(realized_pnl, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "total_pnl": round(realized_pnl + unrealized_pnl, 2),
                "api_costs": {
                    "total_usd": round(api_cost, 4),
                    "today_usd": round(usage.get("cost_today_usd", 0), 4)
                },
                "net_profit": round(realized_pnl + unrealized_pnl - api_cost, 2),
                "portfolio_value": round(portfolio.total_value, 2),
                "initial_capital": settings.trading.initial_capital,
                "target_value": settings.trading.target_capital,
                "progress_pct": round(portfolio.progress_to_target, 2),
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
            trades = await orchestrator.memory.get_trades(limit=1000)

            by_pair = {}
            for trade in trades:
                pair = trade.pair
                if pair not in by_pair:
                    by_pair[pair] = {
                        "realized_pnl": 0,
                        "trade_count": 0,
                        "wins": 0,
                        "losses": 0
                    }

                pnl = trade.realized_pnl or 0
                by_pair[pair]["realized_pnl"] += pnl
                by_pair[pair]["trade_count"] += 1
                if pnl > 0:
                    by_pair[pair]["wins"] += 1
                elif pnl < 0:
                    by_pair[pair]["losses"] += 1

            # Calculate win rates
            for pair in by_pair:
                total = by_pair[pair]["trade_count"]
                wins = by_pair[pair]["wins"]
                by_pair[pair]["win_rate"] = wins / total if total > 0 else 0

            return {"pairs": by_pair}
        except Exception as e:
            logger.error(f"Error getting P&L by pair: {e}")
            return {"pairs": {}}

    # =========================================================================
    # Dynamic Pairs Endpoints
    # =========================================================================

    @app.get("/api/pairs/available")
    async def get_available_pairs():
        """Get all discoverable AUD pairs from Kraken."""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")

        try:
            if hasattr(orchestrator.exchange, 'get_all_pairs'):
                pairs = await orchestrator.exchange.get_all_pairs("AUD")
                return {
                    "count": len(pairs),
                    "pairs": pairs
                }
            else:
                return {
                    "count": len(settings.trading.pairs),
                    "pairs": [{"pair": p} for p in settings.trading.pairs],
                    "note": "Static pair list (exchange does not support discovery)"
                }
        except Exception as e:
            logger.error(f"Error getting available pairs: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/pairs/tradable")
    async def get_tradable_pairs(min_volume: float = 1000):
        """Get tradable pairs filtered by volume."""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")

        try:
            if hasattr(orchestrator.exchange, 'get_tradable_pairs'):
                pairs = await orchestrator.exchange.get_tradable_pairs(
                    quote_currency="AUD",
                    min_volume_24h=min_volume
                )
                return {
                    "count": len(pairs),
                    "min_volume": min_volume,
                    "pairs": pairs
                }
            else:
                return {
                    "count": len(settings.trading.pairs),
                    "pairs": settings.trading.pairs,
                    "note": "Static pair list"
                }
        except Exception as e:
            logger.error(f"Error getting tradable pairs: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # =========================================================================
    # Portfolio-Scaled Risk Endpoints
    # =========================================================================

    @app.get("/api/risk/scaled")
    async def get_scaled_risk():
        """Get portfolio-scaled risk configuration."""
        if not orchestrator:
            raise HTTPException(status_code=503, detail="Agent not initialized")

        try:
            from core.risk.portfolio_scaled import get_scaled_config_dict

            portfolio = await orchestrator._get_portfolio_state()
            scaled_config = get_scaled_config_dict(portfolio.total_value)

            return scaled_config
        except Exception as e:
            logger.error(f"Error getting scaled risk: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # =========================================================================
    # Journal & Reflection Endpoints
    # =========================================================================

    @app.get("/api/journal/entries")
    async def get_journal_entries(
        pair: Optional[str] = None,
        outcome: Optional[str] = None,
        limit: int = 50
    ):
        """Get trade journal entries."""
        try:
            # Check if journal is available
            if hasattr(orchestrator, 'trade_journal') and orchestrator.trade_journal:
                entries = await orchestrator.trade_journal.get_entries(
                    pair=pair,
                    outcome=outcome,
                    limit=limit
                )
                return {
                    "count": len(entries),
                    "entries": [e.to_dict() for e in entries]
                }
            else:
                return {
                    "count": 0,
                    "entries": [],
                    "note": "Trade journal not initialized"
                }
        except Exception as e:
            logger.error(f"Error getting journal entries: {e}")
            return {"count": 0, "entries": [], "error": str(e)}

    @app.get("/api/journal/stats")
    async def get_journal_stats(days: int = 30):
        """Get journal summary statistics."""
        try:
            if hasattr(orchestrator, 'trade_journal') and orchestrator.trade_journal:
                stats = await orchestrator.trade_journal.get_summary_stats(days=days)
                return stats
            else:
                return {"note": "Trade journal not initialized"}
        except Exception as e:
            logger.error(f"Error getting journal stats: {e}")
            return {"error": str(e)}

    @app.get("/api/reflection/insights")
    async def get_reflection_insights():
        """Get current trading insights from reflection agent."""
        try:
            from pathlib import Path
            insights_path = Path("data/insights/trading_insights.md")

            if insights_path.exists():
                content = insights_path.read_text(encoding="utf-8")
                mtime = datetime.fromtimestamp(insights_path.stat().st_mtime, tz=timezone.utc)
                return {
                    "available": True,
                    "content": content,
                    "updated_at": mtime.isoformat(),
                    "age_hours": (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
                }
            else:
                return {
                    "available": False,
                    "content": None,
                    "note": "No insights file yet. Run reflection agent to generate."
                }
        except Exception as e:
            logger.error(f"Error getting insights: {e}")
            return {"available": False, "error": str(e)}

    @app.post("/api/reflection/trigger")
    async def trigger_reflection():
        """Manually trigger reflection analysis."""
        try:
            if hasattr(orchestrator, 'reflection_agent') and orchestrator.reflection_agent:
                report = await orchestrator.reflection_agent.reflect(days=30)
                if report:
                    return {
                        "success": True,
                        "report": report.to_dict()
                    }
                else:
                    return {
                        "success": False,
                        "note": "Not enough trades for reflection"
                    }
            else:
                return {
                    "success": False,
                    "note": "Reflection agent not initialized"
                }
        except Exception as e:
            logger.error(f"Error triggering reflection: {e}")
            return {"success": False, "error": str(e)}

    @app.get("/api/correlation")
    async def get_correlation_matrix():
        """
        Get correlation matrix for all trading pairs.

        Calculates pairwise correlations from recent price returns.
        Returns matrix with all configured pairs.
        """
        import numpy as np
        from collections import defaultdict

        try:
            pairs = settings.trading.pairs
            # Extract base assets (e.g., "BTC" from "BTC/AUD")
            assets = sorted(list(set([p.split("/")[0] for p in pairs])))

            # Fetch recent price data for correlation calculation
            price_data = {}
            for pair in pairs:
                try:
                    ohlcv = await orchestrator.exchange.get_ohlcv(pair, interval=60, limit=48)
                    if ohlcv and len(ohlcv) >= 10:
                        closes = [c["close"] for c in ohlcv]
                        # Calculate returns
                        returns = []
                        for i in range(1, len(closes)):
                            if closes[i-1] > 0:
                                returns.append((closes[i] - closes[i-1]) / closes[i-1])
                        asset = pair.split("/")[0]
                        price_data[asset] = returns
                except Exception as e:
                    logger.warning(f"Could not fetch data for {pair}: {e}")

            # Calculate correlation matrix
            matrix = {}
            high_correlation_pairs = []

            for i, asset1 in enumerate(assets):
                for j, asset2 in enumerate(assets):
                    if i == j:
                        matrix[f"{asset1}_{asset2}"] = 1.0
                    elif asset1 in price_data and asset2 in price_data:
                        returns1 = price_data[asset1]
                        returns2 = price_data[asset2]
                        # Align lengths
                        min_len = min(len(returns1), len(returns2))
                        if min_len >= 5:
                            r1 = np.array(returns1[:min_len])
                            r2 = np.array(returns2[:min_len])
                            # Calculate Pearson correlation
                            if np.std(r1) > 0 and np.std(r2) > 0:
                                corr = float(np.corrcoef(r1, r2)[0, 1])
                                matrix[f"{asset1}_{asset2}"] = round(corr, 3)
                                # Track high correlations (only count once)
                                if i < j and abs(corr) > 0.8:
                                    high_correlation_pairs.append({
                                        "pair1": asset1,
                                        "pair2": asset2,
                                        "correlation": round(corr, 3)
                                    })
                            else:
                                matrix[f"{asset1}_{asset2}"] = 0.0
                        else:
                            matrix[f"{asset1}_{asset2}"] = 0.0
                    else:
                        matrix[f"{asset1}_{asset2}"] = 0.0

            return {
                "pairs": assets,
                "matrix": matrix,
                "high_correlation_pairs": high_correlation_pairs,
                "high_correlation": len(high_correlation_pairs) > 0,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Error calculating correlations: {e}")
            # Return default structure with zeros
            assets = sorted(list(set([p.split("/")[0] for p in settings.trading.pairs])))
            matrix = {f"{a1}_{a2}": (1.0 if a1 == a2 else 0.0) for a1 in assets for a2 in assets}
            return {
                "pairs": assets,
                "matrix": matrix,
                "high_correlation_pairs": [],
                "high_correlation": False,
                "error": str(e)
            }

    # =========================================================================
    # AI Activity Endpoints (for Cyberpunk Dashboard)
    # =========================================================================

    @app.get("/api/ai/activity")
    async def get_ai_activity(limit: int = 10):
        """
        Get recent AI trading cycle activity with decisions and reasoning.
        Used for the AI Activity Feed on the dashboard.
        """
        try:
            activity = orchestrator.get_cycle_activity(limit)
            return {
                "cycles": activity,
                "total_cycles": orchestrator.get_cycle_count(),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            logger.error(f"Error fetching AI activity: {e}")
            return {"cycles": [], "total_cycles": 0, "error": str(e)}

    @app.get("/api/ai/cycle/current")
    async def get_current_cycle_status():
        """
        Get current cycle status including next scheduled run time.
        """
        try:
            next_run = scheduler.get_job("trading_cycle").next_run_time if scheduler.get_job("trading_cycle") else None
            now = datetime.now(timezone.utc)

            # Calculate seconds until next cycle
            seconds_until_next = None
            if next_run:
                delta = next_run - now
                seconds_until_next = max(0, int(delta.total_seconds()))

            return {
                "cycle_count": orchestrator.get_cycle_count(),
                "scheduler_running": scheduler.running,
                "next_cycle": next_run.isoformat() if next_run else None,
                "seconds_until_next": seconds_until_next,
                "is_paused": orchestrator.sentinel._paused if hasattr(orchestrator.sentinel, '_paused') else False,
                "timestamp": now.isoformat()
            }
        except Exception as e:
            logger.error(f"Error fetching cycle status: {e}")
            return {"error": str(e)}

    @app.get("/api/positions/detailed")
    async def get_detailed_positions():
        """
        Get detailed position information including stop-loss levels.
        """
        try:
            portfolio = await orchestrator.memory.get_portfolio()
            positions = []

            for symbol, position in portfolio.positions.items():
                # Get stop-loss from sentinel if available
                stop_loss_pct = orchestrator.sentinel.stop_loss_pct if hasattr(orchestrator.sentinel, 'stop_loss_pct') else 0.05
                stop_loss_price = position.entry_price * (1 - stop_loss_pct) if position.entry_price else None

                positions.append({
                    "symbol": symbol,
                    "pair": f"{symbol}/AUD",
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

    @app.get("/api/market/ohlcv/{pair:path}")
    async def get_market_ohlcv(pair: str, interval: int = 60, limit: int = 100):
        """
        Get OHLCV (candlestick) data for a trading pair.
        Used for mini charts and expanded chart view.

        Args:
            pair: Trading pair (e.g., "BTC/AUD", "BTCAUD", or "BTC-AUD")
            interval: Candle interval in minutes (default: 60 = 1 hour)
            limit: Number of candles to return (default: 100)
        """
        try:
            # Normalize pair format to "XXX/AUD"
            pair = pair.replace("-", "/").upper()
            if "/" not in pair and len(pair) >= 6:
                # Handle formats like "BTCAUD" -> "BTC/AUD"
                pair = f"{pair[:-3]}/{pair[-3:]}"

            ohlcv = await orchestrator.exchange.get_ohlcv(pair, interval=interval, limit=limit)

            if not ohlcv:
                return {"candles": [], "pair": pair, "error": "No data available"}

            return {
                "pair": pair,
                "interval": interval,
                "candles": ohlcv,
                "count": len(ohlcv),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            logger.error(f"Error fetching OHLCV for {pair}: {e}")
            return {"candles": [], "pair": pair, "error": str(e)}

    # Serve dashboard static files
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/dashboard", StaticFiles(directory=str(static_dir), html=True), name="static")


# Create default app instance
app = create_app()
