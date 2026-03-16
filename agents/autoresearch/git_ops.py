"""Git operations for autoresearch experiments."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_TIMEOUT = 30  # seconds


def _ensure_repo(repo_root: Path) -> bool:
    """Ensure a git repo exists at repo_root. Initialises one if needed."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        if result.returncode == 0:
            return True
        # No repo — initialise
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=str(repo_root),
            capture_output=True,
            timeout=_TIMEOUT,
        )
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(repo_root),
            capture_output=True,
            timeout=_TIMEOUT,
        )
        subprocess.run(
            ["git", "commit", "-m", "initial", "--allow-empty"],
            cwd=str(repo_root),
            capture_output=True,
            timeout=_TIMEOUT,
        )
        logger.info("Initialised git repo at %s", repo_root)
        return True
    except Exception as e:
        logger.error("Failed to ensure git repo: %s", e)
        return False


def commit_experiment(
    file_path: str,
    message: str,
    repo_root: Path,
) -> Tuple[bool, Optional[str]]:
    """Stage a single file and commit.

    Returns:
        (success, commit_hash or None)
    """
    try:
        _ensure_repo(repo_root)

        # Stage the file
        result = subprocess.run(
            ["git", "add", file_path],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        if result.returncode != 0:
            logger.error("git add failed: %s", result.stderr)
            return False, None

        # Commit
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        if result.returncode != 0:
            logger.error("git commit failed: %s", result.stderr)
            return False, None

        # Get the commit hash
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        if result.returncode == 0:
            commit_hash = result.stdout.strip()
            logger.info("Committed experiment: %s (%s)", commit_hash[:8], message)
            return True, commit_hash

        return True, None

    except subprocess.TimeoutExpired:
        logger.error("Git operation timed out")
        return False, None
    except FileNotFoundError:
        logger.error("git binary not found — is git installed?")
        return False, None
    except Exception as e:
        logger.error("Git commit failed: %s", e)
        return False, None


def revert_experiment(
    commit_hash: str,
    repo_root: Path,
) -> bool:
    """Revert a specific commit by hash.

    Returns:
        True if revert succeeded.
    """
    try:
        result = subprocess.run(
            ["git", "revert", commit_hash, "--no-edit"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        if result.returncode != 0:
            logger.error("git revert failed: %s", result.stderr)
            return False

        logger.info("Reverted experiment commit: %s", commit_hash[:8])
        return True

    except subprocess.TimeoutExpired:
        logger.error("Git revert timed out")
        return False
    except FileNotFoundError:
        logger.error("git binary not found — is git installed?")
        return False
    except Exception as e:
        logger.error("Git revert failed: %s", e)
        return False


def get_diff(file_path: str, repo_root: Path) -> Optional[str]:
    """Get the git diff for a staged/unstaged file."""
    try:
        result = subprocess.run(
            ["git", "diff", file_path],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        return result.stdout if result.returncode == 0 else None
    except Exception:
        return None
