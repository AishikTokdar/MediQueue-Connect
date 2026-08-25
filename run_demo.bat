@echo off
REM =======================================================
REM   MediQueue Connect - Production Backend Launcher
REM =======================================================

echo =======================================================
echo     MediQueue Connect - Production Backend Launcher
echo =======================================================
echo.

REM Optional test execution if --test parameter passed
if "%1"=="--test" (
    echo [0/4] Running Pytest Suite...
    python -m pytest -v tests/
    if errorlevel 1 (
        echo [ERROR] Test suite failed! Aborting startup.
        exit /b 1
    )
    echo.
)

echo [1/4] Starting Async Health Center Server (Port 4000)...
start "MediQueue - Health Server (Asyncio + SQLite)" cmd /k python server\health_server.py
timeout /t 2 /nobreak >nul

echo [2/4] Starting Doctor 1 (General Physician)...
start "MediQueue - Dr. Doctor1" cmd /k python clients\doctor.py doctor1
timeout /t 1 /nobreak >nul

echo [3/4] Starting Doctor 2 (Cardiologist)...
start "MediQueue - Dr. Doctor2" cmd /k python clients\doctor.py doctor2
timeout /t 1 /nobreak >nul

echo [4/4] Starting Live Monitoring Dashboard...
start "MediQueue - Live Metrics Dashboard" cmd /k python server\dashboard.py --interval 2
timeout /t 1 /nobreak >nul

echo.
echo =======================================================
echo   All production background services launched!
echo   Launching Patient Client in this terminal window...
echo =======================================================
echo.
python clients\patient.py
