---
description: Показать текущее состояние бота и статистику
---

# /state

Выводит состояние бота: активный профиль, очередь, статистику и флаги воркеров.

## Получить JSON состояние

```bash
Invoke-RestMethod http://localhost:8000/api/dashboard
```

Расширенная версия (+ growth/subscribers/tracker/autopilot):

```bash
Invoke-RestMethod http://localhost:8000/api/dashboard/growth
```

Состояние storage (размер, orphaned файлы):

```bash
Invoke-RestMethod http://localhost:8000/api/cleanup/status
```

## Что искать в ответе `/api/dashboard`

- `active_profile` / `profile_name` — текущий канал
- `queue` / `pending_posts` — сколько постов в очереди на публикацию
- `stats` — `published`, `failed` (всего) и за сегодня
- флаги воркеров в `app_state`: `is_downloading`, `is_publishing`, `is_autopilot`, `is_monitoring`

## Если что-то зависло

- **Флаг = true, но ничего не происходит:** воркер упал или ждёт паузы между постами. Проверь логи (`/logs`).
- **Очередь не уменьшается:** проверь токены и последние ошибки в логах.
- **storage большой / много orphaned:** `/cleanup`.
