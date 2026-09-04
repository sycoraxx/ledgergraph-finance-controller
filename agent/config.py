"""Small dependency-free loader for project-local environment settings."""

from __future__ import annotations

import os
from pathlib import Path


def load_project_env(root: str | Path | None = None) -> Path | None:
    """Load ``.env`` defaults without overriding deployment environment values."""
    project_root = Path(root) if root else Path(__file__).resolve().parents[1]
    path = project_root / ".env"
    if not path.is_file():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)
    return path
