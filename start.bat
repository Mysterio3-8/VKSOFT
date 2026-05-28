@echo off
chcp 65001 >NUL
cd /d "%~dp0"

:: --- Najti Python ---
set PY=
python --version 1>NUL 2>NUL && set PY=python && goto :found_py
py     --version 1>NUL 2>NUL && set PY=py     && goto :found_py
for %%V in (313 312 311 310 39 38) do (
  if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
    set PY=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe
    goto :found_py
  )
)
echo ERROR: Python ne najden.
echo Skachaj python.org, pri ustanovke otmet Add Python to PATH.
pause
exit /b 1

:found_py

:: --- venv ---
if not exist "venv\Scripts\python.exe" (
  echo Sozdayu okruzhenie...
  %PY% -m venv venv
)

set VP=%~dp0venv\Scripts\python.exe

:: --- Zavisimosti ---
"%VP%" -c "import fastapi" 1>NUL 2>NUL
if errorlevel 1 (
  echo Ustanavlivayu zavisimosti...
  "%VP%" -m pip install -r requirements.txt
)

:: --- Port 8000 ---
for /f "tokens=5" %%a in ('netstat -aon 2^>NUL ^| findstr ":8000 " ^| findstr "LISTENING"') do (
  taskkill /PID %%a /F 1>NUL 2>NUL
)

:: --- Server v svernytom okne (pri oshibke okno ostanetsja) ---
start /min "VK Bot Server" "%VP%" main.py

:: --- Zhdem 5 sek, otkryvaem brauzer ---
timeout /t 5 /nobreak
rundll32 url.dll,FileProtocolHandler http://localhost:8000
