@echo off
setlocal EnableExtensions
REM FreedomOS launcher: starts the FreedomOS server (quietly, in the tray) and opens the app.
cd /d "%~dp0"
set "APP=%~dp0"
if not exist "%APP%venv\Scripts\pythonw.exe" (
  REM first run (or something's missing) - run the setup
  start "FreedomOS Setup" "%APP%FreedomOS Setup.cmd"
  exit /b 0
)
set "PORT=7777"
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "(Get-Content -Raw '%APP%config.json' | ConvertFrom-Json).port"`) do set "PORT=%%p"
REM already running? just open the app window
curl -s -m 2 http://127.0.0.1:%PORT%/health | find "autoupdate" >nul 2>nul && goto up
start "" "%APP%venv\Scripts\pythonw.exe" "%APP%boss.py"
set /a TRIES=0
:wait
timeout /t 2 /nobreak >nul
curl -s -m 2 http://127.0.0.1:%PORT%/health >nul 2>nul && exit /b 0
set /a TRIES+=1
if %TRIES% lss 30 goto wait
echo FreedomOS didn't start. Look in "%APP%logs\boss.log" for why.
pause
exit /b 1
:up
set "EXE="
if exist "%APP%browser\builds\current.txt" for /f "usebackq tokens=1" %%a in ("%APP%browser\builds\current.txt") do set "EXE=%APP%browser\builds\%%a\FreedomOS.exe"
if defined EXE if exist "%EXE%" (
  start "" "%EXE%" --show
  exit /b 0
)
start "" msedge --app=http://127.0.0.1:%PORT%/ --window-size=1180,680
exit /b 0
