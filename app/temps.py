"""CPU temperature for the top bar.

Windows keeps the CPU heat in its "Thermal Zone" counters (no admin needed).
typeperf reads them - we take the hottest zone, that's the CPU on these boxes.
"""
import asyncio
import csv
import io
import os
import subprocess

STATE = {"temp": None}
COUNTERS = [r"\Thermal Zone Information(*)\High Precision Temperature",   # tenths of a Kelvin
            r"\Thermal Zone Information(*)\Temperature"]                    # whole Kelvin


def _read_windows():
    for i, c in enumerate(COUNTERS):
        try:
            r = subprocess.run(["typeperf", c, "-sc", "1"], capture_output=True, text=True, timeout=12,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            continue
        rows = [x for x in csv.reader(io.StringIO(r.stdout)) if len(x) > 1]
        if len(rows) < 2:
            continue
        vals = []
        for v in rows[1][1:]:
            try:
                k = float(v) / (10 if i == 0 else 1)
            except ValueError:
                continue
            c_ = k - 273.15
            if 15 < c_ < 115:                       # skip zones that report junk
                vals.append(c_)
        if vals:
            return round(max(vals))
    return None


def _read_linux():
    best = None
    base = "/sys/class/thermal"
    if not os.path.isdir(base):
        return None
    for z in os.listdir(base):
        try:
            with open(os.path.join(base, z, "temp")) as f:
                c_ = int(f.read().strip()) / 1000
            if 15 < c_ < 115:
                best = max(best or 0, c_)
        except Exception:
            pass
    return round(best) if best else None


async def loop(hub):
    read = _read_windows if os.name == "nt" else _read_linux
    misses = 0
    while True:
        try:
            t = await asyncio.to_thread(read)
        except Exception:
            t = None
        if t is not None or STATE["temp"] is not None:
            STATE["temp"] = t
            hub.send({"type": "cpu", "cpu": dict(STATE)})
        misses = misses + 1 if t is None else 0
        await asyncio.sleep(5 if misses < 5 else 60)     # this PC doesn't share it? stop asking so much
