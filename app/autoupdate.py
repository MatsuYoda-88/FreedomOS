"""FreedomOS auto-update.

Claude drops new files into the FreedomOS folder (or the file sync brings them over from the other PC).
This watches for that and updates the running crew by itself - no bat needed:
  * only the page changed  -> the open windows just refresh
  * the Python brains changed      -> check the new code is OK, install any new packages,
                                      wait till the crew isn't mid-job, then restart the boss
"""
import asyncio
import os
import py_compile
import subprocess
import sys
import tempfile
import time
from pathlib import Path

D = {}
CHECK_EVERY = 10          # seconds between looks
SETTLE = 25               # wait till nothing's changed for this long (sync drops files one by one)
MAX_WAIT_JOBS = 15 * 60   # don't wait on a running job forever
SKIP_DIRS = {"venv", "memory", "logs", "engine", "engine_vulkan", "engine_prism", "imagegen", "outputs", "models",
             "claude pics", "training", "__pycache__", "mystyles", "my style", "refs-dropped"}


def init(here, log, hub, busy, before_restart, on_browser=None):
    D.update(here=Path(here), log=log, hub=hub, busy=busy, before_restart=before_restart, on_browser=on_browser)


def _watched():
    here = D["here"]
    out = {}
    for p in [here / "config.json", here / "requirements.txt", here / "pixelshop" / "requirements.txt"]:
        if p.exists():
            out[p] = p.stat().st_mtime
    for p in here.glob("*.py"):
        out[p] = p.stat().st_mtime
    for p in (here / "pixelshop").glob("*.py") if (here / "pixelshop").exists() else []:
        out[p] = p.stat().st_mtime
    bs = here / "browser" / "src"                          # 🌐 WiBro's code - changes get rebuilt, no restart
    if bs.exists():
        for p in list(bs.glob("*.cs")) + list(bs.glob("*.csproj")) + list(bs.glob("*.ico")):
            out[p] = p.stat().st_mtime
    w = here / "widget"
    if w.exists():
        for root, dirs, files in os.walk(w):
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]
            for f in files:
                if not f.startswith(".sync-tmp"):
                    p = Path(root) / f
                    try:
                        out[p] = p.stat().st_mtime
                    except OSError:
                        pass
    return out


def _code_ok(files):
    """Every changed .py has to compile before we restart on it (a half-copied file won't)."""
    bad = []
    for f in files:
        if f.suffix != ".py":
            continue
        try:
            py_compile.compile(str(f), cfile=os.path.join(tempfile.gettempdir(), "f35_check.pyc"), doraise=True)
        except Exception as e:
            bad.append(f"{f.name}: {str(e).splitlines()[-1][:120]}")
    if any(f.name == "config.json" for f in files):
        import json
        try:
            json.loads((D["here"] / "config.json").read_text(encoding="utf-8"))
        except Exception as e:
            bad.append(f"config.json: {e}")
    return bad


def _pip(req, py):
    if not req.exists() or not Path(py).exists():
        return
    D["log"](f"🔄 Update: installing anything new in {req.parent.name}\\{req.name} ...")
    r = subprocess.run([str(py), "-m", "pip", "install", "-q", "-r", str(req)], capture_output=True, text=True, timeout=900)
    if r.returncode:
        D["log"](f"🔄 Update: pip had trouble: {(r.stderr or r.stdout)[-300:]}")


async def restart_now(reason):
    """Start a fresh boss (it waits for the port), then this one bows out."""
    here = D["here"]
    env = dict(os.environ, F35_RESTARTED="1")
    flags, extra = 0, {}
    if os.name == "nt":                               # its own little log window, minimized like the bat does it
        flags = subprocess.CREATE_NEW_CONSOLE
        si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow = 7   # SW_SHOWMINNOACTIVE
        extra["startupinfo"] = si
    D["log"](f"🔄 Update: restarting the boss - {reason}")
    D["hub"].send({"type": "bye", "reason": "Updating - back in a few seconds", "restart": True})
    await asyncio.sleep(1.5)                                  # let that message reach the windows
    try:
        D["before_restart"]()
    except Exception as e:
        D["log"](f"🔄 Update: cleanup hiccup ({e})")
    subprocess.Popen([sys.executable, str(here / "boss.py")], cwd=str(here), env=env, creationflags=flags,
                     **(extra if os.name == "nt" else {"start_new_session": True}))
    time.sleep(0.5)
    os._exit(0)


async def loop():
    base = await asyncio.to_thread(_watched)
    pending, last_change, wait_since = set(), 0.0, None
    while True:
        await asyncio.sleep(CHECK_EVERY)
        try:
            now_ = await asyncio.to_thread(_watched)
        except Exception:
            continue
        changed = {p for p, m in now_.items() if base.get(p) != m}
        if changed:
            pending |= changed
            last_change = time.time()
            base = now_
            continue
        if not pending or time.time() - last_change < SETTLE:
            continue
        files = sorted(pending)
        brw = [f for f in files if f.suffix in (".cs", ".csproj", ".ico") and "browser" in [x.lower() for x in f.parts]]
        if brw:                                            # 🌐 browser code changed -> rebuild it in the background
            D["log"](f"🔄 Update: new WiBro code ({', '.join(f.name for f in brw[:4])}) - rebuilding it")
            if D.get("on_browser"):
                D["on_browser"]()
            files = [f for f in files if f not in brw]
            if not files:
                pending.clear()
                continue
        code = [f for f in files if f.suffix == ".py" or f.name in ("config.json", "requirements.txt")]
        if not code:                                       # just the page: refresh the windows
            D["log"](f"🔄 Update: new page files ({', '.join(f.name for f in files[:6])}) - refreshing the windows")
            D["hub"].send({"type": "reload", "why": "update"})
            pending.clear()
            continue
        bad = await asyncio.to_thread(_code_ok, files)
        if bad:
            D["log"](f"🔄 Update: new code isn't ready yet, waiting - {'; '.join(bad)}")
            last_change = time.time()                      # look again after the next settle
            continue
        if D["busy"]():
            wait_since = wait_since or time.time()
            if time.time() - wait_since < MAX_WAIT_JOBS:
                if int(time.time() - wait_since) % 120 < CHECK_EVERY:
                    D["log"]("🔄 Update: waiting for the crew to finish its job before restarting")
                continue
        here = D["here"]
        for f in files:
            if f.name == "requirements.txt":
                vpy = here / "venv" / "Scripts" / "python.exe" if f.parent == here else here / "pixelshop" / "venv" / "Scripts" / "python.exe"
                if f.parent == here and not vpy.exists():
                    vpy = Path(sys.executable)
                await asyncio.to_thread(_pip, f, vpy)
        await restart_now(", ".join(f.name for f in files[:6]) + (" ..." if len(files) > 6 else ""))


def wait_for_port(port, secs=40):
    """A freshly restarted boss waits for the old one to let go of the port."""
    import socket
    end = time.time() + secs
    while time.time() < end:
        with socket.socket() as s:          # nobody answers on the port = the old boss is gone
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                time.sleep(0.5)
                return True
        time.sleep(0.5)
    return False
