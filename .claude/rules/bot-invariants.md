---
paths:
  - "main.py"
  - "config.py"
  - "api/**/*.py"
  - "services/**/*.py"
  - "workers/**/*.py"
  - "vk/**/*.py"
---

# VK Bot — Инварианты кода

Эти правила применяются ко ВСЕМУ коду в проекте. Нарушения = баги.

## Архитектура слоёв (КРИТИЧНО)

### 1. `services/` — чистая бизнес-логика

❌ ЗАПРЕЩЕНО:
- Импортировать `fastapi`, `starlette`
- Использовать `@router`, `@app`
- Возвращать `Response`, `JSONResponse`
- Работать с HTTP напрямую

✅ ПРАВИЛЬНО:
```python
# services/storage.py
def read_statistics(profile_id: str) -> dict:
    file = STORAGE_DIR / profile_id / 'statistics.json'
    return json.loads(file.read_text())
```

### 2. `api/` — HTTP роутинг ТОЛЬКО

❌ ЗАПРЕЩЕНО:
- Писать бизнес-логику в маршруте
- Работать напрямую с файлами (без services)
- Запускать фоновые задачи (используй workers)

✅ ПРАВИЛЬНО:
```python
# api/statistics.py
@router.get('/stats')
async def get_stats():
    stats = read_statistics(app_state.active_profile_id)
    return {'data': stats}
```

### 3. `workers/` — асинхронные фоновые задачи ТОЛЬКО

❌ ЗАПРЕЩЕНО:
- Использовать синхронный код (без асинхронного обертывания)
- Возвращать HTTP ответы
- Обращаться к HTTP напрямую (используй `services/`)

✅ ПРАВИЛЬНО:
```python
# workers/publish.py
async def publish_worker():
    while True:
        posts = await load_posts()
        for post in posts:
            await publish_one(post)
        await asyncio.sleep(INTERVAL)
```

### 4. `vk/` — VK API абстракция ТОЛЬКО

❌ ЗАПРЕЩЕНО:
- Писать бизнес-логику (фильтрацию, обработку)
- Работать с хранилищем (используй `services/`)

✅ ПРАВИЛЬНО:
```python
# vk/api.py
def vk_call_safe(method: str, params: dict):
    # Только API вызов + retry + error handling
    pass
```

---

## Использование AppState

### Profile-specific пути

❌ ЗАПРЕЩЕНО:
```python
posts = list((STORAGE_DIR / 'downloaded_posts').glob('*.json'))  # Hardcoded!
```

✅ ПРАВИЛЬНО:
```python
posts = list(app_state.posts_dir.glob('*.json'))  # Учитывает active_profile_id
```

### Синхронизация конфига

❌ ЗАПРЕЩЕНО:
```python
app_state.profile['something'] = 123  # Меняешь память, но не сохранишь на диск
```

✅ ПРАВИЛЬНО:
```python
app_state.profile['something'] = 123
app_state.save_config()  # Явное сохранение на диск
```

---

## VK API вызовы

### Все вызовы через vk_call_safe()

❌ ЗАПРЕЩЕНО:
```python
vk = vk_api.VkApi(...)
vk.method('wall.get', {...})  # Прямой вызов, нет retry!
```

✅ ПРАВИЛЬНО:
```python
from vk.api import vk_call_safe
result = vk_call_safe('wall.get', {...})  # Автоматический retry + error handling
```

### Обработка ошибок 5, 28 (токен истёк)

Обязательно:
```python
try:
    result = vk_call_safe('wall.get', {...})
except TokenExpiredError:
    app_state.add_log('Токен истёк!', 'error')
    # Telegram алерт если настроен
    send_critical_alert(f'Token expired for {app_state.active_profile_id}')
```

---

## Логирование

### Используй app_state.add_log(), не print()

❌ ЗАПРЕЩЕНО:
```python
print('Published post')
```

✅ ПРАВИЛЬНО:
```python
app_state.add_log('Published post 12345', 'info')
```

### Уровни

- `'error'` → критичные ошибки (токены, сетевые, падения)
- `'warning'` → аномалии (лимиты, orphaned photos)
- `'info'` → обычные события (публикация, скачивание)
- `'debug'` → деятали (параметры вызовов)

---

## Хранилище

### JSON файлы — atomiс write

❌ ЗАПРЕЩЕНО:
```python
with open(file, 'w') as f:
    json.dump(data, f)
```

✅ ПРАВИЛЬНО:
```python
import tempfile
with tempfile.NamedTemporaryFile(dir=file.parent, delete=False) as tmp:
    json.dump(data, tmp)
    os.rename(tmp.name, file)
```

### Orphaned photos — проверь перед удалением

❌ ЗАПРЕЩЕНО:
```python
import shutil
shutil.rmtree(photo_dir)  # Мог быть баг, фото может быть нужна
```

✅ ПРАВИЛЬНО:
```python
# В cleanup_storage.py
json_file = posts_dir / f'{community_id}_{post_id}.json'
if not json_file.exists():
    shutil.rmtree(photo_dir)  # Безопасно
    app_state.add_log(f'Удалена orphaned папка {photo_dir.name}', 'info')
```

---

## Типизация

### Type hints на ВСЕХ функциях

❌ ЗАПРЕЩЕНО:
```python
def load_posts(profile_id):
    return [...]
```

✅ ПРАВИЛЬНО:
```python
def load_posts(profile_id: str) -> list[dict]:
    return [...]
```

### Используй `Optional` для nullable

```python
def find_post(post_id: int) -> dict | None:
    ...
```

---

## Тестирование

### Unit-тесты в `tests/`

- Все новые функции в `services/` → unit-тесты
- Все изменения в `vk/api.py` → интеграционные тесты
- Минимум 80% покрытие

### Запуск тестов

```bash
pytest tests/ -v --cov=.
```

---

## Комментарии

### Только WHY, не WHAT

❌ ЗАПРЕЩЕНО:
```python
# Загружаем посты
posts = load_posts()
```

✅ ПРАВИЛЬНО:
```python
# Используем pHash для дедупликации (по требованию фронта)
seen = load_seen_photos()
posts = [p for p in posts if hash(p) not in seen]
```

---

## Коммиты

### Соглашение

```
type: description

optional body

Examples:
- feat: add Smart Brain recommendations
- fix: handle VK 214 error on full queue
- refactor: extract publish logic to services
- docs: update README with setup instructions
```

### Правила

- 1 коммит = 1 логичное изменение
- Рефакторинг + новая фича = 2 коммита
- Проверь что типы валидны перед коммитом
