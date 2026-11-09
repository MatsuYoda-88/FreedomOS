"""
FreedomOS - the boss server.

Plain words:
  * Takes a job (from Claude through the plug-in, or from the Home screen box).
  * The planner agent (names in config.json) splits it into pieces.
  * The worker agents do the pieces AT THE SAME TIME on the same local brain.
  * The checker agent CHECKS each piece. If it's not good enough it gets sent back once with notes.
  * The planner glues it together, saves it to outputs, and flags anything
    Claude should double-check (code, or stuff that failed the check).
  * Every move is streamed to the Home screen so you can watch.
Engine: llama.cpp's llama-server (official build). MoE "experts" that aren't working
get parked in regular RAM so big brains fit on a 12 GB card.
"""
import asyncio
import json
import socket
import os
import random
import re
import secrets
import shutil
import subprocess
import threading
import sys
import time
import uuid
from pathlib import Path

from aiohttp import web, ClientSession, ClientTimeout

import pixelshop   # the Pixel Shop (HereticPixel built in)
import filesync    # 📁 the same files on the laptop, the desktop and the phone
import claudechat  # the 💬 chat line straight to Claude (Claude Code on your plan)
import pixlite     # Pixel Shop Lite - pictures on the laptop (no NVIDIA needed)
import autoupdate  # new files from Claude -> the running crew updates itself
import f35web    # 🔎 search + clean reader + WiBro
import f35discord  # 🎙 the Discord overlay (reads the Discord tab inside the app)
import f35music  # 🎧 WiMix - your own YouTube Music app, driven from here
import winfs       # maximize the window -> borderless fullscreen
import temps       # CPU temperature for the top bar
BOOT_ID = __import__("uuid").uuid4().hex[:8]   # changes every start - windows reload if the boss restarted

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
# THIS PC's own brain pick lives in memory/ (config.json syncs between the PCs, the pick doesn't)
PICK_FILE = HERE / "memory" / "brain_pick.json"
CFG.pop("remote_brain", None)                     # (older versions kept these in config.json - ignore them now)
CFG["brain"] = "small"
try:
    CFG.update(json.loads(PICK_FILE.read_text(encoding="utf-8")))
except Exception:
    pass


def save_pick(**kw):
    try:
        d = json.loads(PICK_FILE.read_text(encoding="utf-8")) if PICK_FILE.exists() else {}
    except Exception:
        d = {}
    d.update(kw)
    PICK_FILE.parent.mkdir(exist_ok=True)
    PICK_FILE.write_text(json.dumps(d, indent=1), encoding="utf-8")
# which computer is this? NVIDIA card = big brains allowed. No NVIDIA -> the "no_nvidia" settings (small brain, runs on Intel/AMD graphics via Vulkan)
from gpu_check import nvidia_now
HAS_NVIDIA = nvidia_now()      # a card actually plugged in (desktop, or the laptop on the eGPU dock) - not just drivers
BRAINS = CFG.get("brains", {})          # "small" (9B, default) and "big" (35B, NVIDIA desktop only) - pick in the 📊 popup


def brain_ok(name):
    return name in BRAINS and (HAS_NVIDIA or not BRAINS[name].get("nvidia_only"))


def apply_brain(name):
    """Load one brain's settings into CFG (then the laptop's tweaks on top). Returns the brain actually used."""
    global MODEL_LABEL
    if not brain_ok(name):
        name = "small" if brain_ok("small") else next((n for n in BRAINS if brain_ok(n)), name)
    if name in BRAINS:
        CFG.update({k: v for k, v in BRAINS[name].items() if k != "nvidia_only"})
        for k in ("gpu_layers", "model_file", "no_reasoning", "cache_word"):     # don't let the last brain's extras stick around
            if k not in BRAINS[name]:
                CFG.pop(k, None)
    if not HAS_NVIDIA and isinstance(CFG.get("no_nvidia"), dict):
        CFG.update(CFG["no_nvidia"])
    CFG["brain_now"] = name
    MODEL_LABEL = CFG.get("model_label", CFG["model_hf"])
    return name


apply_brain(CFG.get("brain", "small"))
VERSION = CFG.get("version", "1.0.1")
BOSS = CFG.get("boss_name", "Atlas")
CHECKER = CFG.get("checker_name", "Sentry")
WORKERS = CFG["workers"]
BENCH = CFG.get("bench", [])
KEEPERS = CFG.get("keepers", [])
PORT = int(CFG["port"])
ENGINE = f"http://127.0.0.1:{CFG['engine_port']}"
MODEL_LABEL = CFG.get("model_label", CFG["model_hf"])
apply_brain(CFG.get("brain", "small"))
ALLOWED = [Path(os.path.expandvars(p)).expanduser().resolve() for p in CFG["allowed_folders"]]
WORK_DIR = pixlite.documents() / "FreedomOS"          # your FreedomOS work folder - the crew can always read it
try:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    ALLOWED.append(WORK_DIR.resolve())
except Exception:
    pass
OUT_DIR, LOG_DIR = HERE / "outputs", HERE / "logs"
OUT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)
IS_WIN = os.name == "nt"
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "todelete", "engine", "engine_vulkan"}
CODE_WORDS = re.compile(r"\b(code|script|function|python|javascript|html|css|bat|powershell|bug|fix|compile)\b", re.I)


# Each agent has a "way of thinking" - used when the crew double-checks a quick answer (they each look it up their own way and vote).
PERSONA = {
    "Atlas": "the planner - calm, organized, splits big jobs into clean pieces and ties them back together",
    "Sentry": "the checker - strict but fair; hunts for wrong facts, missed steps and made-up stuff",
    "Nova": "the researcher - reads lots of sources fast and pulls out what matters",
    "Bolt": "the coder - practical, tests ideas, likes short working code over long explanations",
    "Echo": "the writer - turns messy notes into clear, friendly plain-language writing",
    "Sage": "the fact-checker - trusts official manuals and specs over forums",
    "Rook": "the organizer - sorts, lists, compares and puts data in tables",
}
STYLE_RULES = "Friendly, clear and short. No slurs, nothing hateful, nothing sexual."


def log(msg: str):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    try:
        with open(LOG_DIR / "boss.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- live feed --
class Hub:
    def __init__(self):
        self.subs: set[asyncio.Queue] = set()

    def send(self, event: dict):
        for q in list(self.subs):
            if q.qsize() < 500:
                q.put_nowait(event)


hub = Hub()
agents: dict[str, dict] = {}
jobs: dict[str, dict] = {}
gpu_state: dict = {}
engine_state = {"status": "off", "detail": ""}   # off / downloading / loading / ready / failed
last_activity = time.time()
engine_proc = None


def set_agent(name, station, status="", job=None, text=None):
    a = agents[name]
    a.update(station=station, status=status, job=job)
    if text is not None:
        a["text"] = text
    elif station == "idle" and a["role"] not in ("bench", "keeper"):
        a["text"] = ""
    hub.send({"type": "agent", **a})


# ALL HANDS: a quick question, a picture or a Claude chat - every agent who's not on a job pitches in
HANDS_LINES = {
    "shop": {"Atlas": "Let's get this right - check your sources.", "Nova": "Searching the web...", "Sage": "Checking the official spec...",
             "Sentry": "I'll compare the answers.", "Bolt": "Running the numbers...", "Echo": "Writing it up clean...", "Rook": "Lining up the results..."},
    "pic": {"Atlas": "Picture job - on it.", "Echo": "Describing the scene...", "Rook": "Setting up the canvas..."},
    "chat": {"Atlas": "Watching Claude work.", "Nova": "Claude's thinking...", "Sentry": "Standing by to check it."}}
HANDS_AT = {"shop": "boss", "pic": "code", "chat": "boss"}


def all_hands(kind, on=True):
    for n, a in agents.items():
        if a.get("job"):
            continue                                    # he's on a real job - leave him be
        if on:
            a["hands"] = kind
            set_agent(n, HANDS_AT.get(kind, "boss"), "working", None, text=HANDS_LINES.get(kind, {}).get(n, "Helping out..."))
        elif a.get("hands") == kind:
            a.pop("hands", None)
            set_agent(n, "idle", "idle", None)


def set_engine(status, detail=""):
    if engine_state["status"] != status or engine_state["detail"] != detail:
        engine_state.update(status=status, detail=detail)
        hub.send({"type": "engine", "engine": engine_state})


def job_summary(j):
    return {
        "id": j["id"], "task": j["task"][:300], "status": j["status"],
        "created": j["created"], "finished": j.get("finished"),
        "done": sum(1 for s in j["subtasks"] if s["status"] in ("done", "failed")),
        "total": len(j["subtasks"]),
        "subtasks": [{k: s.get(k) for k in ("title", "station", "worker", "status", "review", "tries")}
                     for s in j["subtasks"]],
        "output_file": j.get("output_file"), "error": j.get("error"),
        "claude_check": j.get("claude_check", []),
    }


def push_job(j):
    hub.send({"type": "job", "job": job_summary(j)})


# ------------------------------------------------------------------- files --
def safe_path(p: str) -> Path:
    rp = Path(os.path.expandvars(p.strip().strip('"'))).expanduser().resolve()
    for a in ALLOWED:
        if rp == a or a in rp.parents:
            return rp
    raise PermissionError(f"{rp} is outside the crew's allowed folders")


def list_folder(folder: str, cap=300):
    root = safe_path(folder)
    if not root.is_dir():
        raise FileNotFoundError(f"No folder at {root}")
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                out.append((str(p), p.stat().st_size))
            except OSError:
                continue
            if len(out) >= cap:
                return out
    return out


def read_text_file(p: str) -> str:
    rp = safe_path(p)
    with open(rp, "rb") as f:
        raw = f.read(CFG["max_file_chars"] * 4)
    if b"\x00" in raw[:4096]:
        return f"[{rp.name} looks like a binary file - skipped]"
    text = raw.decode("utf-8", errors="replace")
    if len(text) > CFG["max_file_chars"]:
        text = text[: CFG["max_file_chars"]] + "\n...[cut off, file too long]"
    return text


# ------------------------------------------------------------------ engine --
def find_engine():
    ed = HERE / ("engine" if HAS_NVIDIA else "engine_vulkan")
    for p in (ed / "llama-server.exe", ed / "llama-server"):
        if p.exists():
            return str(p)
    return shutil.which("llama-server")


def model_cache_gb():
    """How much of the brain has downloaded so far (for the progress readout)."""
    roots = [Path(os.environ.get("LLAMA_CACHE", "")) if os.environ.get("LLAMA_CACHE") else None,
             Path(os.environ.get("LOCALAPPDATA", "")) / "llama.cpp",
             Path.home() / ".cache" / "llama.cpp", Path.home() / ".cache" / "huggingface" / "hub"]
    tot, word = 0, CFG.get("cache_word", "qwen")   # only count THIS brain's files
    for r in roots:
        if r and r.exists():
            for f in r.rglob("*"):
                try:
                    if f.is_file() and word in str(f).lower():
                        tot += f.stat().st_size
                except OSError:
                    pass
    return tot / 1e9


# ---- borrow the OTHER PC's brain (a laptop -> the desktop's GPU), over the Tailscale link the 📁 sync already set up ----
REMOTE = None      # {"peer", "url", "key", "brain", "label"} when this PC is using the other PC's brain


def engine_base():
    return f"{REMOTE['url']}/engine" if REMOTE else ENGINE


def engine_hdr():
    return {"X-Crew-Key": REMOTE["key"]} if REMOTE else {}


def peer_by_name(name=None):
    peers = filesync.CFG.get("peers") or []
    return next((p for p in peers if not name or p["name"] == name), None)


async def engine_health(session):
    try:
        async with session.get(f"{engine_base()}/health", headers=engine_hdr(),
                               timeout=ClientTimeout(total=10 if REMOTE else 3)) as r:
            return r.status   # 200 ready, 503 still loading
    except Exception:
        return None


async def ensure_remote(session, wait=True):
    """Using the other PC's brain: just check it's up (it starts/loads itself over there)."""
    t0 = time.time()
    while True:
        st = await engine_health(session)
        if st == 200:
            set_engine("ready", MODEL_LABEL)
            return True
        if st is None:
            set_engine("failed", f"can't reach {REMOTE['peer']} - is it on with FreedomOS running + Tailscale on?")
            return False
        set_engine("loading", f"{REMOTE['peer']} is loading {REMOTE['label']}...")
        if not wait or time.time() - t0 > 1800:
            return False
        await asyncio.sleep(4)


def engine_args(exe):
    model = ["-hfr", CFG["model_hf"], "-hff", CFG["model_file"]] if CFG.get("model_file") else ["-hf", CFG["model_hf"]]
    a = [exe, *model, "--host", "127.0.0.1", "--port", str(CFG["engine_port"]),
         "-c", str(CFG["context_total"]), "--parallel", str(CFG["parallel"])]
    moe = CFG.get("cpu_moe_layers", "auto")
    if str(moe) != "auto":                                  # manual split (auto lets llama.cpp fit it to your GPU itself)
        a += ["-ngl", "999", "--n-cpu-moe", str(moe)]
    elif CFG.get("gpu_layers") is not None:                 # laptop: put the whole brain on the Intel graphics
        a += ["-ngl", str(CFG["gpu_layers"])]
    a += ["-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0",       # smaller scratch memory
          "--load-mode", "none",                             # load the brain into RAM, don't read it off the SSD every time
          "--no-mmproj",                                     # skip the picture-reading add-on - frees video memory
          "--jinja", "-t", str(CFG["threads"]),
          "--temp", "0.7", "--top-p", "0.8", "--top-k", "20", "--min-p", "0"]
    if CFG.get("no_reasoning"):                             # Bonsai: server stays on auto, each request says "none"
        a += ["--reasoning", "auto"]
    a += [str(x) for x in CFG.get("extra_engine_args", [])]
    # settings this llama.cpp build said it doesn't know: renamed or dropped (see heal_engine_args)
    fixes = engine_fixes()
    out, i = [], 0
    while i < len(a):
        flag = a[i]
        if flag in fixes:
            new = fixes[flag]
            takes_value = i + 1 < len(a) and not a[i + 1].startswith("-")
            if new:
                out.append(new)
                if takes_value: out.append(a[i + 1])
            i += 2 if takes_value else 1
            continue
        out.append(flag); i += 1
    return out


FIX_FILE = LOG_DIR.parent / "engine_fixes.json"
# when a newer llama.cpp renames a setting, try these spellings next (None = just drop it)
ALIASES = {"--load-mode": [None], "--no-mmproj": [None],
           "--n-cpu-moe": ["-ncmoe", "--cpu-moe-layers"], "-fa": ["--flash-attn"], "-ctk": ["--cache-type-k"],
           "-ctv": ["--cache-type-v"], "--parallel": ["-np"], "-ngl": ["--n-gpu-layers"], "--jinja": [None],
           "--min-p": [None], "--top-k": [None], "--top-p": [None], "--temp": [None]}


def engine_fixes():
    try:
        return json.loads(FIX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def heal_engine_args():
    """Read why the engine quit. If it didn't know a setting, swap in the next known spelling or drop it.
    Returns True if something was fixed (so it's worth starting again)."""
    try:
        tail = (LOG_DIR / "engine.log").read_text(encoding="utf-8", errors="replace")[-4000:]
    except OSError:
        return False
    last_start = tail.rfind("==== ")
    found = re.findall(r"(?:invalid argument|unknown argument|unrecognized (?:option|argument))[:\s]+'?(-{1,2}[\w-]+)", tail[last_start:])
    if not found:
        return False
    bad = found[-1]
    fixes = engine_fixes()
    original = next((k for k, v in fixes.items() if v == bad), bad)   # the setting we first asked for
    tried = fixes.get("_tried_" + original, [])
    options = [o for o in ALIASES.get(original, [None]) if o not in tried]
    nxt = options[0] if options else None
    fixes[original] = nxt
    fixes["_tried_" + original] = tried + [nxt]
    FIX_FILE.write_text(json.dumps(fixes, indent=1), encoding="utf-8")
    log(f"Engine didn't know '{bad}' - " + (f"trying '{nxt}' instead." if nxt else "dropping it.") + " Restarting the brain.")
    return True


_engine_lock = asyncio.Lock()


async def ensure_engine(session, wait=True):
    """Make sure the brain is running. Starts it if needed. Returns True when ready."""
    global engine_proc
    if REMOTE:
        return await ensure_remote(session, wait)
    if pixelshop.owns_gpu():
        set_engine("off", "parked - the Pixel Shop has the GPU (Close shop to wake it)")
        return False
    async with _engine_lock:
        st = await engine_health(session)
        want = " ".join(engine_args(find_engine() or "llama-server"))
        stamp = LOG_DIR / "engine_settings.txt"
        if st == 200 and engine_proc is None:
            # a brain is already running that WE didn't start - make sure it has today's settings
            had = stamp.read_text(encoding="utf-8") if stamp.exists() else ""
            if had.split(" ", 1)[-1] != want.split(" ", 1)[-1]:
                log("Old brain's running with old settings - swapping it out for the new tune.")
                set_engine("loading", "swapping in the faster brain settings...")
                kill_engine()
                for _ in range(30):
                    await asyncio.sleep(1)
                    st = await engine_health(session)
                    if st is None:
                        break
        if st == 200:
            set_engine("ready", MODEL_LABEL)
            return True
        if st is None and (engine_proc is None or engine_proc.poll() is not None):
            if pixelshop.owns_gpu():
                set_engine("off", "parked - the Pixel Shop has the GPU (Close shop to wake it)")
                return False
            exe = find_engine()
            if not exe:
                set_engine("failed", "llama.cpp engine missing - run 'FreedomOS Setup' from the Start menu")
                log("!! No llama-server found. Run 'FreedomOS Setup' from the Start menu to install it.")
                return False
            flags = 0
            if IS_WIN:
                flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            logf = open(LOG_DIR / "engine.log", "a", encoding="utf-8")
            logf.write(f"\n==== {time.ctime()} starting: {' '.join(engine_args(exe))}\n")
            logf.flush()
            stamp.write_text(" ".join(engine_args(exe)), encoding="utf-8")
            engine_proc = subprocess.Popen(engine_args(exe), cwd=str(Path(exe).parent), stdout=logf,
                                           stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                           creationflags=flags)
            log(f"Started the brain: {MODEL_LABEL} (split: {CFG.get('cpu_moe_layers', 'auto')})")
    if not wait:
        return False
    # wait for download + load (first time can be a long while)
    while True:
        if pixelshop.owns_gpu():   # the Pixel Shop opened while we were waiting - stand down
            kill_engine()
            set_engine("off", "parked - the Pixel Shop has the GPU (Close shop to wake it)")
            return False
        st = await engine_health(session)
        if st == 200:
            set_engine("ready", MODEL_LABEL)
            log("Brain's loaded. Ready to work.")
            return True
        if engine_proc is not None and engine_proc.poll() is not None and st is None:
            heals = getattr(ensure_engine, "heals", 0)
            if heals < 8 and heal_engine_args():
                ensure_engine.heals = heals + 1
                set_engine("loading", "fixing an engine setting and restarting...")
                return await ensure_engine(session, wait)
            set_engine("failed", "brain crashed on startup - check logs/engine.log")
            log("!! Engine died. Last lines of logs/engine.log will say why (often: not enough VRAM -> raise cpu_moe_layers).")
            return False
        gb = model_cache_gb()
        if st is None and gb < CFG.get("model_download_gb", 23) * 0.97:
            set_engine("downloading", f"{gb:.1f} / ~{CFG.get('model_download_gb', 23)} GB")
        else:
            set_engine("loading", "loading the brain into the GPU + RAM...")
        await asyncio.sleep(2)


def _strip_think(s: str) -> str:
    return re.sub(r"<think>.*?</think>", "", s, flags=re.S).strip()


HANDBOOK_FILE = HERE / "crew handbook.txt"
_HB = {"mtime": 0, "text": ""}


def handbook():
    """The crew handbook (what the brains know about YOU and how you like things). Re-read when edited."""
    try:
        m = HANDBOOK_FILE.stat().st_mtime
        if m != _HB["mtime"]:
            _HB.update(mtime=m, text=HANDBOOK_FILE.read_text(encoding="utf-8", errors="replace").strip()[:8000])
    except OSError:
        _HB.update(mtime=0, text="")
    return _HB["text"]


def with_handbook(messages):
    hb = handbook()
    if not hb:
        return messages
    out, done = [], False
    for m in messages:
        if m.get("role") == "system" and not done:
            m = dict(m, content=m["content"] + "\n\n---\nCREW HANDBOOK (stuff you know about the user - follow it):\n" + hb)
            done = True
        out.append(m)
    return out


async def chat(session, messages, json_mode=False, max_tokens=3000, on_text=None, think=False, temp=None, handbook=False):
    """Talk to the brain. If the line drops before any words come back, ring again (up to 3 tries)."""
    import aiohttp
    if handbook:
        messages = with_handbook(messages)
    for attempt in range(3):
        try:
            return await _chat_once(session, messages, json_mode, max_tokens, on_text, think, temp)
        except (aiohttp.ServerDisconnectedError, aiohttp.ClientOSError, ConnectionResetError) as e:
            if attempt == 2:
                raise
            log(f"   brain line dropped ({type(e).__name__}) - ringing again")
            await asyncio.sleep(1 + attempt)


async def _chat_once(session, messages, json_mode=False, max_tokens=3000, on_text=None, think=False, temp=None):
    """Talk to the brain (OpenAI-style API on llama-server). Streams words to the widget."""
    body = {"messages": messages, "stream": True, "max_tokens": max_tokens,
            "temperature": temp if temp is not None else (0.6 if think else 0.7),
            "chat_template_kwargs": {"enable_thinking": bool(think)}}
    if CFG.get("no_reasoning"):           # Bonsai 2: thinking is switched by reasoning_effort, and it wants ONE system message up top
        body["reasoning_effort"] = "medium" if think else "none"
        sysm = "\n\n".join(m["content"] for m in messages if m.get("role") == "system") or "You are a helpful assistant"
        body["messages"] = [{"role": "system", "content": sysm}] + [m for m in messages if m.get("role") != "system"]
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    buf, last_push = [], 0.0
    async with session.post(f"{engine_base()}/v1/chat/completions", json=body,
                            headers=dict(engine_hdr(), Connection="close"),   # fresh line every call, no stale hang-ups
                            timeout=ClientTimeout(total=1800, sock_read=600)) as r:
        if r.status != 200:
            raise RuntimeError(f"Brain said {r.status}: {(await r.text())[:300]}")
        async for raw in r.content:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            d = json.loads(data)
            if d.get("error"):
                raise RuntimeError(str(d["error"]))
            ch = (d.get("choices") or [{}])[0]
            delta = ch.get("delta") or {}
            piece = delta.get("content") or ""
            if piece:
                buf.append(piece)
            if on_text and time.time() - last_push > 0.35:
                last_push = time.time()
                shown = "".join(buf) or ("(thinking...) " + (delta.get("reasoning_content") or ""))
                on_text(shown)
    return _strip_think("".join(buf))


def parse_json(s: str):
    s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def tail(s: str, n=110):
    return " ".join(s.split())[-n:]


# --------------------------------------------------------------- the work --
free_workers: asyncio.Queue = None


async def plan_job(session, job, file_list):
    files_txt = ""
    if file_list:
        files_txt = "\n\nFILE LIST (full paths, size in bytes):\n" + "\n".join(f"{p} ({sz})" for p, sz in file_list)
    sys_prompt = (
        f"You are {BOSS}, boss of a crew of {len(WORKERS)} AI workers ({', '.join(WORKERS)}) who work AT THE SAME TIME. "
        f"Split the job into 1 to {CFG['max_subtasks']} pieces that can be done independently and in parallel. "
        f"Prefer {len(WORKERS)} pieces when the job is big enough; small jobs = 1 piece. "
        "Never make a piece that needs another piece's answer.\n"
        "Each piece has:\n"
        '  "title": short name (max 6 words)\n'
        '  "station": one of "read" (reading/summarizing/researching files), "code" (writing or fixing code), '
        '"write" (writing text, emails, docs, explanations), "sort" (sorting, listing, organizing, comparing, data)\n'
        '  "instructions": clear, complete, self-contained instructions, including what a GOOD answer must contain\n'
        f'  "files": full file paths from the FILE LIST this piece needs (max {CFG["max_files_per_subtask"]}, can be empty)\n'
        'Reply with ONLY JSON like {"subtasks":[{"title":"...","station":"read","instructions":"...","files":[]}]}'
    )
    set_agent(BOSS, "boss", "planning", job["id"], text="Okay team, here's the plan...")
    raw = await chat(session, [{"role": "system", "content": sys_prompt},
                               {"role": "user", "content": f"JOB: {job['task']}{files_txt}"}],
                     json_mode=True, max_tokens=2000,
                     on_text=lambda t: set_agent(BOSS, "boss", "planning", job["id"], text=tail(t)), handbook=True)
    known = {p for p, _ in file_list}
    subs = []
    try:
        data = parse_json(raw)
        items = data.get("subtasks") if isinstance(data, dict) else data
        for it in (items or [])[: CFG["max_subtasks"]]:
            st = it.get("station", "write")
            files = [f for f in (it.get("files") or []) if isinstance(f, str) and (not known or f in known)]
            subs.append({"title": str(it.get("title", "piece"))[:60],
                         "station": st if st in ("read", "code", "write", "sort") else "write",
                         "instructions": str(it.get("instructions", job["task"])),
                         "files": files[: CFG["max_files_per_subtask"]],
                         "worker": None, "status": "waiting", "output": "", "review": None, "tries": 0})
    except Exception as e:
        log(f"Plan didn't parse ({e}); doing it as one piece.")
    if not subs:
        subs = [{"title": "Whole job", "station": "write", "instructions": job["task"],
                 "files": [p for p, _ in file_list][: CFG["max_files_per_subtask"]],
                 "worker": None, "status": "waiting", "output": "", "review": None, "tries": 0}]
    return subs


async def review_piece(session, job, sub):
    """The checker grades a worker's piece. Returns (ok, notes)."""
    set_agent(CHECKER, sub["station"], "checking", job["id"], text=f"Lemme see that, {sub['worker']}...")
    await asyncio.sleep(0.8)  # let him stomp over
    raw = await chat(session, [
        {"role": "system", "content": f"You are {CHECKER}, the crew's strict but fair quality inspector. Check a worker's piece of a job. "
         "Look for: wrong facts, missed instructions, made-up stuff, broken or incomplete code, lazy short answers. "
         "The crew CANNOT draw or make pictures - if the piece claims it made, drew, generated or embedded an image "
         "(or has base64 / image data in it), FAIL it and say pictures come from the Pixel Shop. "
         'Reply with ONLY JSON: {"ok": true/false, "notes": "what is wrong and exactly how to fix it (empty if ok)"}'},
        {"role": "user", "content": f"OVERALL JOB: {job['task']}\n\nPIECE: {sub['title']}\nINSTRUCTIONS: {sub['instructions']}"
         f"\n\nWORKER'S ANSWER:\n{sub['output'][:20000]}"},
    ], json_mode=True, max_tokens=800,
        on_text=lambda t: set_agent(CHECKER, sub["station"], "checking", job["id"], text=tail(t)), handbook=True)
    try:
        d = parse_json(raw)
        ok, notes = bool(d.get("ok", True)), str(d.get("notes", ""))
    except Exception:
        ok, notes = True, ""
    set_agent(CHECKER, sub["station"], "done" if ok else "failed", job["id"],
              text="Passes. Barely." if ok else "This is garbage. Do it again!")
    if not ok and notes:
        first = re.split(r"(?<=[.!?])\s", notes.strip())[0][:80]
        hub.send({"type": "say", "name": CHECKER, "secs": 4.5,
                  "text": f"{sub['worker']}, needs another pass: {first}"})
    return ok, notes


async def do_piece(session, job, sub, name, notes=""):
    station = sub["station"]
    file_blob = ""
    for f in sub["files"]:
        set_agent(name, "read", "reading", job["id"], text=f"Reading {Path(f).name}...")
        await asyncio.sleep(0.6)
        try:
            file_blob += f"\n\n=== FILE: {f} ===\n{read_text_file(f)}"
        except Exception as e:
            file_blob += f"\n\n=== FILE: {f} ===\n[couldn't read: {e}]"
    msg = f"Redoing it... the {CHECKER}'s mad" if notes else f"On it: {sub['title']}"
    set_agent(name, station, "working", job["id"], text=msg)
    user = (f"OVERALL JOB: {job['task']}\n\nYOUR PIECE: {sub['title']}\n"
            f"INSTRUCTIONS: {sub['instructions']}{file_blob}")
    msgs = [{"role": "system", "content": f"You are {name}, a worker on {BOSS}'s crew. Do ONLY your piece of the job, "
             f"do it well and completely, be clear and practical. The {CHECKER} will check it."},
            {"role": "user", "content": user}]
    if notes:
        msgs += [{"role": "assistant", "content": sub["output"]},
                 {"role": "user", "content": f"The {CHECKER} sent it back. His notes: {notes}\n"
                  "Redo the WHOLE piece with those fixed."}]
    return await chat(session, msgs, max_tokens=4000,
                      on_text=lambda t: set_agent(name, station, "working", job["id"], text=tail(t)), handbook=True)




ALL_CAST = [BOSS] + WORKERS + [CHECKER]










MEM_DIR = HERE / "memory"
























improv_state = {"last": 0.0, "busy": False}




IDLE = {"since": 0}


def busy_now():
    return any(j["status"] in ("queued", "planning", "working", "merging") for j in jobs.values())




TRAY = {"on": False}

# 🧠 the brain switch. ON = stays loaded. OFF = unloaded, but a question or a job
#    wakes it up for that and it goes back off a minute after.
_SW_FILE = Path(__file__).resolve().parent / "logs" / "brain_switch.txt"
try:
    BRAIN_SW = {"on": _SW_FILE.read_text(encoding="utf-8").strip() != "off"}
except Exception:
    BRAIN_SW = {"on": True}
# 🚀 a fresh start (not an update restart) = brain OFF. The boot id tells the windows it's a fresh start.
_BOOT_FILE = _SW_FILE.parent / "boot_id.txt"
if not os.environ.get("F35_RESTARTED"):                 # fresh start = brain OFF (cool + quiet), wallpaper on
    BRAIN_SW["on"] = False
    try:
        _SW_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SW_FILE.write_text("off", encoding="utf-8")
        _BOOT_FILE.write_text(str(int(time.time())), encoding="utf-8")
    except Exception:
        pass
try:
    BOOT_ID = _BOOT_FILE.read_text(encoding="utf-8").strip()
except Exception:
    BOOT_ID = "0"


def ensure_autostart():
    """FreedomOS (quiet, in the tray) + Tailscale start with Windows. Your own sign-in only - no admin needed."""
    if not IS_WIN:
        return
    try:
        import winreg
        here = Path(__file__).resolve().parent
        pyw = here / "venv" / "Scripts" / "pythonw.exe"
        if not pyw.exists():
            return
        vbs = here / "FreedomOS startup.vbs"
        # no PC-specific paths in here: the file syncs between the laptop + desktop, so it finds its own folder
        want = ('Set sh = CreateObject("WScript.Shell")\r\n'
                'here = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)\r\n'
                'sh.CurrentDirectory = here\r\n'
                'WScript.Sleep 20000\r\n'                                   # give Wi-Fi + Tailscale a sec
                'sh.Run """" & here & "\\venv\\Scripts\\pythonw.exe"" """ & here & "\\boss.py""", 0, False\r\n')
        if not vbs.exists() or vbs.read_text(encoding="mbcs", errors="ignore") != want:
            vbs.write_text(want, encoding="mbcs", newline="")
        run = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            cmd = f'wscript.exe "{vbs}"'
            try:
                have = winreg.QueryValueEx(k, "FreedomOS")[0]
            except OSError:
                have = ""
            if have != cmd:
                winreg.SetValueEx(k, "FreedomOS", 0, winreg.REG_SZ, cmd)
                log("🚀 FreedomOS now starts with Windows (quiet, in the tray)")
            ts = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale-ipn.exe"
            if ts.exists():
                try:
                    winreg.QueryValueEx(k, "Tailscale")
                except OSError:
                    winreg.SetValueEx(k, "Tailscale", 0, winreg.REG_SZ, f'"{ts}"')
                    log("🚀 Tailscale now starts with Windows")
    except Exception as e:
        log(f"(couldn't set up start-with-Windows: {e})")


async def h_brain_switch(request):
    if request.method == "POST":
        try:
            on = bool((await request.json()).get("on"))
        except Exception:
            on = not BRAIN_SW["on"]
        BRAIN_SW["on"] = on
        try:
            _SW_FILE.parent.mkdir(parents=True, exist_ok=True)
            _SW_FILE.write_text("on" if on else "off", encoding="utf-8")
        except Exception:
            pass
        log("🧠 Brain switched ON - stays loaded" if on else "🧠 Brain switched OFF - wakes up just for questions + jobs")
        if on and engine_state["status"] in ("off", "error") and not pixelshop.owns_gpu():
            async def warm():
                async with ClientSession() as s:
                    await ensure_engine(s, wait=False)
            asyncio.get_running_loop().create_task(warm())
        elif not on and not busy_now() and not improv_state["busy"] and not REMOTE and engine_state["status"] in ("ready", "loading"):
            kill_engine()
            set_engine("off", "switched off - wakes up for questions + jobs")
        hub.send({"type": "brainsw", "on": BRAIN_SW["on"]})
    return web.json_response({"ok": True, "on": BRAIN_SW["on"], "boot": BOOT_ID})


def tray_thread(loop):
    """FreedomOS lives in the tray: closing the window just tucks it away. Quit here to shut it down for real."""
    try:
        import pystray
        from pystray import MenuItem as I, Menu
        from PIL import Image
    except Exception as e:
        log(f"(no tray icon: {e})")
        return
    try:
        im = Image.open(HERE / "widget" / "icon-192.png").convert("RGBA").resize((64, 64))
    except Exception:
        im = Image.new("RGBA", (64, 64), (60, 120, 60, 255))

    def open_win(*_):
        if f35web.open_app():
            return
        subprocess.Popen(f'start "" msedge --app=http://127.0.0.1:{PORT}/ --window-size=1180,680', shell=True)

    def music(*_):
        asyncio.run_coroutine_threadsafe(f35music.control("open"), loop)

    def quit_all(*_):
        icon.stop()
        asyncio.run_coroutine_threadsafe(shutdown_soon("you quit from the tray"), loop)

    status = lambda _: ("🧰 working on a job" if busy_now() else "🧠 brain on" if BRAIN_SW["on"] else "💤 brain resting") + \
        (" · window closed" if not hub.subs else "")
    icon = pystray.Icon("FreedomOS", im, "FreedomOS", Menu(
        I("Open FreedomOS", open_win, default=True), I(status, None, enabled=False), Menu.SEPARATOR,
        I("🎧 WiMix", music), I("🌐 WiBro", lambda *_: f35web.open_browser("")), Menu.SEPARATOR, I("Quit FreedomOS (for real)", quit_all)))
    TRAY["on"] = True
    icon.run()
    TRAY["on"] = False


async def _browser_soon():
    await asyncio.sleep(25)                       # let FreedomOS get on its feet first
    await f35web.ensure_built("startup")


async def nap_loop():
    """Brain switch off: after a question or job is done, the brain goes back to sleep a minute later."""
    while True:
        await asyncio.sleep(20)
        try:
            if not BRAIN_SW["on"] and not busy_now() and not improv_state["busy"] and not REMOTE \
                    and engine_state["status"] == "ready" and time.time() - max(last_activity, IDLE["since"]) > 60:
                kill_engine()
                set_engine("off", "switched off - wakes up for questions + jobs")
                log("🧠 Done working - brain switched back off")
        except Exception as e:
            log(f"(nap hiccup: {e})")






# ------------------------------------------------------------ quick answers --
# Ask a quick question (a spec, a number, what a code means...) -> quick web search -> brain reads it -> just the number.
ASK_FILE = HERE / "memory" / "asks.json"
ASK_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _load_asks():
    try:
        return json.loads(ASK_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


asks = _load_asks()


def _html_text(h):
    import html as _h
    h = re.sub(r"(?is)<(script|style|noscript|svg|head|nav|footer)[^>]*>.*?</\1>", " ", h)
    h = _WS.sub(" ", h)                                     # the page's own line breaks mean nothing
    h = re.sub(r"(?i)<(br|p|div|li|tr|h\d|dt)[^>]*>", "\n", h)
    h = re.sub(r"(?i)<(td|th|dd)[^>]*>", " | ", h)          # keep a table row on one line: "spindle nut | 181 | 245"
    return _h.unescape(_TAG.sub(" ", h))


WEB_ERR = {"last": ""}


async def _get(session, url, secs, data=None):
    try:
        kw = dict(headers={"User-Agent": ASK_UA, "Accept-Language": "en-US,en;q=0.9"}, timeout=ClientTimeout(total=secs), ssl=None)
        async with (session.post(url, data=data, **kw) if data else session.get(url, **kw)) as r:
            if r.status != 200:
                WEB_ERR["last"] = f"{url.split('/')[2]} said {r.status}"
                return ""
            return (await r.content.read(400_000)).decode("utf-8", "ignore")
    except Exception as e:
        WEB_ERR["last"] = f"{url.split('/')[2]}: {type(e).__name__} {str(e)[:80]}"
        return ""


async def web_search(session, q):
    """Top results - tries twice (a Wi-Fi blip or a slow DNS shouldn't kill a quick question)."""
    out = await _web_search_once(session, q, 4)
    if not out:
        await asyncio.sleep(1)
        out = await _web_search_once(session, q, 8)
        if not out:
            log(f"(web search came back empty twice: {WEB_ERR['last'] or 'no results'})")
    return out


async def _web_search_once(session, q, secs):
    """Top results as [(title, url, snippet)]. DuckDuckGo first, Bing if that comes back empty."""
    import html as _h
    from urllib.parse import unquote, quote_plus
    out = []
    page = await _get(session, "https://html.duckduckgo.com/html/", secs, data={"q": q})
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>', page, re.S):
        url = m.group(1)
        u = re.search(r"uddg=([^&]+)", url)
        url = unquote(u.group(1)) if u else url
        if "duckduckgo.com/y.js" in url:      # ads
            continue
        out.append((_h.unescape(_TAG.sub("", m.group(2))).strip(), url, _h.unescape(_TAG.sub("", m.group(3))).strip()))
    if not out:
        page = await _get(session, "https://www.bing.com/search?q=" + quote_plus(q) + "&setlang=en", secs)
        for m in re.finditer(r'<li class="b_algo".*?<a[^>]+href="(http[^"]+)"[^>]*>(.*?)</a>.*?<p[^>]*>(.*?)</p>', page, re.S):
            out.append((_h.unescape(_TAG.sub("", m.group(2))).strip(), m.group(1), _h.unescape(_TAG.sub("", m.group(3))).strip()))
    return out[:8]


SYNONYMS = {"axle": {"spindle", "driveshaft", "hub", "axle"}, "cv": {"spindle", "driveshaft", "axle"}, "lug": {"wheel"},
            "oil": {"capacity", "viscosity", "quart", "filter", "sae"}, "plug": {"spark", "drain"}, "caliper": {"bracket", "brake"},
            "trans": {"atf", "fluid", "capacity"}, "coolant": {"capacity", "antifreeze"}, "tire": {"psi", "pressure"}}


def _best_bits(text, q, limit=1400):
    """Pull the lines of a page that look like they hold the answer (question words + numbers)."""
    words = {w for w in re.findall(r"[a-z0-9]{3,}", q.lower())} - {"the", "what", "for", "and", "how", "much", "does", "with", "spec", "specs", "torque"}
    for k, extra in SYNONYMS.items():
        if k in q.lower():
            words |= extra
    keep, head = [], ""
    unit = re.compile(r"ft[-. ]?lbs?|lb[-. ]?ft|in[-. ]?lbs?|n[·.-]?m\b|quarts?|qts?|liters?|litres?|psi")
    for line in text.split("\n"):
        line = _WS.sub(" ", line).strip()
        if line.startswith("|") and unit.search(line.lower()) and not re.search(r"\d", line):
            head = line                                   # table header like "| Fastener | ft-lb | Nm" - stick it on the rows below
            continue
        if not (12 <= len(line) <= 400):
            continue
        if head and line.startswith("|"):
            line = f"{line}   [columns: {head}]"
        low = line.lower()
        score = sum(w in low for w in words) + (2 if re.search(r"\d", line) else 0) + \
            (2 if re.search(r"ft[-. ]?lb|n[·.-]?m|quart|qt|liter|litre|\bl\b|sae|\dw-?\d|psi|code|p0|p1|p2|u0|b0|c0", low) else 0)
        if score >= 3 and re.search(r"\d", line):
            keep.append((score, line))
    keep.sort(key=lambda x: -x[0])
    out, n = [], 0
    for _, l in keep:
        if n + len(l) > limit:
            break
        out.append(l); n += len(l)
    return "\n".join(out)


ASK_RULES = """You are a fast answer machine. The user is busy - give them the answer like Google's top box.
Reply ONLY JSON: {"memory": "...", "answer": "...", "extra": "...", "sure": "high" or "check", "values_seen": ["..."]}
- "memory": FIRST write what YOU remember the answer is (factory spec), before looking at the web results. "" if you don't know.
- "answer": JUST the answer, as short as possible. A spec = the number and units only (e.g. "185 ft-lb", "0W-20 · 4.4 qt w/ filter", "32 psi").
  A trouble code = what it means in under 10 words. Never a sentence when a number will do.
- "extra": optional, max ~25 words. Only what they'd actually need: e.g. "new nut, stake it", "varies by year - this is 2015-19", or for codes the
  2-3 most common fixes in order, cheapest first, separated by " · ". Empty string if nothing useful.
- "values_seen": every different value the web results give for this exact thing (e.g. ["181 lb-ft", "184 lb-ft", "134 lb-ft"]).
- "sure": "high" ONLY if ALL of these are true: two or more different sites give the SAME value, those pages are for this exact
  year range / generation, no page contradicts itself, ft-lb and Nm convert correctly (1 ft-lb = 1.356 Nm), and it matches your memory.
  Otherwise "check". Watch for junk spec sites that mix up Nm and ft-lb, list two values for one bolt, or show a different generation.
- If they disagree, answer with the most trustworthy value and put the others in "extra" like "other sites: 184 ft-lb; memory: 134 ft-lb".
  Torque specs that hold a wheel or brake on are critical - when in doubt say "check".
- No intro, no safety lecture, no "it depends" without a number."""


def spread_out(values):
    """True if the values don't agree (Nm turned into ft-lb first, ~1% wiggle room)."""
    got = []
    for v in values:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(n[·.-]?m)?", str(v).lower())
        if m:
            x = float(m.group(1)) / (1.356 if m.group(2) else 1)
            got.append(x)
    return bool(got) and (max(got) - min(got)) > 0.012 * max(got)


async def quick_answer(session, q):
    t0 = time.time()
    hits = await web_search(session, q)
    pages = []
    if hits:
        texts = await asyncio.gather(*[_get(session, u, 3) for _, u, _ in hits[:3]])
        for (title, url, _), page in zip(hits[:3], texts):
            bits = _best_bits(_html_text(page), q) if page else ""
            if bits:
                pages.append(f"[{title} - {url}]\n{bits}")
    web = ""
    if hits:
        web = "WEB RESULTS (search snippets):\n" + "\n".join(f"- {t}: {s}" for t, _, s in hits) + \
              ("\n\nFROM THE TOP PAGES:\n" + "\n\n".join(pages) if pages else "")
    srcs = [{"site": re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*", r"\1", u)), "url": u} for _, u, _ in hits[:3]]
    brain_ok = (not pixelshop.owns_gpu()) and engine_state["status"] == "ready"
    if not brain_ok and not pixelshop.owns_gpu():          # brain's still waking up? give it a bit instead of quitting
        try:
            brain_ok = await asyncio.wait_for(ensure_engine(session), 45)
        except asyncio.TimeoutError:
            brain_ok = False
    if not brain_ok:
        if not pixelshop.owns_gpu():
            async def _wake():
                async with ClientSession() as s2:
                    await ensure_engine(s2, wait=False)
            asyncio.get_running_loop().create_task(_wake())   # wake him up for next time
        if not hits:
            return {"answer": "No web and the brain's asleep", "extra": "Couldn't reach the internet or the brain. Check Wi-Fi, then try again.", "sure": "check", "sources": [], "secs": round(time.time() - t0, 1)}
        t, u, s = hits[0]
        return {"answer": s[:160], "extra": "Raw top search result - the brain's still waking up (or the Pixel Shop has the GPU).",
                "sure": "check", "sources": srcs, "secs": round(time.time() - t0, 1)}
    raw = await chat(session, [{"role": "system", "content": ASK_RULES},
                               {"role": "user", "content": (web[:6000] + "\n\n" if web else "(no web results - answer from memory, sure=check)\n\n") + "QUESTION: " + q}],
                     json_mode=True, max_tokens=300, think=False, temp=0.1, handbook=True)
    d = parse_json(raw)
    sure = "high" if str(d.get("sure", "")).lower() == "high" and hits else "check"
    nums = lambda x: set(re.findall(r"\d+(?:\.\d+)?", str(x)))
    seen = {str(v) for v in (d.get("values_seen") or []) if str(v).strip()}
    mem, ans_n = str(d.get("memory") or "").strip(), nums(d.get("answer"))
    if spread_out(seen):                                           # sites gave different numbers
        sure = "check"
    if mem and ans_n and not (nums(mem) & ans_n):                  # brain's memory disagrees with the web
        sure = "check"
        if mem.lower() not in str(d.get("extra", "")).lower():
            d["extra"] = (str(d.get("extra") or "") + f" · brain remembers: {mem}").strip(" ·")
    return {"answer": str(d.get("answer", "")).strip()[:160] or "Couldn't find it", "extra": str(d.get("extra", "")).strip()[:260],
            "sure": sure, "sources": srcs if hits else [], "secs": round(time.time() - t0, 1), "web": bool(hits)}


# ---- THE CREW DOUBLE-CHECK: a ⚠ answer? Every agent looks it up THEIR way and they vote. ------------------------------
CHECK_ANGLE = {"Atlas": "official manual", "Nova": "forum", "Echo": "specifications chart",
               "Bolt": "", "Sentry": "manufacturer spec", "Sage": "official documentation", "Rook": "comparison table"}
CHECK_RULES = """You are double-checking ONE quick answer for the user, using only the pages below and what you know.
Reply ONLY JSON: {"answer": "...", "says": "...", "site": "..."}
- "answer": just the value/meaning, as short as possible (e.g. "185 ft-lb", "0W-20 · 4.4 qt"). "" if you truly can't tell.
- "says": one short line IN CHARACTER (under 12 words) about what you found.
- "site": the site you trusted most ("" if from memory)."""


def _to_num(v, unit_hint=""):
    """'250 Nm' -> 184.4 (ft-lb) so different units can be compared."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(n[·.-]?m)?", str(v).lower())
    if not m:
        return None
    x = float(m.group(1))
    return x / 1.356 if m.group(2) else x


def _same(a, b):
    x, y = _to_num(a), _to_num(b)
    if x is not None and y is not None:
        return abs(x - y) <= 0.015 * max(x, y, 1)
    return re.sub(r"\W", "", str(a).lower())[:24] == re.sub(r"\W", "", str(b).lower())[:24]


async def crew_check(q, first):
    """Every guy searches his own way and gives his answer. Then they vote. Sends events so the Home screen + answer box update live."""
    cast = [n for n in ALL_CAST if n in PERSONA]                 # all hands on deck - every guy checks it
    hub.send({"type": "askcheck", "stage": "start", "q": q, "cast": cast, "first": first.get("answer", "")})
    votes = []

    async def one(session, name, k):
        angle = CHECK_ANGLE.get(name, "")
        hits = await web_search(session, (q + " " + angle).strip())
        if not angle:                                             # the agent with no angle reads the results the others skipped
            hits = hits[3:6] or hits
        pages = []
        texts = await asyncio.gather(*[_get(session, u, 3) for _, u, _ in hits[:2]])
        for (title, url, _), page in zip(hits[:2], texts):
            bits = _best_bits(_html_text(page), q, 900) if page else ""
            if bits:
                pages.append(f"[{title} - {url}]\n{bits}")
        web_txt = "\n".join(f"- {t}: {s}" for t, _, s in hits[:5]) + ("\n\n" + "\n\n".join(pages) if pages else "")
        try:
            raw = await chat(session, [{"role": "system", "content": f"You are {name}: {PERSONA[name]}\n\n" + CHECK_RULES},
                                       {"role": "user", "content": (web_txt[:3500] or "(no web results)") + "\n\nQUESTION: " + q}],
                             json_mode=True, max_tokens=160, think=False, temp=0.2, handbook=True)
            d = parse_json(raw)
        except Exception:
            d = {}
        v = {"who": name, "answer": str(d.get("answer", "")).strip()[:80], "says": str(d.get("says", "")).strip()[:100],
             "site": str(d.get("site", "")).strip()[:60]}
        votes.append(v)
        hub.send({"type": "askcheck", "stage": "vote", "q": q, "vote": v})
        return v

    async with ClientSession() as session:
        await asyncio.gather(*[one(session, n, i) for i, n in enumerate(cast)], return_exceptions=True)
    real = [v for v in votes if v["answer"]]
    groups = []
    for v in real:
        g = next((g for g in groups if _same(g[0]["answer"], v["answer"])), None)
        (g.append(v) if g else groups.append([v]))
    groups.sort(key=len, reverse=True)
    top = groups[0] if groups else []
    n, total = len(top), len(cast)
    agrees_first = bool(top) and _same(top[0]["answer"], first.get("answer", ""))
    if top and n >= max(3, total - 1) and agrees_first:
        verdict, sure = "agree", "high"
    elif top and n >= 3 and not agrees_first:
        verdict, sure = "different", "check"
    else:
        verdict, sure = "split", "check"
    res = {"verdict": verdict, "count": n, "total": total, "answer": top[0]["answer"] if top else "", "votes": votes, "sure": sure, "when": time.time()}
    hub.send({"type": "askcheck", "stage": "done", "q": q, "check": res})
    log(f"Crew check: {q[:50]} -> {verdict} ({n}/{total}) {res['answer'][:40]}")
    return res




async def run_crew_check(q, first):
    global asks
    try:
        res = await crew_check(q, first)
    except Exception as e:
        log(f"(crew check fumbled: {e})")
        return
    finally:
        all_hands("shop", False)
    for a in asks:
        if a["q"].lower() == q.lower():
            a["crew"] = res
            if res["sure"] == "high":
                a["sure"] = "high"                # the whole crew backs it - trust it next time (instant)
            break
    try:
        ASK_FILE.write_text(json.dumps(asks, indent=1), encoding="utf-8")
    except Exception:
        pass


QUICK_WORDS = re.compile(r"torque|ft[- ]?lbs?|lb[- ]?ft|n[- ]?m\b|spec|capacity|how much oil|oil (type|weight)|viscosity|quarts?|psi|pressure|"
                         r"firing order|gap|fluid|coolant|refrigerant|freon|bolt pattern|lug|thread|socket size|what size|"
                         r"\b[pbcu][0-9][0-9a-f]{3}\b|code|tsb|recall|fuse|relay|mean|what does", re.I)
WORK_WORDS = re.compile(r"\b(write|summari[sz]e|make me|build|create|folder|files?|spreadsheet|script|program|essay|plan|list every|compare all)\b", re.I)


def looks_quick(task):
    t = task.strip()
    return len(t) <= 160 and t.count("\n") < 2 and bool(QUICK_WORDS.search(t)) and not WORK_WORDS.search(t)


async def h_ask(request):
    """POST /ask {"q": "..."}  ->  {"answer": "185 ft-lb", "extra": "...", "sure": "high|check", "sources": [...]}"""
    global last_activity, asks
    last_activity = time.time()
    if request.method == "GET":
        return web.json_response({"recent": asks[:15]})
    data = await request.json()
    q = " ".join(str(data.get("q") or "").split())[:300]
    if not q:
        return web.json_response({"error": "ask something first"}, status=400)
    key = q.lower()
    for a in asks:                                     # asked it before? instant.
        if a["q"].lower() == key and time.time() - a.get("when", 0) < 30 * 86400 and a.get("sure") == "high":
            return web.json_response({**a, "cached": True, "secs": 0})
    all_hands("shop")
    async with ClientSession() as session:
        try:
            ans = await quick_answer(session, q)
        except Exception as e:
            all_hands("shop", False)
            return web.json_response({"error": f"the crew fumbled that one ({e})"}, status=500)
    rec = {"q": q, **ans, "when": time.time()}
    asks = [rec] + [a for a in asks if a["q"].lower() != key][:99]
    try:
        ASK_FILE.parent.mkdir(parents=True, exist_ok=True)
        ASK_FILE.write_text(json.dumps(asks, indent=1), encoding="utf-8")
    except Exception:
        pass
    hub.send({"type": "ask", "q": q, "answer": ans["answer"], "sure": ans["sure"]})
    log(f"Quick Q ({ans['secs']}s): {q[:60]} -> {ans['answer'][:60]}")
    if (ans["sure"] != "high" or data.get("check")) and engine_state["status"] == "ready" and not pixelshop.owns_gpu() \
            and CFG.get("crew_check", True):
        rec["checking"] = True                   # ⚠ answer -> the whole crew double-checks it in the background
        asyncio.get_running_loop().create_task(run_crew_check(q, ans))
    else:
        all_hands("shop", False)                 # no crew check this time - back to whatever they were doing
    return web.json_response(rec)


TRAIN_DIR = HERE / "training"


async def h_ask_rate(request):
    """👍/👎 on a quick answer -> saved as a training example (per-PC file so the two PCs never fight over it)."""
    d = await request.json()
    q, ans = str(d.get("q") or "")[:300], str(d.get("answer") or "")[:500]
    if not q or not ans:
        return web.json_response({"error": "nothing to save"}, status=400)
    good = bool(d.get("good"))
    row = {"q": q, "answer": ans, "extra": str(d.get("extra") or "")[:500], "good": good,
           "fix": str(d.get("fix") or "")[:500], "sources": d.get("sources") or [], "brain": MODEL_LABEL, "when": time.strftime("%Y-%m-%d %H:%M")}
    TRAIN_DIR.mkdir(exist_ok=True)
    f = TRAIN_DIR / f"shop-examples-{re.sub(r'[^A-Za-z0-9_-]', '_', socket.gethostname())}.jsonl"
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    count = 0
    for g in TRAIN_DIR.glob("shop-examples-*.jsonl"):           # both PCs' examples (they sync)
        try:
            count += sum(1 for line in g.read_text(encoding="utf-8").splitlines() if '"good": true' in line)
        except OSError:
            pass
    log(f"Training example saved ({'good' if good else 'needs fixin'}): {q[:50]}")
    return web.json_response({"ok": True, "count": count})


async def h_ask_check(request):
    """POST /ask/check {"q": "..."} - make the crew double-check an answer you already got (even a ✔ one)."""
    data = await request.json()
    q = " ".join(str(data.get("q") or "").split())[:300]
    first = next((a for a in asks if a["q"].lower() == q.lower()), None)
    if not first:
        return web.json_response({"error": "ask it first"}, status=400)
    if engine_state["status"] != "ready" or pixelshop.owns_gpu():
        return web.json_response({"error": "the brain's not up right now"}, status=409)
    asyncio.get_running_loop().create_task(run_crew_check(q, first))
    return web.json_response({"ok": True})


def in_shop_hours():
    """No idle shutdown during busy hours (config "shop_hours": "07:00-18:00", "" = off)."""
    sh = str(CFG.get("shop_hours", "") or "")
    m = re.match(r"(\d{1,2}):(\d\d)\s*-\s*(\d{1,2}):(\d\d)", sh)
    if not m:
        return False
    lt = time.localtime(); now_m = lt.tm_hour * 60 + lt.tm_min
    a, b = int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])
    return a <= now_m < b if a <= b else (now_m >= a or now_m < b)




async def run_subtask(session, job, sub):
    name = await free_workers.get()
    try:
        sub["worker"], sub["status"] = name, "working"
        push_job(job)
        sub["output"] = await do_piece(session, job, sub, name)
        sub["tries"] = 1
        if CFG.get("review", True):
            for _ in range(CFG.get("max_redo", 1) + 1):
                set_agent(name, sub["station"], "waiting", job["id"], text=f"Waiting on the {CHECKER}...")
                ok, notes = await review_piece(session, job, sub)
                if ok:
                    sub["review"] = "passed"
                    break
                sub["review"] = f"sent back: {notes}"
                if sub["tries"] > CFG.get("max_redo", 1):
                    sub["review"] = f"FAILED the {CHECKER}'s check: {notes}"
                    break
                push_job(job)
                sub["output"] = await do_piece(session, job, sub, name, notes)
                sub["tries"] += 1
        sub["status"] = "done"
        rv = sub.get("review")
        set_agent(name, sub["station"], "done", job["id"],
                  text="Done!" if sub["review"] in (None, "passed") else "Did my best...")
        await asyncio.sleep(0.8)
    except Exception as e:
        sub["output"], sub["status"], sub["review"] = f"[failed: {e}]", "failed", "crashed"
        log(f"{name} failed on '{sub['title']}': {e}")
        set_agent(name, "idle", "failed", None, text="That one broke")
        await asyncio.sleep(1.5)
    finally:
        set_agent(name, "idle", "idle", None)
        push_job(job)
        free_workers.put_nowait(name)


async def run_job(job):
    global last_activity
    last_activity = time.time()
    try:
        async with ClientSession() as session:
            set_agent(BOSS, "boss", "waiting", job["id"], text="Waking up the brain...")
            if not await ensure_engine(session):
                raise RuntimeError(engine_state.get("detail") or "brain isn't running")
            file_list = list_folder(job["folder"]) if job.get("folder") else []
            job["status"] = "planning"
            push_job(job)
            job["subtasks"] = await plan_job(session, job, file_list)
            job["status"] = "working"
            set_agent(BOSS, "boss", "waiting", job["id"],
                      text=f"{len(job['subtasks'])} pieces handed out. Get to work, team.")
            push_job(job)
            await asyncio.gather(*(run_subtask(session, job, s) for s in job["subtasks"]))

            if not any(s["status"] == "done" for s in job["subtasks"]):
                raise RuntimeError("Every piece failed")
            if len(job["subtasks"]) == 1:
                result = job["subtasks"][0]["output"]
            else:
                job["status"] = "merging"
                push_job(job)
                set_agent(BOSS, "boss", "merging", job["id"], text="Putting it all together...")
                pieces = "\n\n".join(f"--- {s['worker']} did '{s['title']}' ({s['status']}, check: {s['review']}) ---\n{s['output']}"
                                     for s in job["subtasks"])
                result = await chat(session, [
                    {"role": "system", "content": f"You are {BOSS}, the boss. Combine your workers' results into ONE clean, "
                     "organized final answer to the job. Keep all the useful details, drop repeats, fix obvious mistakes. "
                     "If a piece failed or failed the inspector's check, say so at the end."},
                    {"role": "user", "content": f"JOB: {job['task']}\n\nWORKER RESULTS:\n{pieces}"}],
                    max_tokens=6000, on_text=lambda t: set_agent(BOSS, "boss", "merging", job["id"], text=tail(t)), handbook=True)
            # what should Claude spot-check?
            flags = []
            for s in job["subtasks"]:
                if s["status"] == "failed" or (s["review"] or "").startswith("FAILED"):
                    flags.append(f"'{s['title']}' ({s['worker']}) - {s['review']}")
                elif s["station"] == "code" or CODE_WORDS.search(s["title"]):
                    flags.append(f"'{s['title']}' ({s['worker']}) - it's code, give it a look")
            job["claude_check"] = flags
            job["result"] = result
            out_file = OUT_DIR / f"job-{job['id']}.md"
            out_file.write_text(f"# Job {job['id']}\n\n**Task:** {job['task']}\n\n{result}\n", encoding="utf-8")
            job["output_file"] = str(out_file)
            job["status"] = "done"
            set_agent(BOSS, "boss", "done", None, text="Job's done.")
            log(f"Job {job['id']} done -> {out_file}")
    except Exception as e:
        job["status"], job["error"] = "failed", str(e)
        log(f"Job {job['id']} FAILED: {e}")
        set_agent(BOSS, "boss", "failed", None, text="We hit a problem.")
    finally:
        job["finished"] = time.time()
        last_activity = time.time()
        push_job(job)
        await asyncio.sleep(2)
        if not any(j["status"] in ("planning", "working", "merging") for j in jobs.values()):
            set_agent(BOSS, "idle", "idle", None)
            set_agent(CHECKER, "idle", "idle", None)


# ------------------------------------------------------------ remote watch --
KEY_FILE = HERE / "crew_key.txt"


def crew_key():
    """Secret key for watching from another device. Made once, kept in crew_key.txt."""
    if not KEY_FILE.exists():
        KEY_FILE.write_text(secrets.token_urlsafe(18), encoding="utf-8")
    return KEY_FILE.read_text(encoding="utf-8").strip()


def ts_exe():
    exe = shutil.which("tailscale")
    guess = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"
    return exe or (str(guess) if guess.exists() else None)


def tailscale_https():
    """Turn on Tailscale's https link -> this PC's port. Needed so the phone can install it as an app.
    Returns (ok, approval_url_or_message)."""
    exe = ts_exe()
    if not exe:
        return False, "Tailscale not installed"
    try:
        kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WIN else {}
        r = subprocess.run([exe, "serve", "--bg", str(PORT)], capture_output=True, text=True, timeout=15, **kw)
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 0:
            return True, ""
    except subprocess.TimeoutExpired as e:
        out = ((e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")) + \
              ((e.stderr or b"").decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or ""))
    except Exception as e:
        return False, str(e)
    m = re.search(r"https://login\.tailscale\.com/\S+", out)
    return False, (m.group(0) if m else out.strip()[:300])


def tailscale_ip():
    """Your desktop's private Tailscale address (100.x.x.x), if Tailscale is running."""
    exe = ts_exe()
    if not exe:
        return None, None
    try:
        kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WIN else {}
        ip = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=8, **kw).stdout.split()
        st = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=8, **kw).stdout
        name = (json.loads(st).get("Self") or {}).get("DNSName", "").rstrip(".") if st else ""
        return (ip[0] if ip and ip[0].startswith("100.") else None), (name or None)
    except Exception:
        return None, None


KEY = crew_key()


PUBLIC = {"/manifest.webmanifest", "/sw.js", "/icon-192.png", "/icon-512.png"}   # harmless app bits
PROXY_HEADERS = ("X-Forwarded-For", "X-Forwarded-Proto", "Forwarded", "Tailscale-User-Login", "Tailscale-User-Name")


def local_file_cors(request):
    """The wallpaper is a file on this PC (its 'origing is null). Let ONLY that read the crew feed -
    websites open in your browser still can't."""
    if request.remote in ("127.0.0.1", "::1") and request.headers.get("Origin") == "null":
        return {"Access-Control-Allow-Origin": "null"}
    return {}


@web.middleware
async def no_stale(request, handler):
    """Never let a browser keep an old copy of the page or app code - updates show up on the next reload."""
    resp = await handler(request)
    p = request.path
    if request.method == "GET" and (p == "/" or p.endswith((".html", ".js", ".webmanifest", ".css"))):
        try:
            resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        except Exception:
            pass
    return resp


@web.middleware
async def guard(request, handler):
    """Your own PC gets in free. Anything else - including stuff relayed by
    Tailscale's https link, which arrives looking local - needs the secret key."""
    relayed = any(h in request.headers for h in PROXY_HEADERS)
    if (request.remote in ("127.0.0.1", "::1") and not relayed) or request.path in PUBLIC:
        resp = await handler(request)
        if not resp.prepared:
            resp.headers.update(local_file_cors(request))
        return resp
    given = request.query.get("key") or request.cookies.get("crew_key") or request.headers.get("X-Crew-Key") or ""
    main_key = secrets.compare_digest(given, KEY)
    if not main_key:
        if request.cookies.get("crew_key") and secrets.compare_digest(request.cookies["crew_key"], KEY):
            main_key = True
        elif request.path.startswith("/pixel/app") and pixelshop.key_ok(request):
            return await handler(request)   # Pixel Shop key: the shop and nothing else
        else:
            return web.Response(status=403, text="Wrong key.")
    resp = await handler(request)
    if request.query.get("key") and secrets.compare_digest(request.query["key"], KEY) and not resp.prepared:
        resp.set_cookie("crew_key", KEY, max_age=60 * 60 * 24 * 365, httponly=True, samesite="Lax",
                        secure=request.headers.get("X-Forwarded-Proto") == "https")
    return resp


def write_work_link(ip, name, https_ok=True, https_note=""):
    lines = ["FreedomOS - open it from your phone or another computer",
             "=======================================================",
             "First: that device needs Tailscale installed and signed in to the SAME account as this desktop.", ""]
    if not https_ok:
        lines += ["!! The https link isn't switched on yet, so the phone can't INSTALL it as an app (it still works in Chrome).",
                  "   One-time fix - open this on any device signed in to Tailscale and hit Enable, then restart FreedomOS:",
                  f"   {https_note or 'https://login.tailscale.com/admin/dns  (turn on MagicDNS + HTTPS Certificates)'}", ""]
    if name:
        lines += ["PHONE APP: open this in Chrome, then menu (3 dots) > 'Install app' / 'Add to home screen':",
                  f"   https://{name}/?key={KEY}", "",
                  "WORK LAPTOP: same link in any browser (bookmark it):",
                  f"   https://{name}/?key={KEY}", "",
                  "Backup link if the https one won't load:"]
    lines.append(f"   http://{ip}:{PORT}/?key={KEY}")
    lines += ["", "Keep this key private - anyone with it AND on your Tailscale can give the crew jobs.",
              "New key: delete %LOCALAPPDATA%\\FreedomOS\\crew_key.txt and restart FreedomOS."]
    for spot in (WORK_DIR / "FreedomOS phone link.txt", HERE / "FreedomOS phone link.txt"):
        try:
            spot.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass


# ------------------------------------------------------------------- web --
APP_TYPES = {".webmanifest": "application/manifest+json", ".js": "text/javascript", ".png": "image/png"}


async def app_file(request):
    f = HERE / "widget" / request.path.lstrip("/")
    return web.FileResponse(f, headers={"Content-Type": APP_TYPES[f.suffix], "Cache-Control": "no-cache"})


def set_remote(r):
    """Switch to (or off) the other PC's brain, and remember it for next time."""
    global REMOTE, MODEL_LABEL
    REMOTE = r
    try:
        save_pick(remote_brain={"peer": r["peer"], "brain": r["brain"], "label": r["label"]} if r else None)
    except Exception as e:
        log(f"(couldn't save the brain pick: {e})")
    if r:
        CFG["brain_now"] = "remote:" + r["brain"]
        CFG["no_reasoning"] = bool(BRAINS.get(r["brain"], {}).get("no_reasoning"))   # same brain rules, just on the other PC
        MODEL_LABEL = f"🖥 {r['peer']}: {r['label']}"
    else:
        apply_brain(CFG.get("brain", "small"))


async def remote_choices():
    p = peer_by_name()
    if not p:
        return None
    try:
        async with ClientSession() as s:
            async with s.get(f"{p['url']}/brain", headers={"X-Crew-Key": p["key"]}, timeout=ClientTimeout(total=8)) as r:
                d = await r.json()
        return {"peer": p["name"], "now": d.get("now"), "choices": [c for c in d.get("choices", []) if c.get("ok")]}
    except Exception:
        return {"peer": p["name"], "error": "can't reach it right now", "choices": []}


async def pick_remote(bid):
    p = peer_by_name()
    if not p:
        return web.json_response({"error": "link your PCs first (📁 → 🔗 Link PCs)"}, status=400)
    if any(j["status"] in ("queued", "planning", "working", "merging") for j in jobs.values()):
        return web.json_response({"error": "the crew is mid-job - swap brains when they're done"}, status=409)
    try:
        async with ClientSession() as s:
            async with s.post(f"{p['url']}/brain", json={"pick": bid}, headers={"X-Crew-Key": p["key"]},
                              timeout=ClientTimeout(total=30)) as r:
                d = await r.json()
    except Exception as e:
        return web.json_response({"error": f"can't reach {p['name']} - is it on with FreedomOS running? ({str(e)[:60]})"}, status=400)
    if d.get("error"):
        return web.json_response({"error": f"{p['name']} says: {d['error']}"}, status=400)
    label = next((c.get("label", bid) for c in d.get("choices", []) if c.get("id") == bid), bid)
    set_remote({"peer": p["name"], "url": p["url"], "key": p["key"], "brain": bid, "label": label})
    kill_engine()                                               # free up this PC - the other one's doing the thinking
    log(f"Using {p['name']}'s brain now: {label}")
    set_engine("loading", f"{p['name']} is loading {label}...")
    hub.send({"type": "brain", "brain": brain_info(), "model": MODEL_LABEL})

    async def wake():
        async with ClientSession() as s2:
            await ensure_engine(s2)
    asyncio.get_running_loop().create_task(wake())
    return web.json_response({"ok": True, **brain_info()})


async def h_brain_remote(request):
    return web.json_response(await remote_choices() or {"error": "not linked", "choices": []})


async def h_engine_proxy(request):
    """The OTHER PC borrowing this PC's brain: pass its questions to the local llama.cpp and stream the answer back."""
    global last_activity
    last_activity = time.time()
    tail = request.match_info["tail"]
    async with ClientSession() as s:
        if tail == "health":
            st = await engine_health(s)
            if st is None and BRAIN_SW["on"]:
                asyncio.get_running_loop().create_task(ensure_engine(s, wait=False))
                if pixelshop.owns_gpu():
                    return web.Response(status=503, text="Pixel Shop has the GPU")
            return web.Response(status=st or 503, text="ok" if st == 200 else "loading")
        if not await ensure_engine(s):
            return web.Response(status=503, text="brain isn't up on this PC")
        body = await request.read()
        async with s.request(request.method, f"{ENGINE}/{tail}", data=body,
                             headers={"Content-Type": request.headers.get("Content-Type", "application/json")},
                             timeout=ClientTimeout(total=1800, sock_read=600)) as r:
            resp = web.StreamResponse(status=r.status, headers={"Content-Type": r.headers.get("Content-Type", "application/json")})
            await resp.prepare(request)
            async for chunk in r.content.iter_any():
                await resp.write(chunk)
                last_activity = time.time()
            await resp.write_eof()
            return resp


def brain_info():
    return {"now": CFG.get("brain_now"), "remote": ({"peer": REMOTE["peer"], "brain": REMOTE["brain"], "label": REMOTE["label"]} if REMOTE else None),
            "choices": [{"id": n, "label": b.get("model_label", n), "gb": b.get("model_download_gb"),
            "ok": brain_ok(n)} for n, b in BRAINS.items()]}


_swap_lock = asyncio.Lock()


async def h_brain(request):
    """POST /brain {"pick": "small"|"big"} - swap brains (saved for next time too)."""
    if request.method == "GET":
        return web.json_response(brain_info())
    pick = str((await request.json()).get("pick", ""))
    if pick.startswith("remote:"):
        return await pick_remote(pick[7:])
    if not brain_ok(pick):
        return web.json_response({"error": "that brain needs the NVIDIA desktop" if pick in BRAINS else "no such brain"}, status=400)
    if any(j["status"] in ("queued", "planning", "working", "merging") for j in jobs.values()):
        return web.json_response({"error": "the crew is mid-job - swap brains when they're done"}, status=409)
    async with _swap_lock:
        if REMOTE:                                             # coming back home from the other PC's brain
            set_remote(None)
            CFG["brain_now"] = None
        if pick == CFG.get("brain_now"):
            return web.json_response({"ok": True, **brain_info()})
        try:                                                   # remember it (this PC only)
            save_pick(brain=pick)
        except Exception as e:
            log(f"(couldn't save the brain pick: {e})")
        CFG["brain"] = pick
        apply_brain(pick)
        log(f"Swapping brains -> {MODEL_LABEL}")
        set_engine("loading", f"swapping in {MODEL_LABEL}...")
        kill_engine()
        await asyncio.sleep(3)
        hub.send({"type": "brain", "brain": brain_info(), "model": MODEL_LABEL})

        async def wake():
            async with ClientSession() as s2:
                await ensure_engine(s2)
        asyncio.get_running_loop().create_task(wake())
    return web.json_response({"ok": True, **brain_info()})


RACE_FILE = HERE / "memory" / "brain_race.json"
RACE = {"running": False, "now": "", "results": {}}
try:
    RACE["results"] = json.loads(RACE_FILE.read_text(encoding="utf-8")).get("results", {})
except Exception:
    pass
RACE_PROMPT = [{"role": "system", "content": "You are a friendly, helpful assistant."},
               {"role": "user", "content": "Explain step by step how to change a flat tire. About 150 words."}]


async def _race_one(session, name):
    """Swap in one brain, wait for it, time how fast it talks."""
    CFG["brain"] = name
    apply_brain(name)
    set_engine("loading", f"brain race: loading {MODEL_LABEL}...")
    kill_engine()
    await asyncio.sleep(3)
    hub.send({"type": "brain", "brain": brain_info(), "model": MODEL_LABEL})
    RACE["now"] = f"{BRAINS[name].get('short', name)} loading (first time downloads it - watch the 🧠 line)..."
    hub.send({"type": "brainrace", "race": RACE})
    try:
        ok = await asyncio.wait_for(ensure_engine(session), 3600)
    except asyncio.TimeoutError:
        ok = False
    if not ok:
        return {"error": "it wouldn't load - check logs/engine.log"}
    best = None
    for _ in range(2):                                  # run twice, keep the better one (first run warms it up)
        body = {"messages": RACE_PROMPT, "max_tokens": 260, "temperature": 0.7, "stream": False,
                "chat_template_kwargs": {"enable_thinking": False}}
        if CFG.get("no_reasoning"):
            body["reasoning_effort"] = "none"
        async with session.post(f"{ENGINE}/v1/chat/completions", json=body, timeout=ClientTimeout(total=900)) as r:
            d = await r.json()
        tm = d.get("timings") or {}
        row = {"tps": round(tm.get("predicted_per_second", 0), 1), "read_tps": round(tm.get("prompt_per_second", 0), 1),
               "said": _strip_think((d.get("choices") or [{}])[0].get("message", {}).get("content", ""))[:400]}
        if not best or row["tps"] > best["tps"]:
            best = row
    return best


async def run_brain_race():
    if RACE["running"] or REMOTE:
        return
    keep = CFG.get("brain_now")
    RACE.update(running=True, now="starting the race...")
    hub.send({"type": "brainrace", "race": RACE})
    try:
        async with ClientSession() as session:
            for name in [n for n in BRAINS if brain_ok(n)]:
                RACE["now"] = f"{BRAINS[name].get('short', name)} is up..."
                hub.send({"type": "brainrace", "race": RACE})
                try:
                    res = await _race_one(session, name)
                except Exception as e:
                    res = {"error": str(e)[:120]}
                RACE["results"][name] = dict(res, label=BRAINS[name].get("short", name), when=time.strftime("%Y-%m-%d %H:%M"),
                                             pc="desktop" if HAS_NVIDIA else "laptop")
                log(f"Brain race: {BRAINS[name].get('short', name)} -> {res.get('tps', '?')} words-ish/sec")
                hub.send({"type": "brainrace", "race": RACE})
            RACE_FILE.write_text(json.dumps({"results": RACE["results"]}, indent=1), encoding="utf-8")
            apply_brain(keep)                                       # put the regular brain back
            CFG["brain"] = keep
            kill_engine()
            await asyncio.sleep(3)
            hub.send({"type": "brain", "brain": brain_info(), "model": MODEL_LABEL})
            await ensure_engine(session)
    finally:
        RACE.update(running=False, now="")
        hub.send({"type": "brainrace", "race": RACE})


async def h_brain_race(request):
    """GET = last results, POST = race every brain this PC can run (the crew pauses while it runs)."""
    if request.method == "POST":
        if REMOTE:
            return web.json_response({"error": "you're using the other PC's brain - pick a brain on THIS PC to race"}, status=409)
        if any(j["status"] in ("queued", "planning", "working", "merging") for j in jobs.values()):
            return web.json_response({"error": "the crew is mid-job - race when they're done"}, status=409)
        asyncio.get_running_loop().create_task(run_brain_race())
    return web.json_response(RACE)






DISCORD = {"n": 0, "t": 0.0}


async def h_discord(request):
    """👾 the app tells us how many Discord pings are waiting - badge on the button"""
    if request.method == "POST":
        try:
            n = int((await request.json()).get("n", 0))
        except Exception:
            n = 0
        more = n > DISCORD["n"]
        DISCORD["n"] = n
        hub.send({"type": "discord", "n": n})
    return web.json_response({"n": DISCORD["n"]})



























async def h_index(request):
    return web.FileResponse(HERE / "widget" / "index.html")


async def h_health(request):
    return web.json_response({"ok": True, "app": "FreedomOS", "version": VERSION, "model": MODEL_LABEL,
                              "workers": WORKERS, "engine": engine_state, "autoupdate": True})


PICTURE_WORDS = re.compile(r"\b(draw|drawing|paint|picture|pic|image|photo|pixel art|sprite|sprites|logo|icon|artwork|illustration|"
                           r"wallpaper|portrait|render|sketch)\b", re.I)
PICTURE_ASK = re.compile(r"\b(make|draw|create|generate|paint|design|give me|do|render|sketch|show me)\b", re.I)


def looks_picture(task):
    t = task.strip()
    return len(t) <= 400 and bool(PICTURE_WORDS.search(t)) and bool(PICTURE_ASK.search(t)) and not WORK_WORDS.search(re.sub(r"\b(make|create)\b", "", t, flags=re.I))


async def picture_job(task):
    """'Make a picture of...' -> the real picture maker. The brain can't draw, so it never pretends to."""
    jid = uuid.uuid4().hex[:6]
    job = {"id": jid, "task": task, "folder": "", "status": "working", "created": time.time(), "subtasks": [], "picture": True}
    jobs[jid] = job
    push_job(job)

    async def go():
        if pixelshop.installed() and HAS_NVIDIA:
            job.update(status="done", result="Pictures get made in the 🎨 Pixel Shop on this PC - open it from the 🎨 button and type:\n\n" + task)
        elif not pixlite.installed():
            job.update(status="failed", error="Pixel Shop Lite isn't set up on this laptop yet - open 🎨 and hit 'Set up' (one-time ~5.5 GB download). "
                                              "The crew's brain can't draw, so nobody's gonna fake it.")
        else:
            look = "sprite" if re.search(r"\b(sprite|character)\b", task, re.I) else "picture" if re.search(r"\b(photo|realistic|real looking)\b", task, re.I) else "pixel"
            match = bool(re.search(r"\b(like (the )?(ones|guys)|this app|same style|match)\b", task, re.I))
            try:
                res = await pixlite.make(task, look, match)
                job.update(status="done", result=f"Made it! Saved to:\n{res['path']}\n\n(took {res['secs']} s - see it in the 🎨 popup)",
                           output_file=res["path"], image=res["name"])
            except Exception as e:
                job.update(status="failed", error=str(e))
        push_job(job)
        log(f"Picture job {jid}: {job['status']} - {task[:60]}")
    asyncio.get_running_loop().create_task(go())
    return web.json_response({"id": jid, "picture": True})


async def h_new_job(request):
    data = await request.json()
    task = (data.get("task") or "").strip()
    if not task:
        return web.json_response({"error": "no task given"}, status=400)
    folder = (data.get("folder") or "").strip()
    if folder:
        try:
            safe_path(folder)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)
    if not folder and looks_picture(task) and not data.get("full_crew"):
        return await picture_job(task)
    if not folder and looks_quick(task) and not data.get("full_crew"):
        # a quick question - don't make the whole crew plan it for 10 minutes
        async with ClientSession() as session:
            try:
                ans = await quick_answer(session, " ".join(task.split())[:300])
            except Exception as e:
                ans = None
                log(f"(quick lane failed, giving it to the crew: {e})")
        if ans:
            jid = uuid.uuid4().hex[:6]
            txt = ans["answer"] + (f"\n{ans['extra']}" if ans.get("extra") else "") + \
                ("\n(sources agree)" if ans["sure"] == "high" else "\n(DOUBLE-CHECK this one)") + \
                "".join(f"\n- {s['url']}" for s in ans.get("sources", []))
            job = {"id": jid, "task": task, "folder": "", "status": "done", "created": time.time(), "subtasks": [], "result": txt, "quick": True}
            jobs[jid] = job
            push_job(job)
            hub.send({"type": "ask", "q": task, "answer": ans["answer"], "sure": ans["sure"]})
            log(f"Quick lane ({ans['secs']}s) instead of a full job: {task[:60]} -> {ans['answer'][:50]}")
            return web.json_response({"id": jid, "quick": {"q": task, **ans}})
    jid = uuid.uuid4().hex[:6]
    job = {"id": jid, "task": task, "folder": folder, "status": "queued",
           "created": time.time(), "subtasks": [], "result": None}
    jobs[jid] = job
    push_job(job)
    log(f"New job {jid}: {task[:80]}")
    asyncio.get_running_loop().create_task(run_job(job))
    return web.json_response({"id": jid})


async def h_jobs(request):
    return web.json_response([job_summary(j) for j in sorted(jobs.values(), key=lambda j: -j["created"])])


async def h_job(request):
    j = jobs.get(request.match_info["jid"])
    if not j:
        return web.json_response({"error": "no such job"}, status=404)
    d = job_summary(j)
    d["result"] = j.get("result")
    d["pieces"] = [{"title": s["title"], "worker": s["worker"], "status": s["status"],
                    "review": s.get("review"), "tries": s.get("tries"), "output": s["output"]}
                   for s in j["subtasks"]]
    return web.json_response(d)


async def h_agents(request):
    return web.json_response({"agents": list(agents.values()), "gpu": gpu_state, "engine": engine_state})


async def h_events(request):
    global last_activity
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream",
                                       "Cache-Control": "no-cache", "Connection": "keep-alive", **local_file_cors(request)})
    await resp.prepare(request)
    q: asyncio.Queue = asyncio.Queue()
    hub.subs.add(q)
    try:
        snap = {"type": "snapshot", "agents": list(agents.values()), "gpu": gpu_state, "engine": engine_state,
                "jobs": [job_summary(j) for j in sorted(jobs.values(), key=lambda j: -j["created"])][:20],
                "model": MODEL_LABEL, "version": VERSION, "boot": BOOT_ID, "cpu": temps.STATE, 
                "brain": brain_info(), "crew": {"boss": BOSS, "checker": CHECKER, "workers": WORKERS, "persona": PERSONA},
                "pixel": dict(pixelshop.state, installed=pixelshop.installed(), desktop_only=not HAS_NVIDIA), "pixlite": pixlite.public(), "cc": claudechat.public(), "files": filesync.public()}
        await resp.write(f"data: {json.dumps(snap)}\n\n".encode())
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=15)
                await resp.write(f"data: {json.dumps(ev)}\n\n".encode())
            except asyncio.TimeoutError:
                await resp.write(b": ping\n\n")
            last_activity = time.time()
    except (ConnectionResetError, asyncio.CancelledError, RuntimeError):
        pass
    finally:
        hub.subs.discard(q)
    return resp


def kill_engine():
    if engine_proc is not None and engine_proc.poll() is None:
        engine_proc.kill()
    if IS_WIN:
        subprocess.run(["taskkill", "/f", "/im", "llama-server.exe"], capture_output=True)


async def shutdown_soon(reason):
    log(f"Shutting down: {reason}")
    hub.send({"type": "bye", "reason": reason})
    await asyncio.sleep(0.8)
    pixelshop.stop_sync()
    kill_engine()   # frees the GPU and the RAM
    os._exit(0)


async def h_shutdown(request):
    asyncio.get_running_loop().create_task(shutdown_soon("you hit Shut down"))
    return web.json_response({"ok": True})


async def h_warmup(request):
    async def go():
        async with ClientSession() as s:
            await ensure_engine(s)
    asyncio.get_running_loop().create_task(go())
    return web.json_response({"ok": True, "engine": engine_state})


# -------------------------------------------------------------- background --
async def gpu_loop():
    smi = shutil.which("nvidia-smi")
    if not smi:
        return
    while True:
        try:
            p = await asyncio.create_subprocess_exec(
                smi, "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                "--format=csv,noheader,nounits", stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if IS_WIN else 0)
            out, _ = await p.communicate()
            v = [x.strip() for x in out.decode().splitlines()[0].split(",")]
            gpu_state.update(util=float(v[0]), mem_used=float(v[1]), mem_total=float(v[2]), temp=float(v[3]),
                             power=float(v[4]) if v[4] not in ("[N/A]", "") else None)
            hub.send({"type": "gpu", "gpu": gpu_state})
        except Exception:
            pass
        await asyncio.sleep(2)


async def idle_watch():
    limit = CFG.get("idle_shutdown_minutes", 20) * 60
    while True:
        await asyncio.sleep(30)
        busy = any(j["status"] in ("queued", "planning", "working", "merging") for j in jobs.values())
        if busy or hub.subs or TRAY["on"] or in_shop_hours() or engine_state["status"] in ("downloading", "loading") or pixelshop.recently_used(limit):
            continue
        if time.time() - last_activity > limit:
            await shutdown_soon(f"idle {limit // 60} min, nobody watching - saving power")


async def on_start(app):
    global free_workers
    free_workers = asyncio.Queue()
    for w in WORKERS:
        free_workers.put_nowait(w)

    threading.Thread(target=ensure_autostart, daemon=True).start()
    if IS_WIN and not os.environ.get("F35_RESTARTED"):
        async def open_desktop():                        # 🖥 fresh start: FreedomOS comes up as your desktop
            await asyncio.sleep(4)
            try:
                exe = f35web.f35_browser_exe()
                if exe:
                    subprocess.Popen([str(exe), "--boot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=0x00000008 | 0x00000200)
            except Exception as e:
                log(f"(couldn't open the desktop: {e})")
        asyncio.get_running_loop().create_task(open_desktop())

    async def warm():
        if not BRAIN_SW["on"]:
            set_engine("off", "switched off - wakes up for questions + jobs")
            return
        async with ClientSession() as s:
            await ensure_engine(s)
    if IS_WIN:
        threading.Thread(target=tray_thread, args=(asyncio.get_running_loop(),), daemon=True).start()
    app["bg"] = [asyncio.create_task(gpu_loop()), asyncio.create_task(idle_watch()), asyncio.create_task(warm()),
                 asyncio.create_task(pixelshop.watch_loop()),
                 asyncio.create_task(filesync.loop()), asyncio.create_task(autoupdate.loop()),
                 asyncio.create_task(winfs.loop(log)), asyncio.create_task(nap_loop()), asyncio.create_task(f35music.loop()), asyncio.create_task(f35discord.loop()), asyncio.create_task(_browser_soon()), asyncio.create_task(temps.loop(hub))]
    log(f"FreedomOS v{VERSION}: {BOSS} + {', '.join(WORKERS)} on http://127.0.0.1:{PORT}  brain={MODEL_LABEL}"
        f"  ({'NVIDIA desktop' if HAS_NVIDIA else 'no NVIDIA - laptop setup'})")


def main():
    agents[BOSS] = {"name": BOSS, "role": "boss", "station": "idle", "status": "idle", "job": None, "text": ""}
    if CFG.get("review", True):
        agents[CHECKER] = {"name": CHECKER, "role": "checker", "station": "idle", "status": "idle", "job": None, "text": ""}
    for w in WORKERS:
        agents[w] = {"name": w, "role": "worker", "station": "idle", "status": "idle", "job": None, "text": ""}
    for c in KEEPERS:
        if c not in agents:
            agents[c] = {"name": c, "role": "keeper", "station": "idle", "status": "idle", "job": None, "text": "Working the till."}
    for b in BENCH:
        agents[b] = {"name": b, "role": "bench", "station": "idle", "status": "idle", "job": None,
                     "text": "Benched."}
    app = web.Application(client_max_size=32 * 1024 * 1024, middlewares=[guard, no_stale])
    pixelshop.init(HERE, log, hub, set_agent, set_engine, kill_engine, ensure_engine, agents, IS_WIN)
    pixlite.init(HERE, log, hub, set_agent, agents)
    pixlite.D["hands"] = all_hands
    pixelshop.D["hands"] = all_hands
    claudechat.HANDS = all_hands
    claudechat.init(hub, log)
    pixelshop.D["engine_up"] = lambda: (engine_proc is not None and engine_proc.poll() is None) or \
        engine_state["status"] in ("ready", "loading", "downloading")
    pixelshop.D["port"] = PORT
    app.add_routes([
        web.get("/", h_index), web.get("/health", h_health),
        web.post("/jobs", h_new_job), web.get("/jobs", h_jobs), web.get("/jobs/{jid}", h_job),
        web.get("/agents", h_agents), web.get("/events", h_events),
        web.post("/shutdown", h_shutdown), web.post("/warmup", h_warmup), web.post("/ask", h_ask), web.get("/ask", h_ask), web.post("/ask/check", h_ask_check), web.post("/ask/rate", h_ask_rate), web.post("/brain", h_brain), web.route("*", "/brain/switch", h_brain_switch), web.route("*", "/discord/ping", h_discord), web.get("/brain", h_brain), web.get("/brain/race", h_brain_race), web.get("/brain/remote", h_brain_remote), web.route("*", "/engine/{tail:.*}", h_engine_proxy), web.post("/brain/race", h_brain_race),
        web.static("/widget", HERE / "widget"),
        web.get("/manifest.webmanifest", app_file), web.get("/sw.js", app_file),
        web.get("/icon-192.png", app_file), web.get("/icon-512.png", app_file),
        *pixelshop.routes(lambda r: r.remote in ("127.0.0.1", "::1") and not any(h in r.headers for h in PROXY_HEADERS)),
        *pixlite.routes(lambda r: r.remote in ("127.0.0.1", "::1") and not any(h in r.headers for h in PROXY_HEADERS)),
    ])
    claudechat.routes(app)
    filesync.routes(app)
    f35music.routes(app)
    f35discord.routes(app)
    f35web.routes(app)
    app.on_startup.append(on_start)
    hosts = ["127.0.0.1"]
    ip = None
    if CFG.get("remote_watch", True):
        ip, name = tailscale_ip()
        if ip:
            hosts.append(ip)   # ONLY your private Tailscale network, not your home Wi-Fi or the internet
            ok, note = tailscale_https()
            log("Tailscale https link: " + ("ON" if ok else f"not on yet ({note})"))
            write_work_link(ip, name, ok, note)
            pixelshop.write_link(ip, name, ok)
            log(f"Remote watching ON at http://{ip}:{PORT}  (link + key in Documents\\FreedomOS\\FreedomOS phone link.txt)")
        else:
            log("Remote watching off - Tailscale isn't installed/signed in on this PC.")
            pixelshop.write_link(None, None)
    f35music.init(hub, log)
    f35discord.init(hub, log, CFG)
    f35web.D.update(log=log, web_search=web_search, get=_get, html_text=_html_text, chat=chat, err=lambda: WEB_ERR["last"],
                    ensure_engine=lambda s: ensure_engine(s), has_gpu=lambda: HAS_NVIDIA, me=lambda: filesync.CFG.get("me", ""),
                    peers=lambda: [p for p in (filesync.CFG.get("peers") or []) if p.get("url") and p.get("key")])
    filesync.init(hub, log, pixlite.documents, KEY, f"http://{ip}:{PORT}" if ip else "")

    def crew_busy():          # a job, a picture or a Claude chat in the middle of something
        if any(j.get("status") in ("queued", "planning", "working", "merging") for j in jobs.values()):
            return True
        try:
            if pixlite.state.get("busy"):
                return True
        except Exception:
            pass
        return False

    def before_restart():
        try:
            pixelshop.stop_sync()
        except Exception:
            pass
        kill_engine()

    autoupdate.init(HERE, log, hub, crew_busy, before_restart,
                    on_browser=lambda: asyncio.get_running_loop().create_task(f35web.ensure_built("new code")))
    if os.environ.get("F35_RESTARTED"):
        log("🔄 Update: fresh boss starting up after an update")
        autoupdate.wait_for_port(PORT)
    rb = CFG.get("remote_brain")
    if rb and peer_by_name(rb.get("peer")):                     # was borrowing the other PC's brain last time
        p = peer_by_name(rb["peer"])
        global REMOTE, MODEL_LABEL
        REMOTE = {"peer": p["name"], "url": p["url"], "key": p["key"], "brain": rb["brain"], "label": rb.get("label", rb["brain"])}
        CFG["brain_now"] = "remote:" + rb["brain"]
        CFG["no_reasoning"] = bool(BRAINS.get(rb["brain"], {}).get("no_reasoning"))
        MODEL_LABEL = f"🖥 {p['name']}: {REMOTE['label']}"
    try:
        web.run_app(app, host=hosts, port=PORT, print=None)
    except OSError as e:
        log(f"Port {PORT} busy - boss is probably already running. ({e})")


if __name__ == "__main__":
    main()
