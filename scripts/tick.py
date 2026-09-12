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

HELP = (
    "Привет. Кидай сюда фото и видео с объекта и пиши обычными словами — "
    "никаких команд запоминать не надо.\n\n"
    "Например: «вот кухня в Химках, до и после, собери пост», «покажи, что в очереди», "
    "«третий перепиши покороче», «опубликуй».\n\n"
    "Чем больше расскажешь про объект — город, помещение, стадия, что делали, — "
    "тем меньше воды будет в тексте. Готовый пост пришлю сюда с кнопками."
)


# ---------------------------------------------------------------- сводки


def queue_text(st: dict) -> str:
    rows = [(pid, p) for pid, p in st.get("posts", {}).items()
            if p.get("status") in ("review", "scheduled")]
    if not rows:
        return "Сейчас в работе ничего нет."
    lines = []
    for pid, p in sorted(rows, key=lambda kv: int(kv[0])):
        when = ""
        if p.get("scheduled_at"):
            try:
                when = datetime.fromisoformat(p["scheduled_at"]).strftime("%d.%m %H:%M")
            except ValueError:
                when = p["scheduled_at"]
        mark = "ждёт твоего решения" if p["status"] == "review" else f"выйдет {when} по Москве"
        head = (p.get("topic") or p.get("text", "")[:60]).replace("\n", " ")
        lines.append(f"#{pid} · {mark}\n{head}")
    return "\n\n".join(lines)


def health_text(st: dict) -> str:
    """Ответ на «всё работает?» — по-человечески, а не приборной панелью."""
    good, bad = [], []
    try:
        brand.ask("Ответь одним словом: работает", 20)
        good.append("тексты пишу")
    except Exception as e:  # noqa: BLE001
        bad.append(f"текст сейчас не пишется ({e})")
    try:
        me = tg.call("getMe")
        member = tg.call("getChatMember", chat_id=settings.channel_id, user_id=me["id"])
        if member.get("can_post_messages") or member.get("status") == "creator":
            good.append("в канал публикую")
        else:
            bad.append(f"в канал писать не могу, статус {member.get('status')}")
    except Exception as e:  # noqa: BLE001
        bad.append(f"с каналом заминка ({e})")

    music = [m for m in MUSIC_DIR.iterdir()
             if m.suffix.lower() in {".mp3", ".m4a", ".wav"}] if MUSIC_DIR.exists() else []
    if music:
        good.append(f"музыки {len(music)} трек(ов)")
    else:
        bad.append("музыки нет, ролики выходят немыми")

    waiting = sum(1 for p in st.get("posts", {}).values()
                  if p.get("status") in ("review", "scheduled"))
    head = "Всё на месте: " + ", ".join(good) + "." if good else ""
    tail = " Из недоделанного: " + "; ".join(bad) + "." if bad else ""
    work = f" Сейчас в работе постов: {waiting}." if waiting else " В работе пока пусто."
    return (head + tail + work).strip()


# ---------------------------------------------------------------- разговор


def remember(st: dict, who: str, text: str) -> None:
    """Складываем переписку, иначе каждая фраза читается в отрыве от предыдущей."""
    log_ = st.setdefault("chat_log", [])
    log_.append({"who": who, "text": (text or "").strip()[:400]})
    del log_[:-20]


def think(text: str, chat: int, st: dict) -> None:
    """Один ход разговора: понять, ответить, сделать.

    Модель возвращает ответ и список действий с параметрами, а не один ярлык —
    поэтому «собери пост, видео не надо, фото по порядку» выполняется как есть.
    """
    remember(st, "Давид", text)
    batch = st.get("batch") or {}
    media = batch.get("media") or []
    posts = [
        {"id": pid, "status": ("ждёт решения" if p["status"] == "review" else "запланирован"),
         "head": (p.get("topic") or p.get("text", ""))[:70].replace("\n", " ")}
        for pid, p in sorted(st.get("posts", {}).items(), key=lambda kv: int(kv[0]))
        if p.get("status") in ("review", "scheduled")
    ]
    shown = [(pid, p) for pid, p in sorted(st.get("posts", {}).items(), key=lambda kv: int(kv[0]))
             if p.get("review_msg_id")]
    last = ({"id": shown[-1][0],
             "head": (shown[-1][1].get("topic") or shown[-1][1].get("text", ""))[:70]}
            if shown else {})
    ctx = {
        "media": {"photos": sum(1 for m in media if m["kind"] == "photo"),
                  "videos": sum(1 for m in media if m["kind"] == "video")},
        "note": batch.get("note") or "",
        "posts": posts,
        "last_post": last,
        "history": st.get("chat_log") or [],
    }

    try:
        plan = brand.decide(text, ctx)
    except Exception as e:  # noqa: BLE001
        log.warning("не разобрал фразу: %s", e)
        if media:
            st["batch"]["note"] = f"{batch.get('note','')} {text}".strip()[:700]
            tg.send_message(chat, "Записал. Скажи, когда собирать.")
        else:
            tg.send_message(chat, HELP)
        return

    log.info("решил: %s", [a["tool"] for a in plan["actions"]] or "просто ответить")
    if plan["reply"]:
        tg.send_message(chat, plan["reply"])
        remember(st, "бот", plan["reply"])

    for act in plan["actions"]:
        try:
            run_tool(act["tool"], act["args"], text, chat, st)
        except Exception as e:  # noqa: BLE001
            log.exception("действие %s упало", act["tool"])
            tg.send_message(chat, f"На «{act['tool']}» споткнулся: {e}")


def run_tool(tool: str, args: dict, text: str, chat: int, st: dict) -> None:
    batch = st.get("batch") or {}

    if tool == "make_post":
        if not batch.get("media"):
            tg.send_message(chat, "Материала пока нет — пришли фото или видео.")
            return
        fmt = str(args.get("format") or "auto").lower()
        batch["format"] = fmt if fmt in ("photos", "reel", "auto") else "auto"
        batch["keep_order"] = bool(args.get("keep_order"))
        add = str(args.get("note") or "").strip()
        if add:
            batch["note"] = f"{batch.get('note','')} {add}".strip()[:700]
        batch["last_ts"] = 0          # закроем пачку в этом же заходе
        batch["silent"] = True        # он уже получил ответ, не дублируем
        st["batch"] = batch
        return

    if tool == "show_queue":
        tg.send_message(chat, queue_text(st))
        return

    if tool == "health":
        tg.send_message(chat, health_text(st))
        return

    if tool == "invent":
        make_auto_post(st, force=True, topic=str(args.get("topic") or "").strip() or None)
        return

    pid = str(args.get("post_id") or "").strip().lstrip("#")
    p = st_mod.post(st, pid)
    if not p:
        tg.send_message(chat, "Не понял, о каком посте речь. Вот что в работе:\n\n"
                              + queue_text(st))
        return

    if tool == "publish":
        mid = publish(p)
        p["status"] = "published"
        p["message_id"] = mid
        tg.send_message(chat, f"Опубликовал. {tg.channel_link(mid)}".strip())

    elif tool == "schedule":
        taken = {q.get("scheduled_at") for q in st.get("posts", {}).values()
                 if q.get("scheduled_at")}
        slot = next_slot(taken=taken)
        p["status"] = "scheduled"
        p["scheduled_at"] = slot.isoformat()
        tg.send_message(chat, f"Поставил на {slot:%d.%m %H:%M} по Москве.")

    elif tool == "drop":
        p["status"] = "rejected"
        p["scheduled_at"] = None

    elif tool == "rewrite":
        p["text"] = brand.rewrite(p["text"], str(args.get("how") or text)).strip()
        resend_preview(st, pid, "Поправил:")

    elif tool == "remake":
        regenerate_post(st, pid, str(args.get("feedback") or text))

    elif tool == "split_post":
        split_post(st, pid)

    elif tool == "remake_video":
        rebuild(st, pid)


# ---------------------------------------------------------------- разбор почты


def handle_message(msg: dict, st: dict, inbox: dict) -> None:
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
        first = not (st.get("batch") or {}).get("media")
        batch = st.get("batch") or {"media": [], "note": "", "last_ts": 0}
        batch["media"].append({"kind": kind, "file_id": file_id})
        batch["last_ts"] = msg.get("date") or int(time.time())
        st["batch"] = batch
        log.info("принял %s, в пачке %d", kind, len(batch["media"]))
        inbox["chat"] = chat
        if first:
            inbox["new_batch"] = True
        # Подпись к фото — такое же указание, как отдельное сообщение.
        # Разбираем её вместе со всеми текстами круга, когда пачка уже осела.
        if msg.get("caption"):
            inbox["texts"].append(msg["caption"].strip())
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

    # ---- всё остальное разбирает модель, но позже: сначала дособерём пачку ----
    inbox["chat"] = chat
    inbox["texts"].append(text)


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
        tg.send_message(chat, queue_text(st))

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
        tg.send_message(chat, health_text(st))

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
    log.info("кнопка «%s» на посте #%s (%s)", action, pid,
             p.get("status") if p else "поста нет в состоянии")
    if not p:
        tg.answer_callback(cb["id"], "Пост уже не найден", alert=True)
        return

    if action == "pub":
        tg.answer_callback(cb["id"], "Публикую…")
        try:
            mid = publish(p)
            p["status"] = "published"
            p["message_id"] = mid
            log.info("пост #%s опубликован, сообщение %s в канале", pid, mid)
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
        tg.answer_callback(cb["id"], "Переделываю…")
        try:
            # кнопка переделывает пост целиком: у автопоста заодно меняется макет
            regenerate_post(st, pid, "переделай заново, другим заходом и другой первой строкой")
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


def clean_one(src: Path, dst: Path, what: str, where: str, problems: list[str],
              tag: str) -> Path:
    """Пробует убрать лишнее с кадра: сперва картиночной моделью, потом обрезкой."""
    try:
        if brand.clean_photo(src, dst, what):
            return dst
    except Exception as e:  # noqa: BLE001
        log.warning("чистка %s упала: %s", tag, e)
    try:
        if brand.crop_edge(src, dst, where):
            log.info("%s: обрезал край %s", tag, where)
            return dst
    except Exception as e:  # noqa: BLE001
        log.warning("обрезка %s упала: %s", tag, e)
    problems.append(f"на кадре {tag} лишнее ({what or 'текст'}), убрать не смог")
    return src


def prepare_shots(photos: list[Path], folder: Path, note: str,
                  problems: list[str]) -> list[dict]:
    """Осмотр кадров: чистка, разрез коллажей, группировка по объектам.

    Возвращает список кадров вида
    {"path", "object", "room", "stage", "role": "before"/"after"/"", "pair": метка}
    — коллаж превращается в два кадра с общей меткой пары. Метка, а не индекс:
    после группировки по объектам индексы разъезжаются, а метка держится.
    """
    plain = [{"path": p, "object": "", "room": "", "stage": "", "role": "", "pair": None}
             for p in photos]
    try:
        info = brand.inspect_photos(photos[:8], note)
    except Exception as e:  # noqa: BLE001
        log.warning("осмотр кадров не удался: %s", e)
        return plain

    by_i = {x["i"]: x for x in info.get("photos", [])}
    shots: list[dict] = []
    index_of: dict[int, int] = {}          # исходный индекс -> индекс первого кадра

    for i, src in enumerate(photos):
        meta = by_i.get(i, {})
        obj = meta.get("object") or ""
        base = {"object": obj, "room": meta.get("room", ""), "stage": meta.get("stage", ""),
                "role": "", "pair": None}

        if meta.get("collage"):
            cut = cards.split_collage(
                src, folder / f"cut{i:02d}a.jpg", folder / f"cut{i:02d}b.jpg",
                axis=meta.get("axis", "vertical"), at=meta.get("at", 0.5),
                left_is_before=meta.get("before_first", True))
            if cut:
                log.info("кадр %d — коллаж, разрезал на две половины", i + 1)
                index_of[i] = len(shots)
                shots.append({**base, "path": cut[0], "role": "before", "pair": f"c{i}"})
                shots.append({**base, "path": cut[1], "role": "after", "pair": f"c{i}"})
                continue
            problems.append(f"кадр {i + 1} похож на склейку до/после, разрезать не вышло")

        path = src
        if meta.get("clutter"):
            path = clean_one(src, folder / f"clean{i:02d}.jpg", meta.get("what", ""),
                             meta.get("where", ""), problems, str(i + 1))
        index_of[i] = len(shots)
        shots.append({**base, "path": path})

    # отдельные фото «до» и «после» одного места
    for pr in info.get("pairs", []):
        bi, ai = index_of.get(pr["before"]), index_of.get(pr["after"])
        if bi is None or ai is None or bi == ai:
            continue
        if shots[bi]["role"] or shots[ai]["role"]:
            continue
        shots[bi].update(role="before", pair=f"d{bi}")
        shots[ai].update(role="after", pair=f"d{bi}")
        if shots[ai]["object"] and not shots[bi]["object"]:
            shots[bi]["object"] = shots[ai]["object"]

    return shots


def group_shots(shots: list[dict]) -> list[list[dict]]:
    """Делит кадры на объекты: сколько квартир прислали, столько и постов."""
    groups: dict[str, list[dict]] = {}
    for sh in shots:
        groups.setdefault(sh.get("object") or "объект", []).append(sh)
    return [g for g in groups.values() if g]


def pick_theme(st: dict) -> str:
    """Чередуем светлую и тёмную тему, чтобы лента не сливалась."""
    posts = sorted(st.get("posts", {}).items(), key=lambda kv: int(kv[0]))
    last = next((p.get("theme") for _, p in reversed(posts) if p.get("theme")), None)
    return "light" if last == "dark" else "dark"


def frames_from_video(path: Path, folder: Path, n: int = 3) -> list[Path]:
    """Пара кадров из ролика, чтобы модели было на что посмотреть."""
    import subprocess
    out = []
    try:
        dur = float(vid.probe(path).get("format", {}).get("duration") or 0)
    except Exception:  # noqa: BLE001
        dur = 0
    spots = [dur * k / (n + 1) for k in range(1, n + 1)] if dur > 1 else [0.5]
    for i, at in enumerate(spots):
        dst = folder / f"eye{i}.jpg"
        try:
            subprocess.run(["ffmpeg", "-y", "-ss", f"{at:.2f}", "-i", str(path),
                            "-frames:v", "1", "-vf", "scale=768:-2", str(dst)],
                           capture_output=True, timeout=60, check=True)
            if dst.exists():
                out.append(dst)
        except Exception as e:  # noqa: BLE001
            log.debug("кадр не вынулся: %s", e)
    return out


def compose_post(st: dict, folder: Path, tag: str, shots: list[dict], videos: list[Path],
                 note: str, fmt: str, problems: list[str], sources: list[str]) -> str | None:
    """Собирает и показывает ОДИН пост из набора кадров одного объекта."""
    owner = settings.owner_id
    photos = [sh["path"] for sh in shots]
    befores = {sh["pair"]: i for i, sh in enumerate(shots)
               if sh.get("pair") and sh.get("role") == "before"}
    pairs_idx = [(befores[sh["pair"]], i) for i, sh in enumerate(shots)
                 if sh.get("pair") in befores and sh.get("role") == "after"]
    rooms = list(dict.fromkeys(sh["room"] for sh in shots if sh.get("room")))
    stages = list(dict.fromkeys(sh["stage"] for sh in shots if sh.get("stage")))
    guess = ", ".join(rooms[:3]) or "материал с объекта"
    if pairs_idx:
        guess = f"до/после: {guess}"
    elif stages:
        guess = f"{guess} ({', '.join(stages[:2])})"

    eyes = photos[:8] or (frames_from_video(videos[0], folder) if videos else [])
    try:
        data = brand.caption_for_object(
            guess=guess, note=note, photos=len(photos), videos=len(videos),
            has_before_after=bool(pairs_idx), images=eyes,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("ИИ не ответил")
        data = {"text": note or "Новый объект в работе.",
                "hashtags": ["#ремонтподключ", "#евроремонт", "#строительнаякомпания"],
                "video_title": "Объект в работе", "video_subtitle": ""}
        problems = problems + [f"текст писал не ИИ, а заглушка: {e}"]

    caption = build_caption(data.get("text", ""), data.get("hashtags"))

    # ---- карточки до/после ----
    pairs, ba_cards, used = [], [], set()
    for k, (bi, ai) in enumerate(pairs_idx):
        b_, a_ = photos[bi], photos[ai]
        used.update((bi, ai))
        pairs.append((ph.label(b_, folder / f"{tag}_ba{k}_do.jpg", "до"),
                      ph.label(a_, folder / f"{tag}_ba{k}_posle.jpg", "после")))
        style = cards.BA_STYLES[(k + len(st.get("posts", {}))) % len(cards.BA_STYLES)]
        try:
            ba_cards.append(cards.before_after(
                folder / f"{tag}_ba{k}_card.jpg", b_, a_,
                title=(data.get("video_title") or "") if k == 0 else "",
                style=style, theme=pick_theme(st)))
        except Exception as e:  # noqa: BLE001
            log.warning("карточка до/после не собралась: %s", e)
    rest = [p_ for i, p_ in enumerate(photos) if i not in used]

    # ---- ролик ----
    want_video = fmt == "reel" or (fmt == "auto" and (videos or len(photos) >= 3))
    if fmt == "photos" and videos:
        problems = problems + ["видео не монтировал — ты просил только фото"]
    video_path = None
    if want_video:
        try:
            title = ph.title_card(folder / f"{tag}_title.jpg",
                                  data.get("video_title") or "Объект в работе",
                                  data.get("video_subtitle") or "",
                                  photos[0] if photos else None)
            outro = ph.outro_card(folder / f"{tag}_outro.jpg")
            report = vid.build_reel(
                videos=videos, photos=rest, before_after=pairs,
                title_card=title, outro_card=outro,
                out_path=folder / f"{tag}_reel.mp4", workdir=folder / f"tmp{tag}",
            )
            video_path = folder / f"{tag}_reel.mp4"
            log.info("монтаж: %s", report)
            problems = problems + report.get("skipped", [])
        except Exception as e:  # noqa: BLE001
            log.exception("монтаж упал")
            problems = problems + [f"видео не собралось: {e}"]

    note_line = ("\n\n⚠️ " + "\n⚠️ ".join(problems[:3])) if problems else ""
    pid = st_mod.new_post(
        st, text=caption, topic=(guess or note)[:120], source="object",
        sources=sources, note=note, theme=pick_theme(st) if ba_cards else None,
    )

    if video_path and video_path.exists():
        msg = tg.send_video(owner, video_path, f"{caption}\n\n———\nПроверь и решай:{note_line}",
                            kb_review(pid, True))
        st["posts"][pid]["video_file_id"] = tg.file_id_of(msg)
        st["posts"][pid]["review_msg_id"] = msg["message_id"]
    else:
        plain = rest if ba_cards else photos
        ready = ba_cards + [ph.to_post(p_, folder / f"{tag}_post{i:02d}.jpg")
                            for i, p_ in enumerate(plain[: 10 - len(ba_cards)])]
        if not ready:
            tg.send_message(owner, "Фотографий не оказалось, а видео ты просил не трогать.")
            return None
        if len(ready) > 1:
            # грузим по одной, чтобы забрать file_id каждой — по ним потом
            # публикуем в канал без повторной загрузки
            sent = [tg.send_photo(owner, p_) for p_ in ready]
            ids = [fid for m in sent if (fid := tg.file_id_of(m))]
            msg = tg.send_message(owner, f"{caption}\n\n———\nПроверь и решай:{note_line}",
                                  kb_review(pid, False))
        else:
            msg = tg.send_photo(owner, ready[0], f"{caption}\n\n———\nПроверь и решай:{note_line}",
                                kb_review(pid, False))
            ids = [fid for fid in [tg.file_id_of(msg)] if fid]
        st["posts"][pid]["photo_file_ids"] = [i for i in ids if i]
        st["posts"][pid]["review_msg_id"] = msg["message_id"]

    remember(st, "система", f"показал пост #{pid} по материалу с объекта: {guess[:80]}")
    log.info("пост #%s собран (%d кадр(ов), пар до/после: %d)", pid, len(photos), len(pairs_idx))
    return pid


def build_post(st: dict) -> None:
    """Разбирает пачку: чистит кадры, режет коллажи и делает столько постов,
    сколько объектов прислали."""
    batch = st.get("batch") or {}
    media = batch.get("media") or []
    if not media:
        st["batch"] = None
        return

    note = (batch.get("note") or "").strip()
    owner = settings.owner_id
    if not batch.get("silent"):
        # когда сборку попросили словами, бот уже ответил — второй раз не повторяемся
        tg.send_message(owner, f"Взял в работу {len(media)} файл(ов). Монтирую…")

    folder = WORK / f"batch{int(time.time())}"
    folder.mkdir(parents=True, exist_ok=True)
    videos, photos, problems = download_batch(media, folder)

    if not videos and not photos:
        tg.send_message(owner, "Ни одного файла забрать не удалось.\n" + "\n".join(problems[:4]))
        st["batch"] = None
        return

    fmt = batch.get("format") or "auto"
    sources = [m["file_id"] for m in media]

    shots = prepare_shots(photos, folder, note, problems) if photos else []
    groups = group_shots(shots) if not batch.get("keep_order") else [shots]
    if len(groups) > 1:
        log.info("в пачке %d разных объекта — делаю столько же постов", len(groups))
        tg.send_message(owner, f"Вижу {len(groups)} разных объекта — соберу отдельный "
                               f"пост на каждый.")

    made = []
    for n, group in enumerate(groups or [[]]):
        # видео кладём в первый пост, чтобы не дублировать ролик в каждом
        pid = compose_post(st, folder, f"g{n}", group, videos if n == 0 else [],
                           note, fmt, list(problems), sources)
        if pid:
            made.append(pid)

    st["batch"] = None
    if not made:
        tg.send_message(owner, "Собрать пост не вышло — пришли материал ещё раз.")


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
    remember(st, "система", f"показал пост #{pid} ({header.rstrip(':').lower()})")


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


def recent_layouts(st: dict, n: int = 3) -> list[str]:
    """Макеты последних карточек — чтобы следующая не выглядела как предыдущая."""
    posts = sorted(st.get("posts", {}).items(), key=lambda kv: int(kv[0]))
    return [p.get("card") for _, p in posts if p.get("card")][-n:]


def render_card(st: dict, folder: Path, data: dict, idea: dict):
    folder.mkdir(parents=True, exist_ok=True)
    try:
        return cards.make(
            folder / "card.jpg",
            title=data.get("card_title") or idea["topic"],
            lines=data.get("card_lines") or [],
            label=brand.RUBRICS.get(idea.get("rubric", ""), "").split(" —")[0],
            layout=data.get("card_layout", "band"),
            hero=data.get("card_hero", ""),
            theme=data.get("card_theme", "light"),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("карточка не нарисовалась: %s", e)
        return None


def regenerate_post(st: dict, pid: str, feedback: str) -> None:
    """Переделать пост целиком: и текст, и картинку, с учётом замечаний."""
    p = st_mod.post(st, pid)
    owner = settings.owner_id
    folder = WORK / f"redo{pid}_{int(time.time())}"

    if p.get("source") == "auto":
        idea = {"rubric": p.get("rubric") or "expertise", "topic": p.get("topic") or "",
                "brief": p.get("brief") or ""}
        data = brand.generate_post(idea["rubric"], idea["topic"], idea["brief"],
                                   st.get("used_topics", []),
                                   feedback=feedback, previous=p.get("text", ""),
                                   avoid_layouts=list({p.get("card"), *recent_layouts(st)} - {None}),
                                   theme="light" if p.get("theme") == "dark" else "dark")
        card = render_card(st, folder, data, idea)
        p["text"] = build_caption(data.get("text", ""), data.get("hashtags"))
        p["card"] = data.get("card_layout")
        p["theme"] = data.get("card_theme")
        body = f"{p['text']}\n\n———\nПеределал (макет: {p['card']}):"
        if card:
            msg = tg.send_photo(owner, card, body, kb_review(pid, False))
            p["photo_file_ids"] = [i for i in [tg.file_id_of(msg)] if i]
        else:
            msg = tg.send_message(owner, body, kb_review(pid, False))
        p["review_msg_id"] = msg["message_id"]
        remember(st, "система", f"показал переделанный пост #{pid}, макет {p['card']}")
        return

    # пост с объекта: качаем исходники заново, чистим, режем коллажи, пересобираем
    folder.mkdir(parents=True, exist_ok=True)
    photos = []
    for i, fid in enumerate(p.get("sources", [])[:10]):
        dest = folder / f"{i:03d}.jpg"
        try:
            tg.download(fid, dest)
            photos.append(dest)
        except Exception as e:  # noqa: BLE001
            log.warning("исходник не скачался: %s", e)
    if not photos:
        tg.send_message(owner, "Исходники недоступны — пришли материал заново.")
        return

    problems: list[str] = []
    shots = prepare_shots(photos, folder, p.get("note") or "", problems)
    p["status"] = "rejected"          # старый пост уступает место пересобранному
    for n, group in enumerate(group_shots(shots)):
        compose_post(st, folder, f"re{pid}_{n}", group, [], p.get("note") or "",
                     "photos", list(problems), p.get("sources", []))


def split_post(st: dict, pid: str) -> None:
    """Разобрать готовый пост на несколько — по объектам на кадрах."""
    regenerate_post(st, pid, "разбей по объектам: на каждый объект отдельный пост")


def make_auto_post(st: dict, force: bool = False, topic: str | None = None) -> str | None:
    if topic:
        idea = {"rubric": "expertise", "topic": topic, "brief": ""}
    else:
        refill_ideas(st)
        ideas = st.get("ideas", [])
        if not ideas:
            tg.send_message(settings.owner_id,
                            "Темы кончились, а придумать новые не вышло. Спроси, всё ли работает.")
            return None
        idea = ideas.pop(0)

    try:
        data = brand.generate_post(idea.get("rubric", "expertise"), idea["topic"],
                                   idea.get("brief", ""), st.get("used_topics", []),
                                   avoid_layouts=recent_layouts(st), theme=pick_theme(st))
    except Exception as e:  # noqa: BLE001
        log.exception("автопост не написался")
        tg.send_message(settings.owner_id, f"Не смог написать автопост: {e}")
        return None

    folder = WORK / f"auto{int(time.time())}"
    card = render_card(st, folder, data, idea)

    caption = build_caption(data.get("text", ""), data.get("hashtags"))
    taken = {q.get("scheduled_at") for q in st.get("posts", {}).values() if q.get("scheduled_at")}
    slot = next_slot(taken=taken)

    pid = st_mod.new_post(st, text=caption, topic=idea["topic"], source="auto",
                          rubric=idea.get("rubric"), sources=[], brief=idea.get("brief", ""),
                          card=data.get("card_layout"), theme=data.get("card_theme"))
    remember(st, "система", f"показал пост #{pid} (автопост, макет {data.get('card_layout')}): "
                            f"{idea['topic'][:80]}")

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


def one_round(st: dict, first: bool) -> None:
    """Один круг: забрать почту, ответить, собрать пачку, опубликовать что пора."""
    # Без offset: Telegram отдаёт всё неподтверждённое и НИЧЕГО не вычёркивает.
    # Подтверждаем сами в конце — так offset физически не может убежать вперёд.
    raw = tg.get_updates(0, poll=settings.poll_seconds)

    updates = [u for u in raw if u["update_id"] >= st["offset"]]
    if raw and not updates:
        log.warning("offset убежал вперёд: в состоянии %s, в очереди %s — откатываю",
                    st["offset"], raw[0]["update_id"])
        st["offset"] = raw[0]["update_id"]
        updates = raw
    if raw or first:
        log.info("в очереди: %d, из них новых: %d", len(raw), len(updates))

    if not raw and first:
        # Первый пустой круг — заодно проверяем, что почта вообще ходит.
        try:
            who = tg.me()
            log.info("диагностика · бот: @%s (id=%s)", who.get("username"), who.get("id"))
            wh = tg.webhook_info()
            if wh.get("url"):
                log.error("диагностика · ВЕБХУК ЗАНЯТ: %s — длинный опрос ничего не получит",
                          wh["url"])
            else:
                log.info("диагностика · вебхука нет, в очереди ждёт: %s",
                         wh.get("pending_update_count"))
        except Exception as e:  # noqa: BLE001
            log.error("диагностика не прошла: %s", e)

    # Разбираем сообщения не по одному: пока летят десять фото, «собери пост»
    # приходит подписью к первому — и в отрыве от остальных читается неверно.
    inbox: dict = {"texts": [], "chat": settings.owner_id, "new_batch": False}

    seen = st.setdefault("seen", [])
    for u in updates:
        st["offset"] = u["update_id"] + 1
        if u["update_id"] in seen:
            # два прогона могли пересечься и забрать одну почту — второй раз не отвечаем
            log.info("событие %s уже разобрано, пропускаю", u["update_id"])
            continue
        seen.append(u["update_id"])
        del seen[:-300]
        try:
            if u.get("message"):
                handle_message(u["message"], st, inbox)
            elif u.get("callback_query"):
                handle_callback(u["callback_query"], st)
        except Exception as e:  # noqa: BLE001
            log.exception("событие %s не обработалось", u.get("update_id"))
            try:
                tg.send_message(settings.owner_id, f"Спотыкнулся на одном сообщении: {e}")
            except Exception:  # noqa: BLE001
                pass

    if inbox["texts"]:
        n = len((st.get("batch") or {}).get("media") or [])
        if inbox["new_batch"] and n:
            remember(st, "система", f"Давид прислал файлов: {n}")
        think(" ".join(inbox["texts"]), inbox["chat"], st)
    elif inbox["new_batch"]:
        # файлы пришли молча — коротко подтверждаем и спрашиваем контекст
        batch = st.get("batch") or {}
        media = batch.get("media") or []
        remember(st, "система", f"Давид прислал файлов: {len(media)}")
        try:
            ack = brand.media_ack(batch.get("note", ""),
                                  sum(1 for m in media if m["kind"] == "photo"),
                                  sum(1 for m in media if m["kind"] == "video"))
        except Exception:  # noqa: BLE001
            ack = "Принял. Расскажи пару слов про объект — и соберу пост."
        tg.send_message(inbox["chat"], ack)
        remember(st, "бот", ack)

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


def main() -> int:
    if not settings.token or not settings.owner_id or not settings.channel_id:
        log.error("не заданы TELEGRAM_BOT_TOKEN / OWNER_ID / CHANNEL_ID")
        return 1

    st = st_mod.load()
    log.info("состояние: offset=%s, постов=%d, тем=%d",
             st["offset"], len(st.get("posts", {})), len(st.get("ideas", [])))

    # Один прогон слушает почту несколько минут подряд: пингер будит нас
    # реже, чем хочется живому диалогу, поэтому внутри крутим свой цикл.
    deadline = time.time() + settings.run_seconds
    rounds = 0
    while True:
        rounds += 1
        try:
            one_round(st, first=(rounds == 1))
        except Exception as e:  # noqa: BLE001
            log.exception("круг %d упал", rounds)
            if rounds == 1:
                st_mod.save(st)
                return 1
        st_mod.save(st)
        if time.time() >= deadline:
            break

    log.info("готово: кругов %d, offset=%s", rounds, st["offset"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
