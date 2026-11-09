"""FreedomOS 📁 - the same files on the laptop, the desktop and (through the 📁 window) your phone.

Four shared spaces:
  Claude        - your Claude work folder (minus the stuff that only belongs to one PC)
  Shared        - Documents\\Shared, a fresh drop-anything folder
  Phone         - Documents\\Phone, where pictures/files sent from the phone land
  Pictures      - Documents\\FreedomOS Pictures, the Pixel Shop pictures

How the PCs stay the same: every couple minutes each FreedomOS asks the other PC "what've you got?"
and pulls over anything new or changed. Deleted on one PC = moved to todelete\\sync trash on the other
(never wiped). Both PCs changed the same file = the newer one wins and the older one is kept as a
"(conflict ...)" copy. Nothing moves until you hit Start the first time (it shows you what'll copy).
"""
import asyncio
import base64
import json
import os
import re
import shutil
import socket
import threading
import time
from pathlib import Path
from urllib.parse import quote

from aiohttp import ClientSession, ClientTimeout, web

HERE = Path(__file__).resolve().parent
STATE_DIR = HERE / "memory"
CFG_FILE = STATE_DIR / "filesync.json"
SYNC_EVERY = 120                    # seconds between check-ins with the other PC
SLACK = 2                           # seconds of clock wiggle when comparing file times
MAX_MB = 4096                       # bigger than this doesn't sync (ISOs, giant models)

# never sync these (they belong to ONE PC, or they're junk / temp files)
SKIP_NAMES = {"todelete", "__pycache__", "venv", ".venv", "node_modules", ".git", "desktop.ini", "thumbs.db", ".ds_store",
              "$recycle.bin", ".sync-tmp"}
SKIP_PARTS = ["ai crew/freedomos/engine", "ai crew/freedomos/engine_vulkan", "ai crew/freedomos/engine_prism",
              "ai crew/freedomos/logs", "ai crew/freedomos/memory", "ai crew/freedomos/imagegen",
              "ai crew/freedomos/pixelshop/models", "ai crew/freedomos/pixelshop/logs", "ai crew/freedomos/pixelshop/venv",
              "ai crew/freedomos/pixelshop/crew_key.txt", "ai crew/freedomos/crew_key.txt",
              "ai crew/freedomos/pixelshop/outputs/recent.json", "ai crew/freedomos wallpaper.html",
              "ai crew/freedomos/firewall_done.txt", "ai crew/freedomos/engine_fixes.json",
              "ai crew/freedomos work link.txt", "ai crew/freedomos/freedomos work link.txt",
              "ai crew/pixel shop crew link.txt", "pixel shop crew link.txt",
              "wifile/memory", "wifile/logs", "wifile/venv", "wifile/key.txt", "wifile/wifile phone link.txt",
              "f35 browser/bin", "f35 browser/src/bin", "f35 browser/src/obj", "f35 browser/build.log",
              "ai crew/freedomos/browser/builds", "ai crew/freedomos/browser/src/bin", "ai crew/freedomos/browser/src/obj", "ai crew/freedomos/browser/build.log",
              "f35 sync/memory", "f35 sync/logs", "f35 sync/venv", "f35 sync/key.txt", "f35 sync/f35 sync phone link.txt"]
SKIP_ENDS = (".tmp", ".part", ".partial", ".crdownload", ".lock", ".pyc")

_hub, _log, _documents = None, print, None
CFG = {"peers": [], "on": False, "me": socket.gethostname()}
STATUS = {"busy": False, "now": "", "done": 0, "todo": 0, "bytes": 0, "bytes_todo": 0, "last": {}, "errors": [], "skipped": []}
_key = ""
_my_url = ""


def init(hub, log, documents, key, my_url):
    global _hub, _log, _documents, _key, _my_url
    _hub, _log, _documents, _key, _my_url = hub, log, documents, key, my_url or os.environ.get("F35_MY_URL", "")
    try:
        CFG.update(json.loads(CFG_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    CFG["me"] = os.environ.get("F35_ME") or socket.gethostname()
    if CFG.get("state_v", 1) < 2:                       # v1.6.8: AI Crew syncs now - start the records fresh (pure merge, no trashing)
        for f in list(STATE_DIR.glob("sync_state_*.json")) + [STATE_DIR / "sync_seen.json", STATE_DIR / "sync_gone.json"]:
            try:
                f.unlink()
            except OSError:
                pass
        CFG["state_v"] = 2
        try:
            save_cfg()
        except Exception:
            pass
    for f in roots().values():
        try:
            f.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


def save_cfg():
    STATE_DIR.mkdir(exist_ok=True)
    CFG_FILE.write_text(json.dumps(CFG, indent=1), encoding="utf-8")


def roots():
    doc = _documents() if _documents else Path.home() / "Documents"
    work = doc / "FreedomOS"
    return {"FreedomOS": work, "Shared": doc / "Shared", "Phone": doc / "Phone", "Pictures": doc / "FreedomOS Pictures"}


def trash_dir():
    return roots()["FreedomOS"] / "todelete" / "sync trash"


def skip(folder, rel):
    low = rel.replace("\\", "/").lower()
    parts = low.split("/")
    if any(p in SKIP_NAMES for p in parts) or low.endswith(SKIP_ENDS) or parts[-1].startswith(("~$", ".sync-tmp-")):
        return True
    if folder == "FreedomOS" and any(low == s or low.startswith(s + "/") for s in SKIP_PARTS):
        return True                     # stuff that belongs to ONE PC only
    return False


def safe_path(folder, rel):
    """Turn folder + relative path into a real path, and refuse anything that tries to climb out."""
    base = roots().get(folder)
    if base is None:
        raise web.HTTPNotFound(text="no such shared folder")
    rel = (rel or "").replace("\\", "/").strip("/")
    p = (base / rel).resolve() if rel else base.resolve()
    if p != base.resolve() and base.resolve() not in p.parents:
        raise web.HTTPForbidden(text="nope")
    return base, rel, p


def scan(folder):
    """What's in a shared folder: {relative path: [size, whole-second mtime]}."""
    base = roots()[folder]
    out, big = {}, []
    if not base.exists():
        return out, big
    for dirpath, dirs, files in os.walk(base):
        rd = os.path.relpath(dirpath, base).replace("\\", "/")
        rd = "" if rd == "." else rd
        dirs[:] = [d for d in dirs if not skip(folder, (rd + "/" + d).lstrip("/"))]
        for f in files:
            rel = (rd + "/" + f).lstrip("/")
            if skip(folder, rel):
                continue
            try:
                st = os.stat(os.path.join(dirpath, f))
            except OSError:
                continue
            if st.st_size > MAX_MB * 1024 * 1024:
                big.append(rel)
                continue
            out[rel] = [st.st_size, int(st.st_mtime)]
    return out, big


_scan_lock = threading.Lock()
TOMB_DAYS = 45


def _jload(f, d):
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return d


def local_scan(folder):
    """Scan + remember what vanished since last time (a 'gone' list with when), so deletes travel to the other PC."""
    with _scan_lock:
        now_files, big = scan(folder)
        seen_f, tomb_f = STATE_DIR / "sync_seen.json", STATE_DIR / "sync_gone.json"
        seen, tombs = _jload(seen_f, {}), _jload(tomb_f, {})
        prev, gone = seen.get(folder), tombs.setdefault(folder, {})
        t = int(time.time())
        since = int(seen.get("_t_" + folder, t))     # it vanished sometime after the last look - use the EARLIEST it could've been
        if prev is not None:
            for rel in set(prev) - set(now_files):
                if not skip(folder, rel):      # stuff we now ignore didn't get deleted - don't tell the other PC it did
                    gone[rel] = since
        for rel in list(gone):
            if rel in now_files or skip(folder, rel) or t - gone[rel] > TOMB_DAYS * 86400:
                gone.pop(rel)
        seen[folder] = now_files
        seen["_t_" + folder] = t
        STATE_DIR.mkdir(exist_ok=True)
        seen_f.write_text(json.dumps(seen), encoding="utf-8")
        tomb_f.write_text(json.dumps(tombs), encoding="utf-8")
        return now_files, big, dict(gone)


def same(a, b):
    return bool(a and b and a[0] == b[0] and abs(a[1] - b[1]) <= SLACK)


def state_file(peer):
    return STATE_DIR / f"sync_state_{re.sub(r'[^A-Za-z0-9_-]', '_', peer)}.json"


def load_state(peer):
    try:
        return json.loads(state_file(peer).read_text(encoding="utf-8"))
    except Exception:
        return {}


def plan(folder, local, remote, last, me, them, my_gone=None, their_gone=None):
    """Decide what THIS PC does. Each PC only ever pulls / trashes its OWN copies, so the two never fight."""
    pull, trash, conflict = [], [], []
    my_gone, their_gone = my_gone or {}, their_gone or {}
    for rel in set(local) | set(remote):
        if skip(folder, rel):
            continue                            # never touch stuff that isn't supposed to sync (even if the other PC lists it)
        l, r, s = local.get(rel), remote.get(rel), last.get(rel)
        if r and not l:
            if (rel in my_gone and my_gone[rel] + SLACK >= r[1]) or (s and same(s, r)):
                continue                        # I deleted it (and they haven't touched it since) - they'll trash theirs
            pull.append(rel)
        elif l and not r:
            if (rel in their_gone and their_gone[rel] + SLACK >= l[1]) or (s and same(s, l)):
                trash.append(rel)               # they deleted it and mine's no newer -> trash mine
        elif l and r and not same(l, r):
            lch, rch = not same(l, s), not same(r, s)
            if rch and not lch:
                pull.append(rel)
            elif lch and rch:                   # both changed (or first time) -> newer wins, loser keeps a copy
                mine_older = l[1] < r[1] or (l[1] == r[1] and me.lower() < them.lower())
                if mine_older:
                    conflict.append(rel)
                    pull.append(rel)
    return sorted(pull), sorted(trash), sorted(conflict)


def push(ev=None):
    if _hub:
        _hub.send(ev or {"type": "files", "files": public()})


def public():
    return {"on": CFG.get("on", False), "me": CFG["me"], "peers": [{"name": p["name"], "url": p["url"]} for p in CFG["peers"]],
            "status": {k: v for k, v in STATUS.items() if k != "skipped"}, "skipped": STATUS["skipped"][:30],
            "folders": {k: str(v) for k, v in roots().items()}, "pair": pair_code()}


def pair_code():
    if not _my_url:
        return ""
    raw = json.dumps({"name": CFG["me"], "url": _my_url, "key": _key}).encode()
    return "F35-" + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def read_pair(code):
    code = code.strip()
    if code.startswith("F35-"):
        code = code[4:]
    d = json.loads(base64.urlsafe_b64decode(code + "=" * (-len(code) % 4)))
    return {"name": str(d["name"])[:60], "url": str(d["url"]).rstrip("/"), "key": str(d["key"])}


# ---------------------------------------------------------------- talking to the other PC
def _hdr(peer):
    return {"X-Crew-Key": peer["key"]}


async def peer_index(s, peer, folder):
    async with s.get(f"{peer['url']}/files/index", params={"folder": folder}, headers=_hdr(peer),
                     timeout=ClientTimeout(total=300)) as r:
        if r.status != 200:
            raise RuntimeError(f"{peer['name']} said {r.status}")
        d = await r.json()
        return d["files"], d.get("gone", {})


async def pull_one(s, peer, folder, rel, mtime, conflict):
    _, _, dest = safe_path(folder, rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".sync-tmp-{dest.name}"
    got = 0
    try:
        async with s.get(f"{peer['url']}/files/get", params={"folder": folder, "path": rel}, headers=_hdr(peer),
                         timeout=ClientTimeout(total=None, sock_read=300)) as r:
            if r.status != 200:
                raise RuntimeError(f"{r.status}")
            with open(tmp, "wb") as f:
                async for chunk in r.content.iter_chunked(1 << 20):
                    f.write(chunk)
                    got += len(chunk)
                    STATUS["bytes"] += len(chunk)
    except BaseException:
        STATUS["bytes"] -= got
        try:
            tmp.unlink()                       # don't leave half a file lying around
        except OSError:
            pass
        raise
    if conflict and dest.exists():
        if folder == "FreedomOS" and rel.lower().startswith("ai crew/"):
            to_trash(folder, rel)              # program files: older copy goes to todelete\sync trash, no clutter
        else:
            stamp = time.strftime("%Y-%m-%d %H%M", time.localtime(dest.stat().st_mtime))
            dest.replace(dest.with_name(f"{dest.stem} (conflict {CFG['me']} {stamp}){dest.suffix}"))
    os.replace(tmp, dest)
    os.utime(dest, (mtime, mtime))


def to_trash(folder, rel):
    _, _, p = safe_path(folder, rel)
    if not p.exists():
        return
    t = trash_dir() / folder / rel
    t.parent.mkdir(parents=True, exist_ok=True)
    if t.exists():
        t = t.with_name(f"{t.stem} {int(time.time())}{t.suffix}")
    shutil.move(str(p), str(t))


async def sync_peer(s, peer, dry=False):
    """One full pass with one other PC. dry=True only counts what WOULD happen (the preview)."""
    state = load_state(peer["name"])
    report = {}
    for folder in roots():
        STATUS["now"] = f"checking {folder} with {peer['name']}..."
        push()
        local, big, my_gone = await asyncio.to_thread(local_scan, folder)
        STATUS["skipped"] = (STATUS["skipped"] + [f"{folder}/{b}" for b in big])[-60:]
        remote, their_gone = await peer_index(s, peer, folder)
        last = state.get(folder, {})
        pull, trash, conflict = plan(folder, local, remote, last, CFG["me"], peer["name"], my_gone, their_gone)
        report[folder] = {"pull": len(pull), "pull_mb": round(sum(remote[r][0] for r in pull) / 1e6, 1),
                          "trash": len(trash), "conflict": len(conflict), "here": len(local), "there": len(remote)}
        if dry:
            continue
        STATUS["todo"] += len(pull) + len(trash)
        STATUS["bytes_todo"] += sum(remote[r][0] for r in pull)
        cset = set(conflict)
        for rel in trash:
            try:
                await asyncio.to_thread(to_trash, folder, rel)
                local.pop(rel, None)
            except Exception as e:
                STATUS["errors"] = (STATUS["errors"] + [f"trash {folder}/{rel}: {e}"])[-20:]
            STATUS["done"] += 1
        for rel in pull:
            STATUS["now"] = f"⬇ {folder}/{rel}"
            push()
            try:
                await pull_one(s, peer, folder, rel, remote[rel][1], rel in cset)
                local[rel] = list(remote[rel])
            except Exception as e:
                STATUS["errors"] = (STATUS["errors"] + [f"{folder}/{rel}: {e}"])[-20:]
            STATUS["done"] += 1
        # what both PCs agree on now = next time's starting point
        state[folder] = {rel: v for rel, v in local.items() if same(v, remote.get(rel))}
        state_file(peer["name"]).write_text(json.dumps(state), encoding="utf-8")
        await asyncio.to_thread(local_scan, folder)       # so my own pulls/trashes don't look like new deletes later
    return report


async def sync_app_up():
    """The stand-alone F35 Sync app (tray) does the syncing now? Then FreedomOS stays out of its way."""
    try:
        async with ClientSession() as s:
            async with s.get("http://127.0.0.1:7790/health", timeout=ClientTimeout(total=2)) as r:
                return r.status == 200 and any(k in await r.text() for k in ("wifile", "f35sync"))
    except Exception:
        return False


async def sync_all(dry=False):
    if STATUS["busy"]:
        return {"error": "already syncing"}
    if await sync_app_up():
        STATUS["now"] = "WiFile (tray app) is doing the syncing now"
        push()
        return {"F35 Sync": {"error": "the WiFile tray app handles syncing now - open it from the tray"}}
    STATUS.update(busy=True, done=0, todo=0, bytes=0, bytes_todo=0, errors=[], skipped=[])
    push()
    out = {}
    try:
        async with ClientSession() as s:
            for peer in CFG["peers"]:
                try:
                    out[peer["name"]] = await sync_peer(s, peer, dry)
                    if not dry:
                        STATUS["last"][peer["name"]] = time.strftime("%I:%M %p").lstrip("0")
                except Exception as e:
                    out[peer["name"]] = {"error": f"can't reach it ({str(e)[:80]}) - is it on with FreedomOS running?"}
                    STATUS["errors"] = (STATUS["errors"] + [f"{peer['name']}: {e}"])[-20:]
    finally:
        STATUS.update(busy=False, now="")
        push()
    return out


async def loop():
    await asyncio.sleep(30)
    while True:
        if CFG.get("on") and CFG["peers"]:
            try:
                await sync_all()
            except Exception as e:
                _log(f"(file sync hiccup: {e})")
        await asyncio.sleep(SYNC_EVERY)


# ---------------------------------------------------------------- web routes (the 📁 window + the other PC)
def same_window(request):
    o = request.headers.get("Origin")
    if o and o != "null" and o.split("://", 1)[-1] != (request.headers.get("X-Forwarded-Host") or request.host):
        return False
    return True


async def h_index(request):
    folder = request.query.get("folder", "")
    if folder not in roots():
        raise web.HTTPNotFound()
    files, _, gone = await asyncio.to_thread(local_scan, folder)
    return web.json_response({"files": files, "gone": gone})


async def h_list(request):
    """One folder level, for browsing in the 📁 window."""
    base, rel, p = safe_path(request.query.get("folder", "Shared"), request.query.get("path", ""))
    folder = request.query.get("folder", "Shared")
    if not p.is_dir():
        raise web.HTTPNotFound()
    rows = []
    for e in sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
        r = (rel + "/" + e.name).lstrip("/")
        if e.name.startswith(".sync-tmp-"):
            continue
        try:
            st = e.stat()
        except OSError:
            continue
        rows.append({"name": e.name, "dir": e.is_dir(), "size": st.st_size if e.is_file() else None,
                     "mtime": int(st.st_mtime), "nosync": skip(folder, r)})
    return web.json_response({"folder": folder, "path": rel, "rows": rows, "where": str(p)})


async def h_get(request):
    _, _, p = safe_path(request.query.get("folder", ""), request.query.get("path", ""))
    if not p.is_file():
        raise web.HTTPNotFound()
    hdr = {"Content-Disposition": f"{'inline' if request.query.get('view') else 'attachment'}; filename*=UTF-8''{quote(p.name)}"}
    size = p.stat().st_size
    if size < 512 * 1024 * 1024:
        return web.FileResponse(p, headers=hdr)
    # big files: send in 4 MB chunks (Windows' fast send gives up past 2 GB - the PS2 ISOs choked on it)
    import mimetypes
    resp = web.StreamResponse(headers=dict(hdr, **{"Content-Type": mimetypes.guess_type(p.name)[0] or "application/octet-stream"}))
    resp.content_length = size
    await resp.prepare(request)
    with open(p, "rb") as f:
        while True:
            chunk = await asyncio.to_thread(f.read, 4 << 20)
            if not chunk:
                break
            await resp.write(chunk)
    await resp.write_eof()
    return resp


async def h_put(request):
    """Upload from the 📁 window (phone pictures, anything). multipart: folder, path, files..."""
    if not same_window(request):
        return web.json_response({"error": "nope"}, status=403)
    reader = await request.multipart()
    folder, sub, saved = "Phone", "", []
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "folder":
            folder = (await part.text()).strip()
        elif part.name == "path":
            sub = (await part.text()).strip()
        elif part.name == "file" and part.filename:
            name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", Path(part.filename).name)[:180]
            _, rel, d = safe_path(folder, sub)
            d.mkdir(parents=True, exist_ok=True)
            dest = d / name
            if dest.exists():
                dest = d / f"{dest.stem} {time.strftime('%H%M%S')}{dest.suffix}"
            with open(dest, "wb") as f:
                while True:
                    c = await part.read_chunk(1 << 20)
                    if not c:
                        break
                    f.write(c)
            saved.append(dest.name)
    push()
    return web.json_response({"ok": True, "saved": saved})


async def h_act(request):
    if not same_window(request):
        return web.json_response({"error": "nope"}, status=403)
    d = await request.json()
    act = d.get("act")
    if act == "pair":
        try:
            peer = read_pair(d.get("code", ""))
        except Exception:
            return web.json_response({"error": "that code doesn't look right - copy the whole thing"}, status=400)
        if peer["key"] == _key:
            return web.json_response({"error": "that's THIS PC's code - paste the OTHER PC's code here"}, status=400)
        try:
            async with ClientSession() as s:
                async with s.get(f"{peer['url']}/files/index", params={"folder": "Shared"}, headers=_hdr(peer),
                                 timeout=ClientTimeout(total=15)) as r:
                    if r.status != 200:
                        raise RuntimeError(f"it said {r.status}")
        except Exception as e:
            return web.json_response({"error": f"can't reach {peer['name']} ({str(e)[:60]}). Both PCs on, FreedomOS running, Tailscale on?"}, status=400)
        CFG["peers"] = [p for p in CFG["peers"] if p["name"] != peer["name"]] + [peer]
        save_cfg()
        push()
        return web.json_response({"ok": True, "files": public()})
    if act == "unpair":
        CFG["peers"] = [p for p in CFG["peers"] if p["name"] != d.get("name")]
        save_cfg()
    elif act == "preview":
        return web.json_response({"ok": True, "preview": await sync_all(dry=True)})
    elif act == "start":
        CFG["on"] = True
        save_cfg()
        asyncio.get_running_loop().create_task(sync_all())
    elif act == "pause":
        CFG["on"] = False
        save_cfg()
    elif act == "now":
        asyncio.get_running_loop().create_task(sync_all())
    elif act == "trash":
        to_trash(d.get("folder", ""), d.get("path", ""))
    elif act == "mkdir":
        _, _, p = safe_path(d.get("folder", ""), (d.get("path", "") + "/" + re.sub(r'[<>:"|?*\\/]', "_", d.get("name", "New folder"))).strip("/"))
        p.mkdir(parents=True, exist_ok=True)
    push()
    return web.json_response({"ok": True, "files": public()})


async def h_status(request):
    return web.json_response(public())


def routes(app):
    app.add_routes([web.get("/files", h_status), web.get("/files/index", h_index), web.get("/files/list", h_list),
                    web.get("/files/get", h_get), web.post("/files/put", h_put), web.post("/files/act", h_act)])
