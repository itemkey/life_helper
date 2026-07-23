from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    database_url: str
    timezone: str = "Europe/Minsk"
    log_level: str = "INFO"
    drop_pending_updates: bool = True


def _parse_bool_env(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise RuntimeError(f"Invalid boolean environment variable value: {value}")


def load_settings() -> Settings:
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    database_url = os.getenv("DATABASE_URL", "").strip()

    missing = []
    if not bot_token:
        missing.append("BOT_TOKEN")
    if not database_url:
        missing.append("DATABASE_URL")
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(f"Missing required environment variables: {names}")

    return Settings(
        bot_token=bot_token,
        database_url=database_url,
        timezone=os.getenv("TZ", "Europe/Minsk").strip() or "Europe/Minsk",
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        drop_pending_updates=_parse_bool_env(os.getenv("DROP_PENDING_UPDATES"), default=True),
    )
