---
description: Показать текущее состояние бота и статистику
---

# /state

Выводит полное состояние бота: активный профиль, количество постов в очереди, статистику и флаги воркеров.

## Получить JSON состояние

```bash
curl http://localhost:8000/api/dashboard/state
```

## Информация в состоянии

```json
{
  "active_profile": "p1",
  "posts_in_queue": 42,
  "stats": {
    "published_today": 5,
    "failed_today": 0,
    "total_published": 2145,
    "total_failed": 12
  },
  "workers": {
    "is_downloading": false,
    "is_publishing": false,
    "is_autopilot": false,
    "is_monitoring": false
  },
  "storage_size_mb": 2.3
}
```

## Что означают флаги

- **is_downloading:** скачивание постов из VK сейчас идёт
- **is_publishing:** публикация постов в VK сейчас идёт
- **is_autopilot:** цикл автопилота (скачивание + публикация) включен
- **is_monitoring:** мониторинг новостей включен

## Если что-то зависло

- **Флаг = true, но ничего не происходит:** воркер упал. Проверь логи (`/logs`).
- **posts_in_queue = 0, но вроде есть посты:** они ещё скачиваются.
- **storage_size большой:** очисти orphaned photos (`/cleanup`).
