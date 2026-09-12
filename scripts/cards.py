"""Карточки для постов. Фирменные макеты вместо голого текста на белом.

Система: белый фон, чёрный #1A1A1A, Oswald капсом в заголовках, Golos Text
в тексте, JetBrains Mono в лейблах. Вместо цифр — линейные иконки, как
в остальных материалах бренда.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

from photo import fit, font  # общий резолвер шрифтов и кроп под формат

BLACK = (26, 26, 26)
WHITE = (255, 255, 255)
GREY = (122, 122, 122)
HAIR = (228, 228, 228)


class Theme:
    """Светлая — белый лист, чёрный текст. Тёмная — та же система в инверсии."""

    def __init__(self, bg, fg, muted, hair, soft):
        self.bg, self.fg, self.muted, self.hair, self.soft = bg, fg, muted, hair, soft


THEMES = {
    "light": Theme(WHITE, BLACK, GREY, HAIR, (70, 70, 70)),
    "dark": Theme(BLACK, WHITE, (165, 165, 165), (64, 64, 64), (215, 215, 215)),
}

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


def _item(d, x, y, text, max_w, head_f, detail_f, head_c=None, detail_c=None,
          t: Theme | None = None) -> float:
    """Пункт с заголовком и приглушённым пояснением. Возвращает высоту."""
    t = t or THEMES["light"]
    head_c = head_c or t.fg
    detail_c = detail_c or t.muted
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


def _footer(img, d, size, height=110, t: Theme | None = None):
    """Полоса внизу с юзернеймом — закрывает пустоту и держит кадр."""
    t = t or THEMES["light"]
    W, H = size
    d.rectangle([0, H - height, W, H], fill=t.fg)
    f = font("text-bold", 34)
    fm = font("mono", 26)
    m = int(W * 0.089)
    d.text((m, H - height + (height - 44) / 2), "@arinastroys", font=f, fill=t.bg)
    right = "МОСКВА · МО · ВСЯ РОССИЯ"
    wgt = tracked_width(d, right, fm, 2)
    tracked(d, (W - m - wgt, H - height + (height - 34) / 2), right, fm, t.muted, 2)


def card_band(dst: Path, title: str, lines: list[str], label: str = "",
              size=POST, theme: str = "light") -> Path:
    """Макет «плашка»: чёрный блок с заголовком сверху, список с иконками снизу."""
    W, H = size
    img, d, t, m, foot = _canvas(size, theme)

    band = int(H * 0.40)
    d.rectangle([0, 0, W, band], fill=t.fg)

    y = m
    fm = font("mono", 26)
    tracked(d, (m, y), "ARINASTROYS", fm, t.muted, 5)
    if label:
        wl = tracked_width(d, label.upper(), fm, 4)
        tracked(d, (W - m - wl, y), label.upper(), fm, t.muted, 4)

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
        d.text((m, ty), ln, font=ft, fill=t.bg)
        ty += step

    items = [x for x in lines if x][:5]
    if items:
        area_top = band + int(m * 0.9)
        area_bot = H - foot - int(m * 0.6)
        slot = (area_bot - area_top) / len(items)
        rich = any(split_item(it)[1] for it in items)
        fi = font("text-bold", 36 if rich or len(items) > 4 else 44)
        fd = font("text", 28 if len(items) > 4 else 30)
        icon_s = min(int(slot * 0.42), 62)
        for i, it in enumerate(items):
            cy = area_top + slot * i
            icon_for(it, i)(d, m, cy + (slot - icon_s) / 2 - 4, icon_s, t.fg)
            tx = m + icon_s + int(m * 0.42)
            tw = W - tx - m
            # считаем высоту, чтобы отцентрировать в слоте
            probe = Image.new("RGB", (10, 10))
            th = _item(ImageDraw.Draw(probe), 0, 0, it, tw, fi, fd, t=t)
            _item(d, tx, cy + max(0, (slot - th) / 2), it, tw, fi, fd, t=t)
            if i < len(items) - 1:
                d.line([(m, cy + slot), (W - m, cy + slot)], fill=t.hair, width=2)

    return _save(img, d, size, foot, t, dst)


def card_hero(dst: Path, hero: str, title: str, lines: list[str],
              label: str = "", size=POST, theme: str = "light") -> Path:
    """Макет «крупная цифра»: одно ударное слово или число во весь кадр."""
    W, H = size
    img, d, t, m, foot = _canvas(size, theme)

    y = m
    fm = font("mono", 26)
    tracked(d, (m, y), "ARINASTROYS", fm, t.muted, 5)
    if label:
        wl = tracked_width(d, label.upper(), fm, 4)
        tracked(d, (W - m - wl, y), label.upper(), fm, t.muted, 4)

    # герой
    box = W - m * 2
    # герой должен уместиться в одну строку целиком, иначе он не герой
    size_h = 240
    while size_h > 80:
        fh = font("display", size_h)
        if d.textlength(hero.upper(), font=fh) <= box:
            break
        size_h -= 4
    y = m + 100
    d.text((m, y), hero.upper(), font=fh, fill=t.fg)
    y += int(fh.size * 1.12)
    d.line([(m, y), (m + 150, y)], fill=t.fg, width=6)
    y += 44

    ft = fit_font(d, title, "text-bold", box, 52, 34)
    for ln in wrap(d, title, ft, box)[:3]:
        d.text((m, y), ln, font=ft, fill=t.fg)
        y += int(ft.size * 1.25)

    items = [x for x in lines if x][:4]
    if items:
        y += 26
        fi = font("text", 38)
        icon_s = 46
        for i, it in enumerate(items):
            if y + icon_s > H - foot - m * 0.5:
                break
            icon_for(it, i)(d, m, y - 4, icon_s, t.muted)
            head = split_item(it)[0]
            d.text((m + icon_s + 24, y), wrap(d, head, fi, box - icon_s - 24)[0],
                   font=fi, fill=t.soft)
            y += icon_s + 26

    return _save(img, d, size, foot, t, dst)


def card_grid(dst: Path, title: str, lines: list[str], label: str = "",
              size=POST, theme: str = "light") -> Path:
    """Макет «сетка»: заголовок сверху, пункты в ячейках с иконками."""
    W, H = size
    img, d, t, m, foot = _canvas(size, theme)

    fm = font("mono", 26)
    tracked(d, (m, m), "ARINASTROYS", fm, t.muted, 5)
    if label:
        wl = tracked_width(d, label.upper(), fm, 4)
        tracked(d, (W - m - wl, m), label.upper(), fm, t.muted, 4)

    box = W - m * 2
    ft = fit_font(d, title.upper(), "display", box, 86, 44, max_lines=2)
    y = m + 84
    for ln in wrap(d, title.upper(), ft, box)[:2]:
        d.text((m, y), ln, font=ft, fill=t.fg)
        y += int(ft.size * 1.06)

    y += 16
    d.line([(m, y), (W - m, y)], fill=t.fg, width=4)
    y += 4

    items = [x for x in lines if x][:6]
    if not items:
        return _save(img, d, size, foot, t, dst)

    cols = 2
    rows = math.ceil(len(items) / cols)
    grid_top = y
    grid_bot = H - foot - int(m * 0.5)
    cw = box / cols
    ch = (grid_bot - grid_top) / rows
    fi = font("text-bold", 36)
    fn = font("mono", 24)

    odd_last = len(items) % cols == 1
    for i, it in enumerate(items):
        r, c = divmod(i, cols)
        wide = odd_last and i == len(items) - 1      # последний — на всю ширину
        cx = m + (0 if wide else c * cw)
        cur_w = box if wide else cw
        cy = grid_top + r * ch
        # разделители
        if c > 0 and not wide:
            d.line([(cx, cy + 12), (cx, cy + ch - 12)], fill=t.hair, width=2)
        if r > 0:
            d.line([(m, cy), (W - m, cy)], fill=t.hair, width=2)

        pad = 30
        tracked(d, (cx + pad, cy + pad), f"{i+1:02d}", fn, t.muted, 2)
        icon_for(it, i)(d, cx + cur_w - pad - 54, cy + pad - 6, 54, t.fg)
        _item(d, cx + pad, cy + pad + 52, it, cur_w - pad * 2, fi, font("text", 27), t=t)

    return _save(img, d, size, foot, t, dst)


def _head(d, W, m, label, color=GREY):
    fm = font("mono", 26)
    tracked(d, (m, m), "ARINASTROYS", fm, color, 5)
    if label:
        wl = tracked_width(d, label.upper(), fm, 4)
        tracked(d, (W - m - wl, m), label.upper(), fm, color, 4)


def _canvas(size, theme: str):
    """Лист, кисть, тема, отступ и высота подвала — одинаковое начало всех макетов."""
    t = THEMES.get(theme, THEMES["light"])
    img = Image.new("RGB", size, t.bg)
    d = ImageDraw.Draw(img)
    return img, d, t, int(size[0] * 0.089), 110


def _save(img, d, size, foot, t, dst: Path) -> Path:
    _footer(img, d, size, foot, t)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=94, optimize=True)
    return dst


def card_split(dst: Path, title: str, lines: list[str], label: str = "",
               size=POST, theme: str = "light") -> Path:
    """Макет «колонка»: чёрная левая колонка с заголовком, справа нумерованный список."""
    W, H = size
    img, d, t, m, foot = _canvas(size, theme)
    col = int(W * 0.40)
    d.rectangle([0, 0, col, H - foot], fill=t.fg)

    fm = font("mono", 24)
    tracked(d, (m * 0.6, m), "ARINASTROYS", fm, t.muted, 4)
    if label:
        tracked(d, (col + m * 0.6, m), label.upper(), fm, t.muted, 4)

    box = col - int(m * 1.2)
    ft = fit_font(d, title.upper(), "display", box, 96, 40, max_lines=5)
    tl = wrap(d, title.upper(), ft, box)[:5]
    step = int(ft.size * 1.05)
    ty = H - foot - m - len(tl) * step
    for ln in tl:
        d.text((m * 0.6, ty), ln, font=ft, fill=t.bg)
        ty += step

    items = [x for x in lines if x][:5]
    if items:
        x = col + int(m * 0.6)
        tw = W - x - m
        top = m + 80
        bot = H - foot - int(m * 0.5)
        slot = (bot - top) / len(items)
        fi = font("text-bold", 34 if len(items) > 3 else 38)
        fd = font("text", 27)
        fn = font("mono", 24)
        for i, it in enumerate(items):
            cy = top + slot * i
            tracked(d, (x, cy + 6), f"{i+1:02d}", fn, t.muted, 2)
            _item(d, x, cy + 40, it, tw, fi, fd, t=t)
            if i < len(items) - 1:
                d.line([(x, cy + slot - 8), (W - m, cy + slot - 8)], fill=t.hair, width=2)

    return _save(img, d, size, foot, t, dst)


def card_quote(dst: Path, title: str, lines: list[str], label: str = "",
               size=POST, theme: str = "light") -> Path:
    """Макет «тезис»: одна крупная мысль на весь кадр, под ней 1–3 пояснения."""
    W, H = size
    img, d, t, m, foot = _canvas(size, theme)
    _head(d, W, m, label, t.muted)

    box = W - m * 2
    d.rectangle([m, m + 90, m + 60, m + 104], fill=t.fg)   # короткий чёрный маркер
    ft = fit_font(d, title.upper(), "display", box, 128, 60, max_lines=4)
    tl = wrap(d, title.upper(), ft, box)[:4]
    y = m + 140
    step = int(ft.size * 1.02)
    for ln in tl:
        d.text((m, y), ln, font=ft, fill=t.fg)
        y += step

    items = [x for x in lines if x][:3]
    if items:
        y += 30
        d.line([(m, y), (W - m, y)], fill=t.fg, width=4)
        y += 36
        fi = font("text-bold", 34)
        fd = font("text", 28)
        for it in items:
            if y > H - foot - m:
                break
            y += _item(d, m, y, it, box, fi, fd, t=t) + 24

    return _save(img, d, size, foot, t, dst)


def card_steps(dst: Path, title: str, lines: list[str], label: str = "",
               size=POST, theme: str = "light") -> Path:
    """Макет «шаги»: этапы по порядку вдоль вертикальной линии процесса."""
    W, H = size
    img, d, t, m, foot = _canvas(size, theme)
    _head(d, W, m, label, t.muted)

    box = W - m * 2
    ft = fit_font(d, title.upper(), "display", box, 80, 40, max_lines=2)
    y = m + 80
    for ln in wrap(d, title.upper(), ft, box)[:2]:
        d.text((m, y), ln, font=ft, fill=t.fg)
        y += int(ft.size * 1.06)

    items = [x for x in lines if x][:6]
    if items:
        top = y + 40
        bot = H - foot - int(m * 0.5)
        slot = (bot - top) / len(items)
        r = 30
        lx = m + r
        d.line([(lx, top + r), (lx, top + slot * (len(items) - 1) + r)], fill=t.hair, width=4)
        fn = font("display", 30)
        fi = font("text-bold", 34 if len(items) > 4 else 38)
        fd = font("text", 27)
        for i, it in enumerate(items):
            cy = top + slot * i
            d.ellipse([lx - r, cy, lx + r, cy + r * 2], fill=t.fg)
            num = f"{i+1}"
            d.text((lx - d.textlength(num, font=fn) / 2, cy + r - 18), num, font=fn, fill=t.bg)
            _item(d, lx + r + 34, cy + 4, it, W - (lx + r + 34) - m, fi, fd, t=t)

    return _save(img, d, size, foot, t, dst)


def card_versus(dst: Path, title: str, lines: list[str], label: str = "",
                size=POST, theme: str = "light") -> Path:
    """Макет «так / не так»: пары пунктов — слева ошибка, справа как правильно."""
    W, H = size
    img, d, t, m, foot = _canvas(size, theme)
    _head(d, W, m, label, t.muted)

    box = W - m * 2
    ft = fit_font(d, title.upper(), "display", box, 78, 40, max_lines=2)
    y = m + 80
    for ln in wrap(d, title.upper(), ft, box)[:2]:
        d.text((m, y), ln, font=ft, fill=t.fg)
        y += int(ft.size * 1.06)
    y += 28

    pairs = [x for x in lines if x]
    pairs = [(pairs[i], pairs[i + 1]) for i in range(0, len(pairs) - 1, 2)][:3]
    gap = 40
    cw = (box - gap) / 2
    lx, rx = m, m + cw + gap
    fm = font("mono", 24)
    tracked(d, (lx + 40, y), "ТАК НЕЛЬЗЯ", fm, t.muted, 4)
    tracked(d, (rx + 40, y), "ТАК ПРАВИЛЬНО", fm, t.fg, 4)
    y += 50
    d.line([(m, y), (W - m, y)], fill=t.fg, width=4)
    y += 10

    if pairs:
        bot = H - foot - int(m * 0.5)
        slot = (bot - y) / len(pairs)
        fi = font("text-bold", 32)
        fd = font("text", 26)
        for i, (bad, good) in enumerate(pairs):
            cy = y + slot * i + 24
            ic_cross(d, lx, cy, 30, t.muted)
            ic_check(d, rx, cy, 30, t.fg)
            _item(d, lx + 44, cy, bad, cw - 44, fi, fd, t.muted, t.muted, t=t)
            _item(d, rx + 44, cy, good, cw - 44, fi, fd, t=t)
            if i < len(pairs) - 1:
                d.line([(m, y + slot * (i + 1)), (W - m, y + slot * (i + 1))], fill=t.hair, width=2)
        d.line([(m + cw + gap / 2, y + 10), (m + cw + gap / 2, bot - 10)], fill=t.hair, width=2)

    return _save(img, d, size, foot, t, dst)


def card_numbers(dst: Path, title: str, lines: list[str], label: str = "",
                 size=POST, theme: str = "light") -> Path:
    """Макет «нумерация»: огромные цифры слева, пункты справа — редакционный стиль."""
    W, H = size
    img, d, t, m, foot = _canvas(size, theme)
    _head(d, W, m, label, t.muted)
    box = W - m * 2
    ft = fit_font(d, title.upper(), "display", box, 76, 40, max_lines=2)
    y = m + 76
    for ln in wrap(d, title.upper(), ft, box)[:2]:
        d.text((m, y), ln, font=ft, fill=t.fg)
        y += int(ft.size * 1.06)
    items = [x for x in lines if x][:5]
    if items:
        top = y + 30
        bot = H - foot - int(m * 0.5)
        slot = (bot - top) / len(items)
        fn = font("display", min(int(slot * 0.62), 118))
        numw = d.textlength("00", font=fn) + 26
        fi = font("text-bold", 34 if len(items) > 3 else 38)
        fd = font("text", 27)
        for i, it in enumerate(items):
            cy = top + slot * i
            d.text((m, cy - 6), f"{i+1:02d}", font=fn, fill=t.hair if theme == "light" else t.hair)
            _item(d, m + numw, cy + 10, it, W - m - (m + numw), fi, fd, t=t)
            if i < len(items) - 1:
                d.line([(m, cy + slot - 6), (W - m, cy + slot - 6)], fill=t.hair, width=2)
    return _save(img, d, size, foot, t, dst)


def card_checklist(dst: Path, title: str, lines: list[str], label: str = "",
                   size=POST, theme: str = "light") -> Path:
    """Макет «чек-лист»: квадратные чекбоксы с галочками — что проверить."""
    W, H = size
    img, d, t, m, foot = _canvas(size, theme)
    _head(d, W, m, label, t.muted)
    box = W - m * 2
    ft = fit_font(d, title.upper(), "display", box, 80, 40, max_lines=2)
    y = m + 76
    for ln in wrap(d, title.upper(), ft, box)[:2]:
        d.text((m, y), ln, font=ft, fill=t.fg)
        y += int(ft.size * 1.06)
    y += 24
    d.line([(m, y), (W - m, y)], fill=t.fg, width=4)
    items = [x for x in lines if x][:6]
    if items:
        top = y + 30
        bot = H - foot - int(m * 0.5)
        slot = (bot - top) / len(items)
        bx = 46
        fi = font("text-bold", 32 if len(items) > 4 else 36)
        fd = font("text", 26 if len(items) > 4 else 28)
        for i, it in enumerate(items):
            cy = top + slot * i + 8
            d.rectangle([m, cy, m + bx, cy + bx], outline=t.fg, width=4)
            ic_check(d, m + 4, cy + 4, bx - 8, t.fg)
            _item(d, m + bx + 30, cy - 2, it, W - m - (m + bx + 30), fi, fd, t=t)
    return _save(img, d, size, foot, t, dst)


def card_stats(dst: Path, title: str, lines: list[str], label: str = "",
               size=POST, theme: str = "light") -> Path:
    """Макет «цифры»: 2-4 больших числа с подписями. Пункт: «28 дней — сохнет стяжка»."""
    W, H = size
    img, d, t, m, foot = _canvas(size, theme)
    _head(d, W, m, label, t.muted)
    box = W - m * 2
    ft = fit_font(d, title.upper(), "display", box, 72, 40, max_lines=2)
    y = m + 76
    for ln in wrap(d, title.upper(), ft, box)[:2]:
        d.text((m, y), ln, font=ft, fill=t.fg)
        y += int(ft.size * 1.06)
    items = [x for x in lines if x][:4]
    if items:
        top = y + 30
        bot = H - foot - int(m * 0.5)
        slot = (bot - top) / len(items)
        fd = font("text", 30)
        fvb = font("text-bold", 34)
        for i, it in enumerate(items):
            num, cap = split_item(it)
            cy = top + slot * i
            if len(num) > 14 or not cap:
                # это не число, а фраза — рисуем как обычный пункт, без гигантского кегля
                _item(d, m, cy + 10, it, box, fvb, fd, t=t)
                if i < len(items) - 1:
                    d.line([(m, cy + slot - 10), (W - m, cy + slot - 10)], fill=t.hair, width=2)
                continue
            fn = font("display", 40)
            for sz in range(min(int(slot * 0.66), 150), 48, -4):
                fn = font("display", sz)
                if d.textlength(num.upper(), font=fn) <= box * 0.58:
                    break
            d.text((m, cy), num.upper(), font=fn, fill=t.fg)
            nx = m + d.textlength(num.upper(), font=fn) + 28
            cy2 = cy + fn.size * 0.32
            for ln in wrap(d, cap, fd, W - nx - m)[:3]:
                d.text((nx, cy2), ln, font=fd, fill=t.soft)
                cy2 += int(fd.size * 1.25)
            if i < len(items) - 1:
                d.line([(m, cy + slot - 10), (W - m, cy + slot - 10)], fill=t.hair, width=2)
    return _save(img, d, size, foot, t, dst)


def card_poster(dst: Path, title: str, lines: list[str], label: str = "",
                size=POST, theme: str = "dark") -> Path:
    """Макет «афиша»: одно-два огромных слова на весь лист, подпись мелко внизу."""
    W, H = size
    img, d, t, m, foot = _canvas(size, theme)
    _head(d, W, m, label, t.muted)
    box = W - m * 2
    ft = fit_font(d, title.upper(), "display", box, 210, 90, max_lines=3)
    tl = wrap(d, title.upper(), ft, box)[:3]
    step = int(ft.size * 0.98)
    total = len(tl) * step
    y = (H - foot - total) / 2 - 20
    for ln in tl:
        d.text((m, y), ln, font=ft, fill=t.fg)
        y += step
    items = [x for x in lines if x][:2]
    if items:
        y = H - foot - m - 20 - len(items) * 44
        fd = font("text", 30)
        for it in items:
            d.text((m, y), wrap(d, split_item(it)[0] if split_item(it)[1] == "" else it, fd, box)[0],
                   font=fd, fill=t.muted)
            y += 44
    return _save(img, d, size, foot, t, dst)


def card_faq(dst: Path, title: str, lines: list[str], label: str = "",
             size=POST, theme: str = "light") -> Path:
    """Макет «вопрос-ответ»: пары «Вопрос? — Ответ». Вопрос капсом, ответ обычным."""
    W, H = size
    img, d, t, m, foot = _canvas(size, theme)
    _head(d, W, m, label, t.muted)
    box = W - m * 2
    ft = fit_font(d, title.upper(), "display", box, 64, 36, max_lines=2)
    y = m + 76
    for ln in wrap(d, title.upper(), ft, box)[:2]:
        d.text((m, y), ln, font=ft, fill=t.fg)
        y += int(ft.size * 1.06)
    y += 20
    items = [x for x in lines if x][:4]
    fq = font("display", 40)
    fa = font("text", 29)
    for it in items:
        q, a = split_item(it)
        if y > H - foot - m * 1.2:
            break
        d.rectangle([m, y + 12, m + 14, y + 40], fill=t.fg)
        qx = m + 34
        for ln in wrap(d, q.upper(), fq, box - 34)[:2]:
            d.text((qx, y), ln, font=fq, fill=t.fg)
            y += int(fq.size * 1.1)
        y += 6
        for ln in wrap(d, a, fa, box - 34)[:3]:
            d.text((qx, y), ln, font=fa, fill=t.soft)
            y += int(fa.size * 1.3)
        y += 30
    return _save(img, d, size, foot, t, dst)


def card_myth(dst: Path, title: str, lines: list[str], label: str = "",
              size=POST, theme: str = "light") -> Path:
    """Макет «миф / на деле»: пары пунктов стопкой, миф зачёркнут."""
    W, H = size
    img, d, t, m, foot = _canvas(size, theme)
    _head(d, W, m, label, t.muted)
    box = W - m * 2
    ft = fit_font(d, title.upper(), "display", box, 70, 38, max_lines=2)
    y = m + 76
    for ln in wrap(d, title.upper(), ft, box)[:2]:
        d.text((m, y), ln, font=ft, fill=t.fg)
        y += int(ft.size * 1.06)
    y += 16
    pairs = [x for x in lines if x]
    pairs = [(pairs[i], pairs[i + 1]) for i in range(0, len(pairs) - 1, 2)][:3]
    fm = font("mono", 24)
    fmyth = font("text-bold", 36)
    ffact = font("text-bold", 36)
    fd = font("text", 28)
    if pairs:
        bot = H - foot - int(m * 0.4)
        slot = (bot - y) / len(pairs)
        for i, (myth, fact) in enumerate(pairs):
            cy = y + slot * i + 14
            tracked(d, (m, cy), "МИФ", fm, t.muted, 4)
            cy += 30
            mh = split_item(myth)[0]
            for ln in wrap(d, mh, fmyth, box)[:2]:
                d.text((m, cy), ln, font=fmyth, fill=t.muted)
                wl = d.textlength(ln, font=fmyth)
                d.line([(m, cy + fmyth.size * 0.58), (m + wl, cy + fmyth.size * 0.58)],
                       fill=t.muted, width=3)
                cy += int(fmyth.size * 1.2)
            cy += 10
            tracked(d, (m, cy), "НА ДЕЛЕ", fm, t.fg, 4)
            cy += 30
            cy += _item(d, m, cy, fact, box, ffact, fd, t=t)
            if i < len(pairs) - 1:
                d.line([(m, y + slot * (i + 1)), (W - m, y + slot * (i + 1))], fill=t.hair, width=2)
    return _save(img, d, size, foot, t, dst)


def card_table(dst: Path, title: str, lines: list[str], label: str = "",
               size=POST, theme: str = "light") -> Path:
    """Макет «таблица»: строки «параметр — значение».

    Короткое значение («4%», «28 дней») прижато вправо крупно; длинное — идёт
    второй строкой под параметром, иначе они наезжают друг на друга.
    """
    W, H = size
    img, d, t, m, foot = _canvas(size, theme)
    _head(d, W, m, label, t.muted)
    box = W - m * 2
    ft = fit_font(d, title.upper(), "display", box, 72, 38, max_lines=2)
    y = m + 76
    for ln in wrap(d, title.upper(), ft, box)[:2]:
        d.text((m, y), ln, font=ft, fill=t.fg)
        y += int(ft.size * 1.06)
    y += 24
    d.line([(m, y), (W - m, y)], fill=t.fg, width=4)
    items = [x for x in lines if x][:7]
    if items:
        top = y
        bot = H - foot - int(m * 0.5)
        slot = (bot - top) / len(items)
        fk = font("text", 30 if len(items) <= 5 else 27)
        fv = font("display", 38 if len(items) <= 5 else 34)
        fkm = font("mono", 22)
        fvb = font("text-bold", 32 if len(items) <= 5 else 28)
        for i, it in enumerate(items):
            k, v = split_item(it)
            cy = top + slot * i
            vw = d.textlength(v.upper(), font=fv) if v else 0
            short = bool(v) and vw <= box * 0.42 and len(v) <= 18
            if short:
                kl = wrap(d, k, fk, box - vw - 40)[:2]
                ky = cy + slot / 2 - len(kl) * fk.size * 0.62
                for ln in kl:
                    d.text((m, ky), ln, font=fk, fill=t.soft)
                    ky += int(fk.size * 1.2)
                d.text((W - m - vw, cy + slot / 2 - fv.size * 0.62), v.upper(),
                       font=fv, fill=t.fg)
            else:
                # длинное значение — параметр мелко сверху, значение жирно снизу
                tracked(d, (m, cy + 14), k.upper(), fkm, t.muted, 3)
                vy = cy + 14 + fkm.size + 12
                for ln in wrap(d, v or k, fvb, box)[:2]:
                    if vy + fvb.size > cy + slot - 6:
                        break
                    d.text((m, vy), ln, font=fvb, fill=t.fg)
                    vy += int(fvb.size * 1.22)
            d.line([(m, top + slot * (i + 1)), (W - m, top + slot * (i + 1))], fill=t.hair, width=2)
    return _save(img, d, size, foot, t, dst)


def card_warning(dst: Path, title: str, lines: list[str], label: str = "",
                 size=POST, theme: str = "light") -> Path:
    """Макет «внимание»: косая штриховка сверху, крупный заголовок, пункты-ошибки."""
    W, H = size
    img, d, t, m, foot = _canvas(size, theme)
    stripe_h = 64
    for x in range(-stripe_h, W + stripe_h, 48):
        d.polygon([(x, 0), (x + 24, 0), (x + 24 - stripe_h, stripe_h), (x - stripe_h, stripe_h)],
                  fill=t.fg)
    fm = font("mono", 26)
    tracked(d, (m, stripe_h + 34), "ARINASTROYS", fm, t.muted, 5)
    if label:
        wl = tracked_width(d, label.upper(), fm, 4)
        tracked(d, (W - m - wl, stripe_h + 34), label.upper(), fm, t.muted, 4)
    box = W - m * 2
    ft = fit_font(d, title.upper(), "display", box, 96, 44, max_lines=3)
    y = stripe_h + 34 + 70
    for ln in wrap(d, title.upper(), ft, box)[:3]:
        d.text((m, y), ln, font=ft, fill=t.fg)
        y += int(ft.size * 1.04)
    items = [x for x in lines if x][:5]
    if items:
        top = y + 30
        bot = H - foot - int(m * 0.5)
        slot = (bot - top) / len(items)
        fi = font("text-bold", 34 if len(items) > 3 else 38)
        fd = font("text", 27)
        for i, it in enumerate(items):
            cy = top + slot * i
            ic_cross(d, m, cy + 4, 34, t.fg)
            _item(d, m + 56, cy, it, W - m - (m + 56), fi, fd, t=t)
    return _save(img, d, size, foot, t, dst)


def card_columns(dst: Path, title: str, lines: list[str], label: str = "",
                 size=POST, theme: str = "light") -> Path:
    """Макет «две колонки»: верх с заголовком в инверсии, ниже пункты в две колонки."""
    W, H = size
    img, d, t, m, foot = _canvas(size, theme)
    top_h = int(H * 0.36)
    d.rectangle([0, 0, W, top_h], fill=t.fg)
    fm = font("mono", 26)
    mid = (128, 128, 128)          # читается и на чёрном, и на белом блоке
    tracked(d, (m, m), "ARINASTROYS", fm, mid, 5)
    if label:
        wl = tracked_width(d, label.upper(), fm, 4)
        tracked(d, (W - m - wl, m), label.upper(), fm, mid, 4)
    box = W - m * 2
    ft = fit_font(d, title.upper(), "display", box, 92, 40, max_lines=3)
    tl = wrap(d, title.upper(), ft, box)[:3]
    step = int(ft.size * 1.04)
    room = top_h - m - (m + 44)
    while len(tl) * step > room and ft.size > 34:
        ft = font("display", ft.size - 3)
        tl = wrap(d, title.upper(), ft, box)[:3]
        step = int(ft.size * 1.04)
    y = top_h - m - len(tl) * step + 10
    for ln in tl:
        d.text((m, y), ln, font=ft, fill=t.bg)
        y += step
    items = [x for x in lines if x][:6]
    if items:
        gap = 40
        cw = (box - gap) / 2
        rows = (len(items) + 1) // 2
        top = top_h + int(m * 0.8)
        bot = H - foot - int(m * 0.5)
        rh = (bot - top) / rows
        fi = font("text-bold", 32)
        fd = font("text", 26)
        fn = font("mono", 22)
        for i, it in enumerate(items):
            r, c = divmod(i, 2)
            cx = m + c * (cw + gap)
            cy = top + r * rh
            tracked(d, (cx, cy), f"{i+1:02d}", fn, t.muted, 2)
            d.line([(cx, cy + 34), (cx + 60, cy + 34)], fill=t.fg, width=3)
            _item(d, cx, cy + 50, it, cw, fi, fd, t=t)
    return _save(img, d, size, foot, t, dst)


# ---------------------------------------------------------------- до / после


def _tag(d, x, y, text, t: Theme, size: int = 30, pad: int = 18):
    """Плашка-ярлык «ДО» / «ПОСЛЕ» в фирменной моноширинке."""
    fm = font("mono", size)
    w = tracked_width(d, text, fm, 4)
    d.rectangle([x, y, x + w + pad * 2, y + size + pad * 1.4], fill=t.fg)
    tracked(d, (x + pad, y + pad * 0.6), text, fm, t.bg, 4)


def _load(path) -> Image.Image:
    from PIL import ImageOps
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def before_after(dst: Path, before, after, title: str = "", style: str = "side",
                 size=POST, theme: str = "light") -> Path:
    """Пара «до / после» одной карточкой: рядом, стопкой или диагональю."""
    W, H = size
    img, d, t, m, foot = _canvas(size, theme)
    a, b = _load(before), _load(after)

    head_h = 0
    if title:
        box = W - m * 2
        ft = fit_font(d, title.upper(), "display", box, 64, 36, max_lines=2)
        tl = wrap(d, title.upper(), ft, box)[:2]
        y = int(m * 0.8)
        for ln in tl:
            d.text((m, y), ln, font=ft, fill=t.fg)
            y += int(ft.size * 1.06)
        head_h = y + int(m * 0.5)

    top = head_h
    area_h = H - foot - top
    gap = 12

    if style == "stack":
        ph_h = (area_h - gap) // 2
        img.paste(fit(a, (W, ph_h), "upper"), (0, top))
        img.paste(fit(b, (W, ph_h), "upper"), (0, top + ph_h + gap))
        d.rectangle([0, top + ph_h, W, top + ph_h + gap], fill=t.bg)
        _tag(d, m, top + m * 0.6, "ДО", t)
        _tag(d, m, top + ph_h + gap + m * 0.6, "ПОСЛЕ", t)

    elif style == "diag":
        full_a = fit(a, (W, area_h), "upper")
        full_b = fit(b, (W, area_h), "upper")
        mask = Image.new("L", (W, area_h), 0)
        md = ImageDraw.Draw(mask)
        # правая-нижняя часть — «после», граница идёт наискось
        md.polygon([(int(W * 0.62), 0), (W, 0), (W, area_h), (int(W * 0.38), area_h)], fill=255)
        comp = Image.composite(full_b, full_a, mask)
        img.paste(comp, (0, top))
        d.line([(int(W * 0.62), top), (int(W * 0.38), top + area_h)], fill=t.bg, width=gap)
        _tag(d, m, top + m * 0.6, "ДО", t)
        fm = font("mono", 30)
        w = tracked_width(d, "ПОСЛЕ", fm, 4) + 36
        _tag(d, W - m - w, top + area_h - m * 0.6 - 30 - 25, "ПОСЛЕ", t)

    else:  # side
        ph_w = (W - gap) // 2
        img.paste(fit(a, (ph_w, area_h), "upper"), (0, top))
        img.paste(fit(b, (ph_w, area_h), "upper"), (ph_w + gap, top))
        d.rectangle([ph_w, top, ph_w + gap, top + area_h], fill=t.bg)
        _tag(d, m * 0.5, top + m * 0.6, "ДО", t)
        _tag(d, ph_w + gap + m * 0.5, top + m * 0.6, "ПОСЛЕ", t)

    return _save(img, d, size, foot, t, dst)


BA_STYLES = ("side", "stack", "diag")


# ---------------------------------------------------------------- разбор коллажей


def _profile(im: Image.Image, axis: str) -> list[float]:
    """Насколько «однотонна» каждая колонка (axis=x) или строка (axis=y).
    Низкое число — ровная полоса, рамка или разделитель."""
    g = im.convert("L")
    if axis == "x":
        g = g.transpose(Image.Transpose.ROTATE_90)   # колонки становятся строками
    w, h = g.size
    small = g.resize((max(w // 4, 8), h), Image.BILINEAR)
    px = small.load()
    out = []
    for y in range(h):
        row = [px[x, y] for x in range(small.width)]
        mean = sum(row) / len(row)
        out.append(sum(abs(v - mean) for v in row) / len(row))
    return out


def _edge_color(im: Image.Image, corner: str) -> tuple:
    """Цвет рамки берём из угла — так мы режем именно рамку, а не светлую стену."""
    w, h = im.size
    x = 2 if corner in ("tl", "bl") else w - 3
    y = 2 if corner in ("tl", "tr") else h - 3
    return im.convert("RGB").getpixel((x, y))


def _trim_to(im: Image.Image, colour: tuple, tol: int, max_frac: float) -> Image.Image:
    """Срезает по краям всё, что совпадает с colour. Не больше max_frac с каждой стороны."""
    from PIL import ImageChops
    rgb = im.convert("RGB")
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, colour))
    mask = diff.convert("L").point(lambda v: 255 if v > tol else 0)
    box = mask.getbbox()
    if not box:
        return im
    w, h = im.size
    lim_x, lim_y = int(w * max_frac), int(h * max_frac)
    left = min(box[0], lim_x)
    top = min(box[1], lim_y)
    right = max(box[2], w - lim_x)
    bottom = max(box[3], h - lim_y)
    if right - left < w * 0.5 or bottom - top < h * 0.5:
        return im
    return im.crop((left, top, right, bottom))


def autocrop_borders(im: Image.Image, tol: int = 14, max_frac: float = 0.14) -> Image.Image:
    """Убирает однотонные рамки и плашки по краям: белые поля, чёрные полосы.

    Цвет рамки определяем по углам, поэтому светлая стена внутри кадра остаётся
    на месте — режется только то, что действительно совпадает с краем.
    """
    seen = set()
    for corner in ("tl", "br", "tr", "bl"):
        colour = _edge_color(im, corner)
        if colour in seen:
            continue
        seen.add(colour)
        im = _trim_to(im, colour, tol, max_frac)
    return im


def find_divider(im: Image.Image, axis: str, approx: float, tol: float = 7.0,
                 window: float = 0.10) -> tuple[int, int] | None:
    """Ищет однотонную полосу-разделитель около approx (доля 0..1). Возвращает (от, до)."""
    prof = _profile(im, axis)
    n = len(prof)
    c = int(n * approx)
    lo, hi = max(0, int(c - n * window)), min(n, int(c + n * window))
    best = None
    i = lo
    while i < hi:
        if prof[i] <= tol:
            j = i
            while j < hi and prof[j] <= tol:
                j += 1
            if best is None or (j - i) > (best[1] - best[0]):
                best = (i, j)
            i = j
        else:
            i += 1
    if best and best[1] - best[0] >= 2:
        return best
    return None


def split_collage(src, out_a, out_b, axis: str = "vertical", at: float = 0.5,
                  left_is_before: bool = True) -> tuple[Path, Path] | None:
    """Режет коллаж «до/после» на две чистые половины.

    axis — по какой оси склеены половины: vertical — рядом (делим по x),
    horizontal — стопкой (делим по y). Разделитель ищем около at; если не нашли —
    режем ровно по at. С каждой половины срезаем рамки и остатки полосы.
    """
    im = autocrop_borders(_load(src))      # внешние рамки и плашки долой до разреза
    w, h = im.size
    ax = "x" if axis == "vertical" else "y"
    n = w if ax == "x" else h
    band = find_divider(im, ax, at)
    if band:
        a_end, b_start = band[0], band[1]
    else:
        a_end = b_start = int(n * at)
    if a_end < n * 0.2 or b_start > n * 0.8:
        return None
    if ax == "x":
        a, b = im.crop((0, 0, a_end, h)), im.crop((b_start, 0, w, h))
    else:
        a, b = im.crop((0, 0, w, a_end)), im.crop((0, b_start, w, h))
    a, b = autocrop_borders(a), autocrop_borders(b)
    if not left_is_before:
        a, b = b, a
    out_a, out_b = Path(out_a), Path(out_b)
    out_a.parent.mkdir(parents=True, exist_ok=True)
    a.save(out_a, "JPEG", quality=93)
    b.save(out_b, "JPEG", quality=93)
    return out_a, out_b


LAYOUTS = {"band": card_band, "grid": card_grid, "hero": card_hero,
           "split": card_split, "quote": card_quote, "steps": card_steps,
           "versus": card_versus, "numbers": card_numbers, "checklist": card_checklist,
           "stats": card_stats, "poster": card_poster, "faq": card_faq,
           "myth": card_myth, "table": card_table, "warning": card_warning,
           "columns": card_columns}


def make(dst: Path, title: str, lines: list[str], label: str = "",
         layout: str = "band", hero: str = "", size=POST, theme: str = "light") -> Path:
    theme = theme if theme in THEMES else "light"
    if layout == "hero" and hero:
        return card_hero(dst, hero, title, lines, label, size, theme)
    return LAYOUTS.get(layout, card_band)(dst, title, lines, label, size, theme)
