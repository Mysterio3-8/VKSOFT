---
description: Собрать и протестировать проект (CI/CD)
---

# /build

Выполняет полную сборку, линтинг, тесты и подготовку к деплою.

## Запуск сборки

### На Windows
```bash
build.bat
```

### На Linux/Mac
```bash
bash build.sh
```

## Что проверяется

1. **Зависимости** — `pip install -r requirements.txt`
2. **Синтаксис Python** — `python -m py_compile *.py` для каждого модуля
3. **Тесты** — `pytest tests/ -v` (если есть)
4. **Линтинг** — проверка на ошибки кодирования (если настроен flake8/ruff)
5. **Типизация** — проверка type hints (если настроена)

## Результаты

```
✓ Dependencies OK
✓ Syntax OK
✓ Tests passed (12/12)
✓ Lint OK
✓ Ready to deploy
```

## На AEZA (VPS)

```bash
bash setup_aeza.sh
```

Это:
1. Клонирует репо из гита
2. Устанавливает Python + зависимости
3. Создаёт systemd сервис
4. Запускает бота как фоновый сервис

## Если сборка упала

1. Проверь логи: выведет точную ошибку
2. Исправь ошибку в коде
3. Запусти сборку снова

## Деплой на продакшен

```bash
# После успешной сборки
bash setup_aeza.sh                    # сборка на AEZA
ssh user@aeza.host systemctl restart vk-bot   # рестарт сервиса
```
