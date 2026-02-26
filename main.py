#!/usr/bin/env python3
"""
Crypto Trading Agent - Main Entry Point

Usage:
    # Stage 1 (MVP)
    python main.py
    
    # With specific stage
    STAGE=stage2 python main.py
    
    # Simulation mode
    SIMULATION_MODE=true python main.py
"""

import os
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn
from dotenv import load_dotenv

from core.config import Stage


def setup_logging():
    """Configure logging"""
    log_level = os.getenv("LOG_LEVEL", "INFO")
    
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Reduce noise from libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def main():
    """Main entry point"""
    # Load environment variables
    load_dotenv()
    
    # Setup logging
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Get stage from environment
    stage_name = os.getenv("STAGE", "stage1")
    stage = Stage(stage_name)
    
    logger.info(f"=" * 60)
    exchange_name = os.getenv("EXCHANGE", "binance").capitalize()
    logger.info(f"{exchange_name} Trading Agent")
    logger.info(f"Stage: {stage.value}")
    logger.info(f"Simulation: {os.getenv('SIMULATION_MODE', 'false')}")
    logger.info(f"=" * 60)
    
    # Check required credentials
    if not os.getenv("SIMULATION_MODE", "").lower() == "true":
        exchange = os.getenv("EXCHANGE", "binance")
        if exchange == "binance":
            testnet = os.getenv("BINANCE_TESTNET", "").lower() in ("1", "true", "yes")
            if testnet:
                api_key = os.getenv("BINANCE_TESTNET_KEY") or os.getenv("BINANCE_API_KEY")
                api_secret = os.getenv("BINANCE_TESTNET_SECRET") or os.getenv("BINANCE_API_SECRET")
                api_key_var = "BINANCE_TESTNET_KEY"
            else:
                api_key = os.getenv("BINANCE_API_KEY")
                api_secret = os.getenv("BINANCE_API_SECRET")
                api_key_var = "BINANCE_API_KEY"
        else:
            api_key = os.getenv("KRAKEN_API_KEY")
            api_secret = os.getenv("KRAKEN_API_SECRET")
            api_key_var = "KRAKEN_API_KEY"

        if not api_key or not api_secret:
            logger.warning(f"{api_key_var} not set - will run in simulation mode")
            os.environ["SIMULATION_MODE"] = "true"
    
    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.warning("ANTHROPIC_API_KEY not set - will use rule-based strategy")
    
    # Run server
    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")
    
    uvicorn.run(
        "api.app:app",
        host=host,
        port=port,
        reload=os.getenv("DEBUG", "").lower() == "true"
    )


if __name__ == "__main__":
    main()
