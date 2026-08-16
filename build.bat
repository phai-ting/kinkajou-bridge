@echo off
setlocal
cd /d "%~dp0"

uv sync
if errorlevel 1 exit /b 1

uv run pyinstaller KinkajouBridge.spec
if errorlevel 1 exit /b 1

mkdir dist\KinkajouBridge\streamerbot
copy streamerbot\KinkajouBridge.sb dist\KinkajouBridge\streamerbot\

powershell -NoProfile -Command ^
  "Compress-Archive -Path 'dist\KinkajouBridge\*' -DestinationPath 'dist\KinkajouBridge-0.1.1-windows-x64.zip' -Force"
if errorlevel 1 exit /b 1

echo.
echo Built: dist\KinkajouBridge-0.1.1-windows-x64.zip
endlocal
