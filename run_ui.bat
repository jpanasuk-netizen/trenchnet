@echo off
title TRENCHNET Desk - WATCH-ONLY / PAPER
cd /d "%~dp0"
set "TN_URL=http://127.0.0.1:8791/"
set "TN_PY=%~dp0.venv\Scripts\python.exe"

REM If the desk already answers on 8791, just open the browser.
call :probe 3
if "%TN_UP%"=="1" goto ready

echo Starting TRENCHNET desk on 127.0.0.1:8791 ...
echo Hot Takes tracker starts with the UI - paper only.
start "TRENCHNET Desk" /MIN "%TN_PY%" -u -m trenchnet.cli ui --port 8791 --no-browser

set /a _n=0
:waitloop
call :probe 2
if "%TN_UP%"=="1" goto ready
set /a _n+=1
if %_n% GEQ 20 goto timeout
timeout /t 1 /nobreak >nul
goto waitloop

:timeout
echo Timed out waiting for the desk - opening browser anyway.
start "" "%TN_URL%"
exit /b 1

:ready
echo Desk ready - opening browser.
start "" "%TN_URL%"
exit /b 0

:probe
set "TN_UP=0"
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri '%TN_URL%' -UseBasicParsing -TimeoutSec %1; if ($r.StatusCode -ge 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 set "TN_UP=1"
exit /b 0