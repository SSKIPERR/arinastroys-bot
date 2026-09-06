"""Один заход бота: забрать почту, собрать пост, опубликовать что пора.

Запускается по расписанию из .github/workflows/tick.yml. Между запусками
ничего не живёт, кроме state/session.json — поэтому всё состояние лежит там,
а тяжёлые файлы не храним вовсе: у Telegram есть file_id, и готовое видео
переотправляется в канал по нему, без повторной загрузки.
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import brand
import cards
import photo as ph
import state as st_mod
import tg
import video as vid
from config import FONTS_DIR, MUSIC_DIR, WORK, settings

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s · %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tick")

DOW = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
CAPTION_LIMIT = 1024


# ---------------------------------------------------------------- вспомогательное


def kb_review(pid: str, has_video: bool) -> list:
    rows = [
        [{"text": "✅ Опубликовать", "callback_data": f"p:{pid}:pub"},
         {"text": "🕙 В очередь", "callback_data": f"p:{pid}:queue"}],
        [{"text": "✏️ Правка текста", "callback_data": f"p:{pid}:edit"},
         {"text": "🔁 Другой текст", "callback_data": f"p:{pid}:retext"}],
    ]
    if has_video:
        rows.append([{"text": "🎬 Перемонтировать", "callback_data": f"p:{pid}:revideo"}])
    rows.append([{"text": "🗑 Удалить", "callback_data": f"p:{pid}:drop"}])
    return rows


def build_caption(text: str, hashtags: list[str] | None) -> str:
    tags = " ".join(dict.fromkeys(hashtags or []))[:200]
    body = (text or "").strip()
    full = f"{body}\n\n{tags}".strip() if tags else body
    if len(full) <= CAPTION_LIMIT:
        return full
    room = CAPTION_LIMIT - len(tags) - 4
    cut = body[:room]
    import re
    marks = list(re.finditer(r"[.!?]\s", cut))
    if marks and marks[-1].end() > room * 0.55:
        cut = cut[: marks[-1].end()]
    cut = cut.rstrip(" \n,;—-")
    return f"{cut}\n\n{tags}".strip() if tags else cut


def next_slot(after: datetime | None = None, taken: set[str] | None = None) -> datetime:
    now = after or datetime.now(settings.tz)
    try:
        hh, mm = (int(x) for x in settings.post_time.split(":"))
    except ValueError:
        hh, mm = 10, 30
    days = {DOW[d] for d in settings.post_days if d in DOW} or {0, 2, 4}
    taken = taken or set()

    probe = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    for _ in range(60):
        if probe > now and probe.weekday() in days and probe.isoformat() not in taken:
            return probe
        probe = (probe + timedelta(days=1)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    return now + timedelta(hours=2)


STRANGER = (
    "Здравствуйте!\n\n"
    "Вы написали в бот канала строительной компании «{brand}». "
    "Он отвечает за публикации и, к сожалению, не сможет обработать обращение.\n\n"
    "Если у вас вопрос по ремонту — будем рады помочь. Напишите, пожалуйста, {contact}: "
    "ответим на вопросы, рассчитаем предварительную смету и согласуем выезд на замер.\n\n"
    "Ремонт квартир, домов и дач под ключ. Москва, Московская область и вся Россия. "
    "Работаем по договору, с гарантией.\n\n"
    "Спасибо за интерес к нашей работе."
)

HELP = """<b>Как со мной работать</b>

Кидай сюда фото и видео с объекта. Я проверяю почту каждые 10 минут,
поэтому пост приходит не мгновенно — обычно в течение 10–20 минут.

Что написать вместе с материалом (можно подписью к первому файлу):
город, помещение, стадия — и всё, что стоит упомянуть.
Чем конкретнее, тем меньше воды в тексте.

<b>Команды</b>
/go — не жди, собери пост прямо сейчас
/queue — что в очереди и когда выйдет
/drop 5 — убрать пост из очереди
/now — придумай пост сам
/health — проверка ключей и прав
/help — это сообщение"""


# ---------------------------------------------------------------- разбор почты


def handle_message(msg: dict, st: dict) -> None:
    user = msg.get("from") or {}
    chat = (msg.get("chat") or {}).get("id")
    if (msg.get("chat") or {}).get("type") != "private":
        return

    if user.get("id") != settings.owner_id:
        seen = st.setdefault("strangers", {})
        uid = str(user.get("id"))
        if time.time() - seen.get(uid, 0) > 3600:
            seen[uid] = time.time()
            tg.send_message(
                chat,
                STRANGER.format(brand=settings.brand_name, contact=settings.contact_username),
                keyboard=[
                    [{"text": "Задать вопрос по ремонту",
                      "url": f"https://t.me/{settings.contact_username.lstrip('@')}"}],
                    [{"text": "Наши объекты",
                      "url": f"https://t.me/{settings.brand_channel.lstrip('@')}"}],
                ],
            )
        return

    # ---- медиа ----
    kind = file_id = None
    if msg.get("photo"):
        kind, file_id = "photo", msg["photo"][-1]["file_id"]
    elif msg.get("video"):
        kind, file_id = "video", msg["video"]["file_id"]
    elif msg.get("video_note"):
        kind, file_id = "video", msg["video_note"]["file_id"]
    elif msg.get("animation"):
        kind, file_id = "video", msg["animation"]["file_id"]
    elif msg.get("document"):
        doc = msg["document"]
        mime = (doc.get("mime_type") or "").lower()
        name = (doc.get("file_name") or "").lower()
        if mime.startswith("video") or name.endswith((".mp4", ".mov", ".m4v")):
            kind, file_id = "video", doc["file_id"]
        elif mime.startswith("image") or name.endswith((".jpg", ".jpeg", ".png", ".heic")):
            kind, file_id = "photo", doc["file_id"]

    if kind:
        batch = st.get("batch") or {"media": [], "note": "", "last_ts": 0}
        batch["media"].append({"kind": kind, "file_id": file_id})
        batch["last_ts"] = msg.get("date") or int(time.time())
        if msg.get("caption"):
            batch["note"] = f"{batch.get('note','')} {msg['caption']}".strip()[:700]
        st["batch"] = batch
        log.info("принял %s, в пачке %d", kind, len(batch["media"]))
        return

    text = (msg.get("text") or "").strip()
    if not text:
        return

    # ---- ждём правку текста ----
    pending = st.get("awaiting_edit")
    if pending and not text.startswith("/"):
        st["awaiting_edit"] = None
        p = st_mod.post(st, pending)
        if not p:
            tg.send_message(chat, "Пост уже не найден.")
            return
        try:
            new = (text.split(":", 1)[1].strip() if text.lower().startswith("текст:")
                   else brand.rewrite(p["text"], text))
            p["text"] = new.strip()
            resend_preview(st, pending, "Поправил:")
        except Exception as e:  # noqa: BLE001
            tg.send_message(chat, f"Не получилось поправить: {e}")
        return

    if text.startswith("/"):
        handle_command(text, chat, st)
        return

    # ---- обычный текст = комментарий к открытой пачке ----
    if st.get("batch"):
        st["batch"]["note"] = f"{st['batch'].get('note','')} {text}".strip()[:700]
        return
    tg.send_message(chat, HELP)


def handle_command(text: str, chat: int, st: dict) -> None:
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()

    if cmd in ("/start", "/help"):
        tg.send_message(chat, HELP)

    elif cmd == "/go":
        if st.get("batch") and st["batch"]["media"]:
            st["batch"]["last_ts"] = 0          # заставляем закрыться в этом же заходе
            tg.send_message(chat, "Принял, собираю прямо сейчас.")
        else:
            tg.send_message(chat, "Пачка пустая — сначала пришли материал.")

    elif cmd == "/queue":
        rows = [(pid, p) for pid, p in st.get("posts", {}).items()
                if p.get("status") in ("review", "scheduled")]
        if not rows:
            tg.send_message(chat, "Очередь пустая.")
            return
        lines = ["<b>В работе</b>", ""]
        for pid, p in sorted(rows, key=lambda kv: int(kv[0])):
            when = ""
            if p.get("scheduled_at"):
                try:
                    when = datetime.fromisoformat(p["scheduled_at"]).strftime("%d.%m %H:%M")
                except ValueError:
                    when = p["scheduled_at"]
            mark = "ждёт решения" if p["status"] == "review" else f"выйдет {when} МСК"
            head = (p.get("topic") or p.get("text", "")[:60]).replace("\n", " ")
            lines.append(f"#{pid} · {mark}\n{head}")
        lines.append("\nУбрать: /drop 5")
        tg.send_message(chat, "\n\n".join(lines))

    elif cmd == "/drop":
        p = st_mod.post(st, arg.strip())
        if not p:
            tg.send_message(chat, "Так: /drop 5")
            return
        p["status"] = "rejected"
        p["scheduled_at"] = None
        tg.send_message(chat, f"Убрал пост #{arg.strip()}.")

    elif cmd == "/now":
        tg.send_message(chat, "Придумываю. Пост придёт в ближайшие пару минут.")
        make_auto_post(st, force=True)

    elif cmd == "/health":
        lines = []
        try:
            out = brand.ask("Ответь одним словом: работает", 20)
            lines.append(f"ИИ: {out[:40]}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"ИИ: ошибка — {e}")
        try:
            me = tg.call("getMe")
            member = tg.call("getChatMember", chat_id=settings.channel_id, user_id=me["id"])
            lines.append(f"Канал: статус бота {member.get('status')}"
                         f" · публикация: {member.get('can_post_messages')}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"Канал: ошибка — {e}")
        fonts = [f.name for f in FONTS_DIR.glob("*.ttf")]
        music = [m for m in MUSIC_DIR.iterdir()
                 if m.suffix.lower() in {".mp3", ".m4a", ".wav"}]
        lines.append(f"Шрифты: {', '.join(fonts) if fonts else 'нет, будет системный'}")
        lines.append(f"Музыка: {len(music)} трек(ов)" if music else "Музыка: нет, ролики немые")
        lines.append(f"Файлы: лимит {tg.MAX_DOWNLOAD_MB} МБ (облачный Bot API)")
        lines.append(f"В очереди: {sum(1 for p in st.get('posts', {}).values() if p.get('status') in ('review','scheduled'))}")
        lines.append(f"Тем в банке: {len(st.get('ideas', []))}")
        tg.send_message(chat, "\n\n".join(lines))

    else:
        tg.send_message(chat, HELP)


def handle_callback(cb: dict, st: dict) -> None:
    user = cb.get("from") or {}
    data = cb.get("data") or ""
    msg = cb.get("message") or {}
    chat = (msg.get("chat") or {}).get("id")

    if user.get("id") != settings.owner_id:
        tg.answer_callback(cb["id"], "Этот бот отвечает только редактору канала.", alert=True)
        return

    try:
        _, pid, action = data.split(":", 2)
    except ValueError:
        tg.answer_callback(cb["id"])
        return

    p = st_mod.post(st, pid)
    if not p:
        tg.answer_callback(cb["id"], "Пост уже не найден", alert=True)
        return

    if action == "pub":
        tg.answer_callback(cb["id"], "Публикую…")
        try:
            mid = publish(p)
            p["status"] = "published"
            p["message_id"] = mid
            tg.edit_markup(chat, msg["message_id"], None)
            tg.send_message(chat, f"Опубликовал. {tg.channel_link(mid)}".strip())
        except Exception as e:  # noqa: BLE001
            log.exception("публикация упала")
            tg.send_message(chat, f"Не смог опубликовать: {e}")

    elif action == "queue":
        taken = {q.get("scheduled_at") for q in st.get("posts", {}).values() if q.get("scheduled_at")}
        slot = next_slot(taken=taken)
        p["status"] = "scheduled"
        p["scheduled_at"] = slot.isoformat()
        tg.answer_callback(cb["id"], "В расписании")
        tg.edit_markup(chat, msg["message_id"], None)
        tg.send_message(chat, f"Пост #{pid} выйдет {slot:%d.%m %H:%M} по Москве.")

    elif action == "edit":
        st["awaiting_edit"] = pid
        tg.answer_callback(cb["id"])
        tg.send_message(
            chat,
            "Напиши, что поправить — например «короче и убери про гарантию».\n"
            "Или пришли готовый текст целиком, начав со слова <b>текст:</b>",
        )

    elif action == "retext":
        tg.answer_callback(cb["id"], "Переписываю…")
        try:
            p["text"] = brand.rewrite(
                p["text"], "Напиши этот пост заново, другим заходом и другой первой "
                           "строкой. Смысл сохрани."
            ).strip()
            resend_preview(st, pid, "Переписал:")
        except Exception as e:  # noqa: BLE001
            tg.send_message(chat, f"Не переписалось: {e}")

    elif action == "revideo":
        tg.answer_callback(cb["id"], "Монтирую заново")
        if not p.get("sources"):
            tg.send_message(chat, "Исходников не осталось — пришли материал заново.")
            return
        try:
            rebuild(st, pid)
        except Exception as e:  # noqa: BLE001
            log.exception("перемонтаж упал")
            tg.send_message(chat, f"Перемонтировать не вышло: {e}")

    elif action == "drop":
        p["status"] = "rejected"
        p["scheduled_at"] = None
        tg.answer_callback(cb["id"], "Убрал")
        tg.edit_markup(chat, msg["message_id"], None)

    else:
        tg.answer_callback(cb["id"])


# ---------------------------------------------------------------- сборка поста


def guess_kind(media: list[dict], note: str) -> tuple[str, bool]:
    """Что нам прислали. Возвращает (описание, есть ли пара до/после)."""
    low = (note or "").lower()
    photos = [m for m in media if m["kind"] == "photo"]
    videos = [m for m in media if m["kind"] == "video"]
    if ("до" in low and "после" in low) or "до/после" in low:
        return "до/после", len(photos) >= 2
    if videos and not photos:
        return "видео с объекта, похоже на обход", False
    if len(photos) >= 2 and not videos:
        return "серия фотографий объекта", False
    return "материал с объекта: фото и видео", False


def download_batch(media: list[dict], folder: Path) -> tuple[list[Path], list[Path], list[str]]:
    videos: list[Path] = []
    photos: list[Path] = []
    problems: list[str] = []
    for i, m in enumerate(media):
        ext = ".mp4" if m["kind"] == "video" else ".jpg"
        dest = folder / f"{i:03d}{ext}"
        try:
            tg.download(m["file_id"], dest)
        except Exception as e:  # noqa: BLE001
            problems.append(
                f"файл {i + 1} не скачался — скорее всего тяжелее {tg.MAX_DOWNLOAD_MB} МБ"
                if "больше" in str(e) or "too big" in str(e).lower() else f"файл {i + 1}: {e}"
            )
            continue
        (videos if m["kind"] == "video" else photos).append(dest)
    return videos, photos, problems


def build_post(st: dict) -> None:
    batch = st.get("batch") or {}
    media = batch.get("media") or []
    if not media:
        st["batch"] = None
        return

    note = (batch.get("note") or "").strip()
    owner = settings.owner_id
    tg.send_message(owner, f"Взял в работу {len(media)} файл(ов). Монтирую…")

    folder = WORK / f"batch{int(time.time())}"
    folder.mkdir(parents=True, exist_ok=True)
    videos, photos, problems = download_batch(media, folder)

    if not videos and not photos:
        tg.send_message(owner, "Ни одного файла забрать не удалось.\n" + "\n".join(problems[:4]))
        st["batch"] = None
        return

    guess, ba = guess_kind(media, note)

    # ---- текст ----
    try:
        data = brand.caption_for_object(
            guess=guess, note=note, photos=len(photos), videos=len(videos),
            has_before_after=ba,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("ИИ не ответил")
        data = {"text": note or "Новый объект в работе.",
                "hashtags": ["#ремонтподключ", "#евроремонт", "#строительнаякомпания"],
                "video_title": "Объект в работе", "video_subtitle": ""}
        problems.append(f"текст писал не ИИ, а заглушка: {e}")

    caption = build_caption(data.get("text", ""), data.get("hashtags"))

    # ---- картинка или ролик ----
    pairs = []
    rest = photos
    if ba and len(photos) >= 2:
        pairs = [(ph.label(photos[0], folder / "ba_do.jpg", "до"),
                  ph.label(photos[-1], folder / "ba_posle.jpg", "после"))]
        rest = photos[1:-1]

    video_path = None
    if videos or len(photos) >= 3:
        try:
            title = ph.title_card(folder / "title.jpg", data.get("video_title") or "Объект в работе",
                                  data.get("video_subtitle") or "", photos[0] if photos else None)
            outro = ph.outro_card(folder / "outro.jpg")
            report = vid.build_reel(
                videos=videos, photos=rest, before_after=pairs,
                title_card=title, outro_card=outro,
                out_path=folder / "reel.mp4", workdir=folder / "tmp",
            )
            video_path = folder / "reel.mp4"
            log.info("монтаж: %s", report)
            problems += report.get("skipped", [])
        except Exception as e:  # noqa: BLE001
            log.exception("монтаж упал")
            problems.append(f"видео не собралось: {e}")

    note_line = ("\n\n⚠️ " + "\n⚠️ ".join(problems[:3])) if problems else ""
    pid = st_mod.new_post(
        st, text=caption, topic=(note or guess)[:120], source="object",
        sources=[m["file_id"] for m in media], note=note,
    )

    if video_path and video_path.exists():
        msg = tg.send_video(owner, video_path, f"{caption}\n\n———\nПроверь и решай:{note_line}",
                            kb_review(pid, True))
        st["posts"][pid]["video_file_id"] = tg.file_id_of(msg)
        st["posts"][pid]["review_msg_id"] = msg["message_id"]
    else:
        ready = [ph.to_post(p, folder / f"post{i:02d}.jpg") for i, p in enumerate(photos[:10])]
        if len(ready) > 1:
            # грузим по одной, чтобы забрать file_id каждой — по ним потом
            # публикуем в канал без повторной загрузки
            sent = [tg.send_photo(owner, p) for p in ready]
            ids = [fid for m in sent if (fid := tg.file_id_of(m))]
            msg = tg.send_message(owner, f"{caption}\n\n———\nПроверь и решай:{note_line}",
                                  kb_review(pid, False))
        else:
            msg = tg.send_photo(owner, ready[0], f"{caption}\n\n———\nПроверь и решай:{note_line}",
                                kb_review(pid, False))
            ids = [fid for fid in [tg.file_id_of(msg)] if fid]
        st["posts"][pid]["photo_file_ids"] = [i for i in ids if i]
        st["posts"][pid]["review_msg_id"] = msg["message_id"]

    st["batch"] = None
    log.info("пост #%s собран", pid)


def rebuild(st: dict, pid: str) -> None:
    """Перемонтировать по сохранённым file_id исходников."""
    p = st_mod.post(st, pid)
    folder = WORK / f"re{pid}_{int(time.time())}"
    folder.mkdir(parents=True, exist_ok=True)
    # тип файла заранее неизвестен — качаем как есть и определяем по содержимому
    videos, photos, problems = [], [], []
    for i, fid in enumerate(p.get("sources", [])):
        dest = folder / f"{i:03d}.bin"
        try:
            tg.download(fid, dest)
        except Exception as e:  # noqa: BLE001
            problems.append(str(e))
            continue
        try:
            info = vid.probe(dest)
            is_video = any(s.get("codec_type") == "video" and (s.get("nb_frames") or "0") != "1"
                           and s.get("codec_name") not in {"mjpeg", "png"}
                           for s in info.get("streams", []))
        except Exception:  # noqa: BLE001
            is_video = False
        final = dest.with_suffix(".mp4" if is_video else ".jpg")
        dest.rename(final)
        (videos if is_video else photos).append(final)

    if not videos and not photos:
        tg.send_message(settings.owner_id, "Исходники недоступны — пришли материал заново.")
        return

    title = folder / "title.jpg"
    ph.title_card(title, p.get("topic", "Объект в работе")[:40], "", photos[0] if photos else None)
    outro = ph.outro_card(folder / "outro.jpg")
    vid.build_reel(videos=videos, photos=photos, before_after=[], title_card=title,
                   outro_card=outro, out_path=folder / "reel.mp4", workdir=folder / "tmp")

    msg = tg.send_video(settings.owner_id, folder / "reel.mp4",
                        f"{p['text']}\n\n———\nПеремонтировал:", kb_review(pid, True))
    p["video_file_id"] = tg.file_id_of(msg)
    p["review_msg_id"] = msg["message_id"]


def resend_preview(st: dict, pid: str, header: str) -> None:
    """Показать обновлённый текст. Медиа переотправляем по file_id — без новой загрузки."""
    p = st_mod.post(st, pid)
    owner = settings.owner_id
    body = f"{p['text']}\n\n———\n{header}"
    kbd = kb_review(pid, bool(p.get("video_file_id")))
    if p.get("video_file_id"):
        msg = tg.send_video(owner, p["video_file_id"], body, kbd)
    elif p.get("photo_file_ids"):
        msg = tg.send_photo(owner, p["photo_file_ids"][0], body, kbd)
    else:
        msg = tg.send_message(owner, body, kbd)
    p["review_msg_id"] = msg["message_id"]


# ---------------------------------------------------------------- публикация


def publish(p: dict) -> int:
    caption = (p.get("text") or "")[:CAPTION_LIMIT]
    chat = settings.channel_id
    if p.get("video_file_id"):
        return tg.send_video(chat, p["video_file_id"], caption)["message_id"]
    ids = p.get("photo_file_ids") or []
    if len(ids) > 1:
        return tg.send_media_group(chat, ids, caption)[0]["message_id"]
    if ids:
        return tg.send_photo(chat, ids[0], caption)["message_id"]
    return tg.send_message(chat, caption)["message_id"]


def publish_due(st: dict) -> None:
    now = datetime.now(settings.tz)
    for pid, p in st.get("posts", {}).items():
        if p.get("status") != "scheduled" or not p.get("scheduled_at"):
            continue
        try:
            when = datetime.fromisoformat(p["scheduled_at"])
        except ValueError:
            continue
        if when > now:
            continue
        try:
            mid = publish(p)
            p["status"] = "published"
            p["message_id"] = mid
            st.setdefault("used_topics", []).append(p.get("topic", ""))
            tg.send_message(settings.owner_id,
                            f"Опубликовал пост #{pid} по расписанию. {tg.channel_link(mid)}".strip())
        except Exception as e:  # noqa: BLE001
            log.exception("публикация по расписанию упала")
            p["status"] = "review"
            tg.send_message(settings.owner_id, f"Не смог опубликовать #{pid}: {e}")


# ---------------------------------------------------------------- автопост


def refill_ideas(st: dict) -> None:
    if len(st.get("ideas", [])) >= 6:
        return
    try:
        fresh = brand.generate_ideas(12, st.get("used_topics", []))
    except Exception as e:  # noqa: BLE001
        log.warning("темы не придумались: %s", e)
        return
    st.setdefault("ideas", []).extend(fresh)
    log.info("добавил %d тем", len(fresh))


def make_auto_post(st: dict, force: bool = False) -> str | None:
    refill_ideas(st)
    ideas = st.get("ideas", [])
    if not ideas:
        tg.send_message(settings.owner_id, "Банк тем пуст, а пополнить не вышло. Проверь /health.")
        return None
    idea = ideas.pop(0)

    try:
        data = brand.generate_post(idea.get("rubric", "expertise"), idea["topic"],
                                   idea.get("brief", ""), st.get("used_topics", []))
    except Exception as e:  # noqa: BLE001
        log.exception("автопост не написался")
        tg.send_message(settings.owner_id, f"Не смог написать автопост: {e}")
        return None

    folder = WORK / f"auto{int(time.time())}"
    folder.mkdir(parents=True, exist_ok=True)
    card = None
    try:
        card = cards.make(
            folder / "card.jpg",
            title=data.get("card_title") or idea["topic"],
            lines=data.get("card_lines") or [],
            label=brand.RUBRICS.get(idea.get("rubric", ""), "").split(" —")[0],
            layout=data.get("card_layout", "band"),
            hero=data.get("card_hero", ""),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("карточка не нарисовалась: %s", e)

    caption = build_caption(data.get("text", ""), data.get("hashtags"))
    taken = {q.get("scheduled_at") for q in st.get("posts", {}).values() if q.get("scheduled_at")}
    slot = next_slot(taken=taken)

    pid = st_mod.new_post(st, text=caption, topic=idea["topic"], source="auto",
                          rubric=idea.get("rubric"), sources=[])

    if card:
        msg = tg.send_photo(settings.owner_id, card,
                            f"{caption}\n\n———\nАвтопост. Тема: {idea['topic']}",
                            kb_review(pid, False))
        st["posts"][pid]["photo_file_ids"] = [i for i in [tg.file_id_of(msg)] if i]
    else:
        msg = tg.send_message(settings.owner_id,
                              f"{caption}\n\n———\nАвтопост. Тема: {idea['topic']}",
                              kb_review(pid, False))
    st["posts"][pid]["review_msg_id"] = msg["message_id"]

    if settings.auto_publish and not force:
        st["posts"][pid]["status"] = "scheduled"
        st["posts"][pid]["scheduled_at"] = slot.isoformat()
        tg.send_message(settings.owner_id,
                        f"Встанет в эфир {slot:%d.%m %H:%M} МСК. Не нравится — жми «Удалить».")
    return pid


# ---------------------------------------------------------------- вход


def main() -> int:
    if not settings.token or not settings.owner_id or not settings.channel_id:
        log.error("не заданы TELEGRAM_BOT_TOKEN / OWNER_ID / CHANNEL_ID")
        return 1

    st = st_mod.load()
    log.info("состояние: offset=%s, постов=%d, тем=%d",
             st["offset"], len(st.get("posts", {})), len(st.get("ideas", [])))

    try:
        # Без offset: Telegram отдаёт всё неподтверждённое и НИЧЕГО не вычёркивает.
        # Подтверждаем сами в конце — так offset физически не может убежать вперёд.
        raw = tg.get_updates(0, poll=20)
    except Exception as e:  # noqa: BLE001
        log.error("почту забрать не вышло: %s", e)
        return 1

    updates = [u for u in raw if u["update_id"] >= st["offset"]]
    if raw and not updates:
        log.warning("offset убежал вперёд: в состоянии %s, в очереди %s — откатываю",
                    st["offset"], raw[0]["update_id"])
        st["offset"] = raw[0]["update_id"]
        updates = raw
    log.info("в очереди: %d, из них новых: %d", len(raw), len(updates))

    if not raw:
        # Почта пуста — выясняем, чья это пустота: Telegram молчит или мы не туда смотрим.
        try:
            who = tg.me()
            log.info("диагностика · бот: @%s (id=%s)", who.get("username"), who.get("id"))
        except Exception as e:  # noqa: BLE001
            log.error("диагностика · getMe не ответил: %s", e)
        try:
            wh = tg.webhook_info()
            if wh.get("url"):
                log.error("диагностика · ВЕБХУК ЗАНЯТ: %s — длинный опрос не получит НИЧЕГО",
                          wh["url"])
            else:
                log.info("диагностика · вебхук не стоит, очередь ждёт: %s, последняя ошибка: %s",
                         wh.get("pending_update_count"), wh.get("last_error_message") or "нет")
        except Exception as e:  # noqa: BLE001
            log.error("диагностика · getWebhookInfo не ответил: %s", e)
        try:
            tail = tg.peek_updates()
            if not tail:
                log.info("диагностика · очередь Telegram действительно пуста — "
                         "события до бота не доходят")
            else:
                u = tail[-1]
                kind = next((k for k in ("message", "callback_query", "channel_post",
                                         "my_chat_member") if u.get(k)), "?")
                log.info("диагностика · последнее событие: update_id=%s, тип=%s, наш offset=%s",
                         u.get("update_id"), kind, st["offset"])
                if u.get("update_id", 0) + 1 < st["offset"]:
                    log.error("диагностика · offset УБЕЖАЛ ВПЕРЁД: просим %s, "
                              "а Telegram отдаёт максимум %s — всё новое отбрасывается",
                              st["offset"], u.get("update_id"))
        except Exception as e:  # noqa: BLE001
            log.error("диагностика · peek не ответил: %s", e)

    for u in updates:
        st["offset"] = u["update_id"] + 1
        try:
            if u.get("message"):
                handle_message(u["message"], st)
            elif u.get("callback_query"):
                handle_callback(u["callback_query"], st)
        except Exception as e:  # noqa: BLE001
            log.exception("событие %s не обработалось", u.get("update_id"))
            try:
                tg.send_message(settings.owner_id, f"Спотыкнулся на одном сообщении: {e}")
            except Exception:  # noqa: BLE001
                pass

    if raw:
        # только теперь просим Telegram вычеркнуть разобранное
        try:
            tg.confirm(raw[-1]["update_id"] + 1)
        except Exception as e:  # noqa: BLE001
            log.warning("очередь не подтвердилась: %s", e)

    # пачка считается законченной, если новых файлов давно не было
    batch = st.get("batch")
    if batch and batch.get("media"):
        quiet = time.time() - (batch.get("last_ts") or 0)
        if quiet >= settings.quiet_seconds:
            log.info("пачка молчит %.0f с — собираю", quiet)
            try:
                build_post(st)
            except Exception as e:  # noqa: BLE001
                log.exception("сборка упала")
                tg.send_message(settings.owner_id, f"Пост не собрался: {e}")
                st["batch"] = None
        else:
            log.info("пачка ещё набирается (тишина %.0f с)", quiet)

    publish_due(st)
    st_mod.save(st)
    log.info("готово, offset=%s", st["offset"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
