# -*- coding: utf-8 -*-
"""Водяной знак на фото через Pillow — антиплагиат без внешних API."""

from pathlib import Path
from config import logger

try:
    from PIL import Image, ImageDraw, ImageFont, ImageEnhance
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


# ── Позиции ────────────────────────────────────────────────────────
POSITIONS = {
    'bottom_right': lambda iw, ih, tw, th: (iw - tw - 20, ih - th - 20),
    'bottom_left':  lambda iw, ih, tw, th: (20, ih - th - 20),
    'top_right':    lambda iw, ih, tw, th: (iw - tw - 20, 20),
    'top_left':     lambda iw, ih, tw, th: (20, 20),
    'center':       lambda iw, ih, tw, th: ((iw - tw) // 2, (ih - th) // 2),
}


def _load_font(size: int):
    """Загрузить шрифт — системный или встроенный fallback."""
    font_candidates = [
        "arial.ttf", "Arial.ttf",
        "DejaVuSans.ttf", "DejaVuSans-Bold.ttf",
        "LiberationSans-Regular.ttf",
        "FreeSans.ttf",
    ]
    for name in font_candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def apply_text_watermark(
    image_path: str | Path,
    text: str,
    *,
    position: str = 'bottom_right',
    font_size: int = 0,      # 0 = авто (3% высоты)
    opacity: int = 180,      # 0-255
    color: tuple = (255, 255, 255),
    shadow: bool = True,
) -> bool:
    """
    Наложить текстовый водяной знак на фото.
    Изменяет файл на месте. Возвращает True при успехе.
    """
    if not _PIL_OK:
        logger.warning("watermark: Pillow не установлен — pip install Pillow")
        return False
    path = Path(image_path)
    if not path.exists():
        return False
    try:
        img = Image.open(path).convert("RGBA")
        iw, ih = img.size

        size = font_size or max(12, int(ih * 0.03))
        font = _load_font(size)

        # Измерить размер текста
        tmp_draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        bbox = tmp_draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        pos_fn = POSITIONS.get(position, POSITIONS['bottom_right'])
        x, y = pos_fn(iw, ih, tw, th)

        # Слой для водяного знака
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)

        if shadow:
            shadow_color = (0, 0, 0, min(255, opacity + 30))
            draw.text((x + 2, y + 2), text, font=font, fill=shadow_color)

        r, g, b = color
        draw.text((x, y), text, font=font, fill=(r, g, b, opacity))

        img = Image.alpha_composite(img, layer).convert("RGB")
        img.save(path, quality=95)
        return True
    except Exception as e:
        logger.warning(f"watermark text: {e}")
        return False


def apply_logo_watermark(
    image_path: str | Path,
    logo_path: str | Path,
    *,
    position: str = 'bottom_right',
    scale: float = 0.12,     # доля от ширины фото
    opacity: int = 200,
) -> bool:
    """
    Наложить PNG-логотип (с прозрачностью) на фото.
    Изменяет файл на месте. Возвращает True при успехе.
    """
    if not _PIL_OK:
        logger.warning("watermark: Pillow не установлен — pip install Pillow")
        return False
    img_p = Path(image_path)
    logo_p = Path(logo_path)
    if not img_p.exists() or not logo_p.exists():
        return False
    try:
        img = Image.open(img_p).convert("RGBA")
        logo = Image.open(logo_p).convert("RGBA")

        iw, ih = img.size
        lw = max(10, int(iw * scale))
        ratio = lw / logo.width
        lh = int(logo.height * ratio)
        logo = logo.resize((lw, lh), Image.LANCZOS)

        # Применить прозрачность
        r, g, b, a = logo.split()
        a = a.point(lambda v: int(v * opacity / 255))
        logo = Image.merge("RGBA", (r, g, b, a))

        pos_fn = POSITIONS.get(position, POSITIONS['bottom_right'])
        x, y = pos_fn(iw, ih, lw, lh)
        x, y = max(0, x), max(0, y)

        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        layer.paste(logo, (x, y), logo)

        img = Image.alpha_composite(img, layer).convert("RGB")
        img.save(img_p, quality=95)
        return True
    except Exception as e:
        logger.warning(f"watermark logo: {e}")
        return False


def apply_watermark_from_profile(image_path: str | Path, profile: dict) -> bool:
    """
    Применить водяной знак согласно настройкам профиля.
    profile['watermark'] = {
        'enabled': true,
        'mode': 'text' | 'logo',
        'text': '@mygroup',
        'logo_path': '/path/to/logo.png',
        'position': 'bottom_right',
        'font_size': 0,
        'opacity': 180,
        'color': [255, 255, 255],
        'logo_scale': 0.12,
    }
    """
    wm = profile.get('watermark', {})
    if not wm.get('enabled'):
        return False

    mode = wm.get('mode', 'text')
    position = wm.get('position', 'bottom_right')
    opacity = int(wm.get('opacity', 180))

    if mode == 'logo':
        logo_path = wm.get('logo_path', '')
        if not logo_path:
            logger.warning("watermark: logo_path не задан, переключаюсь на текст")
            mode = 'text'
        else:
            return apply_logo_watermark(
                image_path, logo_path,
                position=position,
                scale=float(wm.get('logo_scale', 0.12)),
                opacity=opacity,
            )

    if mode == 'text':
        text = wm.get('text', '@channel')
        color_raw = wm.get('color', [255, 255, 255])
        color = tuple(color_raw) if isinstance(color_raw, list) else (255, 255, 255)
        return apply_text_watermark(
            image_path, text,
            position=position,
            font_size=int(wm.get('font_size', 0)),
            opacity=opacity,
            color=color,
            shadow=True,
        )

    return False
