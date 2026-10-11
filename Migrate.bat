@echo off
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
set "PY=python"
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
call %PY% tools\migrate.py %*
