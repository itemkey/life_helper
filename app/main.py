from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from app.config import load_settings
from app.db.session import build_engine, build_session_factory
from app.tgbot.handlers import router
from app.tgbot.middleware import DbSessionMiddleware


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.update.middleware(DbSessionMiddleware(session_factory))
    dispatcher.include_router(router)

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="help", description="Помощь"),
            BotCommand(command="lists", description="Мои списки покупок"),
            BotCommand(command="new", description="Создать список"),
            BotCommand(command="cancel", description="Отменить ввод"),
        ]
    )

    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        await bot.session.close()
        await engine.dispose()
