@echo off
REM Start the know_kernel web server with the PoC demo database.
REM Usage: start.bat [DB_PATH]
REM   DB_PATH defaults to data\master.db

setlocal

set "DB=%~1"
if "%DB%"=="" set "DB=data\master.db"

if not exist "%DB%" (
    echo ERROR: database not found: %DB%
    echo.
    echo Available databases:
    dir /b data\*.db 2>nul
    exit /b 1
)

set "KNOW_KERNEL_DB=%DB%"
set "PYTHONPATH=src"

echo Starting know_kernel web server...
echo   Database: %DB%
echo   URL:      http://localhost:8000
echo.

python -m uvicorn web.app:app --host 127.0.0.1 --port 8000 --reload
