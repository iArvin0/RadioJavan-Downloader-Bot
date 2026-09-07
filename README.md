# RadioJavan-Downloader-Bot

A Telegram bot written in Python for downloading **publicly accessible Radio Javan media**. It resolves `rj.app` short links, prefers real 320 kbps MP3 sources, falls back to the next available source, writes ID3 metadata when available, and includes Docker, logging, tests, and GitHub Actions.

**Author:** [iArvin0](https://github.com/iArvin0)

> Use this project only for media you are allowed to download. It does not bypass DRM, authentication, paywalls, or private access controls.

## English

### Features

- `python-telegram-bot` async bot
- `/start` and `/help`
- Supports Radio Javan song links
- Supports `rj.app/m/...` short links
- Podcast and music-video fallbacks
- Prefers **real 320 kbps MP3**; falls back to 256 kbps when needed
- Does **not** transcode 256 kbps audio and falsely label it as 320 kbps
- Validates candidate media URLs before downloading
- Extracts Open Graph title/cover from the public page when available
- Optional Radio Javan metadata API support via environment variables
- Writes MP3 title, artist, album, cover, and source URL to ID3 tags when available
- Rotating error logs
- Configurable concurrency
- Telegram upload-size protection with a direct-link fallback
- Docker + Docker Compose
- Ruff + pytest + GitHub Actions
- No database and no forced-channel membership

### Supported URL examples

```text
https://rj.app/m/...
https://play.radiojavan.com/m/...
https://play.radiojavan.com/song/...
https://play.radiojavan.com/podcast/...
https://play.radiojavan.com/video/...
```

### Requirements

- Python 3.12+
- Telegram Bot Token from BotFather
- Internet access to Radio Javan and Telegram

FFmpeg is **not required** for normal song downloads because the bot sends the original public MP3 source instead of re-encoding it.

### Installation

```bash
git clone https://github.com/iArvin0/RadioJavan-Downloader-Bot.git
cd RadioJavan-Downloader-Bot
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Linux/macOS:

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```env
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
```

Run:

```bash
python run.py
```

### Docker

```bash
cp .env.example .env
# edit .env and add BOT_TOKEN
docker compose up -d --build
```

Logs:

```bash
docker compose logs -f
```

### Optional Radio Javan metadata API

The core downloader does not require an API key: it can resolve public pages and probe known public Radio Javan media hosts. If you have legitimate Radio Javan client/API values, you can optionally set:

```env
RJ_API_KEY=
RJ_USER_AGENT=
```

The bot will use them only to improve metadata/direct-link discovery, then fall back to public-page/CDN resolution if the API request fails.

### Configuration

```env
BOT_TOKEN=
LOG_LEVEL=INFO
LOG_FILE=logs/bot.log
MAX_CONCURRENT_DOWNLOADS=3
TELEGRAM_MAX_UPLOAD_MB=49
REQUEST_TIMEOUT_SECONDS=25
RJ_API_KEY=
RJ_USER_AGENT=
```

### Tests

```bash
pip install -r requirements-dev.txt
python -m ruff check .
python -m pytest -q
```

### How it works

1. Validates that the user sent a Radio Javan / `rj.app` URL.
2. Maps known `rj.app` media paths directly to the public `play.radiojavan.com` player URL, avoiding short-link 403 responses.
3. Reads public page metadata/canonical links.
4. Optionally queries the metadata API if explicitly configured.
5. Builds safe candidate URLs on known Radio Javan media hosts.
6. Probes candidates in quality order: 320 kbps first, then 256 kbps.
7. Streams the media to a temporary directory with a hard upload-size limit.
8. Adds ID3 metadata/cover when possible.
9. Sends the audio/video to Telegram and deletes the temporary file automatically.

---

## فارسی

این پروژه یک ربات تلگرام پایتونی برای دانلود **فایل‌های عمومی و قابل دسترس Radio Javan** است. لینک‌های کوتاه `rj.app` را به آدرس عمومی `play.radiojavan.com` نگاشت می‌کند، ابتدا منبع واقعی MP3 با کیفیت 320kbps را امتحان می‌کند و اگر موجود نباشد سراغ کیفیت بعدی می‌رود.

### امکانات

- ساخته‌شده با `python-telegram-bot`
- دستورات `/start` و `/help`
- پشتیبانی از لینک آهنگ Radio Javan
- پشتیبانی از لینک کوتاه `rj.app/m/...`
- fallback برای Podcast و Music Video
- اولویت با **MP3 واقعی 320kbps**
- اگر فقط 256kbps موجود باشد همان کیفیت واقعی گزارش می‌شود و فایل به‌صورت جعلی به 320 تبدیل نمی‌شود
- بررسی سالم بودن لینک رسانه قبل از دانلود
- دریافت Title و Cover از متادیتای عمومی صفحه در صورت وجود
- API متادیتای Radio Javan به‌صورت اختیاری از `.env`
- نوشتن Title، Artist، Album، Cover و Source در ID3 فایل MP3 در صورت موجود بودن
- لاگ خطا با Rotation
- محدودیت دانلود همزمان
- کنترل محدودیت حجم آپلود تلگرام و ارائه لینک مستقیم در صورت بزرگ بودن فایل
- Docker و Docker Compose
- Ruff، pytest و GitHub Actions
- بدون SQL و بدون عضویت اجباری کانال

### نصب روی ویندوز

```powershell
git clone https://github.com/iArvin0/RadioJavan-Downloader-Bot.git
cd RadioJavan-Downloader-Bot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

داخل `.env` توکن BotFather را قرار بده:

```env
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
```

سپس:

```powershell
python run.py
```

### Docker

```bash
docker compose up -d --build
```

### تست پروژه

```bash
pip install -r requirements-dev.txt
python -m ruff check .
python -m pytest -q
```

### نکته مهم

این پروژه برای رسانه‌هایی است که به‌صورت عمومی قابل دسترسی هستند. DRM، ورود اجباری، paywall یا دسترسی خصوصی را دور نمی‌زند. ساختار Radio Javan ممکن است در آینده تغییر کند؛ در این حالت فایل `app/radiojavan.py` محل اصلی به‌روزرسانی resolver است.

## License

MIT License — Copyright (c) 2026 iArvin0
