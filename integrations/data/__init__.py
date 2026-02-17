"""Data integrations for sentiment, on-chain, and macro analysis"""

from integrations.data.fear_greed import FearGreedAPI
from integrations.data.news_api import CryptoNewsAPI
from integrations.data.glassnode import GlassnodeClient
from integrations.data.fred import FREDClient

__all__ = ["FearGreedAPI", "CryptoNewsAPI", "GlassnodeClient", "FREDClient"]
