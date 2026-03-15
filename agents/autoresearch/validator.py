"""Pre-commit safety checks for autoresearch code modifications."""

from __future__ import annotations

import ast
import importlib.util
import logging
import re
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)


def validate_modified_code(
    original_content: str,
    new_content: str,
    file_path: Path,
) -> Tuple[bool, List[str]]:
    """Run safety checks on modified Python code.

    Returns:
        (is_valid, list_of_errors)
    """
    errors: List[str] = []

    # 1. Syntax check via ast.parse
    try:
        ast.parse(new_content, filename=str(file_path))
    except SyntaxError as e:
        errors.append(f"Syntax error: {e}")
        return False, errors

    # 2. Size delta check — reject if file grows/shrinks by >50%
    orig_size = len(original_content)
    new_size = len(new_content)
    if orig_size > 0:
        delta_pct = abs(new_size - orig_size) / orig_size
        if delta_pct > 0.50:
            errors.append(
                f"Size change too large: {delta_pct:.0%} "
                f"({orig_size} → {new_size} bytes)"
            )
            return False, errors

    # 3. Check that all imports are resolvable
    try:
        tree = ast.parse(new_content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    _check_import(alias.name, errors)
            elif isinstance(node, ast.ImportFrom):
                if node.module and not node.module.startswith("."):
                    _check_import(node.module, errors)
    except Exception as e:
        errors.append(f"Import analysis failed: {e}")

    # 4. Ensure the file still has at least one class or function definition
    try:
        tree = ast.parse(new_content)
        has_definitions = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            for node in ast.walk(tree)
        )
        if not has_definitions:
            errors.append("Modified file contains no class or function definitions")
    except Exception:
        pass

    # 5. Check for dangerous patterns
    dangerous_patterns = [
        (r"\bos\.system\b", "os.system() call"),
        (r"\beval\(", "eval() call"),
        (r"\bexec\(", "exec() call"),
        (r"\b__import__\b", "__import__() call"),
        (r"\bsubprocess\.(run|call|Popen)\b", "subprocess call"),
    ]
    for pattern, desc in dangerous_patterns:
        if re.search(pattern, new_content) and not re.search(pattern, original_content):
            errors.append(f"New dangerous pattern introduced: {desc}")

    is_valid = len(errors) == 0
    if is_valid:
        logger.info("Validation passed for %s", file_path.name)
    else:
        logger.warning("Validation failed for %s: %s", file_path.name, errors)

    return is_valid, errors


def _check_import(module_name: str, errors: List[str]) -> None:
    """Check if a top-level module is importable."""
    top_level = module_name.split(".")[0]
    # Skip project-internal modules
    internal_prefixes = (
        "agents", "api", "core", "integrations", "memory", "config",
    )
    if top_level in internal_prefixes:
        return
    try:
        spec = importlib.util.find_spec(top_level)
        if spec is None:
            errors.append(f"Module not found: {top_level}")
    except (ModuleNotFoundError, ValueError):
        errors.append(f"Module not importable: {top_level}")
