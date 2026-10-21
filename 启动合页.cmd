@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if exist "%~dp0dist\PDFedit-1.3.4\PDFedit-1.3.4.exe" (
  start "" "%~dp0dist\PDFedit-1.3.4\PDFedit-1.3.4.exe" %*
  exit /b
)
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
  echo Python environment missing. See README.md.
  pause
  exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" -B -s -X utf8 "%~dp0main.py" %*
