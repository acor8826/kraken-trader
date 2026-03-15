"""File policy — allowlist/blocklist for autoresearch code modifications."""

from __future__ import annotations

import fnmatch
from pathlib import Path

# Files that autoresearch is allowed to modify
MODIFIABLE_FILES = [
    "agents/strategist/simple.py",
    "agents/strategist/advanced.py",
    "agents/strategist/cost_optimized.py",
    "agents/strategist/batch.py",
    "agents/strategist/hybrid.py",
    "agents/analysts/technical/basic.py",
    "agents/analysts/sentiment/analyst.py",
    "agents/analysts/fusion.py",
    "agents/sentinel/basic.py",
    "agents/sentinel/circuit_breakers.py",
    "agents/executor/simple.py",
    "agents/executor/smart.py",
    "agents/memetrader/meme_strategist.py",
    "agents/memetrader/meme_sentinel.py",
    "agents/memetrader/volume_analyst.py",
    "agents/memetrader/listing_detector.py",
    "agents/memetrader/config.py",
    "agents/orchestrator/phase3.py",
    "agents/orchestrator/base.py",
    "core/risk/adaptive.py",
]

# Files that must never be modified
PROTECTED_PATTERNS = [
    "api/app.py",
    "memory/postgres.py",
    "memory/redis_cache.py",
    "agents/autoresearch/*",
    "Dockerfile",
    "*.sql",
    "*.env",
    "main.py",
    "requirements.txt",
    "migrations/*",
]


def is_modifiable(file_path: str, repo_root: Path) -> bool:
    """Check if a file path is allowed to be modified.

    Args:
        file_path: Relative path from repo root (e.g. "agents/strategist/simple.py").
        repo_root: Absolute path to the repository root.

    Returns:
        True if the file is in the allowlist and not in the blocklist.
    """
    # Normalise to forward slashes
    norm = file_path.replace("\\", "/").strip("/")

    # Check blocklist first
    for pattern in PROTECTED_PATTERNS:
        if fnmatch.fnmatch(norm, pattern):
            return False

    # Check allowlist
    if norm in MODIFIABLE_FILES:
        # Also verify the file actually exists
        full_path = repo_root / norm
        return full_path.is_file()

    return False
