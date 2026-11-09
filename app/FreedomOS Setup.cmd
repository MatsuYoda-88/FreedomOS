@echo off
setlocal EnableExtensions
chcp 65001 >nul
title FreedomOS Setup
REM ===================================================================
REM  FreedomOS Setup - installs everything FreedomOS needs, one time.
REM  Safe to run again any time (Start menu > FreedomOS > FreedomOS Setup)
REM  - it skips what's already there and fixes what's missing.
REM
REM   1. Python 3.12 + FreedomOS's Python toolbox
REM   2. The llama.cpp brain engine (NVIDIA CUDA build, or Vulkan for Intel/AMD)
REM   3. Pixel Shop (optional, NVIDIA cards only)
REM   4. Tailscale (optional) - use FreedomOS from your phone / other PCs
REM   5. Claude Code (optional) - the chat-with-Claude window
REM   6. Plugs the crew into the Claude desktop app (if you have it)
REM   7. Starts FreedomOS
REM ===================================================================
cd /d "%~dp0"
set "APP=%~dp0"
if not exist "%APP%boss.py" (
  echo Can't find FreedomOS next to this file. Re-run the FreedomOS installer.
  pause
  exit /b 1
)
if not exist "%APP%logs" mkdir "%APP%logs"
echo.
echo   ======================  FreedomOS Setup  ======================
echo.

REM --- 1. Python + toolbox ---------------------------------------------------
set "VPY=%APP%venv\Scripts\python.exe"
if exist "%VPY%" goto have_venv
set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY (
  echo [1/7] Installing Python 3.12 - one time only...
  winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY (
  echo.
  echo   Python didn't install. Install Python 3.12 from https://www.python.org/downloads/
  echo   ^(tick "Add python.exe to PATH"^), then run FreedomOS Setup again.
  pause
  exit /b 1
)
echo [1/7] Building FreedomOS's Python toolbox - one time only...
"%PY%" -m venv "%APP%venv"
"%VPY%" -m pip install --upgrade pip -q
:have_venv
"%VPY%" -m pip install -q -r "%APP%requirements.txt"
if errorlevel 1 (
  echo   Toolbox install failed - check your internet and run FreedomOS Setup again.
  pause
  exit /b 1
)
echo [1/7] Python toolbox ready.

REM --- 2. llama.cpp engine ---------------------------------------------------
"%VPY%" "%APP%get_engine.py"
if exist "%APP%engine\llama-server.exe" goto engine_ok
if exist "%APP%engine_vulkan\llama-server.exe" goto engine_ok
echo   Engine download failed - check your internet and run FreedomOS Setup again.
pause
exit /b 1
:engine_ok
echo [2/7] Brain engine ready. (The brain itself downloads the first time you use it.)

REM --- 3. Pixel Shop (NVIDIA only, optional) --------------------------------
set "NV=0"
nvidia-smi -L 2>nul | find "GPU " >nul && set "NV=1"
if "%NV%"=="0" (
  echo [3/7] No NVIDIA card - skipping the Pixel Shop. ^(Pixel Shop Lite still works - set it up from the 🎨 button.^)
  goto px_done
)
set "PXD=%APP%pixelshop"
set "PVPY=%PXD%\venv\Scripts\python.exe"
if exist "%PVPY%" goto px_have_venv
echo.
echo   You have an NVIDIA card. Set up the Pixel Shop (AI pictures)?
echo   It downloads about 3 GB now, and the picture models the first time you open it.
choice /c YN /m "  Set up the Pixel Shop"
if errorlevel 2 goto px_done
set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY for /f "usebackq delims=" %%P in (`"%VPY%" -c "import sys;print(sys._base_executable)"`) do set "PY=%%P"
"%PY%" -m venv "%PXD%\venv"
"%PVPY%" -m pip install --upgrade pip -q
:px_have_venv
"%PVPY%" "%PXD%\get_torch.py"
if errorlevel 1 (
  echo   Pixel Shop: PyTorch didn't install - the shop won't open. Run FreedomOS Setup again later.
  goto px_done
)
"%PVPY%" -m pip install -q -r "%PXD%\requirements.txt"
if errorlevel 1 echo   Pixel Shop toolbox install failed - run FreedomOS Setup again later.
echo [3/7] Pixel Shop ready (open it from the 🎨 button - "Start work").
:px_done

REM --- 4. Tailscale (optional) ----------------------------------------------
set "TS=%ProgramFiles%\Tailscale\tailscale.exe"
if exist "%TS%" goto have_ts
if exist "%APP%no_remote.txt" goto ts_done
echo.
echo   Want to use FreedomOS from your phone or your other PCs?
echo   That needs Tailscale - a free private tunnel between YOUR devices only.
echo   (See docs\TAILSCALE.md on the FreedomOS GitHub page for the full walkthrough.)
choice /c YN /m "  Install Tailscale on this PC"
if errorlevel 2 (
  echo skip> "%APP%no_remote.txt"
  goto ts_done
)
winget install -e --id Tailscale.Tailscale --silent --accept-package-agreements --accept-source-agreements
if not exist "%TS%" (
  echo   Tailscale didn't install - skipping it for now. You can run FreedomOS Setup again later.
  goto ts_done
)
:have_ts
"%TS%" ip -4 >nul 2>nul
if errorlevel 1 (
  echo.
  echo   ** Sign in to Tailscale: a browser window opens - log in.               **
  echo   ** Use the SAME account on your phone and your other PCs.               **
  start "" "%TS%" up
  echo   Press any key once you're signed in...
  pause >nul
)
set "PORT=7777"
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "(Get-Content -Raw '%APP%config.json' | ConvertFrom-Json).port"`) do set "PORT=%%p"
REM one-time firewall rule for FreedomOS's port, ONLY from Tailscale addresses (Windows asks for admin once)
if not exist "%APP%firewall_done.txt" (
  echo   Windows will ask for permission once - this lets ONLY your Tailscale devices reach FreedomOS.
  powershell -NoProfile -Command "Start-Process netsh -Verb RunAs -Wait -ArgumentList 'advfirewall firewall add rule name=FreedomOS-Tailscale-%PORT% dir=in action=allow protocol=TCP localport=%PORT% remoteip=100.64.0.0/10'"
  echo done> "%APP%firewall_done.txt"
)
:ts_done
echo [4/7] Remote access set.

REM --- 5. Claude Code (optional) --------------------------------------------
where claude >nul 2>nul && goto cc_done
if exist "%USERPROFILE%\.local\bin\claude.exe" goto cc_done
if exist "%APP%no_claude.txt" goto cc_skip
echo.
echo   The 💬 Claude chat window uses Claude Code with your own Claude account (Pro/Max plan).
choice /c YN /m "  Install Claude Code for the chat window"
if errorlevel 2 (
  echo skip> "%APP%no_claude.txt"
  goto cc_skip
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://claude.ai/install.ps1 | iex"
:cc_done
echo [5/7] Claude chat line ready. (First time: open 💬 and hit 🔑 Log in.)
goto cc_after
:cc_skip
echo [5/7] Skipped Claude Code - everything else still works.
:cc_after

REM --- 6. plug the crew into the Claude desktop app -------------------------
"%VPY%" "%APP%install_claude_hook.py"
echo [6/7] Claude desktop plug-in checked.

REM --- 7. start FreedomOS ----------------------------------------------------
echo [7/7] Starting FreedomOS...
call "%APP%FreedomOS.cmd"
echo.
echo   All set! FreedomOS starts with Windows from now on.
echo   First question or job downloads the brain (about 6 GB) - watch the 🧠 line.
echo.
timeout /t 12 >nul
exit /b 0
