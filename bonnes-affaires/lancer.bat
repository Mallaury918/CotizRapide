@echo off
rem Lance DealBot (Windows). Double-cliquez, ou : lancer.bat test   /   lancer.bat sites
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
set PY=py
where py >nul 2>nul || set PY=python
where %PY% >nul 2>nul || (echo Python n'est pas installe : https://www.python.org/downloads/ & pause & exit /b 1)
if not exist config.toml (
  copy config.example.toml config.toml >nul
  echo config.toml cree : ouvrez-le, renseignez [telegram] token et chat_id, puis relancez.
  notepad config.toml
  exit /b 0
)
if "%1"=="test" (%PY% -m dealbot test-telegram & pause & exit /b)
if "%1"=="sites" (%PY% -m dealbot sites & pause & exit /b)
echo DealBot demarre (fermez la fenetre pour arreter)...
%PY% -m dealbot run
pause
