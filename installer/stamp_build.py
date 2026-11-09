"""Marks the pre-built WiBro (app/browser/builds/b0) as the current build, so FreedomOS
uses it right away instead of building WiBro itself on your PC (that would need the .NET SDK).
The hash must match f35web._src_hash() exactly - same files, same order, same math."""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app" / "browser" / "src"
BUILDS = ROOT / "app" / "browser" / "builds"

h = hashlib.md5()
for p in sorted(list(SRC.glob("*.cs")) + list(SRC.glob("*.csproj")) + list(SRC.glob("*.ico"))):
    h.update(p.name.encode())
    h.update(p.read_bytes())
want = h.hexdigest()[:12]

if not (BUILDS / "b0" / "FreedomOS.exe").exists():
    sys.exit("No WiBro build in app/browser/builds/b0 - run dotnet publish first.")
(BUILDS / "current.txt").write_text(f"b0 {want}", encoding="utf-8")
print(f"WiBro build b0 stamped ({want})")
