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


def secret(*names: str, required: bool = True) -> str | None:
    """First non-empty environment value among `names` (aliases, newest name first)."""
    config()  # ensures .env is loaded
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    if required:
        raise RuntimeError(f"Missing {' / '.join(names)}; set it in {ROOT / '.env'}")
    return None


def api_key() -> str:
    return secret("MASSIVE_API_KEY", "POLYGON_API_KEY")


def s3_credentials() -> tuple[str, str] | None:
    """Flat-file S3 credentials: access key id + secret (Massive's secret is the API key)."""
    key_id = secret("MASSIVE_API_KEY_ID", "POLYGON_S3_ACCESS_KEY_ID", required=False)
    secret_key = secret("POLYGON_S3_SECRET_ACCESS_KEY", "MASSIVE_API_KEY", required=False)
    return (key_id, secret_key) if key_id and secret_key else None
