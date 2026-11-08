@echo off
rem Starts iPhone Mirror without a console window. Run install.bat once first.
pushd "%~dp0"
if not exist "%LOCALAPPDATA%\iPhoneMirror\venv\Scripts\pythonw.exe" (
  echo iPhone Mirror is not installed yet. Run install.bat first.
  popd
  pause
  exit /b 1
)
start "" "%LOCALAPPDATA%\iPhoneMirror\venv\Scripts\pythonw.exe" -m iphone_mirror
popd
