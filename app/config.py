from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    database_url: str
    timezone: str = "Europe/Minsk"
    log_level: str = "INFO"


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
    )
