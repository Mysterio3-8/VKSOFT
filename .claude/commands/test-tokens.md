---
description: Проверить VK API токены (без запуска бота)
---

# /test-tokens

Проверяет корректность VK API токенов без полного запуска бота.

## Использование

```bash
curl http://localhost:8000/api/tests/vk_tokens
```

Или через Python:
```bash
cd /c/Users/Professional/Desktop/vk-post-reposting-bot/vk-post-reposting-bot
python -c "from vk.api import test_vk_tokens; test_vk_tokens()"
```

## Результаты

- ✅ Оба токена валидны и имеют доступ
- ⚠️ Один токен не работает (какой конкретно)
- ❌ Оба токена истекли / заблокированы

## Что проверяется

- **user_token:** может ли получить информацию о пользователе
- **group_token:** может ли получить информацию о группе и её стене
- **Редакторство:** может ли пользователь редактировать целевую группу

## Если что-то упало

Смотри `logs/bot.log` для деталей ошибки.
