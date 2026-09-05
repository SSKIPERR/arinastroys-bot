"""Прогон логики без Telegram и без ИИ: подменяем сеть заглушками.

Проверяет то, что чаще всего ломается: разбор пачки, монтаж, сборку подписи,
переходы статусов и публикацию по file_id.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "1:test")
os.environ.setdefault("OWNER_ID", "42")
os.environ.setdefault("CHANNEL_ID", "@arinastroys")

sys.path.insert(0, str(Path(__file__).parent))

import brand  # noqa: E402
import state as st_mod  # noqa: E402
import tg  # noqa: E402
import tick  # noqa: E402

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/srcmedia_test")
SENT: list[tuple[str, str]] = []
_counter = {"n": 0}


def fake_id(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}_file_{_counter['n']}"


# ---- заглушки сети ----
def _download(file_id: str, dest: Path) -> Path:
    src = FILES[file_id]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(Path(src).read_bytes())
    return dest


def _send_message(chat, text, keyboard=None, preview=False):
    SENT.append(("message", text[:70].replace("\n", " ")))
    return {"message_id": _counter["n"] + 100}


def _send_photo(chat, photo, caption="", keyboard=None):
    SENT.append(("photo", str(photo)[-28:]))
    return {"message_id": _counter["n"] + 100, "photo": [{"file_id": fake_id("ph")}]}


def _send_video(chat, video, caption="", keyboard=None):
    SENT.append(("video", str(video)[-28:]))
    return {"message_id": _counter["n"] + 100, "video": {"file_id": fake_id("vid")}}


def _send_media_group(chat, ids, caption=""):
    SENT.append(("group", f"{len(ids)} шт"))
    return [{"message_id": 777}]


tg.download = _download
tg.send_message = _send_message
tg.send_photo = _send_photo
tg.send_video = _send_video
tg.send_media_group = _send_media_group
tg.edit_markup = lambda *a, **k: None
tg.answer_callback = lambda *a, **k: None

# ИИ не дёргаем — проверяем в том числе, что заглушка текста работает
brand.caption_for_object = lambda **kw: (_ for _ in ()).throw(brand.LLMError("ключа нет (так и задумано)"))


def main() -> int:
    videos = sorted(p for p in SRC.iterdir() if p.suffix.lower() in {".mp4", ".mov"})
    photos = sorted(p for p in SRC.iterdir() if p.suffix.lower() in {".jpg", ".png"})
    if not videos and not photos:
        print(f"нет исходников в {SRC}")
        return 1

    global FILES
    FILES = {}
    media = []
    for p in videos:
        fid = fake_id("in")
        FILES[fid] = p
        media.append({"kind": "video", "file_id": fid})
    for p in photos:
        fid = fake_id("in")
        FILES[fid] = p
        media.append({"kind": "photo", "file_id": fid})

    st = json.loads(json.dumps(st_mod.EMPTY))
    st["batch"] = {"media": media, "note": "Казань, кухня, финишная отделка. До и после.",
                   "last_ts": 0}

    print(f"на входе: {len(videos)} видео, {len(photos)} фото")
    print("тип определён как:", tick.guess_kind(media, st["batch"]["note"]))

    tick.build_post(st)

    print("\nчто ушло в личку:")
    for kind, what in SENT:
        print(f"  {kind:8} {what}")

    posts = st.get("posts", {})
    assert posts, "пост не создался"
    pid, p = next(iter(posts.items()))
    print(f"\nпост #{pid}: статус={p['status']}, видео={bool(p.get('video_file_id'))}, "
          f"фото={len(p.get('photo_file_ids', []))}, исходников сохранено={len(p.get('sources', []))}")
    print("текст:", (p["text"][:120] + "…").replace("\n", " "))
    assert st["batch"] is None, "пачка не закрылась"

    # публикация по file_id — без повторной загрузки
    SENT.clear()
    mid = tick.publish(p)
    print(f"\nпубликация: message_id={mid}, отправлено {SENT}")

    # очередь и слот
    slot = tick.next_slot()
    print(f"ближайшее окно: {slot:%a %d.%m %H:%M %Z}")
    slot2 = tick.next_slot(taken={slot.isoformat()})
    assert slot2 > slot
    print(f"следующее после занятого: {slot2:%a %d.%m %H:%M}")

    # подпись длиннее лимита
    long = tick.build_caption("Предложение. " * 200, ["#ремонтподключ"])
    assert len(long) <= 1024, len(long)
    print(f"длинная подпись обрезана до {len(long)} знаков, хвост: …{long[-30:]!r}")

    # состояние сохраняется и читается
    st_mod.save(st)
    back = st_mod.load()
    assert back["posts"] == st["posts"]
    size = (Path(__file__).parent.parent / "state" / "session.json").stat().st_size
    print(f"\nсостояние записано и прочитано, {size} байт")
    print("\nВСЁ ПРОШЛО")
    return 0


if __name__ == "__main__":
    sys.exit(main())
