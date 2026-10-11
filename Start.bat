@echo off
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title nnanserShop
color 0B
if not exist logs mkdir logs

set "PY=python"
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"

cls
call %PY% splash.py boot
if errorlevel 1 (
  echo.
  echo   nnanserShop  ·  не вижу Python. Поставь python.org и запусти снова.
  echo.
  pause
  exit /b 1
)
call %PY% -m pip install -q -r requirements.txt >>logs\pip_install.txt 2>&1
if errorlevel 1 (
  call %PY% -m pip install -q requests urllib3 pyTelegramBotAPI beautifulsoup4 colorama psutil requests-toolbelt python-dotenv pysocks >>logs\pip_install.txt 2>&1
)

cls
call %PY% splash.py go

:loop
echo ========== %date% %time% start ==========>> logs\bot.txt
call %PY% -u main.py
set EXITCODE=%ERRORLEVEL%
echo [%date% %time%] выход %EXITCODE%>> logs\bot.txt
if not "%EXITCODE%"=="0" echo [%date% %time%] аварийный выход %EXITCODE%>> logs\error.txt
call %PY% splash.py down %EXITCODE%
timeout /t 5 /nobreak > nul
goto loop
