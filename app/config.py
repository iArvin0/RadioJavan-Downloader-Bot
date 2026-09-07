from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    log_level: str
    log_file: str
    max_concurrent_downloads: int
    telegram_max_upload_mb: int
    request_timeout_seconds: float
    rj_api_key: str | None
    rj_user_agent: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("BOT_TOKEN is missing. Copy .env.example to .env and set it.")

        api_key = os.getenv("RJ_API_KEY", "").strip() or None
        rj_user_agent = os.getenv("RJ_USER_AGENT", "").strip() or None
        return cls(
            bot_token=token,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            log_file=os.getenv("LOG_FILE", "logs/bot.log"),
            max_concurrent_downloads=max(1, int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "3"))),
            telegram_max_upload_mb=max(1, int(os.getenv("TELEGRAM_MAX_UPLOAD_MB", "49"))),
            request_timeout_seconds=max(5.0, float(os.getenv("REQUEST_TIMEOUT_SECONDS", "25"))),
            rj_api_key=api_key,
            rj_user_agent=rj_user_agent,
        )
