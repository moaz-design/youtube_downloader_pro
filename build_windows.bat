@echo off
setlocal EnableExtensions
set "PYTHONUTF8=1"
chcp 65001 >nul
cd /d "%~dp0" || goto :error

title YouTube Downloader Pro - Build Installer
echo ==========================================================
echo   YouTube Downloader Pro - Windows Installer Builder
echo ==========================================================
where py.exe >nul 2>&1
if errorlevel 1 goto :no_python

if not exist ".venv\Scripts\python.exe" (
  echo Creating an isolated build environment...
  py -3 -m venv ".venv"
  if errorlevel 1 goto :error
)

".venv\Scripts\python.exe" -X utf8 "scripts\build_windows.py" %*
if errorlevel 1 goto :error

echo.
echo Build completed successfully.
echo Installer: Output\YouTubeDownloader-Setup.exe
echo.
pause
exit /b 0

:no_python
echo ERROR: Python Launcher was not found.
echo Install Python 3.11 or newer and enable "Add Python to PATH".
echo Then close this window and run this file again.
pause
exit /b 1

:error
echo.
echo ERROR: Build failed. Review the messages above.
echo Check that Python and Inno Setup are installed, then try again.
pause
exit /b 1
