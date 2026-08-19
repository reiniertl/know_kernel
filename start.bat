@echo off
REM Start the know_kernel web server with the PoC demo database.
REM Usage: start.bat [DB_PATH]
REM   DB_PATH defaults to data\master.db

setlocal

set "SCRIPT_DIR=%~dp0"

set "DB=%~1"
if "%DB%"=="" set "DB=%SCRIPT_DIR%data\master.db"

REM Resolve to absolute path
for %%F in ("%DB%") do set "DB=%%~fF"

if not exist "%DB%" (
    echo ERROR: database not found: %DB%
    echo.
    echo Available databases:
    dir /b "%SCRIPT_DIR%data\*.db" 2>nul
    exit /b 1
)

set "KNOW_KERNEL_DB=%DB%"
if "%KNOW_KERNEL_AUTH_DB%"=="" set "KNOW_KERNEL_AUTH_DB=%SCRIPT_DIR%data\auth.db"
set "PYTHONPATH=%SCRIPT_DIR%src"

echo Starting know_kernel web server...
echo   Database: %DB%
echo   Auth DB:  %KNOW_KERNEL_AUTH_DB%
echo   URL:      http://localhost:8000
echo.

REM authgate.app:app, never web.app:app - the latter serves the knowledge app
REM with no authentication at all (INV-KK-AUTH-GATE-COVERS-MOUNT).
python -m uvicorn authgate.app:app --host 127.0.0.1 --port 8000 --reload
