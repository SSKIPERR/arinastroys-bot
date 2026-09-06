"""Тонкий клиент Telegram Bot API. Без фреймворка — запуск разовый, нужен только HTTP."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

from config import settings

log = logging.getLogger("tg")
API = f"https://api.telegram.org/bot{settings.token}"
FILE_API = f"https://api.telegram.org/file/bot{settings.token}"

# облачный Bot API не отдаёт файлы тяжелее 20 МБ
MAX_DOWNLOAD_MB = 20


class TgError(RuntimeError):
    pass


def call(method: str, http_timeout: int = 60, files: dict | None = None, **params: Any) -> Any:
    """Вызов метода Bot API.

    ВНИМАНИЕ: http_timeout — это таймаут HTTP-запроса, он НЕ уходит в Telegram.
    Все остальные именованные аргументы уходят в Telegram как есть, включая
    timeout= (длинный опрос getUpdates). Раньше параметр назывался timeout и
    перехватывал одноимённый параметр Telegram — длинный опрос молча не работал.
    """
    timeout = http_timeout
    payload = {k: v for k, v in params.items() if v is not None}
    for k, v in list(payload.items()):
        if isinstance(v, (dict, list)):
            payload[k] = json.dumps(v, ensure_ascii=False)

    for attempt in range(3):
        try:
            r = requests.post(f"{API}/{method}", data=payload, files=files, timeout=timeout)
        except requests.RequestException as e:
            if attempt == 2:
                raise TgError(f"{method}: сеть — {e}") from e
            time.sleep(2 * (attempt + 1))
            continue

        try:
            data = r.json()
        except ValueError as e:
            raise TgError(f"{method}: не JSON ({r.status_code})") from e

        if data.get("ok"):
            return data.get("result")

        desc = data.get("description", "")
        if r.status_code == 429:
            wait = int(data.get("parameters", {}).get("retry_after", 3))
            log.warning("лимит, жду %s с", wait)
            time.sleep(wait + 1)
            continue
        raise TgError(f"{method}: {desc}")

    raise TgError(f"{method}: не удалось после трёх попыток")


# ---------------------------------------------------------------- приём

def get_updates(offset: int, poll: int = 25) -> list[dict]:
    return call(
        "getUpdates", http_timeout=poll + 20,
        offset=offset, timeout=poll, limit=100,
        allowed_updates=["message", "callback_query", "channel_post", "my_chat_member"],
    ) or []


def confirm(offset: int) -> None:
    """Подтверждает обработанные события — Telegram убирает их из очереди."""
    call("getUpdates", http_timeout=30, offset=offset, limit=1, timeout=0)


def peek_updates() -> list[dict]:
    """Смотрит очередь, ничего не подтверждая: offset=-1 отдаёт последнее событие."""
    return call("getUpdates", http_timeout=30, offset=-1, limit=1) or []


def webhook_info() -> dict:
    return call("getWebhookInfo", http_timeout=30) or {}


def me() -> dict:
    return call("getMe", http_timeout=30) or {}


def download(file_id: str, dest: Path) -> Path:
    """Скачивает файл. Кидает TgError, если облачный API его не отдаёт."""
    info = call("getFile", file_id=file_id)
    size_mb = (info.get("file_size") or 0) / 1024 / 1024
    path = info.get("file_path")
    if not path:
        raise TgError(f"файл {file_id[:12]}… без пути (вероятно, больше {MAX_DOWNLOAD_MB} МБ)")

    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(f"{FILE_API}/{path}", stream=True, timeout=300) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    log.info("скачал %s (%.1f МБ)", dest.name, size_mb or dest.stat().st_size / 1024 / 1024)
    return dest


# ---------------------------------------------------------------- отправка

def send_message(chat: int | str, text: str, keyboard: list | None = None,
                 preview: bool = False) -> dict:
    return call(
        "sendMessage", chat_id=chat, text=text[:4096], parse_mode="HTML",
        link_preview_options={"is_disabled": not preview},
        reply_markup={"inline_keyboard": keyboard} if keyboard else None,
    )


def send_photo(chat: int | str, photo: Path | str, caption: str = "",
               keyboard: list | None = None) -> dict:
    markup = {"inline_keyboard": keyboard} if keyboard else None
    if isinstance(photo, Path):
        with photo.open("rb") as f:
            return call("sendPhoto", chat_id=chat, caption=caption[:1024] or None,
                        parse_mode="HTML", reply_markup=markup,
                        files={"photo": (photo.name, f)}, http_timeout=300)
    return call("sendPhoto", chat_id=chat, photo=photo, caption=caption[:1024] or None,
                parse_mode="HTML", reply_markup=markup)


def send_video(chat: int | str, video: Path | str, caption: str = "",
               keyboard: list | None = None) -> dict:
    markup = {"inline_keyboard": keyboard} if keyboard else None
    if isinstance(video, Path):
        with video.open("rb") as f:
            return call("sendVideo", chat_id=chat, caption=caption[:1024] or None,
                        parse_mode="HTML", supports_streaming=True,
                        width=1080, height=1920, reply_markup=markup,
                        files={"video": (video.name, f)}, http_timeout=900)
    return call("sendVideo", chat_id=chat, video=video, caption=caption[:1024] or None,
                parse_mode="HTML", supports_streaming=True, reply_markup=markup)


def send_media_group(chat: int | str, file_ids: list[str], caption: str = "") -> list[dict]:
    media = [
        {"type": "photo", "media": fid,
         **({"caption": caption[:1024], "parse_mode": "HTML"} if i == 0 and caption else {})}
        for i, fid in enumerate(file_ids[:10])
    ]
    return call("sendMediaGroup", chat_id=chat, media=media)


def edit_caption(chat: int | str, message_id: int, caption: str,
                 keyboard: list | None = None) -> None:
    try:
        call("editMessageCaption", chat_id=chat, message_id=message_id,
             caption=caption[:1024], parse_mode="HTML",
             reply_markup={"inline_keyboard": keyboard} if keyboard else None)
    except TgError as e:
        log.debug("подпись не обновилась: %s", e)


def edit_markup(chat: int | str, message_id: int, keyboard: list | None) -> None:
    try:
        call("editMessageReplyMarkup", chat_id=chat, message_id=message_id,
             reply_markup={"inline_keyboard": keyboard} if keyboard else None)
    except TgError as e:
        log.debug("кнопки не обновились: %s", e)


def answer_callback(cb_id: str, text: str = "", alert: bool = False) -> None:
    try:
        call("answerCallbackQuery", callback_query_id=cb_id, text=text[:200] or None,
             show_alert=alert)
    except TgError as e:
        log.debug("колбэк не подтверждён: %s", e)


def delete_message(chat: int | str, message_id: int) -> None:
    try:
        call("deleteMessage", chat_id=chat, message_id=message_id)
    except TgError:
        pass


def channel_link(message_id: int) -> str:
    ch = settings.channel_id
    if ch.startswith("@"):
        return f"https://t.me/{ch[1:]}/{message_id}"
    if ch.startswith("-100"):
        return f"https://t.me/c/{ch[4:]}/{message_id}"
    return ""


def file_id_of(msg: dict) -> str | None:
    """Достаёт file_id из отправленного нами сообщения, чтобы переслать без повторной загрузки."""
    if msg.get("video"):
        return msg["video"]["file_id"]
    if msg.get("photo"):
        return msg["photo"][-1]["file_id"]
    if msg.get("animation"):
        return msg["animation"]["file_id"]
    return None
