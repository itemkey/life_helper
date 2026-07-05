from __future__ import annotations

from dataclasses import dataclass, field

from aiogram.filters import CommandObject

from app.tgbot.handlers import cmd_start
from tests.conftest import FakeTelegramUser


@dataclass(slots=True)
class FakeMessage:
    from_user: FakeTelegramUser
    answers: list[tuple[str, object | None]] = field(default_factory=list)

    async def answer(self, text: str, reply_markup=None):
        self.answers.append((text, reply_markup))


async def test_start_without_deep_link_shows_home(session):
    message = FakeMessage(from_user=FakeTelegramUser(id=100))
    command = CommandObject(prefix="/", command="start", mention=None, args=None)

    await cmd_start(message, command, session)

    assert message.answers
    assert "Life Helper" in message.answers[0][0]


async def test_start_with_invalid_deep_link_shows_error(session):
    message = FakeMessage(from_user=FakeTelegramUser(id=100))
    command = CommandObject(prefix="/", command="start", mention=None, args="list_missing")

    await cmd_start(message, command, session)

    assert message.answers
    assert "Ссылка недействительна" in message.answers[0][0]
