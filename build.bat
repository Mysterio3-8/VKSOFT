@echo off
chcp 65001 >nul
echo.
echo  ============================================
echo   VK Post Bot — Сборка .exe
echo  ============================================
echo.

:: Find Python — try "py" launcher first (handles multiple versions on Windows),
:: then fall back to "python"
set PYTHON=
where py >nul 2>&1 && set PYTHON=py
if "%PYTHON%"=="" (
    where python >nul 2>&1 && set PYTHON=python
)
if "%PYTHON%"=="" (
    echo [ОШИБКА] Python не найден в PATH!
    echo.
    echo Что сделать:
    echo  1. Скачай Python с https://www.python.org/downloads/
    echo  2. При установке ОБЯЗАТЕЛЬНО поставь галочку:
    echo     "Add Python to PATH"
    echo  3. Перезапусти командную строку и попробуй снова
    pause
    exit /b 1
)

echo [OK] Python найден: %PYTHON%
%PYTHON% --version
echo.

:: Step 1: Install pip packages
echo [1/4] Устанавливаю зависимости...
%PYTHON% -m pip install --upgrade pip --quiet
%PYTHON% -m pip install pyinstaller --quiet --upgrade
%PYTHON% -m pip install -r requirements.txt --quiet
echo [OK] Зависимости установлены
echo.

:: Step 2: Clean config (no personal tokens)
echo [2/4] Очищаю config.json от личных данных...
%PYTHON% _build_clean_config.py
echo.

:: Step 3: Build exe
echo [3/4] Собираю .exe (подожди 2-5 минут, это нормально)...
echo.
%PYTHON% -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --noconsole ^
    --name "VK_Post_Bot" ^
    --add-data "frontend;frontend" ^
    --add-data "config.json;." ^
    --hidden-import "uvicorn.logging" ^
    --hidden-import "uvicorn.loops" ^
    --hidden-import "uvicorn.loops.auto" ^
    --hidden-import "uvicorn.protocols" ^
    --hidden-import "uvicorn.protocols.http" ^
    --hidden-import "uvicorn.protocols.http.auto" ^
    --hidden-import "uvicorn.protocols.websockets" ^
    --hidden-import "uvicorn.protocols.websockets.auto" ^
    --hidden-import "uvicorn.lifespan" ^
    --hidden-import "uvicorn.lifespan.on" ^
    --hidden-import "vk_api" ^
    --hidden-import "fastapi" ^
    --hidden-import "starlette" ^
    --hidden-import "anyio" ^
    main.py

if errorlevel 1 (
    echo.
    echo [ОШИБКА] Сборка не удалась. Скопируй текст выше и отправь разработчику.
    pause
    exit /b 1
)

:: Step 4: Copy readme to dist
echo.
echo [4/4] Финализирую...
if exist "dist\VK_Post_Bot.exe" (
    copy "README_USER.txt" "dist\README_USER.txt" >nul 2>&1
    echo.
    echo  ============================================
    echo   ГОТОВО!
    echo  ============================================
    echo.
    echo   Папка для отправки: dist\
    echo   Отправь человеку файлы из этой папки:
    echo     - VK_Post_Bot.exe
    echo     - README_USER.txt
    echo.
    echo   Он просто запускает VK_Post_Bot.exe
    echo  ============================================
    echo.
) else (
    echo [ОШИБКА] .exe не создан — смотри лог выше
)

pause
