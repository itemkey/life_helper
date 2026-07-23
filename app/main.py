from __future__ import annotations

import logging
from importlib import metadata

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from app.config import load_settings
from app.db.session import build_engine, build_session_factory
from app.tgbot.handlers import router
from app.tgbot.middleware import DbSessionMiddleware

logger = logging.getLogger(__name__)


def _app_version() -> str:
    try:
        return metadata.version("life-helper")
    except metadata.PackageNotFoundError:
        return "unknown"


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
    allowed_updates = dispatcher.resolve_used_update_types()

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="help", description="Помощь"),
            BotCommand(command="lists", description="Мои тусовки"),
            BotCommand(command="new", description="Создать тусовку"),
            BotCommand(command="cancel", description="Отменить ввод"),
        ]
    )
    await bot.delete_webhook(drop_pending_updates=settings.drop_pending_updates)

    logger.info(
        "Starting life-helper bot version=%s mode=polling drop_pending_updates=%s allowed_updates=%s",
        _app_version(),
        settings.drop_pending_updates,
        ",".join(allowed_updates),
    )

    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=allowed_updates,
        )
    finally:
        await bot.session.close()
        await engine.dispose()
