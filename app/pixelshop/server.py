"""
HereticPixel v1.0 (the Pixel Shop in FreedomOS) - free, local image maker for you and your friends.

Runs on your NVIDIA GPU. Your crew connects over Tailscale with the crew key.
Engines: FLUX.2 klein 4B (4 quick steps, copies your drawings, trains on your style)
         Z-Image Turbo 6B (9 steps, sharp, squeezed to 4-bit to fit 12 GB).
No prompt filter, with two exceptions: nothing sexual involving kids, and anything made from a
dropped picture (could be a real person) has to stay clothed.
Pixel looks get "snapped" onto a real pixel grid with a small colour palette.
"""
import os
import sys
import io
import re
import json
import time
import uuid
import shutil
import queue
import random
import secrets
import base64
import ipaddress
import threading
import subprocess
from datetime import datetime

VERSION = "1.0"
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("HF_HOME", os.path.join(HERE, "models"))   # big model files live here
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from flask import Flask, request, jsonify, send_from_directory, redirect, make_response, abort
from PIL import Image

PORT = int(os.environ.get("HP_PORT", "7860"))
HOST = os.environ.get("HP_HOST", "0.0.0.0")   # FreedomOS runs it on 127.0.0.1 only (crew comes in through FreedomOS)
FAKE = os.environ.get("HP_FAKE") == "1"          # test mode: no GPU, makes fake pictures
IDLE_UNLOAD_MIN = 20                               # free the GPU after 20 min of nothing
OUT_DIR = os.path.join(HERE, "outputs")
LOG_DIR = os.path.join(HERE, "logs")
KEY_FILE = os.path.join(HERE, "crew_key.txt")
STYLE_DIR = os.path.join(HERE, "mystyles")
RECENT_FILE = os.path.join(OUT_DIR, "recent.json")
CLAUDE_DIR = os.path.dirname(HERE)
LINK_FILE = os.path.join(CLAUDE_DIR, "HereticPixel crew link.txt")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(STYLE_DIR, exist_ok=True)

TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")


def log(msg):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with open(os.path.join(LOG_DIR, "heretic.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- crew key
def crew_key():
    if os.path.exists(KEY_FILE):
        k = open(KEY_FILE, encoding="utf-8").read().strip()
        if k:
            return k
    k = secrets.token_urlsafe(9)
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        f.write(k)
    return k


KEY = crew_key()


def tailscale_ip():
    exe = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Tailscale", "tailscale.exe")
    if not os.path.exists(exe):
        return None
    try:
        out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5).stdout.strip()
        return out.splitlines()[0] if out else None
    except Exception:
        return None


def write_link_file():
    if os.environ.get("HP_NO_LINK") == "1":
        return   # FreedomOS writes the crew link itself
    ip = tailscale_ip()
    lines = [
        "HereticPixel v%s - crew link" % VERSION,
        "",
        "YOU (on this desktop):  http://127.0.0.1:%d/" % PORT,
    ]
    if ip:
        lines += [
            "THE CREW (over Tailscale):  http://%s:%d/?key=%s" % (ip, PORT, KEY),
            "",
            "Give that crew link ONLY to the people you've shared this desktop with in Tailscale.",
            "Want to kick everybody out? Delete crew_key.txt in the HereticPixel folder and restart.",
        ]
    else:
        lines += ["", "Tailscale isn't signed in yet, so no crew link. Sign in and run the .bat again."]
    try:
        with open(LINK_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as e:
        log("couldn't write link file: %s" % e)


# ---------------------------------------------------------------- the one hard line
_MINOR = r"(child|children|kid|kids|minor|minors|underage|under\s*age|teen|teens|teenage|teenager|preteen|pre-teen|" \
         r"young\s+girl|young\s+boy|little\s+girl|little\s+boy|schoolgirl|schoolboy|school\s+girl|school\s+boy|" \
         r"toddler|baby|infant|elementary|middle\s*school|high\s*school|juvenile|youngster|" \
         r"(?:[1-9]|1[0-7])\s*(?:yo|y/o|yrs?|years?)(?:[\s-]*old)?)"
_SEX = r"(nude|nudes|naked|nsfw|sex|sexy|sexual|porn|porno|erotic|explicit|topless|bottomless|lingerie|" \
       r"hentai|genital|genitals|breast|breasts|boobs|nipple|nipples|undress|undressed|strip|stripping|lewd|" \
       r"seductive|bikini|panties|underwear|fetish|aroused)"
_ALWAYS = r"(loli|lolicon|lolita|shota|shotacon|cp)"


SEXY = re.compile(r"\b" + _SEX + r"\b")


def hard_line(text):
    t = text.lower()
    if re.search(r"\b" + _ALWAYS + r"\b", t):
        return True
    return bool(re.search(r"\b" + _MINOR + r"\b", t) and re.search(r"\b" + _SEX + r"\b", t))


# ---------------------------------------------------------------- engines + looks
# v1.0: the old SDXL engines are gone. Two new ones, ONE on the GPU at a time (switching takes ~20-60 sec).
# looks: key -> (name, words, snap) - snap = squish it onto a real pixel grid afterwards
ENGINES = {
    "klein": {
        "name": "FLUX.2 klein 4B", "repo": "black-forest-labs/FLUX.2-klein-4B", "train_repo": "black-forest-labs/FLUX.2-klein-base-4B",
        "steps": 4, "cfg": 1.0, "refs": True, "trainable": True, "snap": True, "tail": "",
        "pixel_lora": ("Limbicnation/pixel-art-lora", "pytorch_lora_weights.safetensors"),
        "looks": {
            "pixel": ("Pixel art sprite", "pixel art sprite, game asset, crisp pixels, limited palette", True),
            "dospixel": ("90s DOS pixel", "pixel art, 1990s dos game sprite, gritty, low-res, dark palette", True),
            "cartoon": ("Cartoon", "flat 2d cartoon illustration, bold black outlines, cel shading", False),
            "photo": ("Photo", "raw photo, natural light, 35mm, highly detailed", False),
            "none": ("No extra style", "", False),
        },
    },
    "zimage": {
        "name": "Z-Image Turbo", "repo": "Tongyi-MAI/Z-Image-Turbo",
        "steps": 9, "cfg": 0.0, "refs": False, "trainable": False, "snap": True, "tail": "",
        "looks": {
            "photo": ("Photo", "raw photo, natural light, 35mm film, highly detailed, realistic", False),
            "cinematic": ("Movie still", "cinematic film still, dramatic lighting, anamorphic, color graded", False),
            "pixel": ("Pixel art", "pixel art, 16-bit game sprite, crisp pixels, limited palette", True),
            "anime": ("Anime", "anime illustration, clean line art, vibrant colors", False),
            "darkfantasy": ("Dark fantasy painting", "dark fantasy oil painting, gothic, moody, dramatic lighting", False),
            "none": ("No extra style", "", False),
        },
    },
}
SIZES = {"square": (1024, 1024), "wide": (1216, 832), "tall": (832, 1216), "ultrawide": (1536, 640)}
# picture modes: what to do with a dropped picture
PIC_MODES = ("remake", "snap")


def look_words(engine, look):
    e = ENGINES[engine]
    return e["looks"].get(look, list(e["looks"].values())[0])[1]


def look_snaps(engine, look):
    e = ENGINES[engine]
    return e["looks"].get(look, list(e["looks"].values())[0])[2]


def snap_pixels(img, chunk, colors, sample=Image.NEAREST, palette=None):
    """Squish onto a real pixel grid, cut the colours down, blow it back up crisp.
    Keeps see-through backgrounds if the picture had one."""
    w, h = img.size
    sw, sh = max(1, w // chunk), max(1, h // chunk)
    alpha = None
    if img.mode in ("RGBA", "LA", "P") and "A" in img.convert("RGBA").getbands():
        rgba = img.convert("RGBA").resize((sw, sh), sample)
        a = rgba.split()[3]
        if a.getextrema()[0] < 250:
            alpha = a.point(lambda v: 255 if v >= 128 else 0)
        small = rgba.convert("RGB")
    else:
        small = img.convert("RGB").resize((sw, sh), sample)
    if palette is not None:
        small = small.quantize(palette=palette, dither=Image.Dither.NONE).convert("RGB")
    elif colors and colors > 0:
        small = small.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).convert("RGB")
    if alpha is not None:
        small = small.convert("RGBA")
        small.putalpha(alpha)
    big = small.resize((sw * chunk, sh * chunk), Image.NEAREST)
    return small, big


def fit_long_side(img, long_side=1024):
    w, h = img.size
    s = long_side / max(w, h)
    return img.resize((max(8, round(w * s)), max(8, round(h * s))), Image.LANCZOS)


def sdxl_size(img):
    """Pick a ~1 megapixel size (multiples of 64) that keeps the picture's shape."""
    w, h = img.size
    ratio = w / h
    best = min([(1024, 1024), (1152, 896), (896, 1152), (1216, 832), (832, 1216), (1344, 768),
                (768, 1344), (1536, 640), (640, 1536)], key=lambda wh: abs(wh[0] / wh[1] - ratio))
    return best


# ---------------------------------------------------------------- "my style" packs
def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:32] or "style"


def list_packs():
    packs = []
    for d in sorted(os.listdir(STYLE_DIR)):
        meta = os.path.join(STYLE_DIR, d, "pack.json")
        if os.path.exists(meta):
            try:
                info = json.load(open(meta, encoding="utf-8"))
                if info.get("trained") and info.get("base") != "flux2-klein-4b":
                    info["trained"], info["old_training"] = False, True
                packs.append(info)
            except Exception:
                pass
    return packs


def pack_refs(folder, n=3, side=512):
    """Your drawings, ready to hand klein as reference pictures."""
    out = []
    for i in range(8):
        f = os.path.join(folder, "pic%d.png" % i)
        if os.path.exists(f):
            im = Image.open(f).convert("RGB")
            k = side / max(im.size)
            out.append(im.resize((max(16, int(im.width * k)) // 16 * 16, max(16, int(im.height * k)) // 16 * 16),
                                 Image.NEAREST if k >= 1 else Image.LANCZOS))
        if len(out) >= n:
            break
    return out


def load_pack(pack_id):
    folder = os.path.join(STYLE_DIR, slug(pack_id))
    meta = os.path.join(folder, "pack.json")
    if not os.path.exists(meta):
        return None
    info = json.load(open(meta, encoding="utf-8"))
    if info.get("trained") and info.get("base") != Brain.KLEIN_STYLE_BASE:     # trained for the old SDXL shop - retrain
        info["trained"] = False
    info["collage"] = Image.open(os.path.join(folder, "collage.png")).convert("RGB")
    info["palette"] = Image.open(os.path.join(folder, "palette.png"))
    return info


def build_pack(name, pictures, words, who):
    pid = slug(name)
    folder = os.path.join(STYLE_DIR, pid)
    os.makedirs(folder, exist_ok=True)
    for f in os.listdir(folder):
        os.remove(os.path.join(folder, f))
    pics = []
    pixel = all(max(p.size) <= 320 for p in pictures[:8])          # little pieces = pixel art
    for i, pic in enumerate(pictures[:8]):
        rgba = pic.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (20, 17, 13))
        flat.paste(rgba, mask=rgba.split()[3])
        # pixel art is tiny - blow it up crisp so the style copier can see the pixels
        w, h = flat.size
        k = max(1, 512 // max(w, h))
        flat = flat.resize((w * k, h * k), Image.NEAREST) if k > 1 else fit_long_side(flat, 768)
        flat.save(os.path.join(folder, "pic%d.png" % i))
        pics.append(flat)
    # collage: one picture the style copier looks at
    n = len(pics)
    cols = 1 if n == 1 else 2 if n <= 4 else 3
    rows = -(-n // cols)
    cell = 512
    collage = Image.new("RGB", (cols * cell, rows * cell), (20, 17, 13))
    for i, p in enumerate(pics):
        t = p.copy()
        t.thumbnail((cell, cell), Image.NEAREST)
        collage.paste(t, ((i % cols) * cell + (cell - t.width) // 2, (i // cols) * cell + (cell - t.height) // 2))
    collage.save(os.path.join(folder, "collage.png"))
    # palette thief: the colours you actually drew (see-through parts don't count)
    counts = {}
    for pic in pictures[:8]:
        rgba = pic.convert("RGBA")
        if rgba.width * rgba.height > 1024 * 1024:
            rgba = fit_long_side(rgba, 1024)
        for n_px, (r, g, b, a) in rgba.getcolors(maxcolors=1 << 24):
            if a >= 128:
                counts[(r, g, b)] = counts.get((r, g, b), 0) + n_px
    total = sum(counts.values()) or 1
    px = []
    for c, n_px in counts.items():
        px += [c] * max(1, n_px * 200000 // total)
    strip = Image.new("RGB", (len(px), 1))
    strip.putdata(px)
    ncol = max(2, min(32, len(counts)))
    palette = strip.quantize(colors=ncol, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    palette.save(os.path.join(folder, "palette.png"))
    rgb = palette.getpalette()[:ncol * 3]
    info = {"id": pid, "name": name[:40], "words": words[:200], "count": n, "who": who[:24], "pixel": pixel,
            "colors": ["#%02x%02x%02x" % tuple(rgb[i:i + 3]) for i in range(0, len(rgb), 3)]}
    json.dump(info, open(os.path.join(folder, "pack.json"), "w", encoding="utf-8"))
    log("saved style pack '%s' (%d pics, %d colours) for %s" % (name, n, ncol, who or "someone"))
    return info


def decode_picture(data_url):
    if not data_url:
        return None
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    raw = base64.b64decode(data_url)
    if len(raw) > 15 * 1024 * 1024:
        raise ValueError("Picture's too big. Keep it under 15 MB.")
    img = Image.open(io.BytesIO(raw))
    img.load()
    return img


# ---------------------------------------------------------------- the brain
class Brain:
    """Holds ONE engine on the GPU at a time, plus the clothes checker."""
    KLEIN_STYLE_BASE = "flux2-klein-4b"            # trained styles are made for this one

    def __init__(self):
        self.pipe = None
        self.img2img = None
        self.engine = None
        self.styles = {}               # trained style add-ons snapped on: adapter name -> file time
        self.has_pixel = False
        self.checker = None
        self.squeeze = False
        self.state = "asleep"          # asleep | loading | ready | error | training
        self.note = "Brain's asleep. First picture wakes it up."
        self.lock = threading.Lock()
        self.last_used = time.time()

    # ---- engine swapping
    def load(self, engine):
        if FAKE:
            self.engine, self.state, self.note = engine, "ready", "Ready to rip."
            return
        if self.pipe is not None and self.engine == engine:
            return
        if self.pipe is not None:
            self.unload(quiet=True)
        e = ENGINES[engine]
        self.state = "loading"
        self.note = "Loading %s... FIRST TIME downloads about %s GB (watch the black window)." % (e["name"], "16" if engine == "klein" else "20")
        log(self.note)
        try:
            import torch
            if not torch.cuda.is_available():
                raise RuntimeError("PyTorch can't see the GPU (CUDA not available).")
            self.has_pixel = False
            if engine == "klein":
                from diffusers import Flux2KleinPipeline
                pipe = Flux2KleinPipeline.from_pretrained(e["repo"], torch_dtype=torch.bfloat16)
                try:
                    repo, wn = e["pixel_lora"]
                    pipe.load_lora_weights(repo, weight_name=wn, adapter_name="pixel")
                    self.has_pixel = True
                except Exception as ex:
                    log("(pixel add-on didn't load, pixel looks use words only: %s)" % ex)
            else:
                from diffusers import ZImagePipeline
                qc = None
                try:                                    # 6B core squeezed to 4-bit so it fits next to the desktop's own stuff
                    import bitsandbytes  # noqa: F401
                    from diffusers import PipelineQuantizationConfig
                    qc = PipelineQuantizationConfig(quant_backend="bitsandbytes_4bit",
                                                    quant_kwargs={"load_in_4bit": True, "bnb_4bit_quant_type": "nf4",
                                                                  "bnb_4bit_compute_dtype": torch.bfloat16},
                                                    components_to_quantize=["transformer"])
                except Exception as ex:
                    log("(no bitsandbytes - Z-Image runs in small bites instead: %s)" % ex)
                pipe = ZImagePipeline.from_pretrained(e["repo"], torch_dtype=torch.bfloat16, **({"quantization_config": qc} if qc else {}))
                self.squeeze = qc is None
            if self.squeeze:
                pipe.enable_sequential_cpu_offload()
            else:
                pipe.enable_model_cpu_offload()     # "take turns": each part hops onto the GPU only while it's working
            try:
                pipe.vae.enable_tiling()
            except Exception:
                pass
            pipe.set_progress_bar_config(disable=True)
            self.pipe, self.engine, self.styles = pipe, engine, {}
            self._remake_pipe()
            self.state, self.note = "ready", "Ready to rip."
            mem = vram()
            log("%s engine loaded%s" % (engine, mem))
            if "NEARLY FULL" in mem:
                self.note = "GPU's nearly full - pictures will be slow. Close other GPU stuff (" + gpu_hogs() + ")"
        except Exception as ex:
            self.pipe, self.engine = None, None
            self.state = "error"
            self.note = "Engine failed to load: %s" % ex
            log(self.note)
            raise

    def _remake_pipe(self):
        self.img2img = None
        if self.engine == "zimage":
            from diffusers import ZImageImg2ImgPipeline
            self.img2img = ZImageImg2ImgPipeline.from_pipe(self.pipe)
            self.img2img.set_progress_bar_config(disable=True)

    def unload(self, quiet=False):
        if self.pipe is None:
            return
        if not quiet:
            log("idle %d min - putting the brain to sleep to free the GPU" % IDLE_UNLOAD_MIN)
        self.pipe = self.img2img = None
        self.engine = None
        self.styles = {}
        self.squeeze = False
        try:
            import gc, torch
            gc.collect()
            torch.cuda.empty_cache()
        except Exception:
            pass
        self.state, self.note = "asleep", "Brain's asleep (saving power). Next picture wakes it up."

    # ---- the clothes checker: picture-based results must stay clothed (runs on the CPU)
    def is_nude(self, img):
        if FAKE:
            return os.environ.get("HP_FAKE_NUDE") == "1"
        if self.checker is None:
            from transformers import pipeline
            self.checker = pipeline("image-classification", model="Falconsai/nsfw_image_detection", device=-1)
        scores = {r["label"].lower(): r["score"] for r in self.checker(img.convert("RGB"))}
        return scores.get("nsfw", 0.0) > 0.35

    # ---- add-ons for this picture: klein's pixel add-on, plus YOUR trained style
    def _common(self, p):
        import torch
        names, weights = [], []
        if self.engine == "klein":
            if self.has_pixel and p.get("snap") and not p.get("_pack"):
                names.append("pixel")
                weights.append(p["pixel_strength"])
            pack = p.get("_pack")
            if pack and pack.get("trained") and pack.get("base") == self.KLEIN_STYLE_BASE:
                folder = os.path.join(STYLE_DIR, pack["id"])
                f = os.path.join(folder, "style_lora.safetensors")
                an = "my_" + re.sub(r"[^a-z0-9]", "_", pack["id"])
                stamp = os.path.getmtime(f)
                if self.styles.get(an) != stamp:            # new, or re-trained since last time
                    if an in self.styles:
                        self.pipe.delete_adapters(an)
                    self.note = "Snapping on your style..."
                    self.pipe.load_lora_weights(folder, weight_name="style_lora.safetensors", adapter_name=an)
                    self.styles[an] = stamp
                    log("snapped on style '%s'%s" % (pack["name"], vram()))
                names.append(an)
                weights.append(p["style_strength"])
            if names:
                self.pipe.enable_lora()
                self.pipe.set_adapters(names, adapter_weights=weights)
            elif self.has_pixel or self.styles:
                self.pipe.disable_lora()
        return torch.Generator("cpu").manual_seed(p["seed"])

    # ---- never crawl: if a step takes too long the GPU overflowed into regular RAM.
    # Stop, squeeze (small bites so it fits), try once more. Still too slow? Stop and say so.
    STEP_LIMIT, SQUEEZE_STEP_LIMIT = 20, 90

    def _set_squeeze(self, on):
        if FAKE or self.pipe is None or self.squeeze == on:
            return False
        import torch
        try:
            self.pipe.remove_all_hooks()
            self.pipe.enable_sequential_cpu_offload()       # small bites: only the bit that's working sits on the GPU
            self._remake_pipe()
        except Exception as ex:                             # (a 4-bit squeezed model can't do small bites)
            log("couldn't squeeze: %s" % ex)
            try:
                self.pipe.enable_model_cpu_offload()
            except Exception:
                pass
            return False
        self.squeeze = True
        torch.cuda.empty_cache()
        log("squeeze mode ON (fits in 12 GB, slower)%s" % vram())
        return True

    def _run(self, which, kw):
        import torch
        torch.cuda.empty_cache()
        for attempt in (1, 2):
            pipe = self.img2img if which == "img2img" else self.pipe
            limit = self.SQUEEZE_STEP_LIMIT if self.squeeze else self.STEP_LIMIT
            t = {"last": time.time()}

            def watch(pp, i, ts, k):
                now_ = time.time()
                if now_ - t["last"] > limit:
                    raise TooSlow()
                t["last"] = now_
                return k
            try:
                return pipe(callback_on_step_end=watch, **kw).images[0]
            except TooSlow:
                torch.cuda.empty_cache()
                if attempt == 1 and not self.squeeze:
                    log("GPU overflowed (a step took over %ds) - squeezing in and trying again%s" % (limit, vram()))
                    self.note = "GPU was too full - squeezing it in and trying again..."
                    if self._set_squeeze(True):
                        continue
                self.note = "Ready to rip."
                raise ValueError("Too big for the GPU right now. Try a smaller size, "
                                 "or close other GPU stuff (%s)." % gpu_hogs())

    def _fake(self, p, base=None):
        time.sleep(1.5)
        if base is not None:
            return base
        rnd = random.Random(p["seed"])
        img = Image.new("RGB", (p["width"] // 8, p["height"] // 8))
        px = img.load()
        for y in range(img.height):
            for x in range(img.width):
                px[x, y] = (rnd.randint(20, 90), rnd.randint(40, 110), rnd.randint(10, 60))
        return img.resize((p["width"], p["height"]), Image.NEAREST)

    def make(self, p, prompt, refs=None):
        """Text -> picture. klein can also look at reference pictures (your drawings) while it draws."""
        self.last_used = time.time()
        if FAKE:
            return self._fake(p)
        g = self._common(p)
        kw = dict(prompt=prompt, width=p["width"], height=p["height"], num_inference_steps=p["steps"],
                  guidance_scale=p["cfg"], generator=g)
        if refs and self.engine == "klein":
            kw["image"] = refs
        img = self._run("txt2img", kw)
        self.last_used = time.time()
        self.note = "Ready to rip."
        return img

    def remake(self, p, init_img, prompt, refs=None):
        """Your dropped picture -> redrawn. klein edits it as a reference, Z-Image repaints over it."""
        self.last_used = time.time()
        w, h = sdxl_size(init_img)
        base = Image.new("RGB", init_img.size, (20, 17, 13))
        rgba = init_img.convert("RGBA")
        base.paste(rgba, mask=rgba.split()[3])
        init = base.resize((w, h), Image.LANCZOS)
        if FAKE:
            return self._fake(p, init)
        g = self._common(p)
        if self.engine == "klein":
            img = self._run("txt2img", dict(prompt=prompt, image=[init] + list(refs or [])[:2], width=w, height=h,
                                            num_inference_steps=p["steps"], guidance_scale=p["cfg"], generator=g))
        else:
            change = p["change"]
            steps = max(p["steps"], int(round(2 / max(change, 0.05))))
            img = self._run("img2img", dict(prompt=prompt, image=init, strength=change, width=w, height=h,
                                            num_inference_steps=steps, guidance_scale=p["cfg"], generator=g))
        self.last_used = time.time()
        self.note = "Ready to rip."
        return img


def gpu_hogs():
    """Which programs are sitting on the GPU (so you know what to close)."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=process_name,used_memory", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        me = os.getpid()
        rows = [l.strip() for l in out.splitlines() if l.strip()]
        return "; ".join(os.path.basename(r.split(",")[0]) + " " + r.split(",")[1].strip() for r in rows) or "nothing listed"
    except Exception:
        return "couldn't ask nvidia-smi"


def vram():
    """How full the GPU's video memory is - goes in the log so we can spot overflows."""
    if FAKE:
        return ""
    try:
        import torch
        free, total = torch.cuda.mem_get_info()
        used = (total - free) / 2**30
        ours = torch.cuda.memory_reserved() / 2**30
        warn = ("  !! NEARLY FULL - pictures will crawl. Hogging the GPU: " + gpu_hogs()) if free < 0.8 * 2**30 else ""
        return " (video memory %.1f / %.1f GB used, picture brain %.1f GB of that%s)" % (used, total / 2**30, ours, warn)
    except Exception:
        return ""


class TooSlow(Exception):
    """A step took way too long - the GPU spilled into regular RAM."""


brain = Brain()
jobs = {}
job_q = queue.Queue()
jobs_lock = threading.Lock()


def load_recent():
    try:
        return json.load(open(RECENT_FILE, encoding="utf-8"))
    except Exception:
        return []


def save_recent(items):
    with open(RECENT_FILE, "w", encoding="utf-8") as f:
        json.dump(items[-200:], f)


def documents_dir():
    """Your real Documents folder (Windows knows where it is, even if OneDrive moved it)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            from uuid import UUID

            class GUID(ctypes.Structure):
                _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]
            u = UUID("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}")
            g = GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))
            ptr = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(ptr)) == 0:
                out = ptr.value
                ctypes.windll.ole32.CoTaskMemFree(ptr)
                return out
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def copy_to_documents(src, name):
    """Every picture also lands in Documents\\FreedomOS Pictures."""
    try:
        d = os.path.join(documents_dir(), "FreedomOS Pictures")
        os.makedirs(d, exist_ok=True)
        shutil.copyfile(src, os.path.join(d, name + ".png"))
    except Exception as e:
        print("couldn't copy to Documents:", e, flush=True)


def save_result(img, p, job_id, extra):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = "%s-%s" % (stamp, job_id[:6])
    if p.get("snap"):
        palette = p["_pack"]["palette"] if (p.get("_pack") and p.get("use_palette")) else None
        small, big = snap_pixels(img, p["chunk"], p["colors"], palette=palette)
        big.save(os.path.join(OUT_DIR, name + ".png"))
        small.save(os.path.join(OUT_DIR, name + "_small.png"))
        copy_to_documents(os.path.join(OUT_DIR, name + ".png"), name)
        w, h = small.size
    else:
        img.save(os.path.join(OUT_DIR, name + ".png"))
        copy_to_documents(os.path.join(OUT_DIR, name + ".png"), name)
        thumb = img.copy()
        thumb.thumbnail((384, 384), Image.LANCZOS)
        thumb.save(os.path.join(OUT_DIR, name + "_small.png"))
        w, h = img.size
    entry = {"name": name, "prompt": p["prompt"], "who": p["who"], "seed": p["seed"], "w": w, "h": h,
             "engine": p["engine"], "mode": p["mode"], "snap": bool(p.get("snap")), "when": datetime.now().strftime("%b %d %H:%M")}
    entry.update(extra)
    with jobs_lock:
        rec = load_recent()
        rec.append(entry)
        save_recent(rec)
    return entry


def worker():
    while True:
        job_id = job_q.get()
        job = jobs.get(job_id)
        if not job:
            continue
        p = job["params"]
        try:
            pack = load_pack(p["pack"]) if p.get("pack") else None
            if p.get("pack") and pack is None:
                raise ValueError("That style pack is gone. Pick another look.")
            p["_pack"] = pack
            e = ENGINES[p["engine"]]
            while trainer.running():
                job["status"] = "queued"
                time.sleep(2)
            with brain.lock:
                if brain.engine != p["engine"] or brain.state != "ready" or (brain.pipe is None and not FAKE):
                    job["status"] = "loading"
                    brain.load(p["engine"])
                job["status"] = "working"
                t0 = time.time()
                refs = None
                trained = bool(pack and pack.get("trained") and p["engine"] == "klein")
                if trained:
                    style = ", ".join(x for x in ("%s style" % pack["trigger"], pack["words"]) if x)
                elif pack:      # not trained yet: klein copies straight off your drawings; Z-Image gets your words
                    if e["refs"]:
                        refs = pack_refs(os.path.join(STYLE_DIR, pack["id"]))
                        style = "drawn in the exact same art style as the reference images (same line work, shading and colours)"
                        if pack.get("words"):
                            style += ", " + pack["words"]
                    else:
                        style = pack.get("words", "")
                    if pack.get("pixel"):
                        style = "pixel art, " + style
                else:
                    style = look_words(p["engine"], p["look"])
                pic = p.get("picture")
                parts = [p["prompt"], style, e["tail"]]
                full = ", ".join(x for x in parts if x)
                if pic is None:
                    img = brain.make(p, full, refs)
                else:
                    img = brain.remake(p, pic, full, refs)
                # the one rule for picture jobs: a dropped picture could be a real person - stays clothed
                if pic is not None and brain.is_nude(img):
                    raise ValueError("That came out nude, so it got tossed. Stuff made from a dropped picture has to stay clothed.")
                secs = round(time.time() - t0, 1)
                log("picture took %ss%s" % (secs, vram()))
                seen = ""
            entry = save_result(img, p, job_id, {"seen": seen, "secs": secs,
                                                 "style": (pack["name"] + ("" if trained else " (copied)" if refs else "")) if pack
                                                 else ENGINES[p["engine"]]["looks"].get(p["look"], ("",))[0]})
            job.update(status="done", result=entry)
            log("made %s (%s/%s) for %s in %ss: %s" % (entry["name"], p["engine"], p["mode"], p["who"] or "someone", secs, p["prompt"][:80]))
        except Exception as ex:
            job.update(status="error", error=str(ex))
            log("job failed: %s" % ex)
        finally:
            p["picture"] = None
            p["_pack"] = None


# ---------------------------------------------------------------- TRAIN MY STYLE (v0.5)
class Trainer:
    """Runs train_style.py on one style pack. The picture brain gets put away first so the trainer has the whole GPU."""
    SCRIPT = os.path.join(HERE, "train_style.py")

    def __init__(self):
        self.proc, self.pack, self.starting = None, None, False
        self.lock = threading.Lock()

    def running(self):
        return self.starting or (self.proc is not None and self.proc.poll() is None)

    def start(self, pack_id):
        folder = os.path.join(STYLE_DIR, slug(pack_id))
        if not os.path.exists(os.path.join(folder, "pack.json")):
            raise ValueError("That style pack is gone.")
        with self.lock:
            if self.running():
                raise ValueError("Already learning a style - one at a time.")
            self.pack, self.starting = slug(pack_id), True
            for f in ("train.json", "train.stop"):
                if os.path.exists(os.path.join(folder, f)):
                    os.remove(os.path.join(folder, f))
        json.dump({"state": "waiting", "step": 0, "total": 0, "note": "Waiting for the GPU to finish its picture...", "when": time.time()},
                  open(os.path.join(folder, "train.json"), "w", encoding="utf-8"))

        def go():
            try:
                with brain.lock:                      # waits for any picture in progress, then frees the GPU
                    brain.unload(quiet=True)
                    brain.state, brain.note = "training", "Learning a style - pictures wait till it's done."
                    logf = open(os.path.join(LOG_DIR, "train.log"), "a", encoding="utf-8")
                    logf.write("\n==== %s training %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M"), self.pack))
                    logf.flush()
                    self.proc = subprocess.Popen([sys.executable, self.SCRIPT, folder, "--parent", str(os.getpid())],
                                                 stdout=logf, stderr=subprocess.STDOUT, cwd=HERE,
                                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                log("training style '%s' (watch logs\\train.log)" % self.pack)
            finally:
                self.starting = False
            self.proc.wait()
            st = self.status() or {}
            log("style training %s: %s" % (self.pack, st.get("note", "finished")))
            with brain.lock:
                if brain.state == "training":
                    brain.state, brain.note = "asleep", "Brain's asleep. Next picture wakes it up."
        threading.Thread(target=go, daemon=True).start()

    def stop(self):
        if not self.running() or not self.pack:
            return
        open(os.path.join(STYLE_DIR, self.pack, "train.stop"), "w").close()   # trainer quits at its next step

        def hard():
            time.sleep(25)
            if self.proc is not None and self.proc.poll() is None:
                self.proc.kill()
        threading.Thread(target=hard, daemon=True).start()

    def status(self):
        if not self.pack:
            return None
        try:
            st = json.load(open(os.path.join(STYLE_DIR, self.pack, "train.json"), encoding="utf-8"))
        except Exception:
            return None
        st["pack"], st["running"] = self.pack, self.running()
        if not st["running"] and st.get("state") not in ("done", "stopped", "failed"):
            st.update(state="failed", note="Trainer quit unexpectedly - check logs\\train.log")
        return st


trainer = Trainer()


def idle_watch():
    while True:
        time.sleep(30)
        if brain.pipe is not None and time.time() - brain.last_used > IDLE_UNLOAD_MIN * 60 and job_q.empty():
            with brain.lock:
                brain.unload()


# ---------------------------------------------------------------- web
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024


def client_ip():
    return request.remote_addr or ""


def from_this_pc():
    return client_ip() in ("127.0.0.1", "::1")


def is_local():
    """The guy running the rig (host powers: shut down, toss styles). Through FreedomOS, only
    requests FreedomOS marks as coming from your own desktop count."""
    if not from_this_pc():
        return False
    if request.headers.get("X-HP-Proxied") == "1":
        return request.headers.get("X-HP-Host") == "1"
    return True


def allowed():
    ip = client_ip()
    if from_this_pc():
        return True   # your PC, or FreedomOS passing along someone it already checked the key for
    try:
        if ipaddress.ip_address(ip) not in TAILSCALE_NET:
            return False
    except ValueError:
        return False
    k = request.args.get("key") or request.cookies.get("hp_key") or request.headers.get("X-Crew-Key")
    return bool(k) and secrets.compare_digest(k, KEY)


@app.before_request
def gate():
    if request.path == "/health":
        return None
    if not allowed():
        return make_response("No key, no entry. Ask the person running the Pixel Shop for the crew link.", 403)


@app.route("/health")
def health():
    return jsonify(ok=True, version=VERSION)


@app.route("/")
def index():
    if request.args.get("key"):
        resp = redirect("./")
        resp.set_cookie("hp_key", request.args["key"], max_age=60 * 60 * 24 * 365, samesite="Lax")
        return resp
    return send_from_directory(os.path.join(HERE, "static"), "index.html")


@app.route("/static/<path:p>")
def static_files(p):
    return send_from_directory(os.path.join(HERE, "static"), p)


@app.route("/api/status")
def status():
    waiting = sum(1 for j in jobs.values() if j["status"] in ("queued", "loading", "looking", "working"))
    engines = {k: {"name": e["name"], "snap": e["snap"], "steps": e["steps"], "refs": e["refs"], "trainable": e["trainable"],
                   "looks": [[lk, v[0], v[2]] for lk, v in e["looks"].items()]} for k, e in ENGINES.items()}
    return jsonify(version=VERSION, state=brain.state, note=brain.note, waiting=waiting, loaded=brain.engine, training=trainer.status(),
                   in_f35=os.environ.get("HP_NO_LINK") == "1", made=len(load_recent()),
                   host=is_local(), fake=FAKE, engines=engines, sizes=list(SIZES))


def clamp(v, lo, hi, default, cast=int):
    try:
        return max(lo, min(hi, cast(v)))
    except Exception:
        return default


@app.route("/api/make", methods=["POST"])
def make():
    d = request.get_json(force=True, silent=True) or {}
    prompt = str(d.get("prompt", "")).strip()[:600]
    engine = d.get("engine") if d.get("engine") in ENGINES else "klein"
    e = ENGINES[engine]
    try:
        picture = decode_picture(d.get("picture"))
    except Exception as ex:
        return jsonify(error=str(ex) if "." in str(ex) else "Couldn't read that picture. Try a PNG or JPG."), 400
    mode = "text"
    if picture is not None:
        mode = d.get("mode") if d.get("mode") in PIC_MODES else "remake"
    if not prompt and picture is None:
        return jsonify(error="Type something or drop a picture first."), 400
    if hard_line(prompt):
        log("BLOCKED a prompt from %s (hard line)" % client_ip())
        return jsonify(error="Nope. That's the one thing this rig will never make."), 400
    if mode == "snap":
        pid = slug(str(d.get("style", ""))[3:]) if str(d.get("style", "")).startswith("my:") else None
        return snap_now(picture, d, pid if d.get("use_palette", True) else None)
    if picture is not None and SEXY.search(prompt.lower()):
        log("BLOCKED a sexual picture job from %s" % client_ip())
        return jsonify(error="Nope. Stuff made from a dropped picture has to stay clothed - could be a real person."), 400
    look = str(d.get("style") or "")
    pack_id = None
    if look.startswith("my:"):
        pack_id = slug(look[3:])
        if not os.path.exists(os.path.join(STYLE_DIR, pack_id, "pack.json")):
            return jsonify(error="That style pack is gone. Pick another look."), 400
    elif look not in e["looks"]:
        look = list(e["looks"])[0]
    if pack_id:
        try:
            snap = bool(json.load(open(os.path.join(STYLE_DIR, pack_id, "pack.json"), encoding="utf-8")).get("pixel"))
        except Exception:
            snap = False
    else:
        snap = look_snaps(engine, look)
    if d.get("snap") in (True, False):
        snap = d["snap"]
    w, h = SIZES.get(d.get("size"), SIZES["square"])
    seed = d.get("seed")
    seed = clamp(seed, 0, 2**31 - 1, random.randint(0, 2**31 - 1)) if seed not in (None, "", -1, "-1") \
        else random.randint(0, 2**31 - 1)
    extra_neg = str(d.get("negative", "")).strip()[:300]
    params = {
        "engine": engine, "prompt": prompt, "look": look, "pack": pack_id, "mode": mode,
        "style_strength": clamp(d.get("style_strength"), 0.0, 1.5, 0.8, float),
        "use_palette": bool(d.get("use_palette", True)),
        "negative": extra_neg, "snap": snap,
        "width": w, "height": h,
        "steps": clamp(d.get("steps"), 2, 60, e["steps"]) if d.get("steps") not in (None, "", 0) else e["steps"],
        "cfg": e["cfg"],
        "pixel_strength": clamp(d.get("pixel_strength"), 0.0, 2.0, 1.0, float),
        "chunk": clamp(d.get("chunk"), 4, 32, 8),
        "colors": clamp(d.get("colors"), 0, 256, 32),
        "seed": seed,
        "who": str(d.get("who", "")).strip()[:24],
        "picture": fit_long_side(picture, 1024) if picture is not None else None,
        "change": clamp(d.get("change"), 0.2, 0.95, 0.6, float),
    }
    job_id = uuid.uuid4().hex
    jobs[job_id] = {"status": "queued", "params": params, "made": time.time()}
    job_q.put(job_id)
    for k in [k for k, j in list(jobs.items()) if time.time() - j["made"] > 3600]:
        jobs.pop(k, None)
    return jsonify(id=job_id)


def snap_now(picture, d, pack_id=None):
    """Just pixelate - no AI, no GPU, done in a second."""
    t0 = time.time()
    img = fit_long_side(picture, 1024)
    pack = load_pack(pack_id) if pack_id else None
    small, big = snap_pixels(img, clamp(d.get("chunk"), 4, 32, 8), clamp(d.get("colors"), 0, 256, 32), Image.BOX,
                             palette=pack["palette"] if pack else None)
    name = "%s-%s" % (datetime.now().strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:6])
    big.save(os.path.join(OUT_DIR, name + ".png"))
    small.save(os.path.join(OUT_DIR, name + "_small.png"))
    copy_to_documents(os.path.join(OUT_DIR, name + ".png"), name)
    entry = {"name": name, "prompt": "(pixelated a picture)", "style": "snap", "mode": "snap", "seen": "", "engine": "snap", "snap": True,
             "who": str(d.get("who", "")).strip()[:24], "seed": 0, "w": small.width, "h": small.height,
             "secs": round(time.time() - t0, 1), "when": datetime.now().strftime("%b %d %H:%M")}
    with jobs_lock:
        rec = load_recent()
        rec.append(entry)
        save_recent(rec)
    log("pixelated a picture for %s" % (entry["who"] or "someone"))
    return jsonify(done=entry)


@app.route("/api/job/<job_id>")
def job(job_id):
    j = jobs.get(job_id)
    if not j:
        return jsonify(status="gone"), 404
    ahead = 0
    if j["status"] == "queued":
        ahead = sum(1 for k, o in jobs.items() if o["status"] in ("queued", "loading", "looking", "working") and o["made"] < j["made"])
    return jsonify(status=j["status"], ahead=ahead, note=brain.note,
                   result=j.get("result"), error=j.get("error"))


@app.route("/api/mystyles")
def mystyles():
    return jsonify(list_packs())


@app.route("/api/mystyle", methods=["POST"])
def add_mystyle():
    d = request.get_json(force=True, silent=True) or {}
    name = str(d.get("name", "")).strip()
    if not name:
        return jsonify(error="Give your style a name."), 400
    try:
        pics = [decode_picture(p) for p in (d.get("pictures") or [])[:8]]
    except Exception:
        return jsonify(error="Couldn't read one of those pictures. Use PNG or JPG."), 400
    pics = [p for p in pics if p is not None]
    if not pics:
        return jsonify(error="Drop at least one of your pieces in there."), 400
    with jobs_lock:
        info = build_pack(name, pics, str(d.get("words", "")).strip(), str(d.get("who", "")).strip())
    return jsonify(info)


@app.route("/api/mystyle/<pack_id>", methods=["DELETE"])
def del_mystyle(pack_id):
    if not is_local():
        return jsonify(error="Only the guy running the rig can toss a style."), 403
    import shutil
    if trainer.running() and trainer.pack == slug(pack_id):
        return jsonify(error="It's training right now - stop it first."), 400
    folder = os.path.join(STYLE_DIR, slug(pack_id))
    if os.path.isdir(folder):
        shutil.rmtree(folder)
        log("tossed style pack %s" % pack_id)
    return jsonify(ok=True)


@app.route("/api/mystyle/<pack_id>/train", methods=["POST"])
def train_mystyle(pack_id):
    if not is_local():
        return jsonify(error="Only the person running the PC can train a style (it ties up the GPU for an hour or two)."), 403
    if FAKE:
        return jsonify(error="Test mode - no GPU to train on."), 400
    try:
        trainer.start(pack_id)
    except ValueError as ex:
        return jsonify(error=str(ex)), 400
    return jsonify(ok=True)


@app.route("/api/train")
def train_status():
    return jsonify(trainer.status() or {})


@app.route("/api/train/stop", methods=["POST"])
def train_stop():
    if not is_local():
        abort(403)
    trainer.stop()
    return jsonify(ok=True)


@app.route("/mystyle/<pack_id>/<name>")
def mystyle_img(pack_id, name):
    if not re.fullmatch(r"(collage|pic\d|train_peek\d)\.png", name):
        abort(404)
    return send_from_directory(os.path.join(STYLE_DIR, slug(pack_id)), name)


@app.route("/api/recent")
def recent():
    return jsonify(load_recent()[-48:][::-1])


@app.route("/img/<path:name>")
def img(name):
    if not re.fullmatch(r"[\w\-]+\.png", name):
        abort(404)
    resp = send_from_directory(OUT_DIR, name)
    if request.args.get("dl"):
        resp.headers["Content-Disposition"] = "attachment; filename=%s" % name
    return resp


@app.route("/shutdown", methods=["POST"])
def shutdown():
    if not (from_this_pc() and request.headers.get("X-HP-Proxied") != "1"):   # only FreedomOS itself / this PC directly
        abort(403)
    log("shut down")
    if trainer.proc is not None and trainer.proc.poll() is None:
        trainer.proc.kill()                      # don't leave a trainer hogging the GPU
    threading.Thread(target=lambda: (time.sleep(0.5), os._exit(0)), daemon=True).start()
    return jsonify(ok=True)


def main():
    log("Pixel Shop v%s (FLUX.2 klein + Z-Image) starting on port %d%s" % (VERSION, PORT, " (FAKE test mode)" if FAKE else ""))
    write_link_file()
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=idle_watch, daemon=True).start()
    try:
        from waitress import serve
        serve(app, host=HOST, port=PORT, threads=8)
    except ImportError:
        app.run(host=HOST, port=PORT, threaded=True)


if __name__ == "__main__":
    main()
