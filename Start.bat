@echo off
setlocal EnableDelayedExpansion
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title nnanserShop  ·  запуск
color 0B
if not exist logs mkdir logs

set "PY=python"
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"

call %PY% -c "import sys" >nul 2>&1
if errorlevel 1 (
  echo.
  echo   nnanserShop  ·  не вижу Python. Поставь python.org и запусти снова.
  echo.
  pause
  exit /b 1
)

set DEPS=cached
title nnanserShop  ·  пакеты
call %PY% splash.py deps
if errorlevel 1 (
  set DEPS=fresh
  cls
  title nnanserShop  ·  установка пакетов
  call %PY% splash.py boot
  call %PY% -m pip install -q -r requirements.txt >>logs\pip_install.txt 2>&1
  if errorlevel 1 (
    call %PY% -m pip install -q requests urllib3 pyTelegramBotAPI beautifulsoup4 lxml bcrypt colorama psutil requests-toolbelt python-dotenv pysocks >>logs\pip_install.txt 2>&1
  )
)

cls
title nnanserShop  ·  в работе
call %PY% splash.py go !DEPS!

set FAILS=0
:loop
echo ========== %date% %time% start ==========>> logs\bot.txt
call %PY% -u main.py
set EXITCODE=!ERRORLEVEL!
echo [!date! !time!] выход !EXITCODE!>> logs\bot.txt
if "!EXITCODE!"=="0" (
  set FAILS=0
) else if "!EXITCODE!"=="3221225786" (
  set FAILS=0
) else (
  echo [!date! !time!] аварийный выход !EXITCODE!>> logs\error.txt
  set /a FAILS+=1
)
title nnanserShop  ·  перезапуск
call %PY% splash.py down !EXITCODE! !FAILS!
if !FAILS! GEQ 3 (
  echo.
  echo   Три сбоя подряд. Остановился, чтобы не крутиться вхолостую.
  echo   Открой logs\error.txt, исправь причину и запусти Start.bat снова.
  echo.
  title nnanserShop  ·  остановлен
  pause
  exit /b !EXITCODE!
)
timeout /t 5 /nobreak > nul
title nnanserShop  ·  в работе
goto loop
