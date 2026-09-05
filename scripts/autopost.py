"""Автопост: бот придумывает тему и пишет пост сам. Запускается накануне дня публикации."""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta

import state as st_mod
import tg
from config import settings
from tick import make_auto_post, next_slot, publish_due

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s · %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("autopost")


def main() -> int:
    if not settings.token or not settings.owner_id:
        log.error("не заданы секреты")
        return 1

    st = st_mod.load()
    taken = {p.get("scheduled_at") for p in st.get("posts", {}).values() if p.get("scheduled_at")}
    slot = next_slot(taken=taken)

    # если окно уже занято или до него больше суток — ничего не делаем
    if slot > datetime.now(settings.tz) + timedelta(days=1, hours=6):
        log.info("ближайшее окно %s — ещё рано", slot)
        st_mod.save(st)
        return 0

    waiting = [pid for pid, p in st.get("posts", {}).items() if p.get("status") == "review"]
    if waiting:
        tg.send_message(
            settings.owner_id,
            f"Окно {slot:%d.%m %H:%M} МСК свободно, а у тебя {len(waiting)} пост(ов) "
            f"ждут решения. Нажми «В очередь» на нужном — или я придумаю свой завтра.",
        )
        st_mod.save(st)
        return 0

    pid = make_auto_post(st)
    publish_due(st)
    st_mod.save(st)
    log.info("автопост: %s", pid or "не получился")
    return 0


if __name__ == "__main__":
    sys.exit(main())
