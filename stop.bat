@echo off
chcp 65001 >nul
cls

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║  VK POST REPOSTING BOT - STOPPER                          ║
echo ║  Остановка приложения                                     ║
echo ╚════════════════════════════════════════════════════════════╝
echo.

REM Kill Python processes running on port 8000
echo 🔍 Ищу процессы на порту 8000...

for /f "tokens=5" %%a in ('netstat -aon ^| find "8000" ^| find "LISTENING"') do (
    echo 🛑 Останавливаю процесс %%a...
    taskkill /PID %%a /F
    if errorlevel 1 (
        echo ⚠️  Не удалось остановить процесс %%a
    ) else (
        echo ✅ Процесс %%a остановлен
    )
)

REM Alternative: Kill all Python processes from this directory
echo.
echo 🛑 Останавливаю все Python процессы приложения...
taskkill /F /IM python.exe /T >nul 2>&1

echo.
echo ✅ Приложение остановлено
echo 👋 До встречи!
echo.

timeout /t 2 /nobreak
