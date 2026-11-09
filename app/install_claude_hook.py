"""Plugs FreedomOS into the Claude desktop app (adds it to claude_desktop_config.json)."""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
py = Path(sys.executable)
entry = {"command": str(py), "args": [str(HERE / "mcp_bridge.py")]}

spots = [Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"]
pk = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages"
if pk.exists():  # Microsoft Store version of Claude keeps it here instead
    for d in pk.glob("Claude_*"):
        spots.append(d / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json")

done = 0
for cfg in spots:
    if not cfg.parent.exists() and cfg != spots[0]:
        continue
    cfg.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            cfg.with_suffix(".json.bak").write_text(cfg.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"  (old config was broken - backed up to {cfg.with_suffix('.json.bak')})")
    servers = data.setdefault("mcpServers", {})
    if servers.pop("crewboss", None) is not None:      # the old CrewBoss plug-in retires
        done += 1
    if servers.get("freedomos") == entry:
        print(f"  Claude already plugged in: {cfg}")
        if done: cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
    else:
        servers["freedomos"] = entry
        cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"  Plugged FreedomOS into Claude: {cfg}")
        done += 1
if done:
    print("  >> Fully quit Claude desktop (tray icon > Quit) and reopen it to load the crew tools.")
