---
description: Проверить проект — синтаксис, тесты
---

# /build

Проверяет, что проект в рабочем состоянии перед коммитом/перезапуском.

## Шаги

```bash
# Зависимости (если requirements.txt менялся)
pip install -r requirements.txt

# Синтаксис всех модулей
python -m compileall -q main.py config.py api services workers vk

# Тесты
pytest -q
```

## Результаты

```
✓ Dependencies OK
✓ Syntax OK
✓ Tests passed (N passed)
```

## Если что-то упало

1. Прочитать вывод pytest/compileall — там точная ошибка и файл.
2. Исправить код.
3. Запустить шаги заново.

## Запуск бота после успешной проверки

```bash
start.bat
# или
python main.py
```

Никакого отдельного "сборочного" шага или деплоя на внешний сервер в проекте нет — бот запускается локально на Windows через `start.bat`.
