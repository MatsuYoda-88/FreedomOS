"""
FreedomOS - PIXEL SHOP LITE: a picture maker that runs on the LAPTOP (no NVIDIA needed).
Engine: stable-diffusion.cpp (the picture version of the llama.cpp brain engine), Vulkan build = runs on Intel graphics.
Model: FLUX.2 klein 4B (same as the desktop Pixel Shop), squeezed to 4-bit so it fits: ~5.5 GB total, downloaded once.
Every picture lands in  Documents\\FreedomOS Pictures.
"""
import asyncio
import io
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

D = {}                     # handed over from boss.py: here, log, hub, set_agent, agents
state = {"status": "off", "detail": "", "pct": 0, "busy": False}
API = "https://api.github.com/repos/leejet/stable-diffusion.cpp/releases?per_page=30"
MODELS = [  # (url, file name, about how big)
    ("https://huggingface.co/unsloth/FLUX.2-klein-4B-GGUF/resolve/main/flux-2-klein-4b-Q4_K_M.gguf", "flux-2-klein-4b-Q4_K_M.gguf", 2.6e9),
    ("https://huggingface.co/unsloth/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf", "Qwen3-4B-Q4_K_M.gguf", 2.5e9),
    ("https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-4b/resolve/main/split_files/vae/flux2-vae.safetensors",
     "flux2-vae.safetensors", 3.4e8),
]
LOOKS = {  # what the picture should look like
    "pixel": ("Pixel art", "pixel art, 16-bit video game sprite style, crisp pixels, limited color palette, clean outlines", True),
    "sprite": ("Sprite (see-through-ish)", "pixel art character sprite, full body, standing, plain flat light background, 16-bit, crisp pixels", True),
    "picture": ("Regular picture", "", False),
}
# the same one hard line as the desktop shop - no sexual stuff with kids, ever
_MINOR = r"(child|children|kid|kids|minor|minors|underage|under\s*age|teen|teens|teenage|teenager|preteen|pre-teen|" \
         r"young\s+girl|young\s+boy|little\s+girl|little\s+boy|schoolgirl|schoolboy|toddler|baby|infant|juvenile|" \
         r"(?:[1-9]|1[0-7])\s*(?:yo|y/o|yrs?|years?)(?:[\s-]*old)?)"
_SEX = r"(nude|nudes|naked|nsfw|sex|sexy|sexual|porn|porno|erotic|explicit|topless|bottomless|lingerie|hentai|genital|genitals|" \
       r"breast|breasts|boobs|nipple|nipples|undress|undressed|strip|stripping|lewd|seductive|bikini|panties|underwear|fetish|aroused)"
_ALWAYS = r"(loli|lolicon|lolita|shota|shotacon|cp)"


def hard_line(text):
    t = text.lower()
    return bool(re.search(r"\b" + _ALWAYS + r"\b", t) or (re.search(r"\b" + _MINOR + r"\b", t) and re.search(r"\b" + _SEX + r"\b", t)))


def init(here, log, hub, set_agent, agents):
    D.update(here=Path(here), log=log, hub=hub, set_agent=set_agent, agents=agents)
    D["dir"] = Path(here) / "imagegen"
    if installed():
        _set("ready")


def documents():
    """The real Documents folder (on this laptop it lives in OneDrive)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            from uuid import UUID

            class GUID(ctypes.Structure):
                _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]
            u = UUID("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")            # FOLDERID_Documents
            g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
            p = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(p)) == 0:
                out = Path(p.value)
                ctypes.windll.ole32.CoTaskMemFree(p)
                return out
        except Exception:
            pass
    return Path.home() / "Documents"


def out_dir():
    d = documents() / "FreedomOS Pictures"
    d.mkdir(parents=True, exist_ok=True)
    return d


def my_style_dir():
    d = D["here"] / "my style"
    d.mkdir(exist_ok=True)
    readme = d / "PUT YOUR DRAWINGS HERE.txt"
    if not readme.exists():
        readme.write_text("Drop 1-3 of your own drawings in here (png / jpg / webp).\n"
                          "Every picture Pixel Shop Lite makes copies YOUR style from them - it's on by default.\n"
                          "Take them out to go back to plain.\n", encoding="utf-8")
    return d


def my_style():
    """Your drawings (newest first) - the default style for every picture."""
    pics = [p for p in my_style_dir().iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    return sorted(pics, key=lambda p: p.stat().st_mtime, reverse=True)


def exe():
    for n in ("sd-cli.exe", "sd.exe", "sd-cli", "sd"):
        p = D["dir"] / "bin" / n
        if p.exists():
            return p
    return None


def installed():
    return bool(exe()) and all((D["dir"] / "models" / f).exists() for _, f, _ in MODELS)


def _set(status, detail="", pct=None):
    state["status"], state["detail"] = status, detail
    if pct is not None:
        state["pct"] = pct
    D["hub"].send({"type": "pixlite", "pixlite": public()})


def public():
    return {**state, "installed": installed(), "folder": str(out_dir()), "looks": {k: v[0] for k, v in LOOKS.items()},
            "my_style": [p.name for p in my_style()][:3], "my_style_folder": str(my_style_dir())}


def pictures(limit=60):
    files = sorted(out_dir().glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    return [{"name": p.name, "when": datetime.fromtimestamp(p.stat().st_mtime).strftime("%b %d %H:%M")} for p in files]


ART_AGENT = "Rook"


def _artist(working, text=None):
    """An agent shows as busy while a picture is being made."""
    if ART_AGENT not in D["agents"]:
        return
    if working:
        D["set_agent"](ART_AGENT, "code", "working", None, text=text or "Making a picture...")
    else:
        D["set_agent"](ART_AGENT, "idle", "idle", None)


# ---------------------------------------------------------------- one-time setup (download)
def _get(url, timeout=60, tries=5):
    """Download with retries - GitHub and Hugging Face throw 504 'busy' errors now and then."""
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "FreedomOS", "Accept": "application/vnd.github+json"}), timeout=timeout)
        except Exception as e:
            code = getattr(e, "code", None)
            if i == tries - 1 or (code and code < 500 and code != 429):
                raise RuntimeError(f"{e} (from {url.split('/')[2]})")
            wait = [3, 8, 15, 30, 45][i]
            _set("setting up", f"server's busy ({code or e.__class__.__name__}) - trying again in {wait}s...", state.get("pct", 1))
            D["log"](f"Pixel Shop Lite: {url.split('/')[2]} said {e} - retry {i + 1} in {wait}s")
            time.sleep(wait)


def _releases():
    """Find the engine: the release list, or just the newest release if the list times out."""
    for url in (API.replace("per_page=30", "per_page=8"), API.rsplit("?", 1)[0] + "/latest", API):
        try:
            data = json.load(_get(url, 60, 3))
            return data if isinstance(data, list) else [data]
        except Exception as e:
            last = e
    raise last


def _setup_sync():
    d = D["dir"]
    (d / "bin").mkdir(parents=True, exist_ok=True)
    (d / "models").mkdir(parents=True, exist_ok=True)
    if not exe():
        _set("setting up", "finding the picture engine (Intel graphics version)...", 1)
        pick = None
        for r in _releases():
            for a in r.get("assets", []):
                n = a["name"].lower()
                if n.endswith(".zip") and "win" in n and "vulkan" in n and ("x64" in n or "amd64" in n):
                    pick = (r["tag_name"], a["name"], a["browser_download_url"])
                    break
            if pick:
                break
        if not pick:
            raise RuntimeError("couldn't find a Windows Vulkan build of stable-diffusion.cpp")
        _set("setting up", f"downloading the engine ({pick[1]})...", 2)
        with zipfile.ZipFile(io.BytesIO(_get(pick[2], 300).read())) as z:
            for m in z.infolist():
                if not m.is_dir():
                    (d / "bin" / Path(m.filename).name).write_bytes(z.read(m))
        (d / "bin" / "VERSION.txt").write_text(f"{pick[0]} {pick[1]}\n")
        if not exe():
            raise RuntimeError("the picture engine wasn't in the download")
    total = sum(s for _, _, s in MODELS)
    done = 0
    for url, name, size in MODELS:
        dest = d / "models" / name
        if dest.exists():
            done += size
            continue
        part = dest.with_suffix(dest.suffix + ".part")
        have = part.stat().st_size if part.exists() else 0
        for attempt in range(8):                  # a dropped or busy download picks up where it left off
            have = part.stat().st_size if part.exists() else 0
            req = urllib.request.Request(url, headers={"User-Agent": "FreedomOS", **({"Range": f"bytes={have}-"} if have else {})})
            try:
                with urllib.request.urlopen(req, timeout=60) as r, open(part, "ab" if have and r.status == 206 else "wb") as f:
                    if r.status != 206:
                        have = 0
                    got, last = have, 0
                    while True:
                        b = r.read(1 << 20)
                        if not b:
                            break
                        f.write(b)
                        got += len(b)
                        if time.time() - last > 1:
                            last = time.time()
                            _set("setting up", f"downloading {name}  ({got / 1e9:.1f} GB)", int(5 + 94 * (done + got) / total))
                break
            except Exception as e:
                code = getattr(e, "code", None)
                if code == 416:                          # already had the whole thing
                    break
                if attempt == 7 or (code and code < 500 and code != 429):
                    raise RuntimeError(f"{e} (downloading {name})")
                wait = [3, 8, 15, 30, 45, 60, 90][attempt]
                D["log"](f"Pixel Shop Lite: {name} download hiccup ({e}) - retry {attempt + 1} in {wait}s")
                _set("setting up", f"server's busy - trying {name} again in {wait}s...", state.get("pct", 5))
                time.sleep(wait)
        part.replace(dest)
        done += size
    _set("ready", "Pixel Shop Lite is ready. Make something!", 100)


async def setup():
    if state["status"] == "setting up":
        return
    _set("setting up", "getting ready...", 0)
    try:
        await asyncio.get_running_loop().run_in_executor(None, _setup_sync)
    except Exception as e:
        _set("error", f"setup didn't finish: {e} - hit Set up again, it picks up where it left off")
        D["log"](f"Pixel Shop Lite setup failed: {e}")


# ---------------------------------------------------------------- making a picture
def snap_pixels(img, chunk=6, colors=32):
    from PIL import Image
    w, h = img.size
    small = img.convert("RGB").resize((max(1, w // chunk), max(1, h // chunk)), Image.BOX)
    small = small.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).convert("RGB")
    return small.resize((small.width * chunk, small.height * chunk), Image.NEAREST)


def save_refs(data_urls):
    """Pictures dropped in the 🎨 panel -> PNG files the engine can read (it can't do webp). Max 4, max 1024px."""
    import base64
    import io
    from PIL import Image
    out = []
    rdir = D["dir"] / "refs-dropped"
    rdir.mkdir(parents=True, exist_ok=True)
    for old in rdir.glob("*.png"):
        try:
            old.unlink()
        except OSError:
            pass
    for i, u in enumerate((data_urls or [])[:4]):
        m = re.match(r"data:image/[a-z0-9.+-]+;base64,(.+)$", str(u), re.S)
        if not m:
            continue
        try:
            img = Image.open(io.BytesIO(base64.b64decode(m.group(1)))).convert("RGB")
        except Exception:
            continue
        img.thumbnail((1024, 1024))
        f = rdir / f"ref{i}.png"
        img.save(f)
        out.append(f)
    return out


def _make_sync(prompt, look, match, size, seed, user_refs=None, keep_style=True):
    d = D["dir"] / "models"
    words, snap = LOOKS.get(look, LOOKS["pixel"])[1:]
    full = (prompt + (", " + words if words else "")).strip(", ")
    tmp = D["dir"] / f"tmp-{int(time.time() * 1000)}.png"
    cmd = [str(exe()), "--diffusion-model", str(d / MODELS[0][1]), "--llm", str(d / MODELS[1][1]), "--vae", str(d / MODELS[2][1]),
           "-p", full, "--cfg-scale", "1.0", "--steps", "4", "-W", str(size), "-H", str(size), "--seed", str(seed), "-o", str(tmp)]
    user_refs = list(user_refs or [])
    refs = user_refs + (my_style()[:max(0, 3 - len(user_refs))] if keep_style else [])   # dropped pictures first, then YOUR style
    if refs:
        for r_ in refs[:4]:
            cmd += ["-r", str(r_)]
        cmd += ["--sampling-method", "euler"]
        if not user_refs:
            full += ", drawn in the exact same art style as the reference pictures"
        elif len(refs) > len(user_refs):
            full += ", based on the first reference pictures (same subject, shapes and colors), drawn in the art style of the other reference pictures"
        else:
            full += ", based on the reference pictures (same subject, shapes, colors and style)"
        i = cmd.index("-p"); cmd[i + 1] = full
    t0 = time.time()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=1200, creationflags=flags, cwd=str(D["dir"]))
    if p.returncode != 0 or not tmp.exists():
        tail = (p.stderr or p.stdout or "")[-400:]
        raise RuntimeError(f"the picture engine choked: {tail}")
    from PIL import Image
    img = Image.open(tmp)
    if snap:
        img = snap_pixels(img)
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:40] or "picture"
    name = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{slug}.png"
    img.save(out_dir() / name)
    try:
        tmp.unlink()
    except Exception:
        pass
    return {"name": name, "secs": round(time.time() - t0, 1), "path": str(out_dir() / name), "prompt": prompt, "look": look}


async def make(prompt, look="pixel", match=False, size=512, seed=None, refs=None, keep_style=True):
    prompt = " ".join(str(prompt).split())[:400]
    if not prompt:
        raise ValueError("type what to make first")
    if hard_line(prompt):
        raise ValueError("Nope. Not making that. Ever.")
    if not installed():
        raise ValueError("Pixel Shop Lite isn't set up yet - hit 'Set up' in the 🎨 popup first (one-time ~5.5 GB download)")
    if state["busy"]:
        raise ValueError("already making one - give it a minute")
    state["busy"] = True
    if D.get("hands"):
        D["hands"]("pic")
    try:
        if D.get("ideas"):                                     # every agent throws in an idea, two make it in
            _set("making", "The crew is throwing in ideas...")
            prompt, _ideas = await D["ideas"](prompt)
    except Exception:
        pass
    _set("making", f"Making: {prompt[:60]}")
    _artist(True, f"Making a picture: {prompt[:50]}")
    try:
        user_refs = save_refs(refs) if refs else []
        res = await asyncio.get_running_loop().run_in_executor(
            None, _make_sync, prompt, look, bool(match), int(size), int(seed if seed is not None else random.randint(1, 2**31 - 1)),
            user_refs, bool(keep_style))
        res["refs"] = len(user_refs)
        D["log"](f"Pixel Shop Lite ({res['secs']}s): {prompt[:60]} -> {res['name']}")
        D["hub"].send({"type": "pixlite", "made": res, "pixlite": public()})
        return res
    finally:
        state["busy"] = False
        if D.get("hands"):
            D["hands"]("pic", False)
        _artist(False)
        _set("ready" if installed() else "off", "")


# ---------------------------------------------------------------- web routes
def routes(is_host):
    from aiohttp import web

    async def h_status(request):
        return web.json_response({**public(), "pictures": pictures()})

    async def h_setup(request):
        if not is_host(request):
            return web.json_response({"error": "set it up on the laptop itself"}, status=403)
        asyncio.get_running_loop().create_task(setup())
        return web.json_response({"ok": True})

    async def h_make(request):
        d = await request.json()
        try:
            res = await make(d.get("prompt", ""), d.get("look", "pixel"), d.get("match", False), int(d.get("size", 512) or 512),
                             refs=d.get("refs") or None, keep_style=d.get("keep_style", True))
            return web.json_response(res)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def h_img(request):
        name = Path(request.match_info["name"]).name
        p = out_dir() / name
        if not p.exists() or p.suffix.lower() != ".png":
            return web.json_response({"error": "no such picture"}, status=404)
        return web.FileResponse(p, headers={"Cache-Control": "no-cache"})

    async def h_open(request):
        if not is_host(request):
            return web.json_response({"error": "only on the laptop itself"}, status=403)
        try:
            os.startfile(str(out_dir()))          # pops the folder open in File Explorer
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"ok": True})

    return [web.get("/pixlite", h_status), web.post("/pixlite/setup", h_setup), web.post("/pixlite/make", h_make),
            web.get("/pixlite/img/{name}", h_img), web.post("/pixlite/open", h_open)]
