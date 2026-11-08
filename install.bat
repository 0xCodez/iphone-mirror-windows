@echo off
setlocal
rem iPhone Mirror installer.
rem Creates a Python environment in %LOCALAPPDATA%\iPhoneMirror\venv, installs the
rem dependencies and creates "iPhone Mirror" shortcuts (Desktop + Start menu) that
rem point at this folder. Run it again after moving the folder.

set "APPDIR=%~dp0"
if "%APPDIR:~-1%"=="\" set "APPDIR=%APPDIR:~0,-1%"
set "VENV=%LOCALAPPDATA%\iPhoneMirror\venv"

where python >nul 2>nul || (
  echo Python was not found. Install Python 3.11 or newer from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH" during setup^) and run install.bat again.
  pause & exit /b 1
)
python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>nul || (
  echo Python 3.11 or newer is required. Install it from https://www.python.org/downloads/
  echo and run install.bat again.
  pause & exit /b 1
)

if not exist "%VENV%\Scripts\python.exe" (
  echo Creating the Python environment in "%VENV%" ...
  python -m venv --without-pip "%VENV%" || (pause & exit /b 1)
)

echo Installing the dependencies (this can take a few minutes)...
python -m pip --python "%VENV%\Scripts\python.exe" install -q --upgrade pip -r "%APPDIR%\requirements.txt" || (pause & exit /b 1)

echo Creating the shortcuts...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "foreach ($dir in @([Environment]::GetFolderPath('Desktop'), (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'))) {" ^
  "  $s = $ws.CreateShortcut((Join-Path $dir 'iPhone Mirror.lnk'));" ^
  "  $s.TargetPath = Join-Path $env:VENV 'Scripts\pythonw.exe';" ^
  "  $s.Arguments = '-m iphone_mirror';" ^
  "  $s.WorkingDirectory = $env:APPDIR;" ^
  "  $s.IconLocation = Join-Path $env:APPDIR 'iphone_mirror\icon.ico';" ^
  "  $s.Description = 'Mirror your iPhone screen on Windows';" ^
  "  $s.Save() }" || (
  echo Could not create the shortcuts. You can still start the app with run.bat.
  pause & exit /b 1
)

echo.
echo Done. Start "iPhone Mirror" from the Desktop or the Start menu.
pause
