"""
Twitter Sentiment Analyst

Batch-fetches tweets and uses Haiku to classify sentiment.
Tracks mention velocity, influencer signals, and engagement.
"""

import logging
import re
from typing import Dict, List, Optional
from collections import deque
from datetime import datetime, timezone

from core.interfaces import IAnalyst, ILLM
from core.models import AnalystSignal
from agents.memetrader.models import CoinSentiment, MemeBudgetState

logger = logging.getLogger(__name__)

CLASSIFICATION_SYSTEM = "Classify crypto tweet sentiment. For each tweet output B(bullish), N(neutral), or R(bearish). Just the letters, comma-separated."


def _clamp(value: float, min_val: float = -1.0, max_val: float = 1.0) -> float:
    return max(min_val, min(max_val, value))


class TwitterSentimentAnalyst(IAnalyst):
    """
    Batch tweet fetch + Haiku sentiment classification.
    Weight: 0.55 in meme signal fusion.
    """

    def __init__(self, twitter_client, llm: ILLM, budget: MemeBudgetState = None):
        self.twitter_client = twitter_client
        self.llm = llm
        self.budget = budget or MemeBudgetState()
        self._last_sentiments: Dict[str, CoinSentiment] = {}
        self._velocity_history: Dict[str, deque] = {}  # symbol -> deque of (timestamp, count)

    @property
    def name(self) -> str:
        return "twitter_sentiment"

    @property
    def weight(self) -> float:
        return 0.55

    async def fetch_and_classify_batch(
        self,
        symbols: List[str],
        since_minutes: int = 15,
    ) -> Dict[str, CoinSentiment]:
        """
        Fetch tweets for all symbols in 1 API call, classify with 1 Haiku call.
        Returns sentiment per symbol.
        """
        if not symbols:
            return {}

        # Budget check
        if self.budget.budget_exhausted:
            logger.info("[TWITTER_ANALYST] Budget exhausted, using last known sentiments")
            return dict(self._last_sentiments)

        # 1. Fetch tweets (1 API read)
        try:
            result = await self.twitter_client.search_batch(
                symbols=symbols,
                max_results=100,
                since_minutes=since_minutes,
            )
            self.budget.record_read()
        except Exception as e:
            logger.warning(f"[TWITTER_ANALYST] Fetch failed: {e}")
            return dict(self._last_sentiments)

        tweets = result.get("tweets", [])
        if not tweets:
            logger.debug("[TWITTER_ANALYST] No tweets found")
            return dict(self._last_sentiments)

        # 2. Classify with Haiku (1 LLM call)
        # Truncate tweets for token efficiency
        tweet_texts = [t["text"][:120] for t in tweets[:100]]
        numbered_tweets = "\n".join([f"{i+1}. {t}" for i, t in enumerate(tweet_texts)])

        try:
            classification = await self.llm.complete(
                prompt=f"{CLASSIFICATION_SYSTEM}\n\nTweets:\n{numbered_tweets}",
                max_tokens=200,
            )
        except Exception as e:
            logger.warning(f"[TWITTER_ANALYST] Haiku classification failed: {e}")
            return dict(self._last_sentiments)

        # 3. Parse B/N/R labels
        labels = [l.strip().upper() for l in classification.split(",")]
        # Pad with N if too few
        while len(labels) < len(tweets):
            labels.append("N")

        # 4. Categorize tweets by symbol via cashtag matching
        symbol_tweets: Dict[str, List[Dict]] = {s: [] for s in symbols}
        symbols_upper = {s.upper(): s for s in symbols}

        for i, tweet in enumerate(tweets[:len(labels)]):
            text_upper = tweet["text"].upper()
            label = labels[i] if i < len(labels) else "N"

            # Find which symbol(s) this tweet mentions
            for ticker_upper, orig_symbol in symbols_upper.items():
                if f"${ticker_upper}" in text_upper or ticker_upper in text_upper:
                    tweet_with_label = {**tweet, "label": label}
                    symbol_tweets[orig_symbol].append(tweet_with_label)

        # 5. Compute per-symbol sentiment
        now = datetime.now(timezone.utc)
        sentiments: Dict[str, CoinSentiment] = {}

        for symbol in symbols:
            sym_tweets = symbol_tweets.get(symbol, [])
            mention_count = len(sym_tweets)

            if mention_count == 0:
                sentiments[symbol] = CoinSentiment(symbol=symbol)
                continue

            bullish = sum(1 for t in sym_tweets if t.get("label") == "B")
            bearish = sum(1 for t in sym_tweets if t.get("label") == "R")
            neutral = mention_count - bullish - bearish

            sentiment_score = (bullish - bearish) / mention_count if mention_count > 0 else 0.0
            bullish_ratio = bullish / mention_count if mention_count > 0 else 0.0

            # Influencer mentions (>= 10K followers)
            influencer_mentions = sum(
                1 for t in sym_tweets if t.get("author_followers", 0) >= 10000
            )

            # Engagement rate
            total_engagement = sum(
                t.get("likes", 0) + t.get("retweets", 0) for t in sym_tweets
            )
            engagement_rate = min(1.0, (total_engagement / mention_count) / 100.0) if mention_count > 0 else 0.0

            # Mention velocity
            velocity = self._update_velocity(symbol, mention_count, now, since_minutes)

            sentiments[symbol] = CoinSentiment(
                symbol=symbol,
                mention_count=mention_count,
                sentiment_score=sentiment_score,
                bullish_ratio=bullish_ratio,
                influencer_mentions=influencer_mentions,
                engagement_rate=engagement_rate,
                mention_velocity=velocity,
            )

        self._last_sentiments = sentiments
        logger.info(f"[TWITTER_ANALYST] Classified {len(tweets)} tweets across {len(symbols)} symbols")
        return sentiments

    def _update_velocity(self, symbol: str, count: int, now: datetime, window_minutes: int) -> float:
        """Track mention velocity (mentions per minute) via rolling history."""
        if symbol not in self._velocity_history:
            self._velocity_history[symbol] = deque(maxlen=10)

        self._velocity_history[symbol].append((now, count))
        history = self._velocity_history[symbol]

        if len(history) < 2:
            return count / max(1, window_minutes)

        # Average mentions per minute across history
        total_mentions = sum(c for _, c in history)
        total_windows = len(history)
        return total_mentions / (total_windows * max(1, window_minutes))

    async def analyze(self, pair: str, market_data: Dict) -> AnalystSignal:
        """
        Return signal from cached batch sentiment data.
        Call fetch_and_classify_batch() before this.
        """
        symbol = pair.split("/")[0]
        sentiment = self._last_sentiments.get(symbol)

        if not sentiment or sentiment.mention_count == 0:
            return AnalystSignal(
                source=self.name,
                pair=pair,
                direction=0.0,
                confidence=0.0,
                reasoning="No Twitter data available",
                timeframe="15m",
            )

        # Compute direction from sentiment components
        # SMS = mention_velocity * 0.25 + sentiment_score * 0.40 + influencer_signal * 0.20 + engagement * 0.15
        velocity_norm = min(1.0, sentiment.mention_velocity / 10.0)
        influencer_signal = min(1.0, sentiment.influencer_mentions / 5.0)

        direction = (
            velocity_norm * 0.25 +
            sentiment.sentiment_score * 0.40 +
            influencer_signal * 0.20 +
            sentiment.engagement_rate * 0.15
        )

        # Confidence scales with data points
        confidence = min(0.9, 0.3 + (sentiment.mention_count / 50.0) * 0.6)
        if sentiment.influencer_mentions > 0:
            confidence = min(0.9, confidence + 0.1)

        reasoning_parts = [
            f"mentions={sentiment.mention_count}",
            f"sentiment={sentiment.sentiment_score:+.2f}",
            f"velocity={sentiment.mention_velocity:.1f}/min",
        ]
        if sentiment.influencer_mentions > 0:
            reasoning_parts.append(f"influencers={sentiment.influencer_mentions}")

        return AnalystSignal(
            source=self.name,
            pair=pair,
            direction=_clamp(direction),
            confidence=confidence,
            reasoning="Twitter: " + ", ".join(reasoning_parts),
            timeframe="15m",
            metadata={
                "mention_count": sentiment.mention_count,
                "sentiment_score": sentiment.sentiment_score,
                "bullish_ratio": sentiment.bullish_ratio,
                "influencer_mentions": sentiment.influencer_mentions,
                "engagement_rate": sentiment.engagement_rate,
                "mention_velocity": sentiment.mention_velocity,
            },
        )
