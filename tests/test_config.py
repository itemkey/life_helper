from __future__ import annotations

import pytest

from app.config import load_settings


@pytest.fixture(autouse=True)
def required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("DROP_PENDING_UPDATES", raising=False)


def test_load_settings_drops_pending_updates_by_default() -> None:
    settings = load_settings()

    assert settings.drop_pending_updates is True


def test_load_settings_allows_disabling_pending_updates_drop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DROP_PENDING_UPDATES", "false")

    settings = load_settings()

    assert settings.drop_pending_updates is False
