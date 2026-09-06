"""Картинки под бренд: кроп 4:5, титры для видео, карточки постов, водяной знак.

Фирменное: белый фон, чёрный #1A1A1A, заголовки Oswald капсом, текст Golos Text.
Если шрифтов нет — падаем на DejaVu, чтобы бот не вставал.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from config import BRAND_DIR, FONTS_DIR, settings

log = logging.getLogger(__name__)

BLACK = (26, 26, 26)
WHITE = (255, 255, 255)
GREY = (122, 122, 122)

STORY = (1080, 1920)
POST = (1080, 1350)

_FALLBACKS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def _font_file(*names: str) -> str | None:
    for n in names:
        p = FONTS_DIR / n
        if p.exists():
            return str(p)
    return None


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    """kind: display (Oswald) | text (Golos) | mono (JetBrains)."""
    candidates = {
        "display": ("Oswald-Bold.ttf", "Oswald-SemiBold.ttf", "Oswald-Variable.ttf", "Oswald.ttf"),
        "text": ("GolosText-Regular.ttf", "GolosText-Variable.ttf", "GolosText.ttf"),
        "text-bold": ("GolosText-Bold.ttf", "GolosText-Medium.ttf", "GolosText-Variable.ttf"),
        "mono": ("JetBrainsMono-Regular.ttf", "JetBrainsMono-Variable.ttf"),
    }.get(kind, ())
    path = _font_file(*candidates)
    if not path:
        for fb in _FALLBACKS:
            if Path(fb).exists():
                path = fb
                break
    if not path:
        return ImageFont.load_default()
    try:
        f = ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()
    # вариативные шрифты Google по умолчанию отдают Regular — просим нужный вес
    want = {"display": "Bold", "text-bold": "Bold"}.get(kind, "Regular")
    try:
        f.set_variation_by_name(want)
    except Exception:  # noqa: BLE001  обычный статический шрифт — и хорошо
        pass
    return f


def wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont,
         max_width: int) -> list[str]:
    """Перенос по реальной ширине текста, а не по числу символов.

    Иначе длинные слова капсом вылезают за край кадра.
    """
    words, lines, cur = text.split(), [], ""
    for w in words:
        probe = f"{cur} {w}".strip()
        if draw.textlength(probe, font=f) <= max_width or not cur:
            cur = probe
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit_font(draw: ImageDraw.ImageDraw, text: str, kind: str, max_width: int,
             start: int, minimum: int = 28) -> ImageFont.FreeTypeFont:
    """Уменьшаем кегль, пока самое длинное слово не влезет в ширину."""
    longest = max(text.split(), key=len, default=text)
    size = start
    while size > minimum:
        f = font(kind, size)
        if draw.textlength(longest, font=f) <= max_width:
            return f
        size -= 4
    return font(kind, minimum)


def logo(height: int) -> Image.Image | None:
    for name in ("logo.png", "logo-clean.png", "logo-white.png"):
        p = BRAND_DIR / name
        if p.exists():
            img = Image.open(p).convert("RGBA")
            ratio = height / img.height
            return img.resize((max(int(img.width * ratio), 1), height), Image.LANCZOS)
    return None


# ---------------------------------------------------------------- кадрирование


def fit(img: Image.Image, size: tuple[int, int], focus: str = "center") -> Image.Image:
    """Обрезка под нужный формат без искажения пропорций.

    focus='upper' — для интерьеров: потолок и верх стен важнее пола.
    """
    img = img.convert("RGB")
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    nw, nh = int(img.width * scale + 0.5), int(img.height * scale + 0.5)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - tw) // 2
    top = (nh - th) // 3 if focus == "upper" else (nh - th) // 2
    return img.crop((left, top, left + tw, top + th))


def to_post(src: Path, dst: Path, focus: str = "upper", watermark: bool = True) -> Path:
    img = fit(Image.open(src), POST, focus)
    if watermark:
        img = add_watermark(img)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=92, optimize=True)
    return dst


def to_story(src: Path, dst: Path, focus: str = "center") -> Path:
    img = fit(Image.open(src), STORY, focus)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=92, optimize=True)
    return dst


def add_watermark(img: Image.Image, opacity: int = 150) -> Image.Image:
    """Логотип в углу. Если файла логотипа нет — аккуратная подпись каналом."""
    img = img.convert("RGBA")
    pad = int(img.width * 0.045)
    lg = logo(int(img.height * 0.045))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))

    if lg:
        lg.putalpha(lg.getchannel("A").point(lambda a: int(a * opacity / 255)))
        layer.paste(lg, (img.width - lg.width - pad, img.height - lg.height - pad), lg)
    else:
        d = ImageDraw.Draw(layer)
        f = font("display", int(img.height * 0.026))
        text = settings.brand_latin.upper()
        w = d.textlength(text, font=f)
        x, y = img.width - w - pad, img.height - int(img.height * 0.026) - pad
        d.text((x + 1, y + 1), text, font=f, fill=(0, 0, 0, 90))
        d.text((x, y), text, font=f, fill=(255, 255, 255, opacity + 60))

    return Image.alpha_composite(img, layer).convert("RGB")


def label(src: Path, dst: Path, text: str, size: tuple[int, int] = STORY) -> Path:
    """Метка «ДО» / «ПОСЛЕ» плашкой в углу."""
    img = fit(Image.open(src), size).convert("RGB")
    d = ImageDraw.Draw(img)
    f = font("display", int(size[1] * 0.038))
    pad = int(size[0] * 0.05)
    tw = d.textlength(text.upper(), font=f)
    box_w, box_h = int(tw + pad * 1.2), int(size[1] * 0.062)
    d.rectangle([pad, pad, pad + box_w, pad + box_h], fill=BLACK)
    d.text((pad + pad * 0.6, pad + box_h * 0.24), text.upper(), font=f, fill=WHITE)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=93)
    return dst


# ---------------------------------------------------------------- карточки


def title_card(dst: Path, title: str, subtitle: str = "", photo: Path | None = None) -> Path:
    """Титр в начало ролика. С фото — затемнённый кадр, без — чёрный экран."""
    if photo and Path(photo).exists():
        img = fit(Image.open(photo), STORY).convert("RGB")
        img = img.filter(ImageFilter.GaussianBlur(3))
        img = ImageEnhance.Brightness(img).enhance(0.45)
    else:
        img = Image.new("RGB", STORY, BLACK)

    d = ImageDraw.Draw(img)
    lg = logo(90)
    if lg:
        img.paste(lg, ((STORY[0] - lg.width) // 2, 220), lg)

    box = int(STORY[0] * 0.84)
    f_title = fit_font(d, title.upper(), "display", box, 104, 52)
    f_sub = font("text", 44)
    lines = wrap(d, title.upper(), f_title, box) or [""]
    step = int(f_title.size * 1.14)

    y = (STORY[1] - len(lines) * step) // 2
    for ln in lines:
        w = d.textlength(ln, font=f_title)
        d.text(((STORY[0] - w) / 2, y), ln, font=f_title, fill=WHITE)
        y += step

    if subtitle:
        y += 18
        d.line([(STORY[0] / 2 - 60, y), (STORY[0] / 2 + 60, y)], fill=WHITE, width=3)
        y += 34
        w = d.textlength(subtitle, font=f_sub)
        d.text(((STORY[0] - w) / 2, y), subtitle, font=f_sub, fill=(225, 225, 225))

    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=94)
    return dst


def outro_card(dst: Path, line1: str = "Ремонт под ключ", line2: str = "Москва · МО · вся Россия",
               cta: str = "") -> Path:
    """Финальная плашка ролика."""
    img = Image.new("RGB", STORY, BLACK)
    d = ImageDraw.Draw(img)

    lg = logo(120)
    if lg:
        img.paste(lg, ((STORY[0] - lg.width) // 2, 620), lg)
    else:
        f = font("display", 96)
        t = settings.brand_latin.upper()
        d.text(((STORY[0] - d.textlength(t, font=f)) / 2, 640), t, font=f, fill=WHITE)

    f1, f2, f3 = font("display", 68), font("text", 42), font("text", 46)
    y = 900
    for text, f, color in ((line1.upper(), f1, WHITE), (line2, f2, (190, 190, 190))):
        w = d.textlength(text, font=f)
        d.text(((STORY[0] - w) / 2, y), text, font=f, fill=color)
        y += 96

    cta = cta or settings.brand_channel
    y += 60
    w = d.textlength(cta, font=f3)
    pad_x, pad_y = 46, 24
    d.rounded_rectangle(
        [(STORY[0] - w) / 2 - pad_x, y - pad_y, (STORY[0] + w) / 2 + pad_x, y + 52 + pad_y],
        radius=8, fill=WHITE,
    )
    d.text(((STORY[0] - w) / 2, y), cta, font=f3, fill=BLACK)

    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=94)
    return dst


def text_card(dst: Path, title: str, lines: list[str], size: tuple[int, int] = POST) -> Path:
    """Карточка для автопоста без фото: белый фон, чёрная типографика."""
    img = Image.new("RGB", size, WHITE)
    d = ImageDraw.Draw(img)
    m = int(size[0] * 0.09)

    lg = logo(46)
    if lg:
        img.paste(lg, (m, m), lg)
    else:
        f = font("display", 34)
        d.text((m, m), settings.brand_latin.upper(), font=f, fill=BLACK)

    box = size[0] - m * 2
    f_title = fit_font(d, title.upper(), "display", box, 76, 40)
    y = m + 130
    for ln in wrap(d, title.upper(), f_title, box)[:3]:
        d.text((m, y), ln, font=f_title, fill=BLACK)
        y += int(f_title.size * 1.13)

    y += 26
    d.line([(m, y), (m + 120, y)], fill=BLACK, width=4)
    y += 48

    f_item = font("text", 40)
    f_num = font("mono", 30)
    for i, ln in enumerate(lines[:5], 1):
        d.text((m, y + 6), f"{i:02d}", font=f_num, fill=GREY)
        yy = y
        for wl in wrap(d, ln, f_item, box - 78)[:2]:
            d.text((m + 78, yy), wl, font=f_item, fill=BLACK)
            yy += 50
        y = yy + 26

    f_foot = font("text", 32)
    d.text((m, size[1] - m - 40), settings.brand_channel, font=f_foot, fill=GREY)

    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=94, optimize=True)
    return dst
