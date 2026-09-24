@echo off
title TRENCHNET Desk (WATCH-ONLY / PAPER)
cd /d "%~dp0"

set "TN_URL=http://127.0.0.1:8791/"
set "TN_PY=%~dp0.venv\Scripts\python.exe"

REM If something already answers on 8791, just open the browser (do not start a second server).
REM Hot Take tracker runs inside the UI process (daemon thread) — no separate port.
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri '%TN_URL%' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -ge 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if %ERRORLEVEL%==0 (
  echo TRENCHNET already up at %TN_URL% — opening browser.
  echo Hot Takes tracker is in-process on 8791 (paper only).
  start "" "%TN_URL%"
  exit /b 0
)

echo Starting TRENCHNET desk on 127.0.0.1:8791 ...
echo Hot Takes tracker starts with the UI (daemon; does not block).
start "TRENCHNET Desk" /MIN "%TN_PY%" -u -m trenchnet.cli ui --port 8791 --no-browser

REM Poll until the desk answers (up to ~15s), then open browser.
set /a _n=0
:waitloop
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri '%TN_URL%' -UseBasicParsing -TimeoutSec 1; if ($r.StatusCode -ge 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if %ERRORLEVEL%==0 goto ready
set /a _n+=1
if %_n% GEQ 15 (
  echo Timed out waiting for %TN_URL% — opening browser anyway.
  start "" "%TN_URL%"
  exit /b 1
)
timeout /t 1 /nobreak >nul
goto waitloop

:ready
echo Desk ready. Opening browser.
start "" "%TN_URL%"
exit /b 0
