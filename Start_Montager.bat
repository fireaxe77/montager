@echo off
rem Montager launcher: sets up a first-time settings file (only if none exists), runs the read-only setup check, then
rem starts Montager exactly like Montager.vbs does (pythonw montage.py, no console window).
setlocal
cd /d "%~dp0"
title Montager
set "PY=python"
where python >nul 2>&1
if errorlevel 1 (
  where py >nul 2>&1
  if errorlevel 1 goto nopython
  set "PY=py -3"
)

%PY% first_run.py
echo Checking your setup (read-only) ...
%PY% setup_check.py
set "RC=%ERRORLEVEL%"
if "%RC%"=="1" (
  echo.
  echo Some things need fixing ^(see PROBLEM lines above^). Most of them are fixed in Montager's Settings tab.
  echo Press any key to open Montager anyway, or close this window.
  pause >nul
) else if "%RC%"=="2" (
  echo.
  echo Ready, with warnings ^(see WARN lines above^). Starting Montager ...
  timeout /t 8
) else if not "%RC%"=="0" (
  echo.
  echo The setup check itself failed ^(exit code %RC%^). Press any key to open Montager anyway.
  pause >nul
)

start "" wscript "%~dp0Montager.vbs"
exit /b 0

:nopython
echo Python was not found.
echo Install Python 3.12 ^(64-bit^) from https://www.python.org/downloads/ and tick "Add python.exe to PATH",
echo then double-click Start_Montager.bat again.
pause
exit /b 1
