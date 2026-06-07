---
description: Очистить orphaned photos и старые логи
---

# /cleanup

Удаляет:
1. **Orphaned photos** — папки с фото, у которых нет JSON (если бот упал)
2. **Старые логи** — логи старше 30 дней
3. **Стирает pHash кеш** — seen_photos.json (если размер >10MB)

## Команда

```bash
curl -X POST http://localhost:8000/api/cleanup/orphaned_photos
```

## Вручную очистить всё

```bash
# На Windows (PowerShell)
$profile_dir = "C:\Users\Professional\Desktop\vk-post-reposting-bot\vk-post-reposting-bot\storage\p1"
Remove-Item "$profile_dir\photos\*" -Recurse -Force

# На Linux/Mac
rm -rf /c/Users/Professional/Desktop/vk-post-reposting-bot/vk-post-reposting-bot/storage/p1/photos/*
```

## Безопасность

- **Проверка:** удаляет ТОЛЬКО папки без соответствующего JSON в `downloaded_posts/`
- **Лог:** все удаления логируются в `bot.log`
- **Восстановление:** если случайно удалил нужное — в `bot.log` видно что удалилось

## Когда использовать

1. После краша бота (`is_publishing = true`, но посты не публикуются)
2. Хранилище растёт без причины
3. Перед деплоем на продакшен
