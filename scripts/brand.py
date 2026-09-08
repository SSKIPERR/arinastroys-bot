"""Голос бренда и генерация текстов. Gemini (бесплатный тариф) или Anthropic."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import requests

from config import settings

log = logging.getLogger("brand")

# --------------------------------------------------------------------------
# Всё, что бот знает о компании. Правь этот текст, когда клиент ответит
# на открытые вопросы — про цены, гарантию и города.
# --------------------------------------------------------------------------
BRAND = """
Ты — SMM-редактор строительной компании «Аринастройс» (латиницей ArinaStroys).
Пишешь посты для Telegram-канала компании.

О компании:
- Ремонт и отделка под ключ: квартиры, дома, дачи. Евроремонт, капитальный ремонт.
- База — Москва и Московская область. Работают по всей России: собственник лично
  выезжает на объект, замеряет, считает смету и подписывает договор на месте.
- Комплексный подряд: дизайн, стройка, комплектация — один подрядчик на всё.
- Работа по договору с чёткими этапами и сроками. Авторский надзор. Гарантия
  и постгарантийное обслуживание.
- Заявки принимают в Telegram, по телефону и в директ Instagram.
- Сегмент — средний+.

Как писать:
- По-русски, на «вы», спокойно и по делу. Как говорит прораб, который знает работу,
  а не как рекламное агентство.
- Тон уважительный, без панибратства и без снисходительности. Читатель вкладывает
  в ремонт большие деньги и имеет право на серьёзный разговор. Никакого «ты»,
  сленга и подколок. Если объясняем ошибку — объясняем, а не поучаем.
- Там, где обращаемся к человеку напрямую, формулировать вежливо: «напишите,
  пожалуйста», «будем рады помочь», «спасибо».
- Первая строка цепляет конкретикой, а не лозунгом. Никаких «Мечтаете о ремонте?».
- Короткие абзацы по 1–3 строки, между ними пустая строка. Telegram читают с телефона.
- Конкретика вместо прилагательных: не «качественно и надёжно», а «стяжку сушим
  28 дней, иначе плитка отойдёт».
- Длина поста: 600–1000 знаков.
- Эмодзи — максимум один-два и только по делу. Обычно ноль.

Красные линии (нарушать нельзя):
- НЕ обещать «наши бригады по всей России» и не называть города, где не работали.
  Правильная формулировка: выезжаем на замер, считаем, подписываем договор лично,
  отвечаем по договору. Отвечает юрлицо, а не бригада.
- НЕ выдумывать цены, сроки гарантии, количество объектов, отзывы, имена клиентов
  и любые цифры о компании. Если цифра нужна, а её не дали — переформулируй без неё.
- НЕ писать «АКОБ» — это старое название компании.
- НЕ присваивать компании объект, которого не показывали. Если фото и видео
  не прислали, запрещены обороты «в этом проекте мы», «на объекте в таком-то ЖК
  мы сделали», выдуманные адреса, метражи, планировки и истории заказчиков.
  Пиши обобщённо: «обычно», «в таких случаях», «к нам приходят с задачей»,
  «по опыту». Экспертизу излагать можно и нужно — присваивать себе
  несуществующую работу нельзя.

Хэштеги: не больше 8, отдельной строкой в конце.
Ядро всегда: #ремонтподключ #евроремонт #строительнаякомпания
Если известен город объекта — добавить #ремонтквартир<город> и #ремонт<город>.
Для Москвы и МО: #ремонтквартирмосква #отделкаквартирмосква #ремонтдачи
"""

RUBRICS = {
    "objects": "Объекты и до/после — показываем работу",
    "expertise": "Экспертиза — объясняем, как правильно и почему",
    "process": "Процесс и прозрачность — как устроена работа, договор, этапы, контроль",
    "people": "Люди — команда, прораб, как принимаем работу",
    "sales": "Прямая продажа — пакеты, расчёт сметы, приглашение на замер",
}
RUBRIC_WEIGHTS = {"objects": 40, "expertise": 25, "process": 20, "people": 10, "sales": 5}


class LLMError(RuntimeError):
    pass


# Провайдер выбирается сам: есть ключ Gemini — работаем на нём (бесплатный тариф),
# иначе на Anthropic. Принудительно — переменная LLM_PROVIDER=gemini|anthropic.
PROVIDER = (os.getenv("LLM_PROVIDER") or "").strip().lower()
GEMINI_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or "gemini-3.8-flash").strip()


def provider() -> str:
    if PROVIDER in {"gemini", "anthropic"}:
        return PROVIDER
    return "gemini" if GEMINI_KEY else "anthropic"


def ask(user: str, max_tokens: int = 1600, want_json: bool = False) -> str:
    return _ask_gemini(user, max_tokens, want_json) if provider() == "gemini" \
        else _ask_anthropic(user, max_tokens)


def _gemini_chain() -> list[str]:
    """Модель из настроек, а за ней запасные — на случай перегрузки.

    На бесплатном тарифе самая свежая модель регулярно отвечает 503:
    к ней стоит очередь. Модель постарше в этот момент почти всегда свободна,
    а качество текста для наших задач отличается несильно.
    """
    chain = [GEMINI_MODEL, "gemini-3.5-flash", "gemini-2.5-flash"]
    seen, out = set(), []
    for m in chain:
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _gemini_once(model: str, user: str, max_tokens: int,
                 want_json: bool = False) -> tuple[str | None, str]:
    """Один заход. Возвращает (текст или None, описание проблемы)."""
    cfg: dict = {"maxOutputTokens": max_tokens, "temperature": 0.85}
    if want_json:
        # без этого модель обрамляет JSON пояснениями, и разбор падает
        cfg["responseMimeType"] = "application/json"
    # модели Gemini 3 тратят часть бюджета на размышления, и ответ обрывается
    cfg["thinkingConfig"] = {"thinkingBudget": 0}
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": GEMINI_KEY, "content-type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": BRAND}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": cfg,
            },
            timeout=180,
        )
    except requests.RequestException as e:
        return None, f"{model}: сеть — {e}"

    if r.status_code != 200:
        return None, f"{model}: HTTP {r.status_code} {r.text[:200]}"

    cands = (r.json().get("candidates") or [])
    if not cands:
        return None, f"{model}: пустой ответ"
    parts = (cands[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        # обычно это фильтр безопасности или обрезка по лимиту токенов
        return None, f"{model}: без текста, finishReason={cands[0].get('finishReason')}"
    return text, ""


# коды, при которых имеет смысл подождать и повторить
RETRY_CODES = ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504", "сеть")


def _ask_gemini(user: str, max_tokens: int, want_json: bool = False) -> str:
    if not GEMINI_KEY:
        raise LLMError("не задан GEMINI_API_KEY")

    problems: list[str] = []
    for model in _gemini_chain():
        for attempt in range(3):
            text, why = _gemini_once(model, user, max_tokens, want_json)
            if text:
                if problems:
                    log.info("получилось на %s после %d осечек", model, len(problems))
                return text
            problems.append(why)
            log.warning("Gemini: %s", why)
            if not any(code in why for code in RETRY_CODES):
                break                      # не временная ошибка — меняем модель
            time.sleep(2 * (attempt + 1))  # 2, 4, 6 секунд

    raise LLMError("Gemini не ответил ни одной моделью: " + "; ".join(problems[-3:]))


def _ask_anthropic(user: str, max_tokens: int) -> str:
    if not settings.anthropic_key:
        raise LLMError("не задан ANTHROPIC_API_KEY")
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": settings.anthropic_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": settings.anthropic_model,
            "max_tokens": max_tokens,
            "system": BRAND,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=180,
    )
    if r.status_code != 200:
        raise LLMError(f"{r.status_code}: {r.text[:300]}")
    blocks = r.json().get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


def _json(text: str) -> Any:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start > 0:
        text = text[start:]
    end = max(text.rfind("}"), text.rfind("]"))
    if end >= 0:
        text = text[: end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # чаще всего ответ обрезан по лимиту токенов — покажем начало и конец
        raise LLMError(
            f"не разобрал ответ модели ({e}). Начало: {text[:200]!r} … конец: {text[-120:]!r}"
        ) from e


# ---------------------------------------------------------------- задачи


def caption_for_object(*, guess: str, note: str, photos: int, videos: int,
                       has_before_after: bool) -> dict:
    user = f"""Собери пост для Telegram-канала по материалу с объекта.

Что прислали:
- Похоже на: {guess}
- Комментарий от Давида (может быть пустым): {note or "нет"}
- Фото: {photos}, видео: {videos}{", есть пара до/после" if has_before_after else ""}

Правила для этого поста:
- Опирайся на комментарий. Не выдумывай деталей, которых в нём нет:
  ни города, ни метража, ни сроков, ни материалов.
- Если комментария нет — пиши коротко и общо, про сам факт работы и подход
  компании. Лучше четыре строки правды, чем десять строк выдумки.
- Если в комментарии есть город и это не Москва — упомяни, что выезжали:
  для региональной аудитории это важный сигнал.
- Заголовок первой строкой, без markdown-решёток.

Верни строго JSON:
{{"text": "текст поста без хэштегов",
  "hashtags": ["#..."],
  "video_title": "2-4 слова для титра на видео",
  "video_subtitle": "город или тип объекта, до 30 знаков, можно пустую строку"}}"""
    data = _json(ask(user, 1200, want_json=True))
    data["hashtags"] = data.get("hashtags", [])[:8]
    return data


def generate_post(rubric: str, topic: str, brief: str = "", avoid: list[str] | None = None) -> dict:
    avoid_s = "\n".join(f"- {t}" for t in (avoid or [])[:20]) or "нет"
    user = f"""Напиши пост для Telegram-канала компании.

Рубрика: {RUBRICS.get(rubric, rubric)}
Тема: {topic}
{f"Что раскрыть: {brief}" if brief else ""}

Недавно уже выходило (не повторяйся ни темой, ни первой строкой):
{avoid_s}

Важно: материала по конкретному объекту у тебя нет. Пиши как эксперт о том,
как устроена работа вообще, а не как отчёт о выполненном проекте. Никаких
«в этом проекте мы» и придуманных квартир — только общие формулировки.

Подбери макет картинки под содержание:
- "hero" — если в посте есть ударное число или короткое утверждение в 1-2 слова
  («28 дней», «Ноль доплат», «5 этапов»). Тогда заполни card_hero.
- "grid" — если пунктов ровно 4 или 6 и они равнозначны.
- "band" — во всех остальных случаях. Это выбор по умолчанию.

Верни строго JSON:
{{"text": "готовый текст поста без хэштегов",
  "hashtags": ["#..."],
  "card_title": "заголовок для картинки, 2-5 слов",
  "card_lines": ["до 5 коротких пунктов для картинки, по 3-6 слов"],
  "card_layout": "band | grid | hero",
  "card_hero": "ударное число или слово, только для hero, иначе пустая строка"}}"""
    data = _json(ask(user, 1600, want_json=True))
    data["hashtags"] = data.get("hashtags", [])[:8]
    data["card_lines"] = data.get("card_lines", [])[:5]
    layout = str(data.get("card_layout", "band")).strip().lower()
    hero = str(data.get("card_hero", "") or "").strip()
    # «герой» без ударного слова разваливается — страхуемся
    if layout == "hero" and (not hero or len(hero) > 22):
        layout = "band"
    if layout not in {"band", "grid", "hero"}:
        layout = "band"
    data["card_layout"], data["card_hero"] = layout, hero
    return data


def generate_ideas(n: int = 12, avoid: list[str] | None = None) -> list[dict]:
    avoid_s = "\n".join(f"- {t}" for t in (avoid or [])[:40]) or "нет"
    weights = ", ".join(f"{k} {v}%" for k, v in RUBRIC_WEIGHTS.items())
    user = f"""Придумай {n} тем для постов канала на ближайшие недели.

Распределение по рубрикам примерно такое: {weights}
Рубрики: {json.dumps(RUBRICS, ensure_ascii=False)}

Уже было, не повторять:
{avoid_s}

Требования:
- Тема — конкретный вопрос или утверждение, а не рубрика вообще.
  Плохо: «про плитку». Хорошо: «почему плитку нельзя класть на свежую стяжку».
- Полезно человеку, который выбирает подрядчика или уже начал ремонт.
- Ничего, что требует выдуманных цифр о компании.

Верни строго JSON-массив:
[{{"rubric": "expertise", "topic": "...", "brief": "1-2 предложения"}}]"""
    return [d for d in _json(ask(user, 4000, want_json=True)) if d.get("topic")][:n]


def rewrite(text: str, instruction: str) -> str:
    user = f"""Вот текущий текст поста:

---
{text}
---

Правка от заказчика: {instruction}

Верни только новый текст поста: без пояснений, без хэштегов, без кавычек вокруг."""
    return ask(user, 1400)


# ---------------------------------------------------------------- разговор

ACTIONS = {"build", "note", "queue", "drop", "edit", "publish", "invent",
           "status", "smalltalk"}


def route_message(text: str, ctx: dict) -> dict:
    """Понимает обычную фразу Давида и решает, что делать.

    Команды со слэшем никуда не делись, но помнить их не нужно: сюда приходит
    всё, что он написал словами, а разбирается модель.
    """
    posts = ctx.get("posts") or []
    plist = "\n".join(f"- #{p['id']}: {p['status']}, {p['head']}" for p in posts) or "нет"
    user = f"""Ты разбираешь личную переписку с Давидом. Он ведёт Telegram-канал
компании и пишет тебе обычными словами, без команд. Пойми, чего он хочет.

Его сообщение:
---
{text}
---

Что происходит прямо сейчас:
- Файлов от него, ещё не собранных в пост: {ctx.get('media_count', 0)}
- Что он уже рассказал про этот материал: {ctx.get('note') or 'ничего'}
- Посты, ждущие решения или запланированные:
{plist}

Выбери ровно одно действие:
- "build" — собрать пост из уже присланных файлов. Ставь, когда он просит сделать,
  собрать, смонтировать, оформить, «давай», «готово, работай» — и файлы есть.
- "note" — он рассказывает про объект: город, помещение, стадия, что делали,
  на что обратить внимание. Это контекст для будущего поста, а не приказ.
  Положи суть в поле note.
- "queue" — спрашивает, что в работе, что запланировано, когда выйдет.
- "drop" — просит убрать, удалить, отменить пост. Заполни post_id.
- "edit" — просит переписать, сократить, поправить текст готового поста.
  Заполни post_id и instruction — что именно поменять.
- "publish" — просит опубликовать пост в канал. Заполни post_id.
- "invent" — просит придумать пост самому, без его материала.
- "status" — спрашивает, всё ли работает, что ты умеешь, как дела.
- "smalltalk" — всё остальное: вопрос, благодарность, разговор.

Если номер поста не назван, а подходящий пост ровно один — подставь его.
Если постов несколько и непонятно, о каком речь, ставь "smalltalk"
и в ответе переспроси, о каком именно.

Поле reply — это то, что бот отправит Давиду. Живым языком, на «ты», коротко:
одна-две строки. Без канцелярита, без «ваш запрос принят», без списков,
без markdown и без советов использовать команды — команд для него не существует.
Когда берёшь материал в работу, назови, что именно взял: так он сразу увидит,
что ты понял правильно.

Верни строго JSON:
{{"action": "одно из перечисленных",
  "post_id": "номер поста или пустая строка",
  "instruction": "что поменять, только для edit",
  "note": "что запомнить про объект, только для note",
  "reply": "ответ Давиду"}}"""
    data = _json(ask(user, 700, want_json=True))
    action = str(data.get("action") or "").strip()
    if action not in ACTIONS:
        action = "smalltalk"
    return {
        "action": action,
        "post_id": str(data.get("post_id") or "").strip().lstrip("#"),
        "instruction": str(data.get("instruction") or "").strip(),
        "note": str(data.get("note") or "").strip(),
        "reply": str(data.get("reply") or "").strip(),
    }


def media_ack(note: str, photos: int, videos: int) -> str:
    """Короткая живая реакция на присланный материал."""
    user = f"""Давид только что прислал тебе материал с объекта:
фото — {photos}, видео — {videos}.
Что он написал вместе с ними: {note or "ничего"}.

Ответь ему одной строкой: подтверди, что принял, и скажи, чего не хватает,
чтобы текст получился конкретным (город, помещение, стадия) — но только если
он этого ещё не рассказал. Если рассказал достаточно — просто скажи,
что ждёшь отмашки собирать. На «ты», живым языком, без списков и без команд.
Верни только текст ответа."""
    return ask(user, 200).strip().strip('"')
