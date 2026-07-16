"""Settings loaded from environment variables (optionally via a .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_STEAM_ID = "76561197970928054"
DEFAULT_ITAD_USER = "arcca"
DEFAULT_OUTPUT = "public/games.json"


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _as_float(value: str | None, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    steam_api_key: str | None
    steam_id: str
    itad_user: str
    output_path: Path
    guard_min_ratio: float
    guard_small_list: int
    itad_use_playwright: bool
    http_timeout: float
    log_level: str
    log_format: str

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, dotenv: bool = True) -> "Settings":
        if env is None:
            if dotenv:
                load_dotenv()  # no-op when .env is absent; never overrides real env vars
            env = dict(os.environ)

        key = env.get("STEAM_API_KEY", "").strip() or None
        return cls(
            steam_api_key=key,
            steam_id=env.get("STEAM_ID", "").strip() or DEFAULT_STEAM_ID,
            itad_user=env.get("ITAD_USER", "").strip() or DEFAULT_ITAD_USER,
            output_path=Path(env.get("OUTPUT_PATH", "").strip() or DEFAULT_OUTPUT),
            guard_min_ratio=_as_float(env.get("GUARD_MIN_RATIO"), 0.5),
            guard_small_list=_as_int(env.get("GUARD_SMALL_LIST"), 10),
            itad_use_playwright=_as_bool(env.get("ITAD_USE_PLAYWRIGHT")),
            http_timeout=_as_float(env.get("HTTP_TIMEOUT"), 30.0),
            log_level=env.get("LOG_LEVEL", "").strip() or "INFO",
            log_format=env.get("LOG_FORMAT", "").strip() or "text",
        )
