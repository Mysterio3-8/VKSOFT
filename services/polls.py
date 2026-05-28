# -*- coding: utf-8 -*-
"""VK poll creation service."""

import json
import random

from config import app_state
from vk.api import vk_call_safe


def create_poll(vk_session, owner_id_int: int, questions: list,
                is_anonymous: bool = True, multiple: bool = False) -> str | None:
    """Create a VK poll in the group and return attachment string, e.g. 'poll-123_456'."""
    # Приоритет: библиотека опросов (если включена) → конфигурационные вопросы
    from services.content_library import load_library
    lib = load_library()
    if lib.get('enabled') and lib.get('polls'):
        questions = lib['polls']

    if not questions:
        return None

    q = random.choice(questions)
    question_text = q.get('question', '').strip()
    answers = q.get('answers', [])

    if not question_text or len(answers) < 2:
        app_state.add_log('Опрос: нужен вопрос и минимум 2 ответа', 'warning')
        return None

    try:
        result = vk_call_safe(
            vk_session.polls.create,
            owner_id=-owner_id_int,
            question=question_text,
            add_answers=json.dumps(answers, ensure_ascii=False),
            is_anonymous=1 if is_anonymous else 0,
            multiple=1 if multiple else 0,
        )
        if result and 'id' in result:
            poll_id = result['id']
            attachment = f'poll-{owner_id_int}_{poll_id}'
            app_state.add_log(f'Опрос: "{question_text}" → {attachment}', 'info')
            return attachment
    except Exception as e:
        app_state.add_log(f'Ошибка создания опроса: {e}', 'error')
    return None
