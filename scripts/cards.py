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
             start: int, minimum: int = 32):
    longest = max(text.split(), key=len, default=text)
    size = start
    while size > minimum:
        f = font(kind, size)
        if d.textlength(longest, font=f) <= max_w:
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
    ft = fit_font(d, title.upper(), "display", box, 104, 54)
    tl = wrap(d, title.upper(), ft, box)[:3]
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
        fi = font("text-bold", 40 if len(items) > 4 else 44)
        icon_s = min(int(slot * 0.42), 62)
        for i, t in enumerate(items):
            cy = area_top + slot * i
            icon_for(t, i)(d, m, cy + (slot - icon_s) / 2 - 4, icon_s)
            tx = m + icon_s + int(m * 0.42)
            tw = W - tx - m
            wl = wrap(d, t, fi, tw)[:2]
            th = len(wl) * int(fi.size * 1.22)
            yy = cy + (slot - th) / 2
            for w2 in wl:
                d.text((tx, yy), w2, font=fi, fill=BLACK)
                yy += int(fi.size * 1.22)
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
            d.text((m + icon_s + 24, y), wrap(d, t, fi, box - icon_s - 24)[0],
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
    ft = fit_font(d, title.upper(), "display", box, 86, 48)
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
        wl = wrap(d, t, fi, cur_w - pad * 2)[:3]
        ty = cy + pad + 52
        for w2 in wl:
            d.text((cx + pad, ty), w2, font=fi, fill=BLACK)
            ty += int(fi.size * 1.22)

    _footer(img, d, size, foot)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=94, optimize=True)
    return dst


LAYOUTS = {"band": card_band, "grid": card_grid, "hero": card_hero}


def make(dst: Path, title: str, lines: list[str], label: str = "",
         layout: str = "band", hero: str = "", size=POST) -> Path:
    if layout == "hero" and hero:
        return card_hero(dst, hero, title, lines, label, size)
    return LAYOUTS.get(layout, card_band)(dst, title, lines, label, size)
