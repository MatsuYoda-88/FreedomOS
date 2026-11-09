"""FreedomOS -> Claude chat line.

Runs Claude Code in the background on this PC with your normal Claude login (your plan, no API bill).
Each chat in the 💬 window is its own Claude Code session (resumed every message, so Claude remembers it).
Pictures from your phone/laptop camera get saved in 'FreedomOS\\claude pics' and Claude looks at them.
Chats are saved in memory/claude_chats.json; 📌 pinned ones stay at the top.
"""
import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pixlite   # documents() = the real Documents folder (handles OneDrive)

from aiohttp import web

IS_WIN = sys.platform == "win32"
HERE = Path(__file__).resolve().parent
CHAT_FILE = HERE / "memory" / "claude_chats.json"
PIC_DIR = HERE / "claude pics"
WORK_DIR = (pixlite.documents() / "FreedomOS")   # your FreedomOS work folder (Documents\\FreedomOS)
try:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass
MAX_PIC = 12 * 1024 * 1024

SYSTEM_ADD = ("[Setup note for Claude, not from the user: You're talking to the user through the chat window inside FreedomOS, "
              "their local AI crew app, on their PC or their phone. Use plain words for anything technical. Keep answers short enough to read "
              "on a phone unless they ask for more. When they send a picture, its file path is in the message - open it and look. "
              "Your working folder is their FreedomOS work folder (Documents\\FreedomOS).]")

_hub = None
_log = print
chats = {}          # id -> chat
running = {}        # chat id -> subprocess


def init(hub, log):
    global _hub, _log
    _hub, _log = hub, log
    load()


def load():
    global chats
    try:
        data = json.loads(CHAT_FILE.read_text(encoding="utf-8"))
        chats = {c["id"]: c for c in data.get("chats", [])}
    except Exception:
        chats = {}
    for c in chats.values():
        c["busy"] = False


def save():
    try:
        CHAT_FILE.parent.mkdir(exist_ok=True)
        keep = [dict(c, busy=False) for c in chats.values()]
        tmp = CHAT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"chats": keep}, indent=1), encoding="utf-8")
        tmp.replace(CHAT_FILE)
    except Exception as e:
        _log(f"(couldn't save the Claude chats: {e})")


def find_claude():
    """Where's Claude Code on this PC?"""
    home = Path.home()
    spots = [shutil.which("claude"),
             str(home / ".local" / "bin" / ("claude.exe" if IS_WIN else "claude")),
             str(Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd") if IS_WIN else None,
             str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "claude" / "claude.exe") if IS_WIN else None]
    for p in spots:
        if p and Path(p).exists():
            return p
    return None


def listing():
    rows = sorted(chats.values(), key=lambda c: (not c.get("pinned"), -c.get("updated", 0)))
    return [{"id": c["id"], "title": c.get("title", "New chat"), "pinned": bool(c.get("pinned")), "busy": bool(c.get("busy")),
             "updated": c.get("updated", 0), "n": len(c.get("msgs", []))} for c in rows]


def public():
    return {"chats": listing(), "installed": bool(find_claude())}


def send(ev):
    if _hub:
        _hub.send(ev)


def new_chat(title="New chat"):
    cid = uuid.uuid4().hex[:10]
    chats[cid] = {"id": cid, "title": title, "session": None, "pinned": False, "created": time.time(), "updated": time.time(), "msgs": []}
    return chats[cid]


def save_pic(data_url):
    m = re.match(r"data:image/(png|jpe?g|webp|gif);base64,(.+)$", data_url or "", re.S)
    if not m:
        return None
    raw = base64.b64decode(m.group(2))
    if len(raw) > MAX_PIC:
        return None
    PIC_DIR.mkdir(exist_ok=True)
    ext = "jpg" if m.group(1).startswith("jp") else m.group(1)
    f = PIC_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}.{ext}"
    f.write_bytes(raw)
    return f


def _tool_note(block):
    name = block.get("name", "")
    inp = block.get("input") or {}
    what = inp.get("file_path") or inp.get("command") or inp.get("query") or inp.get("url") or inp.get("pattern") or ""
    if "claude pics" in str(what):
        return "📷 looking at your picture..."
    return f"🔧 {name} {str(what)[:70]}".strip()


async def run_turn(chat, text, pic):
    exe = find_claude()
    reply = {"role": "claude", "text": "", "tools": [], "t": time.time()}
    chat["msgs"].append(reply)
    if not exe:
        reply["text"] = ("Can't find Claude Code on this PC. Run 'FreedomOS Setup' from the Start menu (it installs it), "
                         "or install it from claude.com/claude-code, then hit 🔑 Log in.")
        reply["error"] = True
        return
    prompt = text or "What do you see in this picture?"
    if pic:
        prompt += f"\n\n[Picture he just took: {pic}]"
    if not chat.get("session"):                       # first message of a chat: tell Claude where it is (kept off the command line)
        prompt = SYSTEM_ADD + "\n\n" + prompt
    args = [exe, "-p", "--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions"]
    if not getattr(run_turn, "no_partial", False):
        args.append("--include-partial-messages")      # words show up as Claude types them
    if chat.get("session"):
        args += ["--resume", chat["session"]]
    flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
    env = dict(os.environ)
    try:
        proc = await asyncio.create_subprocess_exec(*args, cwd=str(WORK_DIR), stdin=asyncio.subprocess.PIPE,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                    creationflags=flags, env=env, limit=8 * 1024 * 1024)
    except Exception as e:
        reply["text"], reply["error"] = f"Couldn't start Claude Code: {e}", True
        return
    running[chat["id"]] = proc
    proc.stdin.write(prompt.encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()
    live, last_push, final = [], 0.0, None
    try:
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("{"):
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("session_id"):
                chat["session"] = d["session_id"]
            t = d.get("type")
            if t == "stream_event":
                e = d.get("event") or {}
                if e.get("type") == "content_block_delta" and (e.get("delta") or {}).get("type") == "text_delta":
                    live.append(e["delta"]["text"])
                elif e.get("type") == "message_start" and live:
                    live.append("\n\n")
            elif t == "assistant":
                for b in (d.get("message") or {}).get("content") or []:
                    if b.get("type") == "tool_use":
                        reply["tools"].append(_tool_note(b))
            elif t == "result":
                final = d
            if time.time() - last_push > 0.3:
                last_push = time.time()
                reply["text"] = "".join(live)
                send({"type": "cc_live", "id": chat["id"], "text": reply["text"], "tools": reply["tools"][-3:]})
        await proc.wait()
    finally:
        running.pop(chat["id"], None)
    err = (await proc.stderr.read()).decode("utf-8", "replace").strip() if proc.stderr else ""
    if not final and not live and "include-partial-messages" in err and not getattr(run_turn, "no_partial", False):
        run_turn.no_partial = True                     # older Claude Code - try again without live typing
        chat["msgs"].remove(reply)
        return await run_turn(chat, text, pic)
    if final and final.get("result") and not final.get("is_error"):
        reply["text"] = final["result"]
    elif final and final.get("is_error"):
        reply["text"], reply["error"] = (final.get("result") or "Claude hit a snag.")[:2000], True
    elif not "".join(live):
        reply["text"], reply["error"] = (err[-800:] or "No answer came back.").strip(), True
    else:
        reply["text"] = "".join(live)
    if reply.get("error") and re.search(r"log ?in|/login|api key|authenticat", reply["text"], re.I):
        reply["text"] = "Claude Code isn't logged in on this PC yet. Hit 🔑 Log in at the top of the chat, sign in once, then try again."
        reply["login"] = True
    if final:
        reply["cost"] = final.get("total_cost_usd")
        reply["secs"] = round((final.get("duration_ms") or 0) / 1000, 1)


HANDS = None          # boss hands us "all hands" - the crew gathers round while Claude works


async def turn(chat, text, pic):
    if HANDS:
        HANDS("chat")
    chat["busy"] = True
    chat["updated"] = time.time()
    send({"type": "cc", "chat": chat_out(chat), "list": listing()})
    try:
        await run_turn(chat, text, str(pic) if pic else None)
    except Exception as e:
        chat["msgs"].append({"role": "claude", "text": f"Something broke: {e}", "error": True, "t": time.time()})
        _log(f"Claude chat broke: {e}")
    chat["busy"] = False
    if HANDS:
        HANDS("chat", False)
    chat["updated"] = time.time()
    save()
    send({"type": "cc", "chat": chat_out(chat), "list": listing()})


def chat_out(c):
    return {"id": c["id"], "title": c.get("title"), "pinned": bool(c.get("pinned")), "busy": bool(c.get("busy")),
            "msgs": c.get("msgs", [])[-200:]}


def same_window(request):
    """Only FreedomOS's own page may drive this (stops random websites in your browser poking a full-power Claude)."""
    o = request.headers.get("Origin")
    if o and o != "null":
        host = request.headers.get("X-Forwarded-Host") or request.host
        if o.split("://", 1)[-1] != host:
            return False
    return request.content_type == "application/json"


async def h_list(request):
    return web.json_response(public())


async def h_get(request):
    c = chats.get(request.match_info["cid"])
    if not c:
        return web.json_response({"error": "no such chat"}, status=404)
    return web.json_response(chat_out(c))


async def h_send(request):
    if not same_window(request):
        return web.json_response({"error": "nope"}, status=403)
    d = await request.json()
    text = str(d.get("text") or "").strip()[:20000]
    pic = save_pic(d.get("image")) if d.get("image") else None
    if not text and not pic:
        return web.json_response({"error": "say something first"}, status=400)
    c = chats.get(str(d.get("id") or ""))
    if not c:
        c = new_chat((text or "📷 picture")[:48])
    if c.get("busy"):
        return web.json_response({"error": "Claude's still answering the last one"}, status=409)
    msg = {"role": "you", "text": text, "t": time.time()}
    if pic:
        msg["img"] = pic.name
    c["msgs"].append(msg)
    if c.get("title") in ("New chat", "📷 picture") and text:
        c["title"] = text[:48]
    asyncio.get_running_loop().create_task(turn(c, text, pic))
    return web.json_response({"ok": True, "chat": chat_out(c), "list": listing()})


async def h_act(request):
    """pin / unpin / rename / delete / stop / new"""
    if not same_window(request):
        return web.json_response({"error": "nope"}, status=403)
    d = await request.json()
    act, c = d.get("act"), chats.get(str(d.get("id") or ""))
    if act == "new":
        c = new_chat()
        save()
        return web.json_response({"ok": True, "chat": chat_out(c), "list": listing()})
    if not c:
        return web.json_response({"error": "no such chat"}, status=404)
    if act == "pin":
        c["pinned"] = bool(d.get("on", True))
    elif act == "rename":
        c["title"] = str(d.get("title") or c["title"])[:60]
    elif act == "stop":
        p = running.get(c["id"])
        if p and p.returncode is None:
            p.kill()
    elif act == "delete":
        p = running.get(c["id"])
        if p and p.returncode is None:
            p.kill()
        chats.pop(c["id"], None)
        save()
        return web.json_response({"ok": True, "list": listing()})
    save()
    return web.json_response({"ok": True, "chat": chat_out(c), "list": listing()})


async def h_login(request):
    """Pops a window on this PC where Claude Code walks you through signing in (only works sitting at the PC)."""
    if not same_window(request):
        return web.json_response({"error": "nope"}, status=403)
    exe = find_claude()
    if not exe:
        return web.json_response({"error": "Claude Code isn't installed - run 'FreedomOS Setup' from the Start menu"}, status=400)
    if IS_WIN:
        subprocess.Popen(["cmd", "/c", "start", "Claude login - sign in, then close this window", "cmd", "/k", exe],
                         cwd=str(WORK_DIR), creationflags=subprocess.CREATE_NO_WINDOW)
    return web.json_response({"ok": True})


async def h_pic(request):
    name = request.match_info["name"]
    f = PIC_DIR / name
    if "/" in name or "\\" in name or not f.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(f)


def routes(app):
    app.add_routes([web.get("/cc", h_list), web.get("/cc/chat/{cid}", h_get), web.post("/cc/send", h_send),
                    web.post("/cc/act", h_act), web.post("/cc/login", h_login), web.get("/cc/pic/{name}", h_pic)])
