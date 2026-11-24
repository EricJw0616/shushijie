@echo off
setlocal
set "BOOKDISTILL_APP_DIR=%~dp0"
set "BOOKDISTILL_PORT=%~1"
if not defined BOOKDISTILL_PORT set "BOOKDISTILL_PORT=8942"
set "BOOKDISTILL_HOST=%~2"
if not defined BOOKDISTILL_HOST set "BOOKDISTILL_HOST=127.0.0.1"
where py >nul 2>&1
if not errorlevel 1 (
  py -3 "%BOOKDISTILL_APP_DIR%run.py" --host "%BOOKDISTILL_HOST%" --port "%BOOKDISTILL_PORT%"
  exit /b
)
where python >nul 2>&1
if not errorlevel 1 (
  python "%BOOKDISTILL_APP_DIR%run.py" --host "%BOOKDISTILL_HOST%" --port "%BOOKDISTILL_PORT%"
  exit /b
)
echo Python 3.9 or newer is required. See app/README.md. 1>&2
exit /b 2
