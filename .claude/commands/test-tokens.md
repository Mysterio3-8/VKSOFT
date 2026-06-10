---
description: Проверить VK API токены активного профиля
---

# /test-tokens

Проверяет user_token и group_token активного профиля через VK API.

## Через запущенный бот

```bash
Invoke-RestMethod -Method Post http://localhost:8000/api/vk/validate
```

## Без запуска бота (Python)

```bash
cd C:\Users\Professional\Desktop\vk-post-reposting-bot\vk-post-reposting-bot
python -c "from vk.api import validate_vk_tokens; print(validate_vk_tokens())"
```

`validate_vk_tokens()` определена в `vk/api.py`.

## Что проверяется

- **user_token:** доступен ли, действителен ли (нужен для скачивания постов и загрузки фото).
- **group_token:** доступен ли, действителен ли, есть ли доступ к стене группы (нужен для публикации).
- Токены и group_id берутся из `app_state.profile['vk']` активного профиля.

## Результаты

- `user_ok: true, group_ok: true` — всё в порядке.
- `false` по одному из токенов — нужно обновить именно этот токен в Настройках UI.
- Ошибки 5/28 — токен истёк/отозван, нужен новый токен из VK.

## Если что-то упало

Смотри `logs/bot.log` или `/logs` — там видны коды ошибок VK API.
