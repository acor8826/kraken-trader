"""Tests for Seed Improver dashboard API endpoints."""
import os
import sys
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helpers: fake asyncpg records
# ---------------------------------------------------------------------------

class FakeRecord(dict):
    """Dict that supports attribute-style access like asyncpg Record."""
    def __getitem__(self, key):
        return dict.__getitem__(self, key)


def _make_run_record(**overrides):
    from uuid import uuid4
    defaults = {
        "id": uuid4(),
        "trigger_type": "scheduled",
        "status": "completed",
        "started_at": datetime(2026, 2, 26, 6, 0, 0, tzinfo=timezone.utc),
        "finished_at": datetime(2026, 2, 26, 6, 1, 30, tzinfo=timezone.utc),
        "summary": "Analyzed 5 trades, found 2 issues",
        "recommendations_count": 3,
        "pattern_updates_count": 1,
        "applied_count": 1,
        "error": None,
    }
    defaults.update(overrides)
    return FakeRecord(defaults)


def _make_change_record(**overrides):
    from uuid import uuid4
    defaults = {
        "id": uuid4(),
        "priority": "strategy",
        "hypothesis": "Test hypothesis",
        "change_summary": "Adjust stop-loss",
        "risk_assessment": "low",
        "status": "recommended",
        "verdict": "approve",
        "verdict_reason": "Looks good",
        "verdict_confidence": 0.85,
        "verdict_risk_score": "low",
        "judged_by_model": "claude-3-haiku",
        "implementation_branch": None,
        "implementation_commit_sha": None,
        "implementation_check_result": None,
        "implementation_error": None,
        "created_at": datetime(2026, 2, 26, 6, 0, 30, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return FakeRecord(defaults)


# ---------------------------------------------------------------------------
# Mock app factory
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_app():
    """Create a test FastAPI app with mocked seed_improver + memory."""
    from contextlib import asynccontextmanager

    # Build fake memory with _connection context manager
    fake_conn = AsyncMock()

    @asynccontextmanager
    async def fake_connection():
        yield fake_conn

    fake_memory = MagicMock()
    fake_memory._connection = fake_connection

    # Patch module-level seed_improver
    import importlib
    app_module = importlib.import_module("api.app")

    original_seed_improver = getattr(app_module, "seed_improver", None)
    fake_seed_improver = MagicMock()
    fake_seed_improver.memory = fake_memory
    app_module.seed_improver = fake_seed_improver

    yield app_module.app, fake_conn

    app_module.seed_improver = original_seed_improver


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_runs_returns_paginated(mock_app):
    from httpx import AsyncClient, ASGITransport

    app, fake_conn = mock_app
    runs = [_make_run_record(), _make_run_record(trigger_type="manual")]
    fake_conn.fetch = AsyncMock(return_value=runs)
    fake_conn.fetchval = AsyncMock(return_value=2)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/internal/seed-improver/runs?limit=10&offset=0")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["runs"]) == 2
    assert data["runs"][0]["trigger_type"] in ("scheduled", "manual")
    assert "id" in data["runs"][0]
    assert "started_at" in data["runs"][0]


@pytest.mark.asyncio
async def test_run_detail_returns_changes(mock_app):
    from httpx import AsyncClient, ASGITransport
    from uuid import uuid4

    app, fake_conn = mock_app
    run_id = uuid4()
    run = _make_run_record(id=run_id)
    changes = [_make_change_record(), _make_change_record(verdict="reject")]

    fake_conn.fetchrow = AsyncMock(return_value=run)
    fake_conn.fetch = AsyncMock(return_value=changes)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/internal/seed-improver/runs/{run_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(run_id)
    assert len(data["changes"]) == 2
    assert data["changes"][0]["verdict"] == "approve"
    assert data["changes"][1]["verdict"] == "reject"
    assert "change_summary" in data["changes"][0]


@pytest.mark.asyncio
async def test_run_detail_not_found(mock_app):
    from httpx import AsyncClient, ASGITransport

    app, fake_conn = mock_app
    fake_conn.fetchrow = AsyncMock(return_value=None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/internal/seed-improver/runs/nonexistent-id")

    assert resp.status_code == 404
