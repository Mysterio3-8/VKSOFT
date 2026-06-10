---
description: Очистить orphaned-файлы, мусор и медиа-очереди текущего профиля
---

# /cleanup

Все операции работают на **активном профиле** (`app_state.active_profile_id`) и
блокируются, если в данный момент идёт скачивание/публикация (`is_storage_busy()`).

## Посмотреть статус хранилища

```bash
Invoke-RestMethod http://localhost:8000/api/cleanup/status
```

## Доступные операции

| Что | Команда | Что делает |
|---|---|---|
| Старые скачанные посты | `Invoke-RestMethod -Method Post http://localhost:8000/api/cleanup/posts` | `cleanup_downloaded_posts()` — удаляет посты из очереди старше 0 дней (фактически — все, у кого истёк смысл хранить) |
| Мусор / orphaned | `Invoke-RestMethod -Method Post http://localhost:8000/api/cleanup/junk` | `cleanup_junk()` — папки фото без JSON, временные файлы |
| Медиа-очереди (фото/видео/клипы) | `Invoke-RestMethod -Method Post http://localhost:8000/api/cleanup/media` | `cleanup_media_queues()` |
| Полная очистка | `Invoke-RestMethod -Method Post http://localhost:8000/api/cleanup/all` | Всё вышеперечисленное + сброс статистики, `last_scheduled.txt`, `download_offsets.json`, логов в памяти |

## Безопасность

- `cleanup_junk()` удаляет только папки фото, для которых **нет** соответствующего JSON в `downloaded_posts/`.
- Все удаления логируются (`app_state.add_log`, уровень `warning`) → видно в `/logs` и `logs/bot.log`.
- `/api/cleanup/all` — необратимо сбрасывает статистику и прогресс. Использовать только по явной просьбе пользователя.

## Когда использовать

1. После краша бота — могли остаться папки фото без JSON.
2. Хранилище профиля заметно растёт без причины.
3. Пользователь просит "почистить очередь" / "сбросить статистику".

## Фоновая очистка

Есть автоматический `cleanup_loop()` (см. `services/cleanup_storage.py`), запускается
в `main.py` при старте — не требует ручного вызова в обычном режиме.
