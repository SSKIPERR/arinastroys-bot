"""Голос бренда и генерация текстов. Gemini (бесплатный тариф) или Anthropic."""
from __future__ import annotations

import base64
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


def shrink(path, side: int = 768, quality: int = 78) -> str:
    """Ужимает картинку и отдаёт base64: слать в модель оригиналы дорого и незачем."""
    from io import BytesIO
    from PIL import Image, ImageOps

    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    im.thumbnail((side, side))
    buf = BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def ask(user: str, max_tokens: int = 1600, want_json: bool = False,
        images: list | None = None, think: int = 0) -> str:
    """think — бюджет токенов на размышление до ответа. Ноль — отвечать сразу.
    Для разбора фраз Давида включаем: модель заметно точнее читает контекст."""
    return _ask_gemini(user, max_tokens, want_json, images, think) if provider() == "gemini" \
        else _ask_anthropic(user, max_tokens, images)


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
                 want_json: bool = False,
                 images: list | None = None, think: int = 0) -> tuple[str | None, str]:
    """Один заход. Возвращает (текст или None, описание проблемы)."""
    # размышление входит в лимит выходных токенов — иначе ответ обрывается
    cfg: dict = {"maxOutputTokens": max_tokens + think, "temperature": 0.85}
    if want_json:
        # без этого модель обрамляет JSON пояснениями, и разбор падает
        cfg["responseMimeType"] = "application/json"
    cfg["thinkingConfig"] = {"thinkingBudget": think}
    try:
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": GEMINI_KEY, "content-type": "application/json"},
            json={
                "system_instruction": {"parts": [{"text": BRAND}]},
                "contents": [{"role": "user", "parts": _parts(user, images)}],
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


def _parts(user: str, images: list | None) -> list[dict]:
    """Картинки идут перед текстом: так модель сначала смотрит, потом читает задание."""
    parts: list[dict] = []
    for img in (images or [])[:8]:
        try:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": shrink(img)}})
        except Exception as e:  # noqa: BLE001
            log.warning("картинку %s не приложил: %s", getattr(img, "name", img), e)
    parts.append({"text": user})
    return parts


# коды, при которых имеет смысл подождать и повторить
LAYOUTS_ALL = {"band", "grid", "hero", "split", "quote", "steps", "versus", "numbers",
               "checklist", "stats", "poster", "faq", "myth", "table", "warning", "columns"}

RETRY_CODES = ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504", "сеть")


def _ask_gemini(user: str, max_tokens: int, want_json: bool = False,
                images: list | None = None, think: int = 0) -> str:
    if not GEMINI_KEY:
        raise LLMError("не задан GEMINI_API_KEY")

    problems: list[str] = []
    for model in _gemini_chain():
        for attempt in range(3):
            text, why = _gemini_once(model, user, max_tokens, want_json, images, think)
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


def _ask_anthropic(user: str, max_tokens: int, images: list | None = None) -> str:
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
            "messages": [{"role": "user", "content": [
                *[{"type": "image", "source": {"type": "base64",
                                               "media_type": "image/jpeg",
                                               "data": shrink(i)}}
                  for i in (images or [])[:8]],
                {"type": "text", "text": user},
            ]}],
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
                       has_before_after: bool, images: list | None = None,
                       feedback: str = "", previous: str = "") -> dict:
    """Пишет пост по материалу. Картинки уходят в модель — она пишет о том, что видит."""
    redo = ""
    if previous or feedback:
        redo = f"""
ЭТО ПЕРЕДЕЛКА. Прошлую версию Давид забраковал.
Его замечание: {feedback or "не понравилось, сделай сильнее"}
Прошлый текст (не повторяй ни структуру, ни первую строку):
---
{previous[:1500] or "нет"}
---
"""
    user = f"""Собери пост для Telegram-канала по материалу с объекта.
{redo}
{"Кадры приложены выше — смотри на них и пиши о том, что на них действительно есть."
 if images else "Кадры приложить не удалось, пиши по комментарию."}

Что известно:
- Комментарий от Давида (может быть пустым): {note or "нет"}
- Фото: {photos}, видео: {videos}{", есть пара до/после" if has_before_after else ""}
- На что похоже по типу файлов: {guess}

Правила для этого поста:
- Главный источник правды — сами кадры и комментарий Давида. Если комментарий
  и кадры расходятся, верь комментарию: он знает объект, а ты видишь один ракурс.
- Пиши про то, что реально видно: помещение, стадия, приёмы, материалы, свет,
  узлы. Одна конкретная деталь с фотографии стоит десяти общих слов.
- Категорически нельзя писать «показываем рабочие моменты», «делимся процессом»
  и прочие заглушки ни о чём. Если сказать нечего — скажи мало, но по делу.
- Не выдумывай то, чего не видно и о чём не сказано: метраж, сроки, бренды,
  цены, имена. Не приписывай стадию, если она не видна: готовый интерьер
  не называй промежуточным этапом и наоборот.
- Если в комментарии есть город и это не Москва — упомяни, что выезжали.
- Заголовок первой строкой, без markdown-решёток.

Верни строго JSON:
{{"text": "текст поста без хэштегов",
  "hashtags": ["#..."],
  "video_title": "2-4 слова для титра на видео",
  "video_subtitle": "город или тип объекта, до 30 знаков, можно пустую строку",
  "seen": "одной строкой: что ты разглядел на кадрах"}}"""
    data = _json(ask(user, 1300, want_json=True, images=images))
    data["hashtags"] = data.get("hashtags", [])[:8]
    if data.get("seen"):
        log.info("на кадрах: %s", str(data["seen"])[:200])
    return data


LAYOUT_GUIDE = """Макеты картинки — все в одном фирменном стиле, но выглядят по-разному.
Каждый бывает светлым (белый лист) и тёмным (чёрный лист) — поле card_theme.

- "hero"      ударное число или 1-2 слова («28 дней», «Ноль доплат»). Заполни card_hero.
- "stats"     2-4 больших числа с подписью: пункты вида «28 дней — набирает прочность стяжка».
              Слева от тире — только число с единицей (до 12 знаков), справа — пояснение.
- "steps"     процесс по порядку: этапы, «сначала — потом». 4-6 пунктов.
- "numbers"   редакционный список с огромными номерами 01, 02… 3-5 пунктов.
- "checklist" что проверить / что должно быть: чекбоксы с галочками. 4-6 пунктов.
- "versus"    ошибка против правильного, пункты ПАРАМИ: нечётный «так нельзя»,
              чётный «так правильно». 4 или 6 пунктов.
- "myth"      миф против реальности, пункты ПАРАМИ: нечётный — миф (короткий),
              чётный — как на самом деле (с пояснением). 4 или 6 пунктов.
- "warning"   ошибки, за которые дорого платят: косая штриховка сверху. 3-5 пунктов.
- "faq"       вопрос-ответ, пункты вида «Вопрос? — Ответ». 2-4 пары.
- "table"     параметр — значение: «Влажность перед плиткой — 4%». 4-7 строк.
              Значение — ТОЛЬКО число или 1-2 слова («4%», «28 суток», «1 см в неделю»),
              никаких предложений: длинное значение ломает таблицу.
- "grid"      4 или 6 равнозначных пунктов: критерии, признаки, что входит.
- "columns"   инверсный верх с заголовком, ниже пункты в две колонки. 4-6 пунктов.
- "split"     чёрная колонка с коротким заголовком, справа 3-5 пунктов.
- "quote"     одна сильная мысль крупно; 1-3 пояснения.
- "poster"    афиша: 1-3 слова огромно, внизу 1-2 строки подписи. Только тёмная тема.
- "band"      универсальный: заголовок и 3-5 пунктов."""


def generate_post(rubric: str, topic: str, brief: str = "", avoid: list[str] | None = None,
                  feedback: str = "", previous: str = "",
                  avoid_layouts: list[str] | None = None, theme: str = "") -> dict:
    """Пишет автопост и описывает картинку к нему.

    feedback/previous — когда Давид забраковал прошлую версию: что не так и что было.
    avoid_layouts — макеты последних постов, чтобы лента не выглядела одинаково.
    """
    avoid_s = "\n".join(f"- {t}" for t in (avoid or [])[:20]) or "нет"
    banned = [l for l in (avoid_layouts or []) if l in LAYOUTS_ALL]
    redo = ""
    if previous or feedback:
        redo = f"""
ЭТО ПЕРЕДЕЛКА. Прошлую версию Давид забраковал.
Его замечание: {feedback or "не понравилось, сделай сильнее"}
Прошлый текст (не повторяй ни структуру, ни первую строку, ни формулировки):
---
{previous[:1500] or "нет"}
---
Переделка должна быть заметно другой и заметно лучше: конкретнее, плотнее,
с физикой процесса, цифрами из практики и последствиями ошибок. Без воды.
"""
    user = f"""Напиши пост для Telegram-канала компании.

Рубрика: {RUBRICS.get(rubric, rubric)}
Тема: {topic}
{f"Что раскрыть: {brief}" if brief else ""}
{redo}
Недавно уже выходило (не повторяйся ни темой, ни первой строкой):
{avoid_s}

Важно: материала по конкретному объекту у тебя нет. Пиши как эксперт о том,
как устроена работа вообще, а не как отчёт о выполненном проекте. Никаких
«в этом проекте мы» и придуманных квартир — только общие формулировки.

Насыщенность: читатель должен узнать то, чего не знал. Цифры, допуски, сроки,
почему именно так, что будет, если иначе. Каждый абзац несёт факт, а не настроение.

{LAYOUT_GUIDE}
{("Эти макеты только что использовались, выбери другой: " + ", ".join(banned)) if banned else ""}

Пункты для картинки пиши в формате «Заголовок — пояснение»: заголовок 2-4 слова,
пояснение 4-9 слов с конкретикой. Например: «28 дней набора прочности — раньше
плитка отойдёт вместе с клеем». Пояснение обязательно: без него картинка пустая.
Для stats и table заголовок пункта — это число или значение, пояснение — что оно значит.
{("Тема картинки на этот раз: " + theme + ".") if theme else "Тему (light/dark) выбери сам, под настроение поста."}

Верни строго JSON:
{{"text": "готовый текст поста без хэштегов",
  "hashtags": ["#..."],
  "card_title": "заголовок для картинки, 2-6 слов",
  "card_lines": ["4-6 пунктов «Заголовок — пояснение»"],
  "card_layout": "одно из названий макетов",
  "card_theme": "light | dark",
  "card_hero": "ударное число или слово, только для hero, иначе пустая строка"}}"""
    data = _json(ask(user, 2000, want_json=True))
    data["hashtags"] = data.get("hashtags", [])[:8]
    data["card_lines"] = [str(x) for x in data.get("card_lines", [])][:6]
    layout = str(data.get("card_layout", "band")).strip().lower()
    hero = str(data.get("card_hero", "") or "").strip()
    n = len(data["card_lines"])
    if layout == "hero" and (not hero or len(hero) > 22):
        layout = "split"
    if layout in ("versus", "myth") and n < 4:
        layout = "band"
    # таблица и цифры живут только с короткими значениями — иначе переезжаем на список
    heads = [x.split(" — ", 1)[0] if " — " in x else x for x in data["card_lines"]]
    tails = [x.split(" — ", 1)[1] if " — " in x else "" for x in data["card_lines"]]
    if layout == "table" and any(len(v) > 18 or not v for v in tails):
        layout = "numbers"
    if layout == "stats" and any(len(h) > 12 or not v for h, v in zip(heads, tails)):
        layout = "numbers"
    if layout not in LAYOUTS_ALL or layout in banned:
        # модель выбрала занятый макет — берём первый свободный по порядку предпочтения
        for cand in ("steps", "numbers", "checklist", "split", "columns", "grid", "table",
                     "quote", "warning", "stats", "band", "faq", "versus", "myth", "hero"):
            if cand not in banned and (cand != "hero" or hero) \
                    and (cand not in ("versus", "myth") or n >= 4):
                layout = cand
                break
    th = str(data.get("card_theme") or theme or "light").strip().lower()
    if layout == "poster":
        th = "dark"
    data["card_layout"], data["card_hero"] = layout, hero
    data["card_theme"] = th if th in ("light", "dark") else "light"
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


# ---------------------------------------------------------------- осмотр и чистка кадров


def inspect_photos(images: list, note: str = "") -> dict:
    """Смотрит на присланные кадры до того, как писать текст.

    Возвращает, что на каждом кадре лишнее (наложенный текст, логотипы, даты,
    элементы интерфейса) и какие кадры образуют пары «до / после».
    """
    if not images:
        return {"photos": [], "pairs": []}
    user = f"""Перед тобой {len(images)} кадр(ов) с объекта, в том порядке, в каком приложены
(нумерация с 0). Комментарий Давида: {note or "нет"}.

Задача 1. На каждом кадре найди ЛИШНЕЕ, чего в чистой фотографии интерьера быть
не должно: наложенный текст и подписи, водяные знаки, логотипы, дата и время
съёмки, стикеры, эмодзи, элементы интерфейса приложений, рамки, чужие
надписи. Настоящие объекты — вывески, упаковки, инструмент — лишним не считаются.
Для каждого кадра верни clutter: true/false, коротко what — что именно, и where —
где оно расположено: top, bottom, left, right или center.

Задача 2. Определи, есть ли пары «до / после»: один и тот же ракурс или
помещение до ремонта (черновая, старая отделка, демонтаж) и после (чистовая).
Если пары есть — верни их индексы. Если не уверен — пар нет.

Задача 3. Для каждого кадра одним словом — что на нём: кухня, ванная, коридор,
спальня, черновая, фасад и т.п.

Верни строго JSON:
{{"photos": [{{"i": 0, "clutter": false, "what": "", "where": "", "room": "кухня"}}, ...],
  "pairs": [{{"before": 0, "after": 1}}]}}"""
    data = _json(ask(user, 900, want_json=True, images=images))
    photos = []
    for x in data.get("photos") or []:
        try:
            i = int(x.get("i"))
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(images):
            photos.append({"i": i, "clutter": bool(x.get("clutter")),
                           "what": str(x.get("what") or "")[:120],
                           "where": str(x.get("where") or "")[:10].lower(),
                           "room": str(x.get("room") or "")[:40]})
    pairs = []
    for pr in data.get("pairs") or []:
        try:
            bi, ai = int(pr.get("before")), int(pr.get("after"))
        except (TypeError, ValueError, AttributeError):
            continue
        if bi != ai and 0 <= bi < len(images) and 0 <= ai < len(images):
            pairs.append({"before": bi, "after": ai})
    return {"photos": photos, "pairs": pairs[:3]}


IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "").strip()


def _image_chain() -> list[str]:
    chain = [IMAGE_MODEL, "gemini-2.5-flash-image", "gemini-2.5-flash-image-preview"]
    out, seen = [], set()
    for m in chain:
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def clean_photo(src, dst, what: str = "") -> bool:
    """Убирает с фотографии наложенный текст и прочий мусор картиночной моделью.

    Возвращает True, если dst записан. Модель просят ничего, кроме лишнего,
    не трогать: ни цвет, ни кадрирование, ни предметы.
    """
    if not GEMINI_KEY or provider() != "gemini":
        return False
    prompt = ("Убери с этой фотографии всё наложенное поверх снимка: текст, подписи, "
              "водяные знаки, логотипы, дату и время, стикеры, элементы интерфейса"
              + (f" — в частности: {what}" if what else "") +
              ". Аккуратно дорисуй фон на их месте. Всё остальное оставь ровно как есть: "
              "тот же кадр, те же цвета, та же резкость, ничего не добавляй и не улучшай. "
              "Верни только изображение.")
    problems = []
    for model in _image_chain():
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": GEMINI_KEY, "content-type": "application/json"},
                json={"contents": [{"role": "user", "parts": [
                          {"inline_data": {"mime_type": "image/jpeg", "data": shrink(src, 1280, 90)}},
                          {"text": prompt}]}],
                      "generationConfig": {"responseModalities": ["IMAGE"]}},
                timeout=180,
            )
        except requests.RequestException as e:
            problems.append(f"{model}: сеть — {e}")
            continue
        if r.status_code != 200:
            problems.append(f"{model}: HTTP {r.status_code} {r.text[:120]}")
            continue
        parts = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        for part in parts:
            blob = part.get("inlineData") or part.get("inline_data")
            if blob and blob.get("data"):
                from pathlib import Path as _P
                _P(dst).write_bytes(base64.b64decode(blob["data"]))
                log.info("кадр очищен моделью %s", model)
                return True
        problems.append(f"{model}: в ответе нет картинки")
    log.warning("чистка не удалась: %s", "; ".join(problems[-2:]))
    return False


def crop_edge(src, dst, where: str, share: float = 0.14) -> bool:
    """Запасной путь, когда картиночная модель недоступна: если мусор у края —
    просто отрезаем этот край. Центр так не спасти — тогда оставляем как есть."""
    from PIL import Image, ImageOps
    if where not in ("top", "bottom", "left", "right"):
        return False
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    w, h = im.size
    cut = int((h if where in ("top", "bottom") else w) * share)
    box = {"top": (0, cut, w, h), "bottom": (0, 0, w, h - cut),
           "left": (cut, 0, w, h), "right": (0, 0, w - cut, h)}[where]
    im.crop(box).save(dst, "JPEG", quality=92)
    return True


# ---------------------------------------------------------------- разговор


TOOLS = {"make_post", "remake", "publish", "schedule", "rewrite", "remake_video",
         "drop", "show_queue", "invent", "health"}

TOOLBOX = """Инструменты. Можешь вызвать несколько подряд или ни одного:

make_post — собрать пост из файлов, которые он прислал.
    format: "photos" — фотографиями, без монтажа; "reel" — вертикальный ролик;
            "auto" — есть видео или больше трёх фото → ролик, иначе фото.
    note: детали объекта его словами. keep_order: true, если просил не менять порядок.
remake — ПЕРЕДЕЛАТЬ готовый пост целиком по замечаниям: заново и текст, и картинка
    (другой макет). post_id, feedback — что именно не так, его словами, полностью.
    Это для «так себе», «криво», «мало деталей», «картинка не нравится», «сделай
    насыщеннее», «другой визуал».
rewrite — поправить ТОЛЬКО текст, картинка остаётся. post_id, how.
    Это для «сократи», «убери про гарантию», «замени слово», «добавь абзац про X».
remake_video — перемонтировать ролик у готового поста. post_id.
publish — опубликовать пост в канал. post_id.
schedule — поставить пост в расписание. post_id.
drop — убрать пост. post_id.
show_queue — показать, что в работе.
invent — придумать новый пост на тему. topic (можно пустым — выберу из банка).
health — проверить, всё ли работает."""


def decide(text: str, ctx: dict) -> dict:
    """Решает, что делать с сообщением Давида, и что ему ответить.

    Не классификатор на кнопки, а список действий с параметрами. Перед ответом
    модель думает (think), иначе читает фразы поверхностно.
    """
    posts = ctx.get("posts") or []
    plist = "\n".join(f"- #{p['id']}: {p['status']}, {p['head']}" for p in posts) or "нет"
    hist = "\n".join(f"{h['who']}: {h['text']}" for h in (ctx.get("history") or [])[-16:]) \
        or "это первое сообщение"
    files = ctx.get("media") or {"photos": 0, "videos": 0}
    last = ctx.get("last_post") or {}
    user = f"""Ты — помощник Давида, SMM-редактор строительной компании. Он ведёт
Telegram-канал, ты собираешь ему посты и отвечаешь за визуал. Он пишет обычными
словами, как коллеге, и ждёт, что ты поймёшь с первого раза.

Переписка (старые сообщения сверху):
{hist}

Новое сообщение от Давида:
---
{text}
---

Положение дел:
- Не разобранных файлов от него: фото {files.get('photos', 0)}, видео {files.get('videos', 0)}
- Что уже известно про этот материал: {ctx.get('note') or 'ничего'}
- Последний пост, который ты ему показывал: {("#" + str(last.get("id")) + " — " + str(last.get("head", ""))) if last else "нет"}
- Посты в работе:
{plist}

{TOOLBOX}

Как думать:
1. Прочитай фразу целиком. В ней может быть задание, условие и уточнение сразу:
   «сделай пост, видео не надо, фото по порядку» — один make_post с format="photos"
   и keep_order=true. Отрицание — это условие, а не просьба что-то удалить.
2. Если он ругает пост или картинку — это remake того поста. «Так себе», «криво»,
   «мало деталей», «картинка не нравится», «насыщеннее» — всё remake, с его словами
   в feedback. Не переспрашивай, что именно не так, если он уже сказал хоть что-то:
   сделай и покажи, он поправит.
3. Пост без номера — это последний показанный (см. выше), либо тот, о котором шла
   речь в переписке. Переспрашивай номер, только если постов несколько и по
   переписке правда не понять.
4. Если он уже просил собрать пост — раньше в переписке или подписью к фото, —
   договорённость в силе. Разрешения второй раз не спрашивают.
5. drop — только если он явно просит убрать существующий пост.
6. Если файлов нет, а он просит собрать — не вызывай инструмент, скажи, что ждёшь материал.
7. Обещай ТОЛЬКО то, что делаешь инструментом в этом же ответе. Нет инструмента —
   так и скажи. Фраза «подберу нормальный визуал» без remake — ложь, так нельзя.
8. Если он задал вопрос или просит совета — ответь по существу, как знающий человек,
   без инструментов. Разговаривать ты тоже умеешь.
9. Ничего делать не надо — верни пустой список действий и просто ответь.

Ответ Давиду (reply): живым языком, на «ты». Коротко, когда дело в действии:
скажи, что берёшь и как сделаешь. Развёрнуто, когда он спрашивает или обсуждает.
Без списков, без markdown, без канцелярита, без упоминания команд.

Верни строго JSON:
{{"reply": "что написать Давиду",
  "actions": [{{"tool": "имя инструмента", "args": {{"...": "..."}}}}]}}"""
    try:
        data = _json(ask(user, 1000, want_json=True, think=1024))
    except LLMError as e:
        # если размышление модели недоступно — отвечаем без него, но отвечаем
        log.warning("decide с размышлением не вышел (%s), пробую без", str(e)[:120])
        data = _json(ask(user, 1000, want_json=True))
    actions = []
    for a in (data.get("actions") or [])[:4]:
        if not isinstance(a, dict):
            continue
        tool = str(a.get("tool") or "").strip()
        if tool in TOOLS:
            args = a.get("args")
            actions.append({"tool": tool, "args": args if isinstance(args, dict) else {}})
    return {"reply": str(data.get("reply") or "").strip(), "actions": actions}


def media_ack(note: str, photos: int, videos: int) -> str:
    """Короткая живая реакция на присланный материал."""
    user = f"""Давид только что прислал материал с объекта: фото — {photos}, видео — {videos}.
Что он написал вместе с ними: {note or "ничего"}.

Ответь одной строкой: подтверди, что принял, и спроси то, чего не хватает для
конкретного текста (город, помещение, стадия) — только если он этого ещё не сказал.
Если сказал достаточно — просто спроси, собирать ли. На «ты», без списков и команд.
Верни только текст ответа."""
    return ask(user, 200).strip().strip('"')
