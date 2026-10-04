@echo off
REM ============================================================
REM Bordd - Windows build launcher
REM
REM This file is intentionally ASCII-only. cmd.exe reads .bat files
REM using the console code page (936/GBK on Simplified Chinese
REM Windows); a UTF-8 .bat would be mis-decoded and could break the
REM script. All build logic and Chinese messages live in build.py,
REM which is UTF-8 and handles encoding itself.
REM
REM Products:
REM   dist\Bordd_gui.exe   GUI version (double-click to run)
REM   dist\Bordd.exe       command line version
REM
REM Usage:
REM   build_windows.bat
REM   build_windows.bat --gui-only
REM   set PYTHON=D:\miniconda3\envs\PyTorch\python.exe && build_windows.bat
REM ============================================================
setlocal
cd /d "%~dp0"

if not defined PYTHON set "PYTHON=python"

"%PYTHON%" "%~dp0build.py" %*
set "RC=%errorlevel%"

if not "%RC%"=="0" (
  echo.
  echo [FAILED] build.py exited with code %RC%
)
endlocal & exit /b %RC%
