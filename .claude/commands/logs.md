---
description: Показать последние логи бота (ошибки и публикации)
---

# /logs

Выводит последние логи из `logs/bot.log` с фильтром по ошибкам и важным событиям.

## Команды

```bash
# Последние 50 строк
tail -n 50 /c/Users/Professional/Desktop/vk-post-reposting-bot/vk-post-reposting-bot/logs/bot.log

# Только ошибки
grep ERROR /c/Users/Professional/Desktop/vk-post-reposting-bot/vk-post-reposting-bot/logs/bot.log | tail -n 30

# Только публикации
grep "published\|Published" /c/Users/Professional/Desktop/vk-post-reposting-bot/vk-post-reposting-bot/logs/bot.log | tail -n 20

# Последние 24 часа (Linux)
find /c/Users/Professional/Desktop/vk-post-reposting-bot/vk-post-reposting-bot/logs/ -name "*.log" -mtime -1 -exec cat {} \;

# Live tail (Windows - используй PowerShell)
Get-Content /c/Users/Professional/Desktop/vk-post-reposting-bot/vk-post-reposting-bot/logs/bot.log -Wait
```

## Интерпретация

- **ERROR:** критичные ошибки (токены, сетевые)
- **WARNING:** что-то неправильно (лимиты VK, orphaned photos)
- **INFO:** нормальное событие (публикация, скачивание)
- **DEBUG:** детали выполнения (если нужно)

## Если много ошибок 214

Это значит, что VK очередь переполнена (>150 отложенных постов). Подожди или снизь `publish_delay_min`.

## Если ошибки 5 или 28

Токен истёк. Обновить в конфиге профиля.
