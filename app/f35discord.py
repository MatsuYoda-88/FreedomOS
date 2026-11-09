"""👾 Discord overlay brains - part of FreedomOS.

Reads the Discord tab that lives inside FreedomOS (through the app's private remote-control door, port 9333, this PC only):
who's in voice + who's talking, your mute/deafen, the latest messages. Presses Discord's own buttons for you
(mute, deafen, leave), drops the WiMix song into the chat, and - if the Discord desktop app is running and you've
made a Discord "application" - shows "Playing FreedomOS" on your profile.
"""
import asyncio
import json
import os
import struct
import sys
import time
import uuid

from aiohttp import ClientSession, ClientTimeout, web

IS_WIN = sys.platform == "win32"
PORT = 9333
STATE = {"open": False, "connected": False, "voice": None, "users": [], "mute": False, "deaf": False, "msgs": [], "channel": ""}
on_join = None          # optional hook: called with a name when someone joins your voice channel
_hub = None
_log = print
_cfg = {}
_ws = None
_session = None
_lock = asyncio.Lock()
_mid = 0

SNAP_JS = r"""(() => {
  const q = (s, r = document) => r.querySelector(s), qa = (s, r = document) => [...r.querySelectorAll(s)];
  const btn = l => q(`button[aria-label="${l}"]`) || q(`[role="switch"][aria-label="${l}"]`);
  const on = b => b && (b.getAttribute('aria-checked') === 'true' || b.getAttribute('aria-pressed') === 'true');
  const mute = !!btn('Unmute') || on(btn('Mute'));
  const deaf = !!btn('Undeafen') || on(btn('Deafen'));
  const connected = !!btn('Disconnect');
  let voice = null;
  if (connected) { const a = qa('section[class*="panels"] a, [class*="panels"] a').find(x => (x.textContent || '').trim()); voice = a ? a.textContent.trim() : 'Voice'; }
  const users = qa('[class*="voiceUser"]').map(u => {
    const n = q('[class*="usernameFont"], [class*="username"], [class*="name"]', u);
    const img = q('img', u); const sp = !!q('[class*="avatarSpeaking"], [class*="speaking"]', u) || /speaking/i.test(u.className || '');
    return { name: n ? n.textContent.trim() : '', av: img ? img.src : '', talk: sp }; }).filter(u => u.name).slice(0, 14);
  const msgs = qa('li[id^="chat-messages-"]').slice(-6).map(li => {
    const who = q('[id^="message-username-"]', li), txt = q('[id^="message-content-"]', li);
    return { id: li.id, who: who ? who.textContent.trim() : '', text: txt ? txt.textContent.trim().slice(0, 220) : '' }; }).filter(m => m.text);
  const h = q('section[aria-label*="hannel header"] h1, section[aria-label*="hannel header"] h2, [class*="titleWrapper"] h1');
  return JSON.stringify({ connected, voice, users, mute, deaf, msgs, channel: (h ? h.textContent : '').trim().slice(0, 60) }); })()"""


def init(hub, log, cfg):
    global _hub, _log, _cfg
    _hub, _log, _cfg = hub, log, cfg


async def _targets():
    async with _session.get(f"http://127.0.0.1:{PORT}/json", timeout=ClientTimeout(total=2)) as r:
        return await r.json()


async def _connect():
    global _ws
    if _ws is not None and not _ws.closed:
        return True
    try:
        pages = [t for t in await _targets() if t.get("type") == "page" and "discord.com" in t.get("url", "")]
        if not pages:
            return False
        _ws = await _session.ws_connect(pages[0]["webSocketDebuggerUrl"], max_msg_size=0, timeout=5)
        return True
    except Exception:
        _ws = None
        return False


async def _call(method, **params):
    global _mid
    async with _lock:
        _mid += 1
        mid = _mid
        await _ws.send_json({"id": mid, "method": method, "params": params})
        while True:
            m = await asyncio.wait_for(_ws.receive(), 5)
            if m.type != 1:
                raise ConnectionError("discord tab closed")
            d = json.loads(m.data)
            if d.get("id") == mid:
                return d.get("result", {})


async def _eval(js):
    r = await _call("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)
    return (r.get("result") or {}).get("value")


async def poll_once():
    global _ws
    if not await _connect():
        if STATE["open"]:
            STATE.update(open=False, connected=False, users=[], msgs=[])
        return
    try:
        d = json.loads(await _eval(SNAP_JS) or "{}")
    except Exception:
        _ws = None
        return
    before = {u["name"] for u in STATE["users"]}
    first = not STATE["open"]
    STATE.update(d, open=True)
    if not first and on_join:
        for u in d.get("users", []):
            if u["name"] not in before:
                try:
                    on_join(u["name"])
                except Exception:
                    pass


async def control(what, text=""):
    if not await _connect():
        return {"ok": False, "error": "Discord isn't open"}
    labels = {"mute": ("Mute", "Unmute"), "deaf": ("Deafen", "Undeafen"), "leave": ("Disconnect",)}
    if what in labels:
        js = "(() => { for (const l of %s) { const b = document.querySelector(`button[aria-label=\"${l}\"]`); if (b) { b.click(); return l; } } return ''; })()" % json.dumps(labels[what])
        r = await _eval(js)
        await asyncio.sleep(.3)
        await poll_once()
        return {"ok": bool(r), "state": STATE}
    if what == "share" and text:
        ok = await _eval("""(() => { const t = document.querySelector('[role="textbox"][contenteditable="true"]'); if (!t) return false; t.focus(); return true; })()""")
        if not ok:
            return {"ok": False, "error": "open a channel in Discord first"}
        await _call("Input.insertText", text=text)
        await _call("Input.dispatchKeyEvent", type="keyDown", key="Enter", code="Enter", windowsVirtualKeyCode=13, nativeVirtualKeyCode=13, text="\r")
        await _call("Input.dispatchKeyEvent", type="keyUp", key="Enter", code="Enter", windowsVirtualKeyCode=13, nativeVirtualKeyCode=13)
        return {"ok": True}
    return {"ok": False}


# ---------------------------------------------------------------- 👀 "Playing FreedomOS" on your Discord profile
# Needs the Discord DESKTOP app running + a Discord "application" id in config.json ("discord_app_id").
_rpc = {"pipe": None, "start": int(time.time()), "warned": False, "last": ""}


def _rpc_send(op, payload):
    data = json.dumps(payload).encode()
    _rpc["pipe"].write(struct.pack("<II", op, len(data)) + data)
    _rpc["pipe"].flush()
    hdr = _rpc["pipe"].read(8)
    _, n = struct.unpack("<II", hdr)
    return json.loads(_rpc["pipe"].read(n) or b"{}")


def _presence(details, state):
    app = str(_cfg.get("discord_app_id") or "").strip()
    if not IS_WIN or not app:
        return
    try:
        if _rpc["pipe"] is None:
            for i in range(10):
                try:
                    _rpc["pipe"] = open(rf"\\.\pipe\discord-ipc-{i}", "r+b", buffering=0)
                    break
                except OSError:
                    continue
            if _rpc["pipe"] is None:
                return
            _rpc_send(0, {"v": 1, "client_id": app})
            _log("👀 Discord status: Playing FreedomOS")
        key = details + "|" + state
        if key == _rpc["last"]:
            return
        _rpc["last"] = key
        _rpc_send(1, {"cmd": "SET_ACTIVITY", "nonce": str(uuid.uuid4()), "args": {"pid": os.getpid(), "activity": {
            "details": details[:120], "state": state[:120], "timestamps": {"start": _rpc["start"]},
            "assets": {"large_text": "FreedomOS"}}}})
    except Exception:
        try:
            _rpc["pipe"].close()
        except Exception:
            pass
        _rpc.update(pipe=None, last="")


async def loop():
    global _session
    _session = ClientSession()
    n = 0
    while True:
        try:
            await poll_once()
        except Exception as e:
            _log(f"(Discord overlay hiccup: {e})")
        n += 1
        if n % 10 == 0:                       # every ~15 sec: keep the "Playing FreedomOS" status fresh
            try:
                import f35music
                m = f35music.STATE
                det = "🎧 " + (m.get("title") or "") + (" - " + m["artist"] if m.get("artist") else "") if m.get("playing") and m.get("title") else "On the desktop"
                await asyncio.to_thread(_presence, det, "FreedomOS desktop")
            except Exception:
                pass
        await asyncio.sleep(1.5 if STATE["open"] else 5)


async def h_state(request):
    return web.json_response(STATE)


async def h_ctl(request):
    try:
        d = await request.json()
    except Exception:
        d = {}
    what = str(d.get("do", ""))
    text = str(d.get("text", ""))[:300]
    if what == "share" and not text:
        try:
            import f35music
            m = f35music.STATE
            if m.get("title"):
                text = f"🎧 Now playing: {m['title']}" + (f" - {m['artist']}" if m.get("artist") else "")
        except Exception:
            pass
    return web.json_response(await control(what, text))


def routes(app):
    app.add_routes([web.get("/discord/state", h_state), web.post("/discord/ctl", h_ctl)])
