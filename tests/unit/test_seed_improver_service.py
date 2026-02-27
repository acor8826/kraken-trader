"""Tests for SeedImproverService v2 (Phase 0 + Phase 1)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import tempfile

from agents.seed_improver.service import SeedImproverService, SeedImproverResult
from agents.seed_improver.models import AnalysisResult, Recommendation, ExpectedImpact


@pytest.fixture
def mock_memory():
    memory = MagicMock()
    memory.get_trade_history = AsyncMock(return_value=[])
    # No _connection attribute by default (local mode)
    if hasattr(memory, "_connection"):
        del memory._connection
    return memory


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.analyze_market = AsyncMock(return_value={
        "analysis_summary": "Test analysis",
        "recommendations": [
            {
                "priority": "strategy",
                "category": "entry_timing",
                "hypothesis": "Test hypothesis",
                "change_summary": "Test change",
                "expected_impact": {"metric": "win_rate", "direction": "increase", "magnitude": "small"},
                "risk_assessment": "low",
                "confidence": 0.7,
                "evidence": ["evidence-1"],
            }
        ],
        "patterns_detected": [],
    })
    llm.model = "claude-test"
    return llm


@pytest.fixture
def mock_alert_manager():
    am = MagicMock()
    am.system_alert = AsyncMock()
    return am


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


class TestSeedImproverServiceInit:
    def test_init_without_llm(self, mock_memory, tmp_dir):
        svc = SeedImproverService(memory=mock_memory, repo_root=tmp_dir)
        assert svc.llm is None
        assert svc.analyzer is None
        assert svc.alert_manager is None

    def test_init_with_llm(self, mock_memory, mock_llm, tmp_dir):
        svc = SeedImproverService(memory=mock_memory, llm=mock_llm, repo_root=tmp_dir)
        assert svc.llm is mock_llm
        assert svc.analyzer is not None

    def test_init_with_all(self, mock_memory, mock_llm, mock_alert_manager, tmp_dir):
        svc = SeedImproverService(
            memory=mock_memory, llm=mock_llm, alert_manager=mock_alert_manager, repo_root=tmp_dir
        )
        assert svc.alert_manager is mock_alert_manager


class TestPhase0Only:
    @pytest.mark.asyncio
    async def test_run_phase0_no_llm(self, mock_memory, tmp_dir):
        svc = SeedImproverService(memory=mock_memory, repo_root=tmp_dir)

        result = await svc.run("manual")

        assert isinstance(result, SeedImproverResult)
        assert result.status == "completed"
        assert "Phase0 audit" in result.summary
        assert result.analysis is None

    @pytest.mark.asyncio
    async def test_run_phase0_with_trades(self, mock_memory, tmp_dir):
        class FakeTrade:
            realized_pnl_after_fees = 10.0
            reasoning = "momentum"
            latency_decision_to_fill_ms = 100

        mock_memory.get_trade_history = AsyncMock(return_value=[FakeTrade()])
        svc = SeedImproverService(memory=mock_memory, repo_root=tmp_dir)

        result = await svc.run("scheduled")

        assert result.status == "completed"
        assert "sampled=1" in result.summary
        assert "gaps=0" in result.summary

    @pytest.mark.asyncio
    async def test_run_phase0_detects_gaps(self, mock_memory, tmp_dir):
        class IncompleteTrade:
            realized_pnl_after_fees = None
            reasoning = ""
            latency_decision_to_fill_ms = None

        mock_memory.get_trade_history = AsyncMock(return_value=[IncompleteTrade()])
        svc = SeedImproverService(memory=mock_memory, repo_root=tmp_dir)

        result = await svc.run("manual")

        assert "gaps=3" in result.summary


class TestPhase1WithLLM:
    @pytest.mark.asyncio
    async def test_run_with_llm_produces_analysis(self, mock_memory, mock_llm, tmp_dir):
        class FakeTrade:
            pair = "BTC/USD"
            action = "buy"
            realized_pnl = 100.0
            realized_pnl_after_fees = 95.0
            signal_confidence = 0.8
            reasoning = "momentum"
            entry_price = 50000.0
            exit_price = 51000.0
            latency_decision_to_fill_ms = 150
            id = "t-1"

        mock_memory.get_trade_history = AsyncMock(return_value=[FakeTrade()])
        svc = SeedImproverService(memory=mock_memory, llm=mock_llm, repo_root=tmp_dir)

        result = await svc.run("manual")

        assert result.status == "completed"
        assert result.analysis is not None
        assert len(result.analysis.recommendations) == 1
        assert "Phase1: 1 recommendations" in result.summary

    @pytest.mark.asyncio
    async def test_phase1_failure_doesnt_break_run(self, mock_memory, mock_llm, tmp_dir):
        class FakeTrade:
            pair = "BTC/USD"
            action = "buy"
            realized_pnl = 100.0
            realized_pnl_after_fees = 95.0
            signal_confidence = 0.8
            reasoning = "test"
            entry_price = 50000.0
            exit_price = 51000.0
            latency_decision_to_fill_ms = 100
            id = "t-1"

        mock_memory.get_trade_history = AsyncMock(return_value=[FakeTrade()])
        mock_llm.analyze_market.side_effect = Exception("LLM API error")

        svc = SeedImproverService(memory=mock_memory, llm=mock_llm, repo_root=tmp_dir)

        result = await svc.run("manual")

        # Phase 0 still succeeds
        assert result.status == "completed"
        assert result.analysis is None
        assert "Phase0 audit" in result.summary

    @pytest.mark.asyncio
    async def test_no_trades_skips_phase1(self, mock_memory, mock_llm, tmp_dir):
        mock_memory.get_trade_history = AsyncMock(return_value=[])
        svc = SeedImproverService(memory=mock_memory, llm=mock_llm, repo_root=tmp_dir)

        result = await svc.run("manual")

        assert result.analysis is None
        mock_llm.analyze_market.assert_not_called()


class TestNotifications:
    @pytest.mark.asyncio
    async def test_sends_alert_on_completion(self, mock_memory, mock_llm, mock_alert_manager, tmp_dir):
        class FakeTrade:
            pair = "BTC/USD"
            action = "buy"
            realized_pnl = 100.0
            realized_pnl_after_fees = 95.0
            signal_confidence = 0.8
            reasoning = "test"
            entry_price = 50000.0
            exit_price = 51000.0
            latency_decision_to_fill_ms = 100
            id = "t-1"

        mock_memory.get_trade_history = AsyncMock(return_value=[FakeTrade()])
        svc = SeedImproverService(
            memory=mock_memory, llm=mock_llm, alert_manager=mock_alert_manager, repo_root=tmp_dir
        )

        await svc.run("scheduled")

        mock_alert_manager.system_alert.assert_called_once()
        call_args = mock_alert_manager.system_alert.call_args
        assert "Seed Improver run completed" in call_args.args[0]

    @pytest.mark.asyncio
    async def test_no_alert_without_manager(self, mock_memory, mock_llm, tmp_dir):
        mock_memory.get_trade_history = AsyncMock(return_value=[])
        svc = SeedImproverService(memory=mock_memory, llm=mock_llm, repo_root=tmp_dir)

        # Should not raise
        result = await svc.run("manual")
        assert result.status == "completed"


class TestMarkdownLogging:
    @pytest.mark.asyncio
    async def test_creates_markdown_log(self, mock_memory, tmp_dir):
        svc = SeedImproverService(memory=mock_memory, repo_root=tmp_dir)

        await svc.run("manual")

        md_files = list((tmp_dir / "memory" / "seed_improver").glob("*.md"))
        assert len(md_files) >= 1

    @pytest.mark.asyncio
    async def test_creates_codebase_summary(self, mock_memory, tmp_dir):
        svc = SeedImproverService(memory=mock_memory, repo_root=tmp_dir)

        await svc.run("manual")

        summary_file = tmp_dir / "memory" / "seed_improver" / "codebase-summary.md"
        assert summary_file.exists()
