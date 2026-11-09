"""Downloads the OFFICIAL llama.cpp engine from github.com/ggml-org/llama.cpp releases.
NVIDIA card plugged in -> the CUDA build in FreedomOS\\engine.
No NVIDIA card right now (the laptop off the dock) -> the Vulkan build in FreedomOS\\engine_vulkan (Intel/AMD graphics).
Both can live side by side, so plugging the laptop into the eGPU dock (or not) never re-downloads. Only grabs from that repo."""
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from gpu_check import nvidia_now  # noqa: E402
NV = nvidia_now()
DEST = HERE / ("engine" if NV else "engine_vulkan")
API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "FreedomOS", "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=60)


def cuda_ver(name):
    m = re.search(r"cuda-?(\d+)\.(\d+)", name)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def has_nvidia():
    return NV


def vulkan():
    for r in json.load(get(API)):
        a = {x["name"]: x["browser_download_url"] for x in r.get("assets", [])}
        b = [n for n in a if n.endswith(".zip") and "bin-win-vulkan" in n and "x64" in n]
        if b:
            return r, a, b[0]
    return None, {}, None


def main():
    if (DEST / "llama-server.exe").exists() and "--update" not in sys.argv:
        print(f"  Engine already installed ({'NVIDIA / CUDA' if NV else 'Intel graphics / Vulkan'}).")
        return
    if not has_nvidia():
        rel, assets, pick = vulkan()
        if not pick:
            print("  !! Couldn't find a Windows Vulkan build in the last 30 llama.cpp releases.")
            sys.exit(1)
        print(f"  No NVIDIA card plugged in - grabbing the Intel graphics (Vulkan) engine: llama.cpp {rel['tag_name']} -> {pick}")
        DEST.mkdir(exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(get(assets[pick]).read())) as z:
            for m in z.infolist():
                if not m.is_dir():
                    (DEST / Path(m.filename).name).write_bytes(z.read(m))
        if not (DEST / "llama-server.exe").exists():
            print("  !! llama-server.exe wasn't in the download.")
            sys.exit(1)
        (DEST / "VERSION.txt").write_text(f"{rel['tag_name']} {pick}\n")
        print("  Engine installed.")
        return
    # newest release that actually carries the Windows CUDA zips
    rel, assets, bins = None, {}, []
    for r in json.load(get(API)):
        a = {x["name"]: x["browser_download_url"] for x in r.get("assets", [])}
        b = [n for n in a if n.endswith(".zip") and "bin-win-cuda" in n and "x64" in n and not n.startswith("cudart")]
        if b:
            rel, assets, bins = r, a, b
            break
    if not bins:
        print("  !! Couldn't find a Windows CUDA build in the last 30 llama.cpp releases.")
        sys.exit(1)
    # prefer CUDA 12.x (works on any recent driver), else newest
    twelve = [n for n in bins if cuda_ver(n)[0] == 12]
    pick = max(twelve or bins, key=cuda_ver)
    ver = "%d.%d" % cuda_ver(pick)
    rt = [n for n in assets if n.startswith("cudart") and f"cuda-{ver}" in n and "x64" in n]
    print(f"  llama.cpp {rel['tag_name']}  ->  {pick}")
    DEST.mkdir(exist_ok=True)
    for name in [pick] + rt[:1]:
        print(f"  downloading {name} ...")
        data = get(assets[name]).read()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for m in z.infolist():
                if m.is_dir():
                    continue
                out = DEST / Path(m.filename).name   # flatten, no weird paths
                out.write_bytes(z.read(m))
    if not (DEST / "llama-server.exe").exists():
        print("  !! llama-server.exe wasn't in the download.")
        sys.exit(1)
    (DEST / "VERSION.txt").write_text(f"{rel['tag_name']} {pick}\n")
    print("  Engine installed.")


if __name__ == "__main__":
    main()
