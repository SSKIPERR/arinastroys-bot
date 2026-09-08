"""Настройки. Всё приходит из секретов репозитория (Settings → Secrets → Actions)."""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONTS_DIR = ASSETS / "fonts"
MUSIC_DIR = ASSETS / "music"
BRAND_DIR = ASSETS / "brand"
STATE_DIR = ROOT / "state"
WORK = Path(os.getenv("RUNNER_TEMP", "/tmp")) / "arinastroys"

for _d in (FONTS_DIR, MUSIC_DIR, BRAND_DIR, STATE_DIR, WORK):
    _d.mkdir(parents=True, exist_ok=True)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name) or default)
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    v = _env(name).lower()
    return v in {"1", "true", "yes", "on"} if v else default


class S:
    # --- Telegram ---
    token = _env("TELEGRAM_BOT_TOKEN")
    owner_id = _int("OWNER_ID", 0)
    channel_id = _env("CHANNEL_ID")

    # --- ИИ ---
    anthropic_key = _env("ANTHROPIC_API_KEY")
    anthropic_model = _env("ANTHROPIC_MODEL", "claude-sonnet-4-5")

    # --- Расписание ---
    tz = ZoneInfo(_env("PUBLISH_TZ", "Europe/Moscow"))
    post_days = [d.strip().lower() for d in _env("POST_DAYS", "mon,wed,fri").split(",") if d.strip()]
    post_time = _env("POST_TIME", "10:30")
    auto_publish = _bool("AUTO_PUBLISH", False)

    # --- Приём материала ---
    # пачка считается законченной, если новых файлов не было столько секунд
    quiet_seconds = _int("QUIET_SECONDS", 240)
    # один прогон живёт несколько минут и всё это время слушает почту,
    # иначе ответы приходили бы раз в десять минут и на разговор не похоже
    run_seconds = _int("RUN_SECONDS", 240)
    poll_seconds = _int("POLL_SECONDS", 45)

    # --- Монтаж ---
    video_max_seconds = _float("VIDEO_MAX_SECONDS", 32)
    video_clip_seconds = _float("VIDEO_CLIP_SECONDS", 3.2)
    video_transition = _env("VIDEO_TRANSITION", "xfade")
    keep_original_audio = _bool("KEEP_ORIGINAL_AUDIO", False)
    music_volume = _float("MUSIC_VOLUME", 0.55)
    whisper_model = _env("WHISPER_MODEL")

    # --- Бренд ---
    brand_name = _env("BRAND_NAME", "Аринастройс")
    brand_latin = _env("BRAND_LATIN", "ArinaStroys")
    brand_channel = _env("BRAND_CHANNEL", "@arinastroys")
    contact_username = _env("CONTACT_USERNAME", "@ArturAkopo")


settings = S()

# video.py и photo.py писались под общий конфиг — оставляем те же имена
MUSIC_DIR = MUSIC_DIR
