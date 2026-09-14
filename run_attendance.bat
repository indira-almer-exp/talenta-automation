@echo off
cd /d "%~dp0"
python talenta_attendance.py %*
echo.
echo Exit code %ERRORLEVEL% (0 = all submitted, 2 = some dates failed or run stopped early, 1 = run aborted)
pause
