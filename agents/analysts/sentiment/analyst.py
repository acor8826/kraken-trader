"""
Sentiment Analyst - Phase 2

Analyzes market sentiment from multiple sources:
1. Fear & Greed Index (contrarian indicator)
2. News headlines (bullish/bearish keywords)
3. Social buzz (future enhancement)

Signal Calculation:
- Fear & Greed: 40% weight
  - 0-25 (Extreme Fear) → Bullish signal (+0.6 to +1.0)
  - 75-100 (Extreme Greed) → Bearish signal (-0.6 to -1.0)
- News Sentiment: 40% weight
  - Keyword-based scoring or LLM sentiment
- Social: 20% weight (future)
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import datetime

from core.interfaces import IAnalyst, ILLM
from core.models.signals import AnalystSignal
from integrations.data import FearGreedAPI, CryptoNewsAPI

logger = logging.getLogger(__name__)


@dataclass
class SentimentSource:
    """Single sentiment data source"""
    name: str
    value: float  # -1 to +1
    confidence: float  # 0 to 1
    timestamp: datetime


class SentimentAnalyst(IAnalyst):
    """
    Sentiment analysis from Fear & Greed Index and news.

    This analyst uses contrarian sentiment:
    - High fear (0-25) → BUY signal (people are fearful, we should be greedy)
    - High greed (75-100) → SELL signal (people are greedy, we should be fearful)
    """

    def __init__(
        self,
        fear_greed_api: FearGreedAPI,
        news_api: CryptoNewsAPI,
        llm: Optional[ILLM] = None
    ):
        """
        Initialize Sentiment Analyst.

        Args:
            fear_greed_api: Fear & Greed Index API client
            news_api: Crypto news API client
            llm: Optional LLM for advanced sentiment scoring
        """
        self.fear_greed = fear_greed_api
        self.news = news_api
        self.llm = llm
        self._weight = 0.35  # 35% weight in fusion (increased from 30% in PRD)
        logger.info("SentimentAnalyst initialized")

    @property
    def name(self) -> str:
        return "sentiment"

    @property
    def weight(self) -> float:
        return self._weight

    async def analyze(self, pair: str, market_data: Dict) -> AnalystSignal:
        """
        Generate sentiment signal for trading pair.

        Args:
            pair: Trading pair (e.g., "BTC/AUD")
            market_data: Current market data (not used for sentiment)

        Returns:
            AnalystSignal with direction, confidence, and reasoning
        """
        sources: List[SentimentSource] = []

        # 1. Fear & Greed Index (contrarian signal)
        fg_signal = await self._get_fear_greed_signal()
        if fg_signal:
            sources.append(fg_signal)

        # 2. News Sentiment
        asset = pair.split("/")[0]  # Extract BTC, ETH, etc.
        news_signal = await self._get_news_signal(asset)
        if news_signal:
            sources.append(news_signal)

        # 3. Combine sources
        return self._combine_signals(pair, sources)

    async def _get_fear_greed_signal(self) -> Optional[SentimentSource]:
        """
        Convert Fear & Greed Index to contrarian trading signal.

        Mapping:
        - 0-25 (Extreme Fear) → +0.6 to +1.0 (BUY)
        - 25-45 (Fear) → +0.2 to +0.6 (Slightly bullish)
        - 45-55 (Neutral) → 0.0 (Hold)
        - 55-75 (Greed) → -0.2 to -0.6 (Slightly bearish)
        - 75-100 (Extreme Greed) → -0.6 to -1.0 (SELL)
        """
        try:
            data = await self.fear_greed.get_current()
            if not data:
                return None

            value = data["value"]  # 0-100

            # Convert to contrarian trading signal
            if value <= 25:
                # Extreme Fear → Strong BUY
                signal = 0.6 + (25 - value) / 25 * 0.4  # 0.6 to 1.0
            elif value <= 45:
                # Fear → Moderate BUY
                signal = 0.2 + (45 - value) / 20 * 0.4  # 0.2 to 0.6
            elif value <= 55:
                # Neutral
                signal = 0.0
            elif value <= 75:
                # Greed → Moderate SELL
                signal = -0.2 - (value - 55) / 20 * 0.4  # -0.2 to -0.6
            else:
                # Extreme Greed → Strong SELL
                signal = -0.6 - (value - 75) / 25 * 0.4  # -0.6 to -1.0

            logger.info(
                f"Fear & Greed Index: {value} ({data['value_classification']}) "
                f"→ Signal: {signal:+.2f}"
            )

            return SentimentSource(
                name="fear_greed",
                value=signal,
                confidence=0.8,  # Generally reliable indicator
                timestamp=datetime.now()
            )

        except Exception as e:
            logger.error(f"Fear & Greed fetch failed: {e}")
            return None

    async def _get_news_signal(self, asset: str) -> Optional[SentimentSource]:
        """
        Analyze recent news headlines for sentiment.

        Uses keyword-based scoring:
        - Bullish words: surge, rally, breakout, adoption, bullish
        - Bearish words: crash, dump, plunge, hack, bearish
        """
        try:
            headlines = await self.news.get_headlines(
                asset=asset,
                limit=10,
                hours=24
            )

            if not headlines:
                logger.debug(f"No news found for {asset}")
                return None

            # Score sentiment using keywords
            sentiment = self._keyword_sentiment_score(headlines)

            logger.info(
                f"News sentiment for {asset}: {sentiment:+.2f} "
                f"(from {len(headlines)} headlines)"
            )

            return SentimentSource(
                name="news",
                value=sentiment,
                confidence=0.6,  # Moderate confidence (keyword-based)
                timestamp=datetime.now()
            )

        except Exception as e:
            logger.error(f"News sentiment failed for {asset}: {e}")
            return None

    def _keyword_sentiment_score(self, headlines: List[Dict]) -> float:
        """
        Simple keyword-based sentiment scoring.

        Returns:
            Float between -1.0 and +1.0
        """
        BULLISH = [
            "surge", "rally", "breakout", "bullish", "soars", "gains",
            "adoption", "moon", "pump", "outperform", "upgrade", "positive"
        ]
        BEARISH = [
            "crash", "dump", "bearish", "plunge", "sell-off", "fear",
            "hack", "scam", "plummet", "downgrade", "negative", "warning"
        ]

        score = 0.0
        count = 0

        for item in headlines:
            title = item["title"].lower()

            # Count bullish keywords
            for word in BULLISH:
                if word in title:
                    score += 0.3
                    count += 1

            # Count bearish keywords
            for word in BEARISH:
                if word in title:
                    score -= 0.3
                    count += 1

        if count == 0:
            return 0.0

        # Normalize and clamp to [-1, 1]
        normalized = score / count
        return max(-1.0, min(1.0, normalized))

    def _combine_signals(
        self,
        pair: str,
        sources: List[SentimentSource]
    ) -> AnalystSignal:
        """
        Combine multiple sentiment sources into unified signal.

        Weights:
        - Fear & Greed: 50%
        - News: 40%
        - Social: 10% (future)
        """
        if not sources:
            return AnalystSignal(
                source=self.name,
                pair=pair,
                direction=0.0,
                confidence=0.0,
                reasoning="No sentiment data available"
            )

        # Weighted combination
        weights = {
            "fear_greed": 0.5,
            "news": 0.4,
            "social": 0.1
        }

        total_weight = 0.0
        weighted_direction = 0.0

        for source in sources:
            w = weights.get(source.name, 0.2)
            weighted_direction += source.value * w * source.confidence
            total_weight += w * source.confidence

        # Calculate final values
        direction = weighted_direction / total_weight if total_weight > 0 else 0.0
        confidence = min(0.9, total_weight)  # Cap at 0.9

        # Build reasoning string
        reasons = [
            f"{s.name}: {s.value:+.2f} (conf: {s.confidence:.2f})"
            for s in sources
        ]
        reasoning = f"Sentiment analysis → {', '.join(reasons)}"

        return AnalystSignal(
            source=self.name,
            pair=pair,
            direction=direction,
            confidence=confidence,
            reasoning=reasoning
        )
