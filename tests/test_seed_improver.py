"""Tests for Seed Improver Phases 0-4."""
import asyncio
import json
import os
import pytest
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.seed_improver.service import SeedImproverService, Recommendation, VerdictResult


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeTrade:
    pair: str = "BTC/AUD"
    realized_pnl: Optional[float] = None
    realized_pnl_after_fees: Optional[float] = None
    reasoning: str = ""
    signal_confidence: float = 0.7
    latency_decision_to_fill_ms: Optional[float] = None
    status: str = "filled"


class FakeMemory:
    """In-memory mock that mimics PostgresStore interface for testing."""

    def __init__(self, trades: Optional[List[FakeTrade]] = None):
        self._trades = trades or []

    async def get_trade_history(self, limit: int = 100) -> list:
        return self._trades[:limit]


def _make_service(trades=None):
    memory = FakeMemory(trades or [])
    svc = SeedImproverService(memory=memory)
    return svc


# ---------------------------------------------------------------------------
# Phase 0 tests
# ---------------------------------------------------------------------------

class TestPhase0:
    def test_audit_no_trades(self):
        svc = _make_service([])
        result = asyncio.get_event_loop().run_until_complete(svc._phase0_observability_audit())
        assert result["trade_count_sampled"] == 0
        assert len(result["gaps"]) == 3  # all gaps present

    def test_audit_with_full_data(self):
        trades = [FakeTrade(
            realized_pnl_after_fees=-0.5,
            reasoning="test reason",
            latency_decision_to_fill_ms=120.0,
        )]
        svc = _make_service(trades)
        result = asyncio.get_event_loop().run_until_complete(svc._phase0_observability_audit())
        assert result["trade_count_sampled"] == 1
        assert len(result["gaps"]) == 0


# ---------------------------------------------------------------------------
# Phase 1 tests
# ---------------------------------------------------------------------------

class TestPhase1:
    def test_recommendations_from_gaps(self):
        svc = _make_service([])
        audit = {"gaps": ["Missing realized_pnl_after_fees"], "coverage": {}}
        recs = svc._phase1_analyze_and_recommend([], audit, {})
        assert len(recs) == 1
        assert recs[0].priority == "observability"
        assert recs[0].auto_applicable is True

    def test_consecutive_loss_detection(self):
        trades = [FakeTrade(realized_pnl=-1.0) for _ in range(5)]
        svc = _make_service(trades)
        audit = {"gaps": [], "coverage": {}}
        recs = svc._phase1_analyze_and_recommend(trades, audit, {})
        streak_recs = [r for r in recs if "consecutive" in r.hypothesis.lower()]
        assert len(streak_recs) >= 1

    def test_pair_concentration(self):
        trades = [FakeTrade(pair="DOGE/AUD", realized_pnl=-0.5) for _ in range(4)]
        svc = _make_service(trades)
        audit = {"gaps": [], "coverage": {}}
        recs = svc._phase1_analyze_and_recommend(trades, audit, {})
        pair_recs = [r for r in recs if "DOGE/AUD" in r.change_summary]
        assert len(pair_recs) >= 1

    def test_risk_reward_imbalance(self):
        trades = (
            [FakeTrade(realized_pnl=-10.0) for _ in range(3)] +
            [FakeTrade(realized_pnl=2.0) for _ in range(3)]
        )
        svc = _make_service(trades)
        audit = {"gaps": [], "coverage": {}}
        recs = svc._phase1_analyze_and_recommend(trades, audit, {})
        rr_recs = [r for r in recs if "risk/reward" in r.hypothesis.lower()]
        assert len(rr_recs) >= 1
        assert rr_recs[0].priority == "critical"

    def test_low_confidence_losses(self):
        trades = [FakeTrade(realized_pnl=-1.0, signal_confidence=0.3) for _ in range(3)]
        svc = _make_service(trades)
        audit = {"gaps": [], "coverage": {}}
        recs = svc._phase1_analyze_and_recommend(trades, audit, {})
        conf_recs = [r for r in recs if "confidence" in r.hypothesis.lower()]
        assert len(conf_recs) >= 1

    def test_win_rate_alert(self):
        trades = (
            [FakeTrade(realized_pnl=-1.0) for _ in range(8)] +
            [FakeTrade(realized_pnl=1.0) for _ in range(2)]
        )
        svc = _make_service(trades)
        audit = {"gaps": [], "coverage": {}}
        recs = svc._phase1_analyze_and_recommend(trades, audit, {})
        wr_recs = [r for r in recs if "win rate" in r.hypothesis.lower()]
        assert len(wr_recs) >= 1

    def test_sorted_by_priority(self):
        trades = (
            [FakeTrade(realized_pnl=-10.0, signal_confidence=0.3) for _ in range(5)] +
            [FakeTrade(realized_pnl=2.0) for _ in range(5)]
        )
        svc = _make_service(trades)
        audit = {"gaps": ["gap1"], "coverage": {}}
        recs = svc._phase1_analyze_and_recommend(trades, audit, {})
        if len(recs) >= 2:
            priorities = [r.priority for r in recs]
            order = {"critical": 0, "strategy": 1, "observability": 2, "quality": 3}
            assert all(order.get(priorities[i], 99) <= order.get(priorities[i+1], 99) for i in range(len(priorities)-1))


# ---------------------------------------------------------------------------
# Phase 2 tests
# ---------------------------------------------------------------------------

class TestPhase2:
    def test_extract_patterns_consecutive(self):
        trades = [FakeTrade(realized_pnl=-1.0) for _ in range(4)]
        svc = _make_service(trades)
        patterns = svc._extract_patterns(trades, [])
        keys = [p["key"] for p in patterns]
        assert "consecutive_losses" in keys

    def test_extract_patterns_pair(self):
        trades = [FakeTrade(pair="SOL/AUD", realized_pnl=-0.5) for _ in range(3)]
        svc = _make_service(trades)
        patterns = svc._extract_patterns(trades, [])
        keys = [p["key"] for p in patterns]
        assert any("pair_loss_concentration" in k for k in keys)

    def test_no_patterns_when_no_losses(self):
        trades = [FakeTrade(realized_pnl=1.0) for _ in range(5)]
        svc = _make_service(trades)
        patterns = svc._extract_patterns(trades, [])
        assert len(patterns) == 0


# ---------------------------------------------------------------------------
# Phase 3 tests
# ---------------------------------------------------------------------------

class TestPhase3:
    def test_auto_apply_disabled_by_default(self):
        svc = _make_service([])
        assert svc.auto_apply_enabled is False

    def test_auto_apply_enabled_via_env(self):
        with patch.dict(os.environ, {"SEED_IMPROVER_AUTO_APPLY": "true"}):
            svc = _make_service([])
            assert svc.auto_apply_enabled is True

    def test_strategy_auto_apply_disabled_by_default(self):
        svc = _make_service([])
        assert svc.strategy_auto_apply_enabled is False

    def test_controlled_actioning_skips_when_disabled(self):
        svc = _make_service([])
        recs = [Recommendation(
            priority="quality", hypothesis="test", change_summary="fix",
            expected_impact={}, risk="low", compatibility_notes="ok", auto_applicable=True,
        )]
        result = asyncio.get_event_loop().run_until_complete(
            svc._phase3_controlled_actioning("fake-run-id", recs)
        )
        assert result == []


# ---------------------------------------------------------------------------
# Integration test (no DB)
# ---------------------------------------------------------------------------

class TestFullRun:
    def test_full_run_no_db(self):
        trades = (
            [FakeTrade(realized_pnl=-2.0) for _ in range(4)] +
            [FakeTrade(realized_pnl=1.0) for _ in range(2)]
        )
        svc = _make_service(trades)
        result = asyncio.get_event_loop().run_until_complete(svc.run("manual", {}))
        assert result.status == "completed"
        assert result.recommendations_count > 0
        assert len(result.top_recommendations) > 0
        assert result.pattern_updates_count == 0  # no DB

    def test_full_run_losing_trade_trigger(self):
        trades = [FakeTrade(realized_pnl=-1.0, pair="ETH/AUD") for _ in range(3)]
        svc = _make_service(trades)
        ctx = {"trade": {"pair": "ETH/AUD", "realized_pnl": -1.5}}
        result = asyncio.get_event_loop().run_until_complete(svc.run("losing_trade", ctx))
        assert result.status == "completed"
        assert any("ETH/AUD" in r for r in result.top_recommendations) or result.recommendations_count > 0


# ---------------------------------------------------------------------------
# Phase 5 tests (Autonomous Judge)
# ---------------------------------------------------------------------------

class TestPhase5:
    def _make_rec(self, risk="low", priority="quality"):
        return Recommendation(
            priority=priority, hypothesis="test hyp", change_summary="test change",
            expected_impact={"test": True}, risk=risk, compatibility_notes="ok",
            auto_applicable=True,
        )

    def test_judge_skips_without_api_key(self):
        svc = _make_service([])
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            result = asyncio.get_event_loop().run_until_complete(
                svc._phase5_autonomous_judge("fake-run", [self._make_rec()])
            )
            assert result == []

    def test_judge_calls_anthropic_and_parses(self):
        svc = _make_service([])
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "verdict": "approve", "reason": "Looks good",
            "confidence": 0.9, "risk_score": "low",
        }))]

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("anthropic.Anthropic") as MockClient:
                MockClient.return_value.messages.create.return_value = mock_response
                verdicts = asyncio.get_event_loop().run_until_complete(
                    svc._phase5_autonomous_judge("fake-run", [self._make_rec()])
                )
                assert len(verdicts) == 1
                assert verdicts[0].verdict == "approve"
                assert verdicts[0].confidence == 0.9

    def test_high_risk_auto_deferred(self):
        svc = _make_service([])
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "verdict": "approve", "reason": "Risky but good",
            "confidence": 0.8, "risk_score": "high",
        }))]

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=False):
            os.environ.pop("SEED_IMPROVER_HIGH_RISK_AUTO", None)
            with patch("anthropic.Anthropic") as MockClient:
                MockClient.return_value.messages.create.return_value = mock_response
                verdicts = asyncio.get_event_loop().run_until_complete(
                    svc._phase5_autonomous_judge("fake-run", [self._make_rec(risk="high")])
                )
                assert verdicts[0].verdict == "defer"
                assert "Auto-deferred" in verdicts[0].reason

    def test_high_risk_approved_with_flag(self):
        svc = _make_service([])
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "verdict": "approve", "reason": "OK",
            "confidence": 0.8, "risk_score": "high",
        }))]

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key", "SEED_IMPROVER_HIGH_RISK_AUTO": "true"}):
            with patch("anthropic.Anthropic") as MockClient:
                MockClient.return_value.messages.create.return_value = mock_response
                verdicts = asyncio.get_event_loop().run_until_complete(
                    svc._phase5_autonomous_judge("fake-run", [self._make_rec(risk="high")])
                )
                assert verdicts[0].verdict == "approve"

    def test_judge_error_defers(self):
        svc = _make_service([])
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch("anthropic.Anthropic") as MockClient:
                MockClient.return_value.messages.create.side_effect = Exception("API error")
                verdicts = asyncio.get_event_loop().run_until_complete(
                    svc._phase5_autonomous_judge("fake-run", [self._make_rec()])
                )
                assert verdicts[0].verdict == "defer"
                assert "error" in verdicts[0].reason.lower()


# ---------------------------------------------------------------------------
# Phase 6 tests (Auto-Implementation Pipeline)
# ---------------------------------------------------------------------------

class TestPhase6:
    def _make_rec(self):
        return Recommendation(
            priority="quality", hypothesis="test", change_summary="fix latency",
            expected_impact={}, risk="low", compatibility_notes="ok", auto_applicable=True,
        )

    def test_auto_implement_disabled_by_default(self):
        svc = _make_service([])
        assert svc.auto_implement_enabled is False

    def test_auto_implement_skips_when_disabled(self):
        svc = _make_service([])
        rec = self._make_rec()
        verdict = VerdictResult(verdict="approve", reason="ok", confidence=0.9, risk_score="low", judged_by_model="test")
        result = asyncio.get_event_loop().run_until_complete(
            svc._phase6_auto_implement("fake-run", [rec], [verdict])
        )
        assert result["skipped"] == 1
        assert result["implemented"] == 0

    def test_auto_implement_skips_non_approved(self):
        svc = _make_service([])
        rec = self._make_rec()
        verdict = VerdictResult(verdict="reject", reason="no", confidence=0.9, risk_score="low", judged_by_model="test")
        with patch.dict(os.environ, {"SEED_IMPROVER_AUTO_IMPLEMENT": "true", "ANTHROPIC_API_KEY": "key"}):
            result = asyncio.get_event_loop().run_until_complete(
                svc._phase6_auto_implement("fake-run", [rec], [verdict])
            )
            assert result["skipped"] == 1

    def test_git_run_helper(self):
        svc = _make_service([])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="abc123\n", stderr="")
            output = svc._git_run(["rev-parse", "HEAD"])
            assert output == "abc123\n"

    def test_run_tests_helper(self):
        svc = _make_service([])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="all passed", stderr="")
            result = svc._run_tests()
            assert result["passed"] is True

    def test_run_tests_failure(self):
        svc = _make_service([])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="FAILED", stderr="1 failed")
            result = svc._run_tests()
            assert result["passed"] is False


# ---------------------------------------------------------------------------
# Integration with Phase 5/6 (no DB, no API key)
# ---------------------------------------------------------------------------

class TestFullRunWithPhases56:
    def test_full_run_graceful_without_api_key(self):
        """Phase 5/6 should gracefully skip when no API key is set."""
        trades = [FakeTrade(realized_pnl=-2.0) for _ in range(4)]
        svc = _make_service(trades)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            result = asyncio.get_event_loop().run_until_complete(svc.run("manual", {}))
        assert result.status == "completed"
        assert result.verdicts_summary == {}
        assert result.implementations_summary["skipped"] >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
