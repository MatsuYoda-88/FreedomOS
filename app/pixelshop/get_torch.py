"""Pixel Shop: make sure the NVIDIA build of PyTorch (+ torchvision for style training) is in the shop's toolbox.
Already there and seeing the GPU? Does nothing."""
import subprocess
import sys

INDEX = "https://download.pytorch.org/whl/cu128"     # CUDA 12.8 build - fine for the NVIDIA GPU on any recent driver


def ok():
    try:
        import torch
        import torchvision  # noqa: F401
        return torch.cuda.is_available()
    except Exception:
        return False


if ok():
    import torch
    print("  PyTorch %s already sees the %s." % (torch.__version__, torch.cuda.get_device_name(0)))
    sys.exit(0)
print("  Installing PyTorch + torchvision (NVIDIA build, ~3 GB, one time)...")
r = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "torch", "torchvision", "--index-url", INDEX])
if r.returncode != 0:
    sys.exit(r.returncode)
sys.exit(0 if subprocess.run([sys.executable, "-c", "import torch,torchvision,sys;sys.exit(0 if torch.cuda.is_available() else 1)"]).returncode == 0 else 1)
