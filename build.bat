@echo off
setlocal
cd /d "%~dp0"

uv sync
if errorlevel 1 exit /b 1

uv run pyinstaller KinkajouBridge.spec
if errorlevel 1 exit /b 1

powershell -NoProfile -Command ^
  "Compress-Archive -Path 'dist\KinkajouBridge\*' -DestinationPath 'dist\KinkajouBridge-0.1.0-windows-x64.zip' -Force"
if errorlevel 1 exit /b 1

echo.
echo Built: dist\KinkajouBridge-0.1.0-windows-x64.zip
endlocal
