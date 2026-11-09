"""
FreedomOS v1.0 - the plug-in that lets Claude (desktop app) boss the crew around.
Claude starts this by itself. It just passes messages to the boss server,
and wakes the boss up if he's asleep.
NOTE: never print() in here - the printout line is how Claude talks to it.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
BASE = f"http://127.0.0.1:{CFG['port']}"
mcp = FastMCP("freedomos")


def _req(method, path, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _alive():
    try:
        return _req("GET", "/health", timeout=2).get("ok", False)
    except Exception:
        return False


def _ensure_boss():
    if _alive():
        return True
    py = sys.executable
    pyw = Path(py).with_name("pythonw.exe")
    if pyw.exists():
        py = str(pyw)  # no black window
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008 | subprocess.CREATE_NO_WINDOW
    subprocess.Popen([py, str(HERE / "boss.py")], cwd=str(HERE), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    for _ in range(60):
        time.sleep(1)
        if _alive():
            return True
    return False


def _fmt(job, full=True):
    lines = [f"Job {job['id']} - {job['status'].upper()} ({job['done']}/{job['total']} pieces done)"]
    for s in job.get("subtasks", []):
        rv = f" | {CFG.get('checker_name', 'checker')}: {s['review']}" if s.get("review") else ""
        if (s.get("tries") or 0) > 1:
            rv += " (sent back & redone)"
        lines.append(f"  - [{s['status']}] {s['title']} ({s.get('worker') or 'nobody yet'}, {s['station']}){rv}")
    if job.get("claude_check"):
        lines.append("CLAUDE SPOT-CHECK THESE (open the output file / pieces and verify before trusting):")
        lines += [f"  * {c}" for c in job["claude_check"]]
    if job.get("error"):
        lines.append(f"ERROR: {job['error']}")
    if full and job.get("result"):
        res = job["result"]
        if len(res) > 20000:
            res = res[:20000] + "\n...[cut - full answer in the output file]"
        lines.append(f"\nSaved to: {job.get('output_file')}\n\nRESULT:\n{res}")
    return "\n".join(lines)


@mcp.tool()
def crew_give_job(task: str, folder: str = "") -> str:
    """Hand a job to the LOCAL AI crew: a boss AI, several worker AIs running in parallel, and a checker AI
    (names in the crew's config.json), all on one local brain on the user's PC. The checker grades every
    piece and sends bad work back once.
    Use it for grunt work that doesn't need Claude-level smarts: summarizing or sorting lots of files, first drafts,
    boilerplate code, comparing lists, renaming plans, pulling info out of logs/docs. It saves Claude usage.
    The boss splits the job into pieces and the workers do them at the same time. The result lists anything Claude should
    spot-check (code, or pieces that failed the checker's grading) - do spot-check those before passing it to the user.
    First job after startup may wait a few minutes while the brain loads (first ever run downloads the brain, ~6 GB for the default).
    task: plain-English job, self-contained (the crew can't see this chat).
    folder: optional full Windows path of a folder the crew may read files from (must be inside Documents\\FreedomOS,
    Desktop or Downloads). Returns a job id - then call crew_wait or crew_check."""
    if not _ensure_boss():
        return "Couldn't wake up the boss server. Tell the user to open FreedomOS from the Start menu."
    try:
        r = _req("POST", "/jobs", {"task": task, "folder": folder})
    except urllib.error.HTTPError as e:
        return f"Boss refused the job: {e.read().decode()[:500]}"
    if "id" not in r:
        return f"Boss refused the job: {r}"
    return f"Job {r['id']} handed to the crew. Call crew_wait('{r['id']}') to wait for the answer."


@mcp.tool()
def crew_wait(job_id: str, max_seconds: int = 100) -> str:
    """Wait (up to max_seconds, max 240) for a crew job to finish, then return its result.
    If it's still going when time runs out, you get progress - just call it again."""
    deadline = time.time() + max(5, min(int(max_seconds), 240))
    job = None
    while time.time() < deadline:
        try:
            job = _req("GET", f"/jobs/{job_id}")
        except Exception as e:
            return f"Can't reach the boss: {e}"
        if job.get("status") in ("done", "failed"):
            return _fmt(job)
        time.sleep(2)
    return "Still working...\n" + _fmt(job, full=False) if job else "No answer from the boss."


@mcp.tool()
def crew_check(job_id: str) -> str:
    """Check a crew job right now without waiting. Returns status, and the result if it's done."""
    try:
        return _fmt(_req("GET", f"/jobs/{job_id}"))
    except Exception as e:
        return f"Couldn't check job {job_id}: {e}"


@mcp.tool()
def crew_status() -> str:
    """See what every crew member is doing right now, the GPU load, and recent jobs."""
    if not _alive():
        return "Crew is asleep (boss server not running). crew_give_job will wake them up."
    a = _req("GET", "/agents")
    js = _req("GET", "/jobs")[:8]
    lines = ["CREW:"]
    for ag in a["agents"]:
        lines.append(f"  {ag['name']}: {ag['status']} @ {ag['station']} {('- ' + ag['text']) if ag.get('text') else ''}")
    g = a.get("gpu") or {}
    e = a.get("engine") or {}
    lines.append(f"BRAIN: {e.get('status')} {e.get('detail', '')}")
    if g:
        lines.append(f"GPU: {g.get('util')}% busy, {g.get('mem_used')}/{g.get('mem_total')} MB, {g.get('temp')}C")
    lines.append("JOBS:")
    for j in js:
        lines.append(f"  {j['id']} {j['status']} {j['done']}/{j['total']} - {j['task'][:80]}")
    return "\n".join(lines)


@mcp.tool()
def crew_open_widget() -> str:
    """Pop open the FreedomOS Home screen so the user can watch the crew work."""
    if not _ensure_boss():
        return "Boss server won't start."
    if os.name == "nt":
        subprocess.Popen(f'start "" msedge --app={BASE}/ --window-size=1180,680', shell=True)
    return f"Widget opened ({BASE})."


if __name__ == "__main__":
    mcp.run()
