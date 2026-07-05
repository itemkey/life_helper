from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base


@dataclass(slots=True)
class FakeTelegramUser:
    id: int
    username: str | None = None
    first_name: str | None = "Test"
    last_name: str | None = None
    language_code: str | None = "ru"


@pytest.fixture()
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as db_session:
        yield db_session
        await db_session.rollback()

    await engine.dispose()
