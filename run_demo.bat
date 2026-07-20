@echo off
REM =======================================================
REM   MediQueue Connect - Windows Automated Launcher
REM =======================================================

echo =======================================================
echo        MediQueue Connect - Automated Launcher
echo =======================================================
echo.

echo [1/4] Starting Health Center Server...
start "MediQueue - Health Server" cmd /k python server\health_server.py
timeout /t 2 /nobreak >nul

echo [2/4] Starting Doctor 1 (General Physician)...
start "MediQueue - Dr. Doctor1" cmd /k python clients\doctor.py doctor1
timeout /t 1 /nobreak >nul

echo [3/4] Starting Doctor 2 (Cardiologist)...
start "MediQueue - Dr. Doctor2" cmd /k python clients\doctor.py doctor2
timeout /t 1 /nobreak >nul

echo [4/4] Starting Live Monitoring Dashboard...
start "MediQueue - Dashboard" cmd /k python server\dashboard.py --interval 2
timeout /t 1 /nobreak >nul

echo.
echo =======================================================
echo   All background services launched!
echo   Launching Patient Client in this terminal window...
echo =======================================================
echo.
python clients\patient.py
