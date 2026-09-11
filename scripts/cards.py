"""Карточки для постов. Фирменные макеты вместо голого текста на белом.

Система: белый фон, чёрный #1A1A1A, Oswald капсом в заголовках, Golos Text
в тексте, JetBrains Mono в лейблах. Вместо цифр — линейные иконки, как
в остальных материалах бренда.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

from photo import font  # общий резолвер шрифтов

BLACK = (26, 26, 26)
WHITE = (255, 255, 255)
GREY = (122, 122, 122)
HAIR = (228, 228, 228)

POST = (1080, 1350)
STORY = (1080, 1920)


# ---------------------------------------------------------------- типографика


def tracked(d: ImageDraw.ImageDraw, xy: tuple[float, float], text: str,
            f, fill, tracking: float = 0.0) -> float:
    """Текст с разрядкой. PIL её не умеет, рисуем по букве."""
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=f, fill=fill)
        x += d.textlength(ch, font=f) + tracking
    return x - xy[0]


def tracked_width(d: ImageDraw.ImageDraw, text: str, f, tracking: float = 0.0) -> float:
    return sum(d.textlength(c, font=f) for c in text) + tracking * max(len(text) - 1, 0)


def wrap(d: ImageDraw.ImageDraw, text: str, f, max_w: float) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        probe = f"{cur} {w}".strip()
        if d.textlength(probe, font=f) <= max_w or not cur:
            cur = probe
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_font(d: ImageDraw.ImageDraw, text: str, kind: str, max_w: float,
             start: int, minimum: int = 32, max_lines: int | None = None):
    """Подбирает кегль: самое длинное слово влезает в ширину, а весь текст —
    в max_lines строк, чтобы заголовок не терял последнее слово."""
    longest = max(text.split(), key=len, default=text)
    size = start
    while size > minimum:
        f = font(kind, size)
        if d.textlength(longest, font=f) <= max_w and (
                max_lines is None or len(wrap(d, text, f, max_w)) <= max_lines):
            return f
        size -= 3
    return font(kind, minimum)


# ---------------------------------------------------------------- иконки
# Линейные, в квадрате box=(x, y, side). Толщина подбирается от размера.


def _w(side: float) -> int:
    return max(int(side * 0.095), 4)


def ic_house(d, x, y, s, c=BLACK):
    w = _w(s)
    d.line([(x + s * .08, y + s * .48), (x + s * .5, y + s * .12),
            (x + s * .92, y + s * .48)], fill=c, width=w, joint="curve")
    d.line([(x + s * .2, y + s * .44), (x + s * .2, y + s * .88)], fill=c, width=w)
    d.line([(x + s * .8, y + s * .44), (x + s * .8, y + s * .88)], fill=c, width=w)
    d.line([(x + s * .2, y + s * .88), (x + s * .8, y + s * .88)], fill=c, width=w)


def ic_roller(d, x, y, s, c=BLACK):
    w = _w(s)
    d.rectangle([x + s * .12, y + s * .12, x + s * .78, y + s * .38], outline=c, width=w)
    d.line([(x + s * .45, y + s * .38), (x + s * .45, y + s * .55)], fill=c, width=w)
    d.line([(x + s * .45, y + s * .55), (x + s * .62, y + s * .55)], fill=c, width=w)
    d.rectangle([x + s * .55, y + s * .55, x + s * .7, y + s * .9], outline=c, width=w)


def ic_doc(d, x, y, s, c=BLACK):
    w = _w(s)
    d.rectangle([x + s * .2, y + s * .08, x + s * .8, y + s * .92], outline=c, width=w)
    for i, fy in enumerate((.32, .48, .64)):
        d.line([(x + s * .34, y + s * fy), (x + s * (.66 if i < 2 else .54), y + s * fy)],
               fill=c, width=max(w - 1, 2))


def ic_calc(d, x, y, s, c=BLACK):
    w = _w(s)
    d.rectangle([x + s * .2, y + s * .08, x + s * .8, y + s * .92], outline=c, width=w)
    d.rectangle([x + s * .32, y + s * .2, x + s * .68, y + s * .36], outline=c, width=max(w - 1, 2))
    for r in range(2):
        for col in range(3):
            cx = x + s * (.35 + col * .155)
            cy = y + s * (.52 + r * .18)
            d.ellipse([cx - w, cy - w, cx + w, cy + w], fill=c)


def ic_square(d, x, y, s, c=BLACK):      # угольник
    w = _w(s)
    d.line([(x + s * .14, y + s * .14), (x + s * .14, y + s * .86),
            (x + s * .86, y + s * .86)], fill=c, width=w, joint="curve")
    for i in range(1, 4):
        d.line([(x + s * .14, y + s * (.86 - i * .16)), (x + s * .26, y + s * (.86 - i * .16))],
               fill=c, width=max(w - 1, 2))


def ic_shield(d, x, y, s, c=BLACK):
    w = _w(s)
    d.line([(x + s * .5, y + s * .1), (x + s * .86, y + s * .26)], fill=c, width=w)
    d.line([(x + s * .5, y + s * .1), (x + s * .14, y + s * .26)], fill=c, width=w)
    d.line([(x + s * .14, y + s * .26), (x + s * .14, y + s * .5)], fill=c, width=w)
    d.line([(x + s * .86, y + s * .26), (x + s * .86, y + s * .5)], fill=c, width=w)
    d.arc([x + s * .14, y + s * .1, x + s * .86, y + s * .92], 0, 180, fill=c, width=w)


def ic_helmet(d, x, y, s, c=BLACK):
    w = _w(s)
    d.arc([x + s * .18, y + s * .22, x + s * .82, y + s * .86], 180, 360, fill=c, width=w)
    d.line([(x + s * .08, y + s * .62), (x + s * .92, y + s * .62)], fill=c, width=w)
    d.line([(x + s * .5, y + s * .22), (x + s * .5, y + s * .34)], fill=c, width=max(w - 1, 2))


def ic_clock(d, x, y, s, c=BLACK):
    w = _w(s)
    d.ellipse([x + s * .12, y + s * .12, x + s * .88, y + s * .88], outline=c, width=w)
    d.line([(x + s * .5, y + s * .5), (x + s * .5, y + s * .28)], fill=c, width=w)
    d.line([(x + s * .5, y + s * .5), (x + s * .68, y + s * .58)], fill=c, width=w)


def ic_drop(d, x, y, s, c=BLACK):
    w = _w(s)
    d.arc([x + s * .2, y + s * .34, x + s * .8, y + s * .92], 0, 360, fill=c, width=w)
    d.line([(x + s * .5, y + s * .1), (x + s * .28, y + s * .5)], fill=c, width=w)
    d.line([(x + s * .5, y + s * .1), (x + s * .72, y + s * .5)], fill=c, width=w)


def ic_bulb(d, x, y, s, c=BLACK):
    w = _w(s)
    d.arc([x + s * .24, y + s * .1, x + s * .76, y + s * .62], 0, 360, fill=c, width=w)
    d.line([(x + s * .38, y + s * .62), (x + s * .38, y + s * .78)], fill=c, width=w)
    d.line([(x + s * .62, y + s * .62), (x + s * .62, y + s * .78)], fill=c, width=w)
    d.line([(x + s * .38, y + s * .78), (x + s * .62, y + s * .78)], fill=c, width=w)
    d.line([(x + s * .43, y + s * .9), (x + s * .57, y + s * .9)], fill=c, width=w)


ICONS = [ic_house, ic_roller, ic_square, ic_doc, ic_calc, ic_shield, ic_helmet,
         ic_clock, ic_drop, ic_bulb]


def icon_for(text: str, index: int):
    """Подбираем иконку по смыслу пункта, иначе — по порядку."""
    t = text.lower()
    table = [
        (("договор", "гарант", "акт", "смет", "документ"), ic_doc),
        (("цена", "расч", "бюджет", "стоим"), ic_calc),
        (("замер", "проект", "план", "ровн", "маяк", "выравн"), ic_square),
        (("краск", "отделк", "чистов", "малярн", "штукатур"), ic_roller),
        (("срок", "график", "пауз", "суш", "этап", "время"), ic_clock),
        (("вод", "стяж", "гидро", "влаг", "протеч"), ic_drop),
        (("электр", "свет", "розет", "провод"), ic_bulb),
        (("защит", "надёж", "надеж", "качеств", "контрол", "надзор"), ic_shield),
        (("бригад", "прораб", "команд", "мастер", "монтаж"), ic_helmet),
        (("дом", "квартир", "дач", "объект", "новосель", "ключ"), ic_house),
    ]
    for keys, fn in table:
        if any(k in t for k in keys):
            return fn
    return ICONS[index % len(ICONS)]


def split_item(text: str) -> tuple[str, str]:
    """«Стяжка сохнет 28 дней — иначе плитка отойдёт» → заголовок и пояснение."""
    for sep in (" — ", " –– ", " -- ", ": "):
        if sep in text:
            head, detail = text.split(sep, 1)
            return head.strip(), detail.strip()
    return text.strip(), ""


def ic_cross(d, x, y, s, c=BLACK):
    w = _w(s)
    d.line([(x + s * 0.2, y + s * 0.2), (x + s * 0.8, y + s * 0.8)], fill=c, width=w)
    d.line([(x + s * 0.8, y + s * 0.2), (x + s * 0.2, y + s * 0.8)], fill=c, width=w)


def ic_check(d, x, y, s, c=BLACK):
    w = _w(s)
    d.line([(x + s * 0.18, y + s * 0.52), (x + s * 0.42, y + s * 0.76),
            (x + s * 0.84, y + s * 0.26)], fill=c, width=w, joint="curve")


def _item(d, x, y, text, max_w, head_f, detail_f, head_c=BLACK, detail_c=GREY) -> float:
    """Пункт с заголовком и серым пояснением. Возвращает высоту."""
    head, detail = split_item(text)
    yy = y
    for ln in wrap(d, head, head_f, max_w)[:2]:
        d.text((x, yy), ln, font=head_f, fill=head_c)
        yy += int(head_f.size * 1.2)
    if detail:
        yy += 4
        for ln in wrap(d, detail, detail_f, max_w)[:3]:
            d.text((x, yy), ln, font=detail_f, fill=detail_c)
            yy += int(detail_f.size * 1.28)
    return yy - y


# ---------------------------------------------------------------- макеты


def _footer(img, d, size, height=110):
    """Чёрная полоса внизу с юзернеймом — закрывает пустоту и держит кадр."""
    W, H = size
    d.rectangle([0, H - height, W, H], fill=BLACK)
    f = font("text-bold", 34)
    fm = font("mono", 26)
    m = int(W * 0.089)
    d.text((m, H - height + (height - 44) / 2), "@arinastroys", font=f, fill=WHITE)
    right = "МОСКВА · МО · ВСЯ РОССИЯ"
    wgt = tracked_width(d, right, fm, 2)
    tracked(d, (W - m - wgt, H - height + (height - 34) / 2), right, fm, (170, 170, 170), 2)


def card_band(dst: Path, title: str, lines: list[str], label: str = "",
              size=POST) -> Path:
    """Макет «плашка»: чёрный блок с заголовком сверху, список с иконками снизу."""
    W, H = size
    img = Image.new("RGB", size, WHITE)
    d = ImageDraw.Draw(img)
    m = int(W * 0.089)
    foot = 110

    band = int(H * 0.40)
    d.rectangle([0, 0, W, band], fill=BLACK)

    y = m
    fm = font("mono", 26)
    tracked(d, (m, y), "ARINASTROYS", fm, (150, 150, 150), 5)
    if label:
        wl = tracked_width(d, label.upper(), fm, 4)
        tracked(d, (W - m - wl, y), label.upper(), fm, (150, 150, 150), 4)

    box = W - m * 2
    ft = fit_font(d, title.upper(), "display", box, 104, 46, max_lines=4)
    tl = wrap(d, title.upper(), ft, box)[:4]
    step = int(ft.size * 1.06)
    # заголовок не должен наезжать на верхнюю строку с брендом
    room = band - m - (m + 44)
    while len(tl) * step > room and ft.size > 36:
        ft = font("display", ft.size - 3)
        tl = wrap(d, title.upper(), ft, box)[:4]
        step = int(ft.size * 1.06)
    ty = band - m - len(tl) * step + int(step * 0.12)
    for ln in tl:
        d.text((m, ty), ln, font=ft, fill=WHITE)
        ty += step

    items = [t for t in lines if t][:5]
    if items:
        area_top = band + int(m * 0.9)
        area_bot = H - foot - int(m * 0.6)
        slot = (area_bot - area_top) / len(items)
        rich = any(split_item(t)[1] for t in items)
        fi = font("text-bold", 36 if rich or len(items) > 4 else 44)
        fd = font("text", 28 if len(items) > 4 else 30)
        icon_s = min(int(slot * 0.42), 62)
        for i, t in enumerate(items):
            cy = area_top + slot * i
            icon_for(t, i)(d, m, cy + (slot - icon_s) / 2 - 4, icon_s)
            tx = m + icon_s + int(m * 0.42)
            tw = W - tx - m
            # считаем высоту, чтобы отцентрировать в слоте
            probe = Image.new("RGB", (10, 10))
            th = _item(ImageDraw.Draw(probe), 0, 0, t, tw, fi, fd)
            _item(d, tx, cy + max(0, (slot - th) / 2), t, tw, fi, fd)
            if i < len(items) - 1:
                d.line([(m, cy + slot), (W - m, cy + slot)], fill=HAIR, width=2)

    _footer(img, d, size, foot)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=94, optimize=True)
    return dst


def card_hero(dst: Path, hero: str, title: str, lines: list[str],
              label: str = "", size=POST) -> Path:
    """Макет «крупная цифра»: одно ударное слово или число во весь кадр."""
    W, H = size
    img = Image.new("RGB", size, WHITE)
    d = ImageDraw.Draw(img)
    m = int(W * 0.089)
    foot = 110

    y = m
    fm = font("mono", 26)
    tracked(d, (m, y), "ARINASTROYS", fm, GREY, 5)
    if label:
        wl = tracked_width(d, label.upper(), fm, 4)
        tracked(d, (W - m - wl, y), label.upper(), fm, GREY, 4)

    box = W - m * 2
    # герой должен уместиться в одну строку целиком, иначе он не герой
    size_h = 240
    while size_h > 80:
        fh = font("display", size_h)
        if d.textlength(hero.upper(), font=fh) <= box:
            break
        size_h -= 4
    y = m + 100
    d.text((m, y), hero.upper(), font=fh, fill=BLACK)
    y += int(fh.size * 1.12)
    d.line([(m, y), (m + 150, y)], fill=BLACK, width=6)
    y += 44

    ft = fit_font(d, title, "text-bold", box, 52, 34)
    for ln in wrap(d, title, ft, box)[:3]:
        d.text((m, y), ln, font=ft, fill=BLACK)
        y += int(ft.size * 1.25)

    items = [t for t in lines if t][:4]
    if items:
        y += 26
        fi = font("text", 38)
        icon_s = 46
        for i, t in enumerate(items):
            if y + icon_s > H - foot - m * 0.5:
                break
            icon_for(t, i)(d, m, y - 4, icon_s, GREY)
            head = split_item(t)[0]
            d.text((m + icon_s + 24, y), wrap(d, head, fi, box - icon_s - 24)[0],
                   font=fi, fill=(70, 70, 70))
            y += icon_s + 26

    _footer(img, d, size, foot)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=94, optimize=True)
    return dst


def card_grid(dst: Path, title: str, lines: list[str], label: str = "",
              size=POST) -> Path:
    """Макет «сетка»: заголовок сверху, пункты в ячейках с иконками."""
    W, H = size
    img = Image.new("RGB", size, WHITE)
    d = ImageDraw.Draw(img)
    m = int(W * 0.089)
    foot = 110

    fm = font("mono", 26)
    tracked(d, (m, m), "ARINASTROYS", fm, GREY, 5)
    if label:
        wl = tracked_width(d, label.upper(), fm, 4)
        tracked(d, (W - m - wl, m), label.upper(), fm, GREY, 4)

    box = W - m * 2
    ft = fit_font(d, title.upper(), "display", box, 86, 44, max_lines=2)
    y = m + 84
    for ln in wrap(d, title.upper(), ft, box)[:2]:
        d.text((m, y), ln, font=ft, fill=BLACK)
        y += int(ft.size * 1.06)

    y += 16
    d.line([(m, y), (W - m, y)], fill=BLACK, width=4)
    y += 4

    items = [t for t in lines if t][:6]
    if not items:
        _footer(img, d, size, foot)
        img.save(dst, "JPEG", quality=94)
        return dst

    cols = 2
    rows = math.ceil(len(items) / cols)
    grid_top = y
    grid_bot = H - foot - int(m * 0.5)
    cw = box / cols
    ch = (grid_bot - grid_top) / rows
    fi = font("text-bold", 36)
    fn = font("mono", 24)

    odd_last = len(items) % cols == 1
    for i, t in enumerate(items):
        r, c = divmod(i, cols)
        wide = odd_last and i == len(items) - 1      # последний — на всю ширину
        cx = m + (0 if wide else c * cw)
        cur_w = box if wide else cw
        cy = grid_top + r * ch
        if c > 0 and not wide:
            d.line([(cx, cy + 12), (cx, cy + ch - 12)], fill=HAIR, width=2)
        if r > 0:
            d.line([(m, cy), (W - m, cy)], fill=HAIR, width=2)

        pad = 30
        tracked(d, (cx + pad, cy + pad), f"{i+1:02d}", fn, GREY, 2)
        icon_for(t, i)(d, cx + cur_w - pad - 54, cy + pad - 6, 54)
        _item(d, cx + pad, cy + pad + 52, t, cur_w - pad * 2, fi, font("text", 27))

    _footer(img, d, size, foot)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=94, optimize=True)
    return dst


def _head(d, W, m, label, color=GREY):
    fm = font("mono", 26)
    tracked(d, (m, m), "ARINASTROYS", fm, color, 5)
    if label:
        wl = tracked_width(d, label.upper(), fm, 4)
        tracked(d, (W - m - wl, m), label.upper(), fm, color, 4)


def card_split(dst: Path, title: str, lines: list[str], label: str = "",
               size=POST) -> Path:
    """Макет «колонка»: чёрная левая колонка с заголовком, справа нумерованный список."""
    W, H = size
    img = Image.new("RGB", size, WHITE)
    d = ImageDraw.Draw(img)
    m = int(W * 0.089)
    foot = 110
    col = int(W * 0.40)
    d.rectangle([0, 0, col, H - foot], fill=BLACK)

    fm = font("mono", 24)
    tracked(d, (m * 0.6, m), "ARINASTROYS", fm, (150, 150, 150), 4)
    if label:
        tracked(d, (col + m * 0.6, m), label.upper(), fm, GREY, 4)

    box = col - int(m * 1.2)
    ft = fit_font(d, title.upper(), "display", box, 96, 40, max_lines=5)
    tl = wrap(d, title.upper(), ft, box)[:5]
    step = int(ft.size * 1.05)
    ty = H - foot - m - len(tl) * step
    for ln in tl:
        d.text((m * 0.6, ty), ln, font=ft, fill=WHITE)
        ty += step

    items = [t for t in lines if t][:5]
    if items:
        x = col + int(m * 0.6)
        tw = W - x - m
        top = m + 80
        bot = H - foot - int(m * 0.5)
        slot = (bot - top) / len(items)
        fi = font("text-bold", 34 if len(items) > 3 else 38)
        fd = font("text", 27)
        fn = font("mono", 24)
        for i, t in enumerate(items):
            cy = top + slot * i
            tracked(d, (x, cy + 6), f"{i+1:02d}", fn, GREY, 2)
            _item(d, x, cy + 40, t, tw, fi, fd)
            if i < len(items) - 1:
                d.line([(x, cy + slot - 8), (W - m, cy + slot - 8)], fill=HAIR, width=2)

    _footer(img, d, size, foot)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=94, optimize=True)
    return dst


def card_quote(dst: Path, title: str, lines: list[str], label: str = "",
               size=POST) -> Path:
    """Макет «тезис»: одна крупная мысль на весь кадр, под ней 1–3 пояснения."""
    W, H = size
    img = Image.new("RGB", size, WHITE)
    d = ImageDraw.Draw(img)
    m = int(W * 0.089)
    foot = 110
    _head(d, W, m, label)

    box = W - m * 2
    d.rectangle([m, m + 90, m + 60, m + 104], fill=BLACK)   # короткий чёрный маркер
    ft = fit_font(d, title.upper(), "display", box, 128, 60, max_lines=4)
    tl = wrap(d, title.upper(), ft, box)[:4]
    y = m + 140
    step = int(ft.size * 1.02)
    for ln in tl:
        d.text((m, y), ln, font=ft, fill=BLACK)
        y += step

    items = [t for t in lines if t][:3]
    if items:
        y += 30
        d.line([(m, y), (W - m, y)], fill=BLACK, width=4)
        y += 36
        fi = font("text-bold", 34)
        fd = font("text", 28)
        for t in items:
            if y > H - foot - m:
                break
            y += _item(d, m, y, t, box, fi, fd) + 24

    _footer(img, d, size, foot)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=94, optimize=True)
    return dst


def card_steps(dst: Path, title: str, lines: list[str], label: str = "",
               size=POST) -> Path:
    """Макет «шаги»: этапы по порядку вдоль вертикальной линии процесса."""
    W, H = size
    img = Image.new("RGB", size, WHITE)
    d = ImageDraw.Draw(img)
    m = int(W * 0.089)
    foot = 110
    _head(d, W, m, label)

    box = W - m * 2
    ft = fit_font(d, title.upper(), "display", box, 80, 40, max_lines=2)
    y = m + 80
    for ln in wrap(d, title.upper(), ft, box)[:2]:
        d.text((m, y), ln, font=ft, fill=BLACK)
        y += int(ft.size * 1.06)

    items = [t for t in lines if t][:6]
    if items:
        top = y + 40
        bot = H - foot - int(m * 0.5)
        slot = (bot - top) / len(items)
        r = 30
        lx = m + r
        d.line([(lx, top + r), (lx, top + slot * (len(items) - 1) + r)], fill=HAIR, width=4)
        fn = font("display", 30)
        fi = font("text-bold", 34 if len(items) > 4 else 38)
        fd = font("text", 27)
        for i, t in enumerate(items):
            cy = top + slot * i
            d.ellipse([lx - r, cy, lx + r, cy + r * 2], fill=BLACK)
            num = f"{i+1}"
            d.text((lx - d.textlength(num, font=fn) / 2, cy + r - 18), num, font=fn, fill=WHITE)
            _item(d, lx + r + 34, cy + 4, t, W - (lx + r + 34) - m, fi, fd)

    _footer(img, d, size, foot)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=94, optimize=True)
    return dst


def card_versus(dst: Path, title: str, lines: list[str], label: str = "",
                size=POST) -> Path:
    """Макет «так / не так»: пары пунктов — слева ошибка, справа как правильно."""
    W, H = size
    img = Image.new("RGB", size, WHITE)
    d = ImageDraw.Draw(img)
    m = int(W * 0.089)
    foot = 110
    _head(d, W, m, label)

    box = W - m * 2
    ft = fit_font(d, title.upper(), "display", box, 78, 40, max_lines=2)
    y = m + 80
    for ln in wrap(d, title.upper(), ft, box)[:2]:
        d.text((m, y), ln, font=ft, fill=BLACK)
        y += int(ft.size * 1.06)
    y += 28

    pairs = [t for t in lines if t]
    pairs = [(pairs[i], pairs[i + 1]) for i in range(0, len(pairs) - 1, 2)][:3]
    gap = 40
    cw = (box - gap) / 2
    lx, rx = m, m + cw + gap
    fm = font("mono", 24)
    tracked(d, (lx + 40, y), "ТАК НЕЛЬЗЯ", fm, GREY, 4)
    tracked(d, (rx + 40, y), "ТАК ПРАВИЛЬНО", fm, BLACK, 4)
    y += 50
    d.line([(m, y), (W - m, y)], fill=BLACK, width=4)
    y += 10

    if pairs:
        bot = H - foot - int(m * 0.5)
        slot = (bot - y) / len(pairs)
        fi = font("text-bold", 32)
        fd = font("text", 26)
        for i, (bad, good) in enumerate(pairs):
            cy = y + slot * i + 24
            ic_cross(d, lx, cy, 30, GREY)
            ic_check(d, rx, cy, 30, BLACK)
            _item(d, lx + 44, cy, bad, cw - 44, fi, fd, GREY, GREY)
            _item(d, rx + 44, cy, good, cw - 44, fi, fd)
            if i < len(pairs) - 1:
                d.line([(m, y + slot * (i + 1)), (W - m, y + slot * (i + 1))], fill=HAIR, width=2)
        d.line([(m + cw + gap / 2, y + 10), (m + cw + gap / 2, bot - 10)], fill=HAIR, width=2)

    _footer(img, d, size, foot)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=94, optimize=True)
    return dst


LAYOUTS = {"band": card_band, "grid": card_grid, "hero": card_hero,
           "split": card_split, "quote": card_quote, "steps": card_steps,
           "versus": card_versus}


def make(dst: Path, title: str, lines: list[str], label: str = "",
         layout: str = "band", hero: str = "", size=POST) -> Path:
    if layout == "hero" and hero:
        return card_hero(dst, hero, title, lines, label, size)
    return LAYOUTS.get(layout, card_band)(dst, title, lines, label, size)
