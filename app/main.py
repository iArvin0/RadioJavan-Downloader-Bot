from __future__ import annotations

import asyncio
import logging

from telegram.ext import Application, CommandHandler, MessageHandler, filters

from app.config import Settings
from app.handlers import handle_message, help_command, start
from app.logging_config import setup_logging

logger = logging.getLogger(__name__)


def build_application(settings: Settings) -> Application:
    application = Application.builder().token(settings.bot_token).build()
    application.bot_data["settings"] = settings
    application.bot_data["download_semaphore"] = asyncio.Semaphore(
        settings.max_concurrent_downloads
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return application


def main() -> None:
    settings = Settings.from_env()
    setup_logging(settings.log_level, settings.log_file)
    logger.info("Starting RadioJavan-Downloader-Bot")
    application = build_application(settings)
    application.run_polling(drop_pending_updates=False)
