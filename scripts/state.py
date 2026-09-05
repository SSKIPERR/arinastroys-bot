"""Состояние между запусками. Один JSON-файл, который workflow коммитит обратно в репозиторий."""
from __future__ import annotations

import json
import logging
from typing import Any

from config import STATE_DIR

log = logging.getLogger("state")
SESSION = STATE_DIR / "session.json"

EMPTY: dict[str, Any] = {
    "offset": 0,
    # незакрытая пачка материала: копим file_id, пока Давид не перестанет слать
    "batch": None,
    # посты: {"12": {...}}
    "posts": {},
    "next_id": 1,
    # банк тем для автопостов
    "ideas": [],
    # что уже выходило — чтобы не повторяться
    "used_topics": [],
}


def load() -> dict:
    if not SESSION.exists():
        return json.loads(json.dumps(EMPTY))
    try:
        data = json.loads(SESSION.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        log.warning("состояние битое (%s) — начинаю с чистого", e)
        return json.loads(json.dumps(EMPTY))
    for k, v in EMPTY.items():
        data.setdefault(k, json.loads(json.dumps(v)))
    return data


def save(data: dict) -> None:
    # не даём файлу расти бесконечно
    data["used_topics"] = data.get("used_topics", [])[-60:]
    posts = data.get("posts", {})
    if len(posts) > 80:
        keep = sorted(posts.items(), key=lambda kv: int(kv[0]))[-80:]
        data["posts"] = dict(keep)

    SESSION.parent.mkdir(parents=True, exist_ok=True)
    SESSION.write_text(
        json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )


def new_post(data: dict, **fields: Any) -> str:
    pid = str(data.get("next_id", 1))
    data["next_id"] = int(pid) + 1
    fields.setdefault("status", "review")
    data.setdefault("posts", {})[pid] = fields
    return pid


def post(data: dict, pid: str) -> dict | None:
    return data.get("posts", {}).get(str(pid))
