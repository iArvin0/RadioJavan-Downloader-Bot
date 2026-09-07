from __future__ import annotations

import asyncio
import html
import logging
import tempfile
from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.config import Settings
from app.radiojavan import (
    MediaNotFoundError,
    MediaTooLargeError,
    RadioJavanClient,
    RadioJavanError,
    extract_url,
)

logger = logging.getLogger(__name__)

START_TEXT = """🎵 <b>Radio Javan Downloader Bot</b>

Send me a Radio Javan media link and I will fetch the best public source available.

✅ Songs (320 kbps preferred)
✅ Podcasts
✅ Music videos
✅ rj.app short links
✅ Metadata and cover art when available

Use /help for examples."""

HELP_TEXT = """ℹ️ <b>Help</b>

Send one Radio Javan URL, for example:
<code>https://play.radiojavan.com/song/...</code>
<code>https://play.radiojavan.com/podcast/...</code>
<code>https://rj.app/m/...</code>

The bot prefers a real 320 kbps source. If only a lower quality exists,
it sends that quality instead of fake-upscaling it.

Only publicly accessible media is supported. DRM/private access is not bypassed."""


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


def _semaphore(context: ContextTypes.DEFAULT_TYPE) -> asyncio.Semaphore:
    return context.application.bot_data["download_semaphore"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(START_TEXT, parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not message.text:
        return
    url = extract_url(message.text)
    if not url:
        await message.reply_text("❌ Please send a Radio Javan link.")
        return

    settings = _settings(context)
    status = await message.reply_text("🔎 Resolving Radio Javan link...")
    max_bytes = settings.telegram_max_upload_mb * 1024 * 1024

    async with _semaphore(context):
        try:
            async with RadioJavanClient(
                timeout_seconds=settings.request_timeout_seconds,
                api_key=settings.rj_api_key,
                rj_user_agent=settings.rj_user_agent,
            ) as client:
                track = await client.resolve(url)
                candidate = track.candidates[0]
                await status.edit_text(
                    f"⬇️ Downloading <b>{html.escape(track.title)}</b>\n"
                    f"Quality: <b>{html.escape(candidate.quality)}</b>",
                    parse_mode=ParseMode.HTML,
                )

                if candidate.content_length and candidate.content_length > max_bytes:
                    raise MediaTooLargeError(candidate, max_bytes)

                with tempfile.TemporaryDirectory(prefix="rjbot-") as temp_dir:
                    media = await client.download(track, Path(temp_dir), max_bytes=max_bytes)
                    caption = _caption(track, media.candidate.quality)
                    with media.path.open("rb") as file:
                        if media.candidate.extension == "mp4":
                            await message.reply_video(
                                video=file,
                                caption=caption,
                                parse_mode=ParseMode.HTML,
                                supports_streaming=True,
                            )
                        else:
                            await message.reply_audio(
                                audio=file,
                                caption=caption,
                                parse_mode=ParseMode.HTML,
                                title=track.title[:64],
                                performer=(track.artist or "Radio Javan")[:64],
                                duration=track.duration,
                            )
            await status.delete()
        except MediaTooLargeError as exc:
            logger.info("Media too large for Telegram upload | url=%s", url)
            direct_link = (
                f'<a href="{html.escape(exc.candidate.url, quote=True)}">'
                "Open direct media link</a>"
            )
            await status.edit_text(
                "⚠️ <b>Media found, but it is too large for this bot's "
                "Telegram upload limit.</b>\n\n"
                f"Quality: <b>{html.escape(exc.candidate.quality)}</b>\n"
                f"{direct_link}",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except (RadioJavanError, MediaNotFoundError) as exc:
            logger.info("User-facing Radio Javan error | url=%s | error=%s", url, exc)
            await status.edit_text(
                f"❌ <b>Download failed</b>\n\n{html.escape(str(exc))}",
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            logger.exception("Unexpected download error | url=%s", url)
            await status.edit_text(
                "❌ <b>Unexpected error</b>\n\nCheck the bot log for details.",
                parse_mode=ParseMode.HTML,
            )


def _caption(track, quality: str) -> str:
    lines = [
        f"🎵 <b>{html.escape(track.title)}</b>",
    ]
    if track.artist:
        lines.append(f"👤 {html.escape(track.artist)}")
    if track.album:
        lines.append(f"💿 {html.escape(track.album)}")
    if track.duration:
        minutes, seconds = divmod(track.duration, 60)
        lines.append(f"⏱ {minutes}:{seconds:02d}")
    lines.append(f"🎚 {html.escape(quality)}")
    lines.append("📻 Radio Javan")
    if track.page_url:
        lines.append(f'<a href="{html.escape(track.page_url, quote=True)}">Source</a>')
    return "\n".join(lines)
