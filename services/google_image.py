# -*- coding: utf-8 -*-
"""Google Image search for fallback images."""

import requests as req_lib

from config import app_state


def fetch_google_image(query: str, api_key: str, cx: str):
    """
    Ищет первую подходящую картинку в Google Custom Search Image API.
    Возвращает bytes картинки или None.
    """
    if not api_key or not cx or not query:
        return None
    try:
        resp = req_lib.get(
            'https://www.googleapis.com/customsearch/v1',
            params={
                'key': api_key,
                'cx': cx,
                'q': query[:150],
                'searchType': 'image',
                'num': 5,
                'safe': 'active',
                'imgSize': 'large',
                'imgType': 'photo',
            },
            timeout=15
        )
        resp.raise_for_status()
        items = resp.json().get('items', [])
        for item in items:
            img_url = item.get('link', '')
            if not img_url:
                continue
            try:
                ir = req_lib.get(img_url, timeout=20, stream=True)
                ct = ir.headers.get('content-type', '')
                if ir.ok and 'image' in ct:
                    data = ir.content
                    if len(data) > 5000:  # игнорируем совсем маленькие файлы
                        app_state.add_log(f'Google Image: найдена картинка для "{query[:40]}"', 'info')
                        return data
            except Exception:
                continue
    except Exception as e:
        app_state.add_log(f'Google Image API: {e}', 'warning')
    return None
