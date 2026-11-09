"""
FreedomOS - the Pixel Shop (HereticPixel built in).

Plain words:
  * "Start work" in the Pixel Shop panel parks the crew's brain (frees the GPU) and fires up
    the image generator that lives in the "pixelshop" folder.
  * You open it right inside FreedomOS. Your crew gets in through FreedomOS's address with the
    PIXEL SHOP key - that key ONLY opens the shop, never your jobs or your files.
  * While somebody's making pictures, an agent shows as busy.
  * "Close shop" shuts it down and wakes the crew's brain back up.
"""
import asyncio
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

from aiohttp import web, ClientSession, ClientTimeout

PIX_PORT = 7860
PIX = f"http://127.0.0.1:{PIX_PORT}"
WORKER = "Rook"             # which agent shows as busy while pictures are being made

state = {"status": "off", "detail": "", "waiting": 0, "made": 0, "loaded": None}   # off / starting / ready / working / failed
last_use = 0.0
_proc = None
_lock = asyncio.Lock()
D = {}                      # stuff handed over from boss.py


def init(here, log, hub, set_agent, set_engine, kill_engine, ensure_engine, agents, is_win):
    D.update(here=Path(here), log=log, hub=hub, set_agent=set_agent, set_engine=set_engine,
             kill_engine=kill_engine, ensure_engine=ensure_engine, agents=agents, is_win=is_win)
    D["dir"] = D["here"] / "pixelshop"
    if WORKER not in agents:
        globals()["WORKER"] = next((n for n, a in agents.items() if a["role"] == "worker"), None)


def has_nvidia():
    from gpu_check import nvidia_now   # a card really plugged in, not just drivers
    return nvidia_now()


def installed():
    return (D["dir"] / "server.py").exists()


def py():
    for p in (D["dir"] / "venv" / "Scripts" / "python.exe", D["dir"] / "venv" / "bin" / "python"):
        if p.exists():
            return str(p)
    return None


def owns_gpu():
    return state["status"] in ("starting", "ready", "working")


def recently_used(secs):
    return owns_gpu() and time.time() - last_use < secs


def pix_key():
    f = D["dir"] / "crew_key.txt"
    try:
        k = f.read_text(encoding="utf-8").strip()
        if k:
            return k
    except OSError:
        pass
    k = secrets.token_urlsafe(9)
    try:
        f.write_text(k, encoding="utf-8")
    except OSError:
        pass
    return k


def key_ok(request):
    """The Pixel Shop key opens /pixel/app/ and nothing else."""
    given = request.query.get("key") or request.cookies.get("hp_key") or request.headers.get("X-Crew-Key") or ""
    return bool(given) and secrets.compare_digest(given, pix_key())


def _set(status, detail=""):
    state.update(status=status, detail=detail)
    D["hub"].send({"type": "pixel", "pixel": dict(state)})


def _artist(working, text=None):
    if not WORKER or WORKER not in D["agents"]:
        return
    if working:
        if D.get("hands"):
            D["hands"]("pic")
        D["set_agent"](WORKER, "code", "working", None, text=text or "Making pictures in the shed...")
    else:
        if D.get("hands"):
            D["hands"]("pic", False)
        D["set_agent"](WORKER, "idle", "idle", None)


async def _health(session):
    try:
        async with session.get(PIX + "/health", timeout=ClientTimeout(total=2)) as r:
            return (await r.json()) if r.status == 200 else None
    except Exception:
        return None


async def start():
    """Pause the brain, fire up the shop."""
    global _proc, last_use
    async with _lock:
        if owns_gpu():
            return True
        if not has_nvidia():
            _set("failed", "desktop only - the Pixel Shop needs the NVIDIA card")
            return False
        if not installed():
            _set("failed", "pixelshop folder missing - run 'FreedomOS Setup' from the Start menu")
            return False
        exe = py()
        if not exe:
            _set("failed", "Pixel Shop toolbox not installed - run 'FreedomOS Setup' from the Start menu")
            return False
        _set("starting", "parking the crew's brain to free up the GPU...")
        D["log"]("Pixel Shop: opening up. Parking the brain so the GPU's free.")
        D["kill_engine"]()
        D["set_engine"]("off", "parked - the Pixel Shop has the GPU")
        async with ClientSession() as s:
            if await _health(s):            # an old stand-alone HereticPixel still running? send it home
                try:
                    await s.post(PIX + "/shutdown", timeout=ClientTimeout(total=3))
                except Exception:
                    pass
                await asyncio.sleep(2)
            env = dict(os.environ, HP_HOST="127.0.0.1", HP_PORT=str(PIX_PORT), HP_NO_LINK="1")
            logs = D["here"] / "logs"
            logs.mkdir(exist_ok=True)
            logf = open(logs / "pixelshop.log", "a", encoding="utf-8")
            flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if D["is_win"] else 0
            _proc = subprocess.Popen([exe, str(D["dir"] / "server.py")], cwd=str(D["dir"]), env=env,
                                     stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags)
            _set("starting", "opening the shop...")
            for _ in range(60):
                await asyncio.sleep(1)
                if await _health(s):
                    last_use = time.time()
                    _set("ready", "open for business")
                    D["log"]("Pixel Shop: open.")
                    return True
                if _proc.poll() is not None:
                    break
        _set("failed", "shop wouldn't open - check logs\\pixelshop.log")
        D["log"]("!! Pixel Shop wouldn't start. Check logs/pixelshop.log")
        return False


def _kill():
    global _proc
    if _proc is not None and _proc.poll() is None:
        try:
            _proc.kill()
        except Exception:
            pass
    _proc = None


async def stop(wake_brain=True):
    async with _lock:
        if state["status"] == "off" and _proc is None:
            return
        try:
            async with ClientSession() as s:
                await s.post(PIX + "/shutdown", timeout=ClientTimeout(total=3))
            await asyncio.sleep(1)
        except Exception:
            pass
        _kill()
        _artist(False)
        _set("off", "closed")
        D["log"]("Pixel Shop: closed. the GPU's back for the crew.")
    if wake_brain:
        async def wake():
            async with ClientSession() as s:
                await D["ensure_engine"](s)
        asyncio.get_running_loop().create_task(wake())


def stop_sync():
    """For when FreedomOS itself is shutting down."""
    try:
        import urllib.request
        urllib.request.urlopen(urllib.request.Request(PIX + "/shutdown", method="POST"), timeout=2)
    except Exception:
        pass
    _kill()


async def watch_loop():
    """Keeps the panel + the art agent in sync with what the shop is doing."""
    was_busy = False
    made_before = None
    async with ClientSession() as s:
        while True:
            await asyncio.sleep(3)
            if not owns_gpu():
                was_busy, made_before = False, None
                continue
            # bouncer: the crew's brain stays OFF while the shop has the GPU
            if D.get("engine_up") and D["engine_up"]():
                D["log"]("Pixel Shop: the crew's brain snuck back on - kicked it off the GPU.")
                D["kill_engine"]()
                D["set_engine"]("off", "parked - the Pixel Shop has the GPU (Close shop to wake it)")
            if _proc is not None and _proc.poll() is not None:
                _artist(False)
                _set("off", "shop closed itself")
                was_busy = False
                async def wake():
                    await D["ensure_engine"](s)
                asyncio.get_running_loop().create_task(wake())
                continue
            try:
                async with s.get(PIX + "/api/status", timeout=ClientTimeout(total=3)) as r:
                    st = await r.json()
            except Exception:
                continue
            waiting, made = st.get("waiting", 0), st.get("made", 0)
            state.update(waiting=waiting, made=made, loaded=st.get("loaded"))
            busy = waiting > 0
            if busy:
                note = st.get("note") or ""
                text = "Waiting on the picture machine to warm up..." if st.get("state") == "loading" \
                    else ("Making pictures in the shed..." if waiting == 1 else f"Making pictures - {waiting} in line!")
                _artist(True, text)
                _set("working", note if st.get("state") == "loading" else f"{waiting} in line")
            elif was_busy:
                _artist(False)
                _set("ready", "open for business")
            if made_before is not None and made > made_before and WORKER:
                D["hub"].send({"type": "say", "name": WORKER, "text": "Picture's done! Have a look!", "secs": 4})
            made_before, was_busy = made, busy


# ------------------------------------------------------------------ web bits
async def h_status(request):
    return web.json_response({**state, "installed": installed(), "toolbox": bool(py()) if installed() else False,
                              "desktop_only": not has_nvidia()})


async def h_start(request):
    asyncio.get_running_loop().create_task(start())
    return web.json_response({"ok": True, **state})


async def h_stop(request):
    asyncio.get_running_loop().create_task(stop())
    return web.json_response({"ok": True})


CLOSED_PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Pixel Shop</title><body style="background:#14110d;color:#e6dcc6;font:18px Consolas,monospace;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0;text-align:center"><div>
<h1 style="color:#a4c860;letter-spacing:3px">HERETIC<span style="color:#b8402e">PIXEL</span></h1>
The Pixel Shop's closed right now.<br>Get the boss to hit <b>Start work</b> in FreedomOS.
<script>setTimeout(()=>location.reload(),15000)</script></div>"""


async def h_proxy(request, is_host):
    """Passes the crew through to the shop (it only listens on this PC)."""
    global last_use
    tail = request.match_info.get("tail", "")
    if not owns_gpu() or state["status"] == "starting":
        if request.method == "GET" and not tail.startswith(("api/", "img/", "mystyle/")):
            return web.Response(text=CLOSED_PAGE, content_type="text/html", status=503)
        return web.json_response({"error": "The Pixel Shop's closed right now."}, status=503)
    last_use = time.time()
    url = f"{PIX}/{tail}" + (("?" + request.query_string) if request.query_string else "")
    headers = {"X-HP-Proxied": "1"}
    if request.headers.get("Content-Type"):
        headers["Content-Type"] = request.headers["Content-Type"]
    if is_host:
        headers["X-HP-Host"] = "1"
    body = await request.read()
    try:
        async with ClientSession(timeout=ClientTimeout(total=180)) as s:
            async with s.request(request.method, url, data=body or None, headers=headers, allow_redirects=False) as r:
                data = await r.read()
                out = web.Response(body=data, status=r.status)
                for h in ("Content-Type", "Content-Disposition", "Cache-Control", "Location"):
                    if h in r.headers:
                        out.headers[h] = r.headers[h]
    except Exception:
        return web.json_response({"error": "Couldn't reach the Pixel Shop. Try again in a sec."}, status=502)
    given = request.query.get("key")
    if given and secrets.compare_digest(given, pix_key()):
        out.set_cookie("hp_key", given, max_age=60 * 60 * 24 * 365, httponly=True, samesite="Lax", path="/pixel/app")
    return out


def routes(is_host):
    async def proxy(request):
        return await h_proxy(request, is_host(request))

    async def to_slash(request):
        raise web.HTTPFound("/pixel/app/" + (("?" + request.query_string) if request.query_string else ""))

    return [
        web.get("/pixel/status", h_status), web.post("/pixel/start", h_start), web.post("/pixel/stop", h_stop),
        web.get("/pixel/app", to_slash),
        web.route("*", "/pixel/app/{tail:.*}", proxy),
    ]


def _work():
    import pixlite
    d = pixlite.documents() / "FreedomOS"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_link(ip, name, https_ok=True):
    k = pix_key()
    lines = ["FreedomOS - PIXEL SHOP friends link", "====================================",
             "Give this to the people you've shared this desktop with in Tailscale.",
             "This key ONLY opens the Pixel Shop - not your jobs, not your files.",
             "The shop has to be open (Start work in the FreedomOS panel) for it to load.", ""]
    if name and https_ok:
        lines += [f"   https://{name}/pixel/app/?key={k}", "", "Backup link:"]
    if ip:
        lines.append(f"   http://{ip}:{D.get('port', 7777)}/pixel/app/?key={k}")
    else:
        lines.append("   (Tailscale isn't signed in on this PC yet - no friends link.)")
    lines += ["", "Kick everybody out: delete %LOCALAPPDATA%\\FreedomOS\\pixelshop\\crew_key.txt and restart FreedomOS."]
    try:
        (_work() / "Pixel Shop friends link.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
