"""Is an NVIDIA card actually plugged in and answering RIGHT NOW? (The laptop has the drivers for the eGPU dock,
so 'drivers installed' isn't enough - the GPU might be unplugged.)"""
import shutil
import subprocess
from pathlib import Path


def nvidia_now():
    exe = shutil.which("nvidia-smi") or (r"C:\Windows\System32\nvidia-smi.exe" if Path(r"C:\Windows\System32\nvidia-smi.exe").exists() else None)
    if not exe:
        return False
    try:
        r = subprocess.run([exe, "-L"], capture_output=True, text=True, timeout=8,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0 and "GPU " in r.stdout
    except Exception:
        return False


def engine_dir(here):
    """CUDA engine for a real NVIDIA card, the Vulkan one (Intel graphics) when there isn't one plugged in."""
    return Path(here) / ("engine" if nvidia_now() else "engine_vulkan")
