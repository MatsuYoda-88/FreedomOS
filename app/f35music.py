"""WiMix 🎧 - your own YouTube Music app, part of FreedomOS.

The real YouTube Music runs in its own app window (Edge, its own profile, so you sign in ONCE and it's
your library, likes, playlists and Premium). FreedomOS drives it through Edge's built-in remote control
(a private door on this PC only, port 9343 by default):
  - now playing (song, artist, cover, time) shows up in FreedomOS
  - play/pause, next, back, like from FreedomOS, the tray icon, or your keyboard's media keys
  - mini player: shrinks to a tiny always-on-top bar
  - shop look: FreedomOS's dark colours instead of YouTube's
We only press YouTube Music's own buttons - nothing's downloaded, nothing's taken around YouTube.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, web

IS_WIN = sys.platform == "win32"
PORT = 9343      # the app's private remote-control door (config.json "devtools_port")
try:
    import json as _json
    PORT = int(_json.loads((Path(__file__).resolve().parent / "config.json").read_text(encoding="utf-8")).get("devtools_port", 9343))
except Exception:
    pass
URL = "https://music.youtube.com/"
HERE = Path(__file__).resolve().parent


def _home():
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "F35 Music"      # NOT in the Claude folder - your login never syncs anywhere


SETTINGS = _home() / "settings.json"
S = {"look": True, "mini": False, "video": True, "karaoke": False, "wall": ""}
LYR = {"key": "", "lines": [], "plain": "", "synced": False, "dur": 0}     # 🎤 lyrics for what's playing now
on_song = None        # optional hook: called with (title, artist) when a new song starts
STATE = {"running": False, "title": "", "artist": "", "art": "", "playing": False, "t": 0, "d": 0, "liked": False}
_hub = None
_log = print
_tray = None
_ws = None            # live remote-control line into the YouTube Music window
_ws_lock = asyncio.Lock()
_msg_id = 0
_session = None
_native = False       # True = music lives in a FreedomOS app tab (not its own Edge window)

# ---------------------------------------------------------------- the shop look + mini player (CSS we drop on the page)
LOOK_CSS = """
html, body, ytmusic-app, ytmusic-app-layout, #layout, ytmusic-browse-response, ytmusic-section-list-renderer,
#guide-wrapper, #mini-guide-background, ytmusic-guide-renderer, #guide-content, ytmusic-tabbed-search-results-renderer,
ytmusic-search-page, ytmusic-player-page, #player-page, #main-panel, #side-panel, ytmusic-queue
  { background: #12161f !important; --ytmusic-general-background-a: #12161f !important; --ytmusic-general-background-b: #12161f !important;
    --ytmusic-general-background-c: #171d29 !important; --ytmusic-brand-background-solid: #12161f !important; }
ytmusic-nav-bar, #nav-bar-background, ytmusic-player-bar { background: #1b2130 !important; border-color: #2a3245 !important; }
ytmusic-player-bar { border-top: 2px solid #4b8fe8 !important; }
#progress-bar, tp-yt-paper-slider { --paper-slider-active-color: #4b8fe8 !important; --paper-slider-knob-color: #4b8fe8 !important;
  --paper-slider-secondary-color: #2a3245 !important; }
ytmusic-chip-cloud-chip-renderer[is-selected] a, .ytmusic-chip-cloud-chip-renderer[chip-style="STYLE_PRIMARY"] { background: #4b8fe8 !important; }
::-webkit-scrollbar { width: 10px } ::-webkit-scrollbar-thumb { background: #2a3245; border-radius: 6px }
"""
MINI_CSS = """
ytmusic-nav-bar, #nav-bar-background, #guide-wrapper, #mini-guide, ytmusic-guide-renderer, #content, #player-page,
ytmusic-app-layout > #content, #side-panel, #main-panel { display: none !important; }
ytmusic-player-bar { position: fixed !important; top: 0 !important; left: 0 !important; right: 0 !important; bottom: auto !important;
  width: 100vw !important; height: 72px !important; z-index: 9999 !important; }
body { overflow: hidden !important; }
"""
STYLE_JS = """(css, id) => { let s = document.getElementById(id); if (!css) { if (s) s.remove(); return; }
  if (!s) { s = document.createElement('style'); s.id = id; (document.head || document.documentElement).appendChild(s); } s.textContent = css; }"""
SNAP_JS = """(() => { const m = navigator.mediaSession && navigator.mediaSession.metadata, v = document.querySelector('video');
  const art = m && m.artwork && m.artwork.length ? m.artwork[m.artwork.length - 1].src : '';
  const lb = document.querySelector('ytmusic-like-button-renderer');
  return JSON.stringify({ title: (m && m.title) || '', artist: (m && m.artist) || '', art, playing: !!(v && !v.paused),
    t: v ? Math.round((v.currentTime || 0) * 10) / 10 : 0, d: v && isFinite(v.duration) ? Math.floor(v.duration) : 0,
    liked: !!(lb && lb.getAttribute('like-status') === 'LIKE') }); })()"""
# 🎬 a song with a music video? flip YouTube Music to Video and open the big player
VIDEO_JS = """(() => { let did = '';
  const t = document.querySelector('ytmusic-av-toggle');
  if (t && !t.hidden && getComputedStyle(t).display !== 'none') {
    const v = [...t.querySelectorAll('button, .video-button, [role=button]')].find(b => /video/i.test((b.className || '') + ' ' + (b.textContent || '')));
    if (v && !v.hasAttribute('active') && v.getAttribute('aria-pressed') !== 'true') { v.click(); did += 'video '; } }
  const lay = document.querySelector('ytmusic-app-layout');
  if (lay && !lay.hasAttribute('player-page-open')) { const b = document.querySelector('ytmusic-player-bar .toggle-player-page-button, .toggle-player-page-button'); if (b) { b.click(); did += 'big'; } }
  return did; })()"""
# 🖼 your web.walls behind WiMix, with see-through panels
WALL_CSS = """
/* f35wall-on */ html { background: #000 !important; }
body, ytmusic-app, ytmusic-app-layout, #layout, ytmusic-browse-response, ytmusic-section-list-renderer, ytmusic-search-page,
ytmusic-tabbed-search-results-renderer, #contents, #content, ytmusic-player-page, #player-page, #main-panel, #side-panel, ytmusic-queue,
#guide-wrapper, #mini-guide-background, ytmusic-guide-renderer, #guide-content, #nav-bar-background
  { background: transparent !important; --ytmusic-general-background-a: transparent !important; --ytmusic-general-background-b: transparent !important;
    --ytmusic-general-background-c: rgba(18,22,31,.35) !important; --ytmusic-brand-background-solid: transparent !important; }
ytmusic-nav-bar, ytmusic-player-bar { background: rgba(18,22,31,.55) !important; backdrop-filter: blur(8px); }
#side-panel, #guide-wrapper { background: rgba(18,22,31,.35) !important; backdrop-filter: blur(6px); }
"""
WALL_JS = """((url) => { let f = document.getElementById('f35wall');
  if (!url) { if (f) f.remove(); return 'off'; }
  if (!f) { f = document.createElement('iframe'); f.id = 'f35wall'; f.setAttribute('aria-hidden', 'true'); f.tabIndex = -1;
    f.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;border:0;z-index:-1;pointer-events:none;background:#000';
    document.documentElement.appendChild(f); }
  if (f.src !== url) f.src = url;
  try { localStorage.setItem('f35wallurl', url); } catch (e) {}
  return 'on'; })"""


try:
    _APP_PORT = int(_json.loads((HERE / "config.json").read_text(encoding="utf-8")).get("port", 7777))
except Exception:
    _APP_PORT = 7777


def wall_url():
    w = S.get("wall") or ""
    if not w or w == "off":
        return ""
    return f"http://127.0.0.1:{_APP_PORT}/widget/walls/{w}.html"


async def lyrics_for(title, artist, dur):
    """🎤 free synced lyrics from LRCLIB (open lyrics library - no account, no keys)."""
    key = f"{title}|{artist}"
    if LYR["key"] == key:
        return
    LYR.update(key=key, lines=[], plain="", synced=False, dur=0)
    try:
        import re
        q = {"track_name": title, "artist_name": artist}
        if dur:
            q["duration"] = str(int(dur))
        async with _session.get("https://lrclib.net/api/get", params=q, headers={"User-Agent": "WiMix (FreedomOS)"}, timeout=ClientTimeout(total=8)) as r:
            d = await r.json() if r.status == 200 else None
        if not d:
            async with _session.get("https://lrclib.net/api/search", params={"q": f"{artist} {title}"}, headers={"User-Agent": "WiMix (FreedomOS)"},
                                    timeout=ClientTimeout(total=8)) as r:
                arr = await r.json() if r.status == 200 else []
            d = next((x for x in arr if x.get("syncedLyrics")), arr[0] if arr else None)
        if not d or LYR["key"] != key:
            return
        lines = []
        for ln in (d.get("syncedLyrics") or "").splitlines():
            m = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)", ln)
            if m:
                lines.append([round(int(m.group(1)) * 60 + float(m.group(2)), 2), m.group(3)])
        LYR.update(lines=lines, plain=d.get("plainLyrics") or "", synced=bool(lines), dur=d.get("duration") or 0)
    except Exception as e:
        _log(f"(🎤 no lyrics: {e})")
    if _hub:
        _hub.send({"type": "lyrics", "lyrics": LYR})


async def _new_song(d):
    asyncio.get_running_loop().create_task(lyrics_for(d.get("title", ""), d.get("artist", ""), d.get("d", 0)))
    if on_song:
        try:
            on_song(d.get("title", ""), d.get("artist", ""))
        except Exception:
            pass
    if S.get("video"):
        await asyncio.sleep(2)
        try:
            await _eval(VIDEO_JS)
        except Exception:
            pass


CTL_JS = {   # press YouTube Music's own buttons (fall back to the video itself if the layout ever changes)
    "play": """(() => { const b = document.querySelector('ytmusic-player-bar #play-pause-button'); if (b) { b.click(); return 1; }
      const v = document.querySelector('video'); if (v) { v.paused ? v.play() : v.pause(); return 2; } return 0; })()""",
    "next": """(() => { const b = document.querySelector('ytmusic-player-bar .next-button'); if (b) { b.click(); return 1; } return 0; })()""",
    "prev": """(() => { const b = document.querySelector('ytmusic-player-bar .previous-button'); if (b) { b.click(); return 1; } return 0; })()""",
    "like": """(() => { const b = document.querySelector('ytmusic-like-button-renderer #button-shape-like button, ytmusic-like-button-renderer .like');
      if (b) { b.click(); return 1; } return 0; })()""",
}


def _load():
    try:
        S.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
    except Exception:
        pass


def _save():
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(S), encoding="utf-8")
    except Exception:
        pass


def edge_exe():
    for c in (shutil.which("msedge"), r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if c and Path(c).exists():
            return c
    return shutil.which("chromium") or shutil.which("google-chrome")


def public():
    return dict(STATE, look=S["look"], mini=S["mini"], video=S["video"], karaoke=S["karaoke"])


def push():
    if _hub:
        _hub.send({"type": "music", "music": public()})


# ---------------------------------------------------------------- remote control line (Chrome DevTools Protocol)
async def _targets():
    async with _session.get(f"http://127.0.0.1:{PORT}/json", timeout=ClientTimeout(total=2)) as r:
        return await r.json()


async def _connect():
    global _ws
    if _ws is not None and not _ws.closed:
        return True
    try:
        pages = [t for t in await _targets() if t.get("type") == "page" and "music.youtube.com" in t.get("url", "")]
        if not pages:
            return False
        _ws = await _session.ws_connect(pages[0]["webSocketDebuggerUrl"], max_msg_size=0, timeout=5)
        await _call("Page.enable")
        # shop look + mini player survive page reloads
        await _call("Page.addScriptToEvaluateOnNewDocument", source="""document.addEventListener('DOMContentLoaded', () => {
          try { const c = localStorage.getItem('f35css'); if (c) { const s = document.createElement('style'); s.id = 'f35look'; s.textContent = c; document.head.appendChild(s); } } catch (e) {}
          try { const u = localStorage.getItem('f35wallurl'); if (u && (localStorage.getItem('f35css') || '').includes('f35wall-on')) { const f = document.createElement('iframe'); f.id = 'f35wall'; f.tabIndex = -1;
            f.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;border:0;z-index:-1;pointer-events:none;background:#000'; f.src = u; document.documentElement.appendChild(f); } } catch (e) {} });""")
        await apply_style()
        return True
    except Exception:
        _ws = None
        return False


async def _call(method, **params):
    global _msg_id
    async with _ws_lock:
        _msg_id += 1
        mid = _msg_id
        await _ws.send_json({"id": mid, "method": method, "params": params})
        while True:
            m = await asyncio.wait_for(_ws.receive(), 5)
            if m.type != 1:                       # not text = the window closed
                raise ConnectionError("music window closed")
            d = json.loads(m.data)
            if d.get("id") == mid:
                return d.get("result", {})


async def _eval(js, gesture=False):
    r = await _call("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True, userGesture=gesture)
    return (r.get("result") or {}).get("value")


async def apply_style():
    url = wall_url() if S["look"] else ""
    mini = S["mini"] and not in_app()                     # mini player is only for the old separate window
    css = (LOOK_CSS if S["look"] else "") + (WALL_CSS if url else "") + (MINI_CSS if mini else "")
    await _eval(f"({STYLE_JS})({json.dumps(css)}, 'f35look')")
    await _eval(f"({WALL_JS})({json.dumps(url)})")
    await _eval(f"try {{ localStorage.setItem('f35css', {json.dumps(css)}) }} catch (e) {{}}")


# ---------------------------------------------------------------- the window
def _hwnd():
    if not IS_WIN:
        return None
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    found = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _):
        if u.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(256)
            u.GetWindowTextW(h, buf, 256)
            cls = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(h, cls, 64)
            if "YouTube Music" in buf.value and cls.value.startswith("Chrome_WidgetWin"):
                found.append(h)
        return True
    u.EnumWindows(proc(cb), 0)
    return found[0] if found else None


_big = {}


def _mini_window(on):
    """Mini player: tiny always-on-top bar (top right). Off: back where it was."""
    h = _hwnd()
    if not h:
        return
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    r = wintypes.RECT()
    u.GetWindowRect(h, ctypes.byref(r))
    if on:
        if u.IsZoomed(h):
            u.ShowWindow(h, 9)
        _big["r"] = (r.left, r.top, r.right - r.left, r.bottom - r.top)
        sw = u.GetSystemMetrics(0)
        u.SetWindowPos(h, -1, sw - 640, 40, 620, 112, 0x0040)                 # HWND_TOPMOST, SHOWWINDOW
    else:
        x, y, w, hh = _big.pop("r", (120, 80, 1100, 760))
        u.SetWindowPos(h, -2, x, y, w, hh, 0x0040)                           # HWND_NOTOPMOST


def _focus():
    h = _hwnd()
    if h and IS_WIN:
        import ctypes
        u = ctypes.windll.user32
        if u.IsIconic(h):
            u.ShowWindow(h, 9)
        u.SetForegroundWindow(h)


async def running():
    try:
        async with _session.get(f"http://127.0.0.1:{PORT}/json/version", timeout=ClientTimeout(total=1.5)) as r:
            return r.status == 200
    except Exception:
        return False


def in_app():
    """WiMix lives in a FreedomOS app tab (not its own Edge window)?"""
    if _native:
        return True
    try:
        import f35web
        return bool(IS_WIN and f35web.f35_browser_exe())
    except Exception:
        return False


def _app_tab(what):
    try:
        import f35web
        return f35web.open_app_tab(what)
    except Exception:
        return False


PLAY_STATE_JS = """(() => { const v = document.querySelector('video');
  if (v && !v.paused) return 'playing';
  if (v && v.src && v.readyState > 0) { const b = document.querySelector('ytmusic-player-bar #play-pause-button'); if (b) b.click(); else v.play(); return 'resumed'; }
  return document.readyState === 'complete' && document.querySelector('ytmusic-app') ? 'empty' : 'loading'; })()"""
# nothing queued up? put on your Supermix (or your Liked songs if it's not on the home page)
PICK_JS = """(() => { const a = [...document.querySelectorAll('a[href*="list="]')].find(x => /supermix/i.test((x.textContent || '') + ' ' + (x.getAttribute('title') || '')));
  let id = 'LM'; if (a) { try { id = new URL(a.getAttribute('href'), location.href).searchParams.get('list') || 'LM'; } catch (e) {} }
  location.href = 'https://music.youtube.com/watch?list=' + id; return id === 'LM' ? 'liked' : 'supermix'; })()"""


async def start_music():
    """🎧 button: WiMix opens tucked away, the music starts, and FreedomOS's controls take over."""
    global _native
    if not (IS_WIN and _app_tab("music-bg")):
        return await open_app()
    _native = True
    for _ in range(40):
        await asyncio.sleep(.5)
        if await _connect():
            break
    else:
        return {"ok": False, "error": "WiMix didn't open"}
    tray_start()
    picked = False
    for _ in range(30):                                   # ~15 sec to get something playing
        try:
            st = await _eval(PLAY_STATE_JS, gesture=True)
        except Exception:
            st = "loading"
        if st in ("playing", "resumed"):
            await asyncio.sleep(1)
            if await _eval(PLAY_STATE_JS, gesture=True) == "playing":
                break
        elif st == "empty" and not picked:
            await asyncio.sleep(2)                        # let the home page fill in first
            r = await _eval(PICK_JS)
            _log(f"🎧 WiMix: nothing queued - putting on your {r}")
            picked = True
        await asyncio.sleep(.5)
    _app_tab("tuck:music")                                # playing - tuck WiMix away, FreedomOS's controls take over
    await poll_once()
    return {"ok": True, "music": public()}


async def open_app():
    global _native
    if IS_WIN and _app_tab("music"):          # FreedomOS app: YouTube Music is a 🎧 tab (▁ tucks it back into the toolbar)
        _native = True
        for _ in range(40):
            await asyncio.sleep(.5)
            if await _connect():
                break
        tray_start()
        return {"ok": True, "tab": True}
    if await running():
        await asyncio.to_thread(_focus)
        return {"ok": True, "already": True}
    exe = edge_exe()
    if not exe:
        return {"ok": False, "error": "Edge isn't on this PC"}
    prof = _home() / "profile"
    prof.mkdir(parents=True, exist_ok=True)
    args = [exe, f"--user-data-dir={prof}", f"--remote-debugging-port={PORT}", "--remote-debugging-address=127.0.0.1",
            "--no-first-run", "--no-default-browser-check", f"--app={URL}", "--window-size=1100,760"]
    kw = {"creationflags": 0x00000008 | 0x00000200} if IS_WIN else {"start_new_session": True}   # detached: closing FreedomOS doesn't kill your music
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    _log("🎧 WiMix opened (sign in once - it remembers)")
    for _ in range(40):
        await asyncio.sleep(.5)
        if await _connect():
            break
    tray_start()
    return {"ok": True}


async def control(what):
    if what == "open":
        return await open_app()
    if what == "start":
        return await start_music()
    if not await _connect():
        return {"ok": False, "error": "WiMix isn't open"}
    if what in CTL_JS:
        await _eval(CTL_JS[what])
    elif what in ("video", "karaoke"):
        S[what] = not S[what]; _save(); push()
        if what == "video" and S["video"]:
            await _eval(VIDEO_JS)
    elif what == "look":
        S["look"] = not S["look"]; _save(); await apply_style()
    elif what == "mini" and in_app():
        _app_tab("music")                                   # in the app: "mini" = just the corner card, so tuck/show the tab
    elif what == "mini":
        S["mini"] = not S["mini"]; _save(); await apply_style()
        await asyncio.to_thread(_mini_window, S["mini"])
    elif what == "show" and _native:
        _app_tab("music")
    elif what == "show":
        if S["mini"]:
            S["mini"] = False; _save(); await apply_style(); await asyncio.to_thread(_mini_window, False)
        await asyncio.to_thread(_focus)
    elif what == "quit" and _native:
        _app_tab("close:music")
        global _ws
        _ws = None
    elif what == "quit":
        try:
            async with _session.get(f"http://127.0.0.1:{PORT}/json/version", timeout=ClientTimeout(total=2)) as r:
                wsurl = (await r.json())["webSocketDebuggerUrl"]
            async with _session.ws_connect(wsurl, timeout=5) as bw:
                await bw.send_json({"id": 1, "method": "Browser.close"})
        except Exception:
            pass
    await asyncio.sleep(.25)
    await poll_once()
    return {"ok": True, "music": public()}


async def poll_once():
    global _ws
    up = await running()
    if up and await _connect():
        try:
            d = json.loads(await _eval(SNAP_JS) or "{}")
            changed = any(STATE.get(k) != d.get(k) for k in ("title", "artist", "playing", "liked")) or not STATE["running"] \
                or abs(STATE.get("t", 0) - d.get("t", 0)) > 4
            if d.get("title") and (d.get("title"), d.get("artist")) != (STATE.get("title"), STATE.get("artist")):
                asyncio.get_running_loop().create_task(_new_song(d))
            STATE.update(d, running=True)
            if S["mini"] and in_app():                     # stuck in mini mode inside the app? clear it
                S["mini"] = False; _save(); await apply_style(); changed = True
            if not _tray:
                tray_start()
            if changed:
                push(); tray_refresh()
            return
        except Exception:
            _ws = None
    if STATE["running"]:
        STATE.update(running=False, title="", artist="", art="", playing=False, t=0, d=0)
        push(); tray_stop()


async def loop():
    global _session
    _load()
    _session = ClientSession()
    while True:
        try:
            await poll_once()
        except Exception as e:
            _log(f"(WiMix hiccup: {e})")
        await asyncio.sleep(2 if STATE["running"] else 6)


# ---------------------------------------------------------------- tray icon (only while the music app is open)
_loop_ref = None


def tray_start():
    global _tray
    if _tray or not IS_WIN:
        return
    try:
        import pystray
        from pystray import MenuItem as I, Menu
        from PIL import Image, ImageDraw
    except Exception:
        return
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.ellipse((2, 2, 62, 62), fill=(75, 143, 232)); d.rectangle((24, 14, 30, 44), fill="white"); d.rectangle((24, 14, 46, 20), fill="white")
    d.rectangle((40, 14, 46, 38), fill="white"); d.ellipse((14, 38, 30, 52), fill="white"); d.ellipse((30, 32, 46, 46), fill="white")
    loop = asyncio.get_running_loop()
    go = lambda w: (lambda *_: asyncio.run_coroutine_threadsafe(control(w), loop))
    np = lambda _: (f"{'▶' if STATE['playing'] else '⏸'} {STATE['title'][:40]} - {STATE['artist'][:30]}" if STATE["title"] else "WiMix")
    menu = Menu(I(np, None, enabled=False), Menu.SEPARATOR,
                I("⏯ Play / Pause", go("play"), default=True), I("⏭ Next", go("next")), I("⏮ Back", go("prev")), I("👍 Like", go("like")),
                Menu.SEPARATOR, I(lambda _: "Big player" if S["mini"] else "Mini player", go("mini")), I("Show WiMix", go("show")),
                I("Close WiMix", go("quit")))
    _tray = pystray.Icon("WiMix", im, "WiMix", menu)
    threading.Thread(target=_tray.run, daemon=True).start()


def tray_refresh():
    if _tray:
        try:
            _tray.title = (f"WiMix - {STATE['title']} - {STATE['artist']}" if STATE["title"] else "WiMix")[:127]
            _tray.update_menu()
        except Exception:
            pass


def tray_stop():
    global _tray
    if _tray:
        try:
            _tray.stop()
        except Exception:
            pass
        _tray = None


# ---------------------------------------------------------------- FreedomOS hooks
def init(hub, log):
    global _hub, _log
    _hub, _log = hub, log


async def h_ctl(request):
    if request.remote not in ("127.0.0.1", "::1") or any(h in request.headers for h in ("X-Forwarded-For", "Tailscale-User-Login")):
        pass                                     # phone / work laptop can still play/pause/skip the PC's music
    try:
        d = await request.json()
    except Exception:
        d = {}
    what = str(d.get("do", ""))
    if what not in ("open", "play", "next", "prev", "like", "look", "mini", "show", "quit", "video", "karaoke", "start"):
        return web.json_response({"ok": False}, status=400)
    if what == "open" and request.remote not in ("127.0.0.1", "::1"):
        return web.json_response({"ok": False, "where": "phone"})
    return web.json_response(await control(what))


async def h_state(request):
    return web.json_response(public())


def routes(app):
    app.add_routes([web.post("/music/ctl", h_ctl), web.get("/music/state", h_state), web.get("/music/lyrics", h_lyrics), web.post("/music/wall", h_wall), web.get("/music/wall", h_wall_get)])


async def h_lyrics(request):
    return web.json_response(LYR)


async def h_wall_get(request):
    return web.json_response({"wall": S.get("wall", ""), "url": wall_url()})


async def h_wall(request):
    """the page tells us which wallpaper you picked - WiMix plays it behind the music"""
    try:
        w = str((await request.json()).get("wall", ""))[:60]
    except Exception:
        w = ""
    if w != S.get("wall"):
        S["wall"] = w; _save()
        try:
            if await _connect():
                await apply_style()
        except Exception:
            pass
    return web.json_response({"ok": True})
