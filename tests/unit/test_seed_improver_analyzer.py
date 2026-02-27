"""Tests for SeedImproverAnalyzer."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from agents.seed_improver.analyzer import SeedImproverAnalyzer
from agents.seed_improver.models import AnalysisResult, Recommendation, ExpectedImpact


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.analyze_market = AsyncMock()
    llm.model = "claude-test"
    return llm


@pytest.fixture
def analyzer(mock_llm):
    return SeedImproverAnalyzer(mock_llm)


@pytest.fixture
def sample_llm_response():
    return {
        "analysis_summary": "Win rate is below target. Stop losses are too tight.",
        "recommendations": [
            {
                "priority": "critical",
                "category": "stop_loss",
                "hypothesis": "Stop losses trigger before price reversal completes",
                "change_summary": "Widen stop loss from 2% to 3%",
                "expected_impact": {
                    "metric": "win_rate",
                    "direction": "increase",
                    "magnitude": "medium",
                },
                "risk_assessment": "medium",
                "confidence": 0.78,
                "evidence": ["Trade #12 lost 1.9% then reversed", "Trade #15 similar pattern"],
            },
            {
                "priority": "strategy",
                "category": "entry_timing",
                "hypothesis": "Entries happen too early in momentum moves",
                "change_summary": "Wait for RSI confirmation before entry",
                "expected_impact": {
                    "metric": "avg_pnl",
                    "direction": "increase",
                    "magnitude": "small",
                },
                "risk_assessment": "low",
                "confidence": 0.65,
                "evidence": ["5 of last 10 losing trades entered at RSI < 30"],
            },
        ],
        "patterns_detected": [
            {
                "key": "tight_stop_loss",
                "title": "Tight Stop Losses",
                "description": "Stop losses consistently trigger within 0.1% of reversal",
            }
        ],
    }


@pytest.fixture
def sample_trades():
    return [
        {"pair": "BTC/USD", "action": "buy", "realized_pnl": -50.0, "signal_confidence": 0.8},
        {"pair": "ETH/USD", "action": "sell", "realized_pnl": 120.0, "signal_confidence": 0.9},
    ]


class TestSeedImproverAnalyzer:
    @pytest.mark.asyncio
    async def test_analyze_returns_analysis_result(self, analyzer, mock_llm, sample_llm_response, sample_trades):
        mock_llm.analyze_market.return_value = sample_llm_response

        result = await analyzer.analyze(
            trades=sample_trades,
            stats={"win_rate": 0.4, "total_pnl": -200.0},
            config={"pairs": ["BTC/USD"]},
        )

        assert isinstance(result, AnalysisResult)
        assert len(result.recommendations) == 2
        assert result.recommendations[0].priority == "critical"
        assert result.recommendations[0].category == "stop_loss"
        assert result.recommendations[0].confidence == 0.78
        assert len(result.patterns_detected) == 1
        assert result.model_used == "claude-test"

    @pytest.mark.asyncio
    async def test_analyze_calls_llm(self, analyzer, mock_llm, sample_llm_response, sample_trades):
        mock_llm.analyze_market.return_value = sample_llm_response

        await analyzer.analyze(sample_trades, {}, {})

        mock_llm.analyze_market.assert_called_once()
        call_kwargs = mock_llm.analyze_market.call_args
        assert "system_prompt" in call_kwargs.kwargs or len(call_kwargs.args) > 1

    @pytest.mark.asyncio
    async def test_analyze_handles_empty_response(self, analyzer, mock_llm, sample_trades):
        mock_llm.analyze_market.return_value = {}

        result = await analyzer.analyze(sample_trades, {}, {})

        assert isinstance(result, AnalysisResult)
        assert len(result.recommendations) == 0
        assert result.summary == "" or result.summary == "Parse error"

    @pytest.mark.asyncio
    async def test_analyze_passes_known_patterns(self, analyzer, mock_llm, sample_llm_response, sample_trades):
        mock_llm.analyze_market.return_value = sample_llm_response
        known = [{"key": "prev_pattern", "title": "Previous", "description": "old pattern"}]

        await analyzer.analyze(sample_trades, {}, {}, known_patterns=known)

        call_args = mock_llm.analyze_market.call_args
        prompt = call_args.kwargs.get("prompt", call_args.args[0] if call_args.args else "")
        assert "prev_pattern" in prompt

    def test_trades_to_dicts_with_objects(self, analyzer):
        class FakeTrade:
            pair = "BTC/USD"
            action = "buy"
            realized_pnl = 100.0
            realized_pnl_after_fees = 95.0
            signal_confidence = 0.8
            reasoning = "Strong momentum"
            entry_price = 50000.0
            exit_price = 51000.0
            latency_decision_to_fill_ms = 150
            id = "trade-1"

        result = analyzer._trades_to_dicts([FakeTrade()])
        assert len(result) == 1
        assert result[0]["pair"] == "BTC/USD"
        assert result[0]["realized_pnl"] == 100.0

    def test_trades_to_dicts_with_dicts(self, analyzer):
        trade = {"pair": "ETH/USD", "action": "sell", "pnl": -50}
        result = analyzer._trades_to_dicts([trade])
        assert result == [trade]

    def test_parse_response_valid(self, analyzer, sample_llm_response):
        result = analyzer._parse_response(sample_llm_response)
        assert isinstance(result, AnalysisResult)
        assert result.summary == "Win rate is below target. Stop losses are too tight."
        assert len(result.recommendations) == 2

    def test_parse_response_partial(self, analyzer):
        result = analyzer._parse_response({"analysis_summary": "partial", "bad_key": []})
        assert result.summary == "partial"
        assert len(result.recommendations) == 0


class TestRecommendation:
    def test_to_dict_and_from_dict(self):
        rec = Recommendation(
            priority="critical",
            category="stop_loss",
            hypothesis="Test",
            change_summary="Widen stop",
            expected_impact=ExpectedImpact("win_rate", "increase", "medium"),
            risk_assessment="low",
            confidence=0.9,
            evidence=["trade-1"],
        )
        d = rec.to_dict()
        rec2 = Recommendation.from_dict(d)

        assert rec2.priority == "critical"
        assert rec2.confidence == 0.9
        assert rec2.expected_impact.metric == "win_rate"

    def test_from_dict_defaults(self):
        rec = Recommendation.from_dict({})
        assert rec.priority == "quality"
        assert rec.category == "unknown"
        assert rec.confidence == 0.5


class TestAnalysisResult:
    def test_to_dict(self):
        ar = AnalysisResult(summary="test", model_used="claude")
        d = ar.to_dict()
        assert d["summary"] == "test"
        assert d["model_used"] == "claude"

    def test_from_dict(self, sample_llm_response):
        ar = AnalysisResult.from_dict(sample_llm_response)
        assert ar.summary == "Win rate is below target. Stop losses are too tight."
        assert len(ar.recommendations) == 2
        assert len(ar.patterns_detected) == 1
