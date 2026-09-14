@echo off
cd /d "%~dp0"
python talenta_attendance.py --dry-run %*
echo.
echo Exit code %ERRORLEVEL% (dry run: 0 = every form filled, 2 = some dates failed, 1 = run aborted)
pause
