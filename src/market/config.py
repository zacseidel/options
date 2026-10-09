"""Load config.yaml and .env once; resolve paths relative to the project root."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def config() -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    with (ROOT / "config.yaml").open() as handle:
        return yaml.safe_load(handle)


def path(key: str) -> Path:
    """Absolute path for a `paths:` entry, creating parent directories as needed."""
    resolved = (ROOT / config()["paths"][key]).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def directory(key: str) -> Path:
    """Absolute path for a `paths:` entry that is a directory, creating it as needed."""
    resolved = (ROOT / config()["paths"][key]).resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def secret(name: str, required: bool = True) -> str | None:
    config()  # ensures .env is loaded
    value = (os.getenv(name) or "").strip()
    if required and not value:
        raise RuntimeError(f"Missing {name}; set it in {ROOT / '.env'}")
    return value or None
