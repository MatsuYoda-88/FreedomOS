"""
Pixel Shop v1.0 - TRAIN MY STYLE (FLUX.2 klein 4B).
Teaches klein how YOU draw, from the pieces in one of your style packs.
Makes a small add-on file (a "LoRA") that the shop snaps on whenever you pick that style.

    python train_style.py <style pack folder> [--steps 1000] [--res 512]

Writes progress to <pack>/train.json so the shop can show it. Drop a file called "train.stop" in the pack folder to stop early.
The training itself is the official diffusers script (train_klein_lora.py) with the GPU-friendly settings:
4-bit squeezed base, cached pictures, text reader + picture decoder parked on the CPU, 8-bit optimizer.
"""
import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time

from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "black-forest-labs/FLUX.2-klein-4B"
BASE_TAG = "flux2-klein-4b"


def write_progress(folder, **kw):
    kw["when"] = time.time()
    tmp = os.path.join(folder, "train.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(kw, f)
    os.replace(tmp, os.path.join(folder, "train.json"))


def parent_alive(pid):
    """Is the Pixel Shop that started me still running? (If it got killed, quit - don't hog the GPU.)"""
    if not pid:
        return True
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259             # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def say(msg):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


# ------------------------------------------------------------------ getting the pictures ready
def split_sheet(img):
    """A sheet with several characters side by side -> one crop per character.
    Finds the background colour from the edges, then splits wherever there's a clean gap of background."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    px = rgb.load()
    edge = [px[x, 0] for x in range(w)] + [px[x, h - 1] for x in range(w)] + [px[0, y] for y in range(h)] + [px[w - 1, y] for y in range(h)]
    bg = max(set(edge), key=edge.count)

    def is_fg(c):
        return abs(c[0] - bg[0]) + abs(c[1] - bg[1]) + abs(c[2] - bg[2]) > 36

    col_has = [any(is_fg(px[x, y]) for y in range(0, h, max(1, h // 200))) for x in range(w)]
    runs, start, gap = [], None, 0
    min_gap = max(3, w // 150)
    for x, f in enumerate(col_has + [False] * (min_gap + 1)):
        if f:
            if start is None:
                start = x
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= min_gap:
                runs.append((start, x - gap + 1))
                start, gap = None, 0
    crops = []
    for x0, x1 in runs:
        if x1 - x0 < max(8, w // 60):
            continue
        rows = [y for y in range(h) if any(is_fg(px[x, y]) for x in range(x0, x1, max(1, (x1 - x0) // 60)))]
        if not rows:
            continue
        crops.append(rgb.crop((x0, rows[0], x1, rows[-1] + 1)))
    return (crops if crops else [rgb]), bg


def place(crop, res, bg, fill=0.86):
    """Put one character on a square canvas, scaled up CRISP (no blur - it's pixel art)."""
    w, h = crop.size
    k = fill * res / max(w, h)
    k = max(1, int(k)) if k >= 1 else k        # whole-number blow-up keeps every pixel square
    nw, nh = max(1, int(w * k)), max(1, int(h * k))
    big = crop.resize((nw, nh), Image.NEAREST)
    canvas = Image.new("RGB", (res, res), bg)
    canvas.paste(big, ((res - nw) // 2, (res - nh) // 2))
    return canvas


def recolour_bg(crop, old_bg, new_bg):
    """Swap the background colour behind a character."""
    if old_bg == new_bg:
        return crop
    c = crop.copy()
    px = c.load()
    for y in range(c.height):
        for x in range(c.width):
            p = px[x, y]
            if abs(p[0] - old_bg[0]) + abs(p[1] - old_bg[1]) + abs(p[2] - old_bg[2]) <= 36:
                px[x, y] = new_bg
    return c


def fit_soft(img, res, bg, fill=0.9):
    """Not pixel art: scale smoothly onto a square canvas."""
    w, h = img.size
    k = fill * res / max(w, h)
    big = img.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
    canvas = Image.new("RGB", (res, res), bg)
    canvas.paste(big, ((res - big.width) // 2, (res - big.height) // 2))
    return canvas


def build_dataset(folder, out_dir, res, pixel):
    pics = sorted(f for f in os.listdir(folder) if re.fullmatch(r"pic\d\.png", f))
    crops, bgs = [], []
    for f in pics:
        im = Image.open(os.path.join(folder, f))
        if pixel:
            cs, bg = split_sheet(im)
        else:
            cs, bg = [im.convert("RGB")], (0, 0, 0)
        crops += cs
        bgs += [bg] * len(cs)
    if not crops:
        raise SystemExit("No pictures in that style pack.")
    say("found %d piece(s) in %d picture(s)" % (len(crops), len(pics)))
    backs = [(24, 24, 28), (236, 234, 226), (118, 120, 118), (70, 92, 70)]
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):
        os.remove(os.path.join(out_dir, f))
    n = 0
    for c, bg in zip(crops, bgs):
        for flip in (False, True):
            cc = ImageOps.mirror(c) if flip else c
            if pixel:
                for nb in [bg] + random.sample(backs, 2):
                    fill = 0.86 if len(crops) > 2 else random.choice([0.6, 0.86])
                    place(recolour_bg(cc, bg, nb), res, nb, fill).save(os.path.join(out_dir, "%03d.png" % n)); n += 1
            else:
                fit_soft(cc, res, (0, 0, 0) if random.random() < .5 else (236, 234, 226)).save(os.path.join(out_dir, "%03d.png" % n)); n += 1
    files = sorted(os.listdir(out_dir))
    random.shuffle(files)
    for i, f in enumerate(files[:6]):
        shutil.copy(os.path.join(out_dir, f), os.path.join(folder, "train_peek%d.png" % i))
    for f in files[64:]:                                   # 64 is plenty
        os.remove(os.path.join(out_dir, f))
    say("training set: %d pictures (flipped + different backgrounds)" % min(n, 64))
    return min(n, 64)


STEP_RE = re.compile(r"(\d+)/(\d+) \[")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--steps", type=int, default=1000)
    ap.add_argument("--res", type=int, default=512)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--parent", type=int, default=0)
    ap.add_argument("--dry", action="store_true", help="test: build the set + command, don't train")
    a = ap.parse_args()
    folder = os.path.abspath(a.folder)
    meta_path = os.path.join(folder, "pack.json")
    meta = json.load(open(meta_path, encoding="utf-8"))
    trigger = "pxl" + "".join(ch for ch in meta["id"] if ch.isalnum())[:12]
    pixel = bool(meta.get("pixel", True))
    stop_file = os.path.join(folder, "train.stop")
    if os.path.exists(stop_file):
        os.remove(stop_file)
    t0 = time.time()
    write_progress(folder, state="getting ready", step=0, total=a.steps, note="Getting your pictures ready...")
    data_dir = os.path.join(folder, "train_set")
    build_dataset(folder, data_dir, a.res, pixel)
    out_dir = os.path.join(folder, "lora_out")
    shutil.rmtree(out_dir, ignore_errors=True)
    qcfg = os.path.join(folder, "squeeze_4bit.json")
    json.dump({"load_in_4bit": True, "bnb_4bit_quant_type": "nf4"}, open(qcfg, "w"))
    prompt = "%s style%s" % (trigger, ", pixel art" if pixel else "") + (", " + meta["words"] if meta.get("words") else "")
    cmd = [sys.executable, os.path.join(HERE, "train_klein_lora.py"),
           "--pretrained_model_name_or_path", a.repo, "--instance_data_dir", data_dir, "--output_dir", out_dir,
           "--instance_prompt", prompt, "--resolution", str(a.res), "--train_batch_size", "1",
           "--gradient_accumulation_steps", "2", "--gradient_checkpointing", "--cache_latents",
           "--optimizer", "adamW", "--use_8bit_adam", "--learning_rate", str(a.lr), "--lr_scheduler", "constant",
           "--lr_warmup_steps", "0", "--max_train_steps", str(a.steps), "--rank", str(a.rank), "--lora_alpha", str(a.rank),
           "--mixed_precision", "bf16", "--guidance_scale", "1", "--offload", "--bnb_quantization_config_path", qcfg,
           "--report_to", "none", "--checkpointing_steps", "100000", "--skip_final_inference", "--seed", "0",
           "--dataloader_num_workers", "0"]
    if pixel:
        pass                       # flips are already in the set (random_flip would blur nothing, but keep it simple)
    if os.environ.get("PX_CPU_TEST"):              # test on a PC with no GPU: drop the GPU-only squeezes, tiny model sizes
        drop = {"--use_8bit_adam", "--offload", "--gradient_checkpointing"}
        out, skip = [], False
        for i, c in enumerate(cmd):
            if skip:
                skip = False; continue
            if c in drop:
                continue
            if c in ("--bnb_quantization_config_path", "--mixed_precision", "--resolution"):
                skip = True; continue
            out.append(c)
        cmd = out + ["--mixed_precision", "no", "--resolution", "64", "--text_encoder_out_layers", "1", "--max_sequence_length", "64"]
    say("command: " + " ".join('"%s"' % c if " " in c else c for c in cmd))
    if a.dry:
        write_progress(folder, state="stopped", step=0, total=a.steps, note="Dry run - nothing trained.")
        return
    write_progress(folder, state="loading", step=0, total=a.steps,
                   note="Loading klein for school (first time downloads ~16 GB)...")
    env = dict(os.environ, PYTHONUNBUFFERED="1", TQDM_MININTERVAL="2")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=HERE, env=env,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    buf, last = "", 0.0
    step = 0
    stopped = False
    while True:
        ch = proc.stdout.read(256)
        if not ch:
            break
        txt = ch.decode("utf-8", "ignore")
        sys.stdout.write(txt); sys.stdout.flush()
        buf = (buf + txt)[-600:]
        for m in STEP_RE.finditer(buf):
            if int(m.group(2)) == a.steps:
                step = int(m.group(1))
        now = time.time()
        if now - last > 2:
            last = now
            left = ""
            if step > 5:
                per = (now - t0) / step
                left = " - about %d min left" % max(1, (a.steps - step) * per / 60)
            write_progress(folder, state="training" if step else "loading", step=step, total=a.steps,
                           note=("Learning your style: step %d of %d%s" % (step, a.steps, left)) if step
                           else "Loading klein for school (first time downloads ~16 GB)...")
            if os.path.exists(stop_file) or not parent_alive(a.parent):
                stopped = True
                proc.kill()
                break
    proc.wait()
    lora = os.path.join(out_dir, "pytorch_lora_weights.safetensors")
    if stopped:
        write_progress(folder, state="stopped", step=step, total=a.steps, note="Stopped. Nothing saved - hit TRAIN IT to start over.")
        return
    if proc.returncode != 0 or not os.path.exists(lora):
        write_progress(folder, state="failed", step=step, total=a.steps,
                       note="Training crashed - check logs\\train.log (send it to Claude).")
        raise SystemExit(1)
    shutil.copy(lora, os.path.join(folder, "style_lora.safetensors"))
    meta.update(trained=True, base=BASE_TAG, trigger=trigger, trained_when=time.strftime("%b %d %H:%M"),
                trained_steps=a.steps, train_minutes=round((time.time() - t0) / 60, 1))
    meta.pop("old_training", None)
    json.dump(meta, open(meta_path, "w", encoding="utf-8"))
    shutil.rmtree(out_dir, ignore_errors=True)
    write_progress(folder, state="done", step=a.steps, total=a.steps,
                   note="Done! Your style's ready - pick it under Your styles. (%d min)" % ((time.time() - t0) / 60))
    say("done - style_lora.safetensors saved")


if __name__ == "__main__":
    main()
