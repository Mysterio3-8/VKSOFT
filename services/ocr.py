# -*- coding: utf-8 -*-
"""OCR: определение текста на фото (AI-генеративные)."""

from pathlib import Path

from config import app_state


def photo_has_text(path: Path, min_chars: int = 8) -> bool:
    """
    Возвращает True если фото содержит значимый текст (скорее всего AI с подписью).
    Требует: pip install pytesseract pillow  +  tesseract на PATH.
    """
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(path).convert('L')  # grayscale — ускоряет OCR
        text = pytesseract.image_to_string(img, config='--psm 11').strip()
        return len(text) >= min_chars
    except ImportError:
        app_state.add_log('OCR: pytesseract/pillow не установлены — пропускаю проверку', 'warning')
        return False
    except Exception as e:
        app_state.add_log(f'OCR ошибка: {e}', 'warning')
        return False
