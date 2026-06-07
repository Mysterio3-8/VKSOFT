---
description: Запустить бота (FastAPI на порту 8000)
---

# /start

Запускает FastAPI сервер на `http://localhost:8000`.

## Запуск

```bash
cd /c/Users/Professional/Desktop/vk-post-reposting-bot/vk-post-reposting-bot
python main.py
```

Или на Windows:
```bash
start.bat
```

## Проверка

После запуска проверь:
- **Веб-интерфейс:** http://localhost:8000
- **Health check:** `curl http://localhost:8000/health`
- **Логи:** `logs/bot.log`

## Остановка

- Ctrl+C в терминале
- Или `stop.bat` на Windows

## Проблемы

- **Port 8000 занят:** `netstat -ano | findstr :8000` (Windows) или `lsof -i :8000` (Linux)
- **Модули не найдены:** `pip install -r requirements.txt`
- **Python не найден:** убедись что Python 3.10+ в PATH
