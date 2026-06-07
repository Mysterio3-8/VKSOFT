# VK Bot Claude Code Setup

✅ **Окружение настроено полностью.**

Все необходимые файлы созданы для автономной работы Claude с проектом.

## Что было сделано

### 1. CLAUDE.md (полное описание проекта)

📍 `/c/Users/Professional/Desktop/vk-post-reposting-bot/vk-post-reposting-bot/CLAUDE.md`

- **Архитектура:** полная карта папок и модулей
- **AppState:** все свойства и методы
- **Воркеры:** как работают download/publish/monitor/autopilot
- **Хранилище:** структура JSON файлов
- **Грабли:** известные проблемы и решения
- **Checkpoint:** текущий статус (2026-06-05)

### 2. Скилы (slash commands)

📍 `/c/Users/Professional/Desktop/vk-post-reposting-bot/vk-post-reposting-bot/.claude/commands/`

Доступные команды:

- **`/start`** — запустить бота
- **`/test-tokens`** — проверить VK API токены
- **`/logs`** — показать последние логи
- **`/state`** — текущее состояние бота
- **`/cleanup`** — удалить orphaned photos и старые логи
- **`/build`** — собрать проект и запустить тесты

Примеры запуска:
```bash
# В Claude Code просто введи (внутри проекта)
/start
/logs
/state
```

### 3. Правила кода (инварианты)

📍 `/c/Users/Professional/Desktop/vk-post-reposting-bot/vk-post-reposting-bot/.claude/rules/bot-invariants.md`

**Жёсткие правила архитектуры:**

- 🚫 `services/` — БЕЗ FastAPI импортов
- 🚫 `api/` — ТОЛЬКО HTTP роутинг, вызовы services/
- 🚫 `workers/` — ТОЛЬКО асинхронные фоновые задачи
- 🚫 `vk/` — ТОЛЬКО API абстракция
- ✅ Используй `app_state` для всех путей (profile-specific)
- ✅ Все VK вызовы через `vk_call_safe()`
- ✅ Type hints на ВСЕ функции
- ✅ Логирование через `app_state.add_log()`, не `print()`

### 4. Settings для Claude Code

📍 `/c/Users/Professional/Desktop/vk-post-reposting-bot/vk-post-reposting-bot/.claude/settings.json`

- **Хуки:** проверка синтаксиса Python после редактирования
- **Разрешённые инструменты:** Read, Write, Edit, Glob, Grep, Bash
- **Auto-accept permissions:** disabled (явное подтверждение перед опасными действиями)

### 5. Архитектурные заметки (память)

📍 `/c/Users/Professional\Desktop/vk-post-reposting-bot/.claude/projects/vk-bot/memory/architecture.md`

- Почему выбраны текущие архитектурные решения
- Производственные грабли и как их избежать
- История разработки (v1 → v2)
- Уроки и будущие планы

---

## Как теперь работает Claude

### ✅ Больше НЕ спрашивает о проекте

Теперь Claude:

1. **Знает структуру** — из CLAUDE.md
2. **Знает инварианты** — из rules/bot-invariants.md
3. **Автоматически обновляет** — при изменении проекта (через commit)
4. **Использует правильные пути** — через AppState properties

### ✅ Знает быстрые команды

Введи `/` в Claude Code → подскажет:
```
/start         → запустить бота
/logs          → логи
/state         → состояние
/cleanup       → очистка
/test-tokens   → проверка токенов
/build         → сборка
```

### ✅ Соблюдает инварианты

При редактировании кода Claude сам будет:
- Делить логику по правильным слоям
- Использовать `app_state` для путей
- Добавлять type hints
- Логировать правильно

---

## Ты можешь теперь просто сказать

- ✅ "Добавь эндпоинт для скачивания" → Claude автоматически:
  - Создаст функцию в `services/`
  - Роут в `api/`
  - Не спросит где живёт CLAUDE.md
  - Не спросит как структурировать

- ✅ "Зафиксь баг 214 error loop" → Claude автоматически:
  - Найдёт `workers/publish.py`
  - Посмотрит как обрабатывается 214
  - Проверит что соблюдаются инварианты

- ✅ "Обнови контент-библиотеку до 500 записей" → Claude:
  - Найдёт `content_library.json`
  - Поймёт структуру (из CLAUDE.md)
  - Отредактирует без твоих уточнений

---

## Обновление при изменениях

**CLAUDE.md обновляется автоматически** при:

1. Добавлении новых API маршрутов → обновить список в `api/`
2. Изменении AppState → обновить в "Ключевые объекты"
3. Новых воркеров → добавить описание
4. Новых грабель → добавить в "Известные грабли"
5. Завершении задач → обновить "Checkpoint"

**Как обновить:**
```bash
# После значимого изменения просто скажи Claude:
"Обнови CLAUDE.md — добавил новый сервис X"

# Claude найдёт и обновит автоматически
```

---

## Быстрая справка

### Структура

```
.claude/
├── commands/             # Скилы (/start, /logs, etc.)
├── rules/                # Инварианты кода
└── settings.json         # Настройки Claude Code
../CLAUDE.md              # Описание проекта
```

### Путь к проекту

```
/c/Users/Professional/Desktop/vk-post-reposting-bot/vk-post-reposting-bot/
```

### Гит репозиторий

```
.git/ →  git status, git log, git commit
```

### Главные файлы

- `main.py` — FastAPI точка входа
- `config.py` — AppState синглтон
- `config.json` — конфиги профилей
- `requirements.txt` — зависимости

---

## Если что-то не работает

1. **Claude не находит файл** → проверь путь в CLAUDE.md (раздел "Структура")
2. **Claude нарушает инварианты** → посмотри rules/bot-invariants.md
3. **Claude старая информация** → обнови CLAUDE.md через `/update-docs`
4. **Нужен новый скил** → добавь в `.claude/commands/` как `.md` файл

---

**Дата:** 2026-06-05  
**Статус:** ✅ Готово к работе

