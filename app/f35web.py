"""F35 Web 🔎 - search + a clean reader + a real browser window, built into FreedomOS.

  Search:  DuckDuckGo (Bing backup) -> ads, sponsored junk and spammy sites thrown out -> max 2 hits per site.
           Brain on? It reads the top pages and writes a short straight answer with numbered sources.
           On the laptop it asks the DESKTOP's brain to do it (faster, laptop stays cool), and does it itself
           if the desktop's off.
  Reader:  open any page stripped to just words, pictures and tables - no ads, pop-ups, banners or scripts.
  Browser: "WiBro" = real Edge in its own window + own profile (logins, videos, shopping).
"""
import asyncio
import time
import html as _h
import json
import os
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pixlite   # documents() = the real Documents folder (handles OneDrive)
from urllib.parse import urljoin, urlparse

from aiohttp import ClientSession, ClientTimeout, web

HERE = Path(__file__).resolve().parent

IS_WIN = sys.platform == "win32"
import json as _json
try:
    _DEVTOOLS = int(_json.loads((Path(__file__).resolve().parent / "config.json").read_text(encoding="utf-8")).get("devtools_port", 9343))
except Exception:
    _DEVTOOLS = 9343
D = {}            # boss hands us: web_search, get, html_text, chat, brain_ready, ensure_engine, peers, log, key
# sites that are all ads, scrapers, content farms or login walls - never worth the click
JUNK = ("pinterest.", "quora.com", "answers.com", "ask.com", "ehow.com", "wikihow.com/ads", "scribd.com", "coursehero.com",
        "chegg.com", "brainly.", "facebook.com", "instagram.com", "tiktok.com", "x.com", "twitter.com", "linkedin.com",
        "slideshare.net", "studocu.com", "msn.com", "yahoo.com/news", "bing.com/aclick", "doubleclick", "googleadservices",
        "amazon.com/sspa", "ebay.com/sch", "temu.com", "aliexpress.", "shein.com", "wish.com", "alibaba.com")
SPAMMY = re.compile(r"(best|top)[- ]\d+|\b(coupon|promo code|deal of the day|sponsored|affiliate|vs-?\d{4})\b", re.I)


def site_of(url):
    try:
        return re.sub(r"^www\.", "", urlparse(url).netloc.lower())
    except Exception:
        return ""


def clean_hits(hits):
    out, per = [], {}
    for title, url, snip in hits:
        s = site_of(url)
        if not s or not url.startswith(("http://", "https://")) or any(j in url.lower() for j in JUNK):
            continue
        if SPAMMY.search(title) and not re.search(r"manual|spec|torque|forum|service", title, re.I):
            continue
        if per.get(s, 0) >= 2:
            continue
        per[s] = per.get(s, 0) + 1
        out.append({"title": title, "url": url, "site": s, "snippet": snip})
    return out


async def _peer_search(q, brain):
    """Laptop: let the desktop (the PC with the big graphics card) do the work."""
    for p in D["peers"]():
        try:
            async with ClientSession() as s:
                async with s.post(f"{p['url']}/web/search", json={"q": q, "brain": brain, "from_peer": True},
                                  headers={"X-Crew-Key": p["key"]}, timeout=ClientTimeout(total=90)) as r:
                    if r.status == 200:
                        d = await r.json()
                        d["by"] = p["name"]
                        return d
        except Exception:
            continue
    return None


async def search(q, brain=True, from_peer=False):
    q = q.strip()[:300]
    if not q:
        return {"results": [], "answer": ""}
    if brain and not from_peer and not D["has_gpu"]():
        d = await _peer_search(q, brain)
        if d:
            return d
    async with ClientSession() as s:
        results = clean_hits(await D["web_search"](s, q))
        out = {"q": q, "results": results, "answer": "", "by": D["me"]()}
        if not brain or not results:
            return out
        pages = await asyncio.gather(*[D["get"](s, r["url"], 6) for r in results[:4]], return_exceptions=True)
        docs = []
        for i, (r, pg) in enumerate(zip(results[:4], pages), 1):
            txt = D["html_text"](pg) if isinstance(pg, str) and pg else ""
            txt = re.sub(r"\n\s*\n+", "\n", txt)
            docs.append(f"[{i}] {r['title']} ({r['site']})\n{(txt.strip() or r['snippet'])[:2600]}")
        if not await D["ensure_engine"](s):
            out["answer_note"] = "brain's asleep - here's the clean results"
            return out
        msgs = [{"role": "system", "content": "You answer web searches for a mechanic. Read the pages and write a short, straight answer "
                 "(2-5 sentences, plain words, real numbers when there are any). Put the source number in square brackets after each fact, "
                 "like [1] or [2]. If the pages don't answer it, say so in one line. No ads, no fluff, no 'it depends' without the actual answer."},
                {"role": "user", "content": f"Search: {q}\n\nPAGES:\n\n" + "\n\n".join(docs)}]
        try:
            out["answer"] = (await D["chat"](s, msgs, max_tokens=500, temp=.2)).strip()
        except Exception as e:
            out["answer_note"] = f"brain hiccup: {str(e)[:80]}"
        return out


# ---------------------------------------------------------------- the clean reader
KEEP = {"p", "h1", "h2", "h3", "h4", "h5", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td", "img", "a", "br",
        "strong", "b", "em", "i", "blockquote", "pre", "code", "figure", "figcaption", "hr", "dl", "dt", "dd", "sup", "sub"}
DROP = {"script", "style", "noscript", "iframe", "svg", "form", "button", "nav", "footer", "aside", "header", "select", "input",
        "textarea", "template", "dialog", "object", "embed", "video", "audio", "canvas", "picture>source"}
ADCLASS = re.compile(r"\b(ad|ads|advert\w*|sponsor\w*|promo\w*|banner|cookie\w*|consent|newsletter|subscribe|popup|modal|social|share|"
                     r"related|recommend\w*|outbrain|taboola|comment\w*|sidebar|breadcrumb\w*|paywall|gdpr|signup)\b", re.I)
ADIMG = re.compile(r"doubleclick|adservice|/ads?/|pixel|tracking|beacon|1x1|spacer|logo-?sprite", re.I)


class Cleaner(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.out, self.skip, self.title, self.in_title = base, [], [], "", False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self.in_title = True
        if self.skip:
            if tag not in ("br", "img", "hr", "input", "meta", "link", "source"):
                self.skip.append(tag)
            return
        cls = (a.get("class") or "") + " " + (a.get("id") or "") + " " + (a.get("role") or "")
        if tag in DROP or (tag in ("div", "section", "span", "ul", "aside", "p", "figure") and ADCLASS.search(cls)) or a.get("hidden") is not None \
                or "display:none" in (a.get("style") or "").replace(" ", ""):
            if tag not in ("br", "img", "hr", "input", "meta", "link", "source"):
                self.skip.append(tag)
            return
        if tag not in KEEP:
            return
        if tag == "a":
            href = urljoin(self.base, a.get("href") or "")
            if href.startswith(("http://", "https://")):
                self.out.append(f'<a href="{_h.escape(href, True)}">')
            else:
                self.out.append("<a>")
        elif tag == "img":
            src = a.get("src") or a.get("data-src") or ""
            src = urljoin(self.base, src)
            if src.startswith(("http://", "https://")) and not ADIMG.search(src):
                try:
                    if int(a.get("width") or 99) < 40 or int(a.get("height") or 99) < 40:
                        return
                except ValueError:
                    pass
                self.out.append(f'<img src="{_h.escape(src, True)}" alt="{_h.escape(a.get("alt") or "", True)}" loading="lazy">')
        else:
            self.out.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
            return
        if tag in KEEP and tag not in ("img", "br", "hr"):
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
            return
        if not self.skip and data.strip():
            self.out.append(_h.escape(data))


def readable(page, url):
    m = re.search(r"(?is)<(article|main)[^>]*>(.*)</\1>", page)
    body = m.group(0) if m and len(m.group(2)) > 1500 else page
    c = Cleaner(url)
    try:
        c.feed(body if body is page else page[:page.find("</head>") + 7] + body if "</head>" in page else body)
    except Exception:
        pass
    htm = "".join(c.out)
    htm = re.sub(r"(<(p|li|h\d|td)>\s*</\2>)+", "", htm)                      # empty leftovers
    return {"title": _h.unescape(c.title).strip()[:200] or site_of(url), "html": htm[:400_000], "url": url, "site": site_of(url)}


async def read(url):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    async with ClientSession() as s:
        page = await D["get"](s, url, 12)
    if not page:
        return {"error": f"couldn't load that page ({D['err']() or 'no answer'})", "url": url}
    return readable(page, url)


# ---------------------------------------------------------------- WiBro (real Edge, own window + profile)
def _home():
    return Path(os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")) / "FreedomOS Browser"


def edge_exe():
    for c in (shutil.which("msedge"), r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if c and Path(c).exists():
            return c
    return None


UBO = "https://microsoftedge.microsoft.com/addons/search/uBlock%20Origin%20Lite"


# ---------------------------------------------------------------- WiBro lives INSIDE FreedomOS now: auto-built + auto-updated
BROWSER = HERE / "browser"
BSRC, BUILDS = BROWSER / "src", BROWSER / "builds"
_build = {"busy": False, "state": "", "when": 0}
_restart = {"waiting": False}
_NOWIN = 0x08000000


def _app_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq FreedomOS.exe", "/NH"], capture_output=True, text=True,
                             creationflags=_NOWIN).stdout
        return "FreedomOS.exe" in out
    except Exception:
        return False


def _idle_secs():
    """how long since you last touched the mouse or keyboard"""
    try:
        import ctypes

        class LII(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        li = LII(); li.cbSize = ctypes.sizeof(LII)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
        return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000.0
    except Exception:
        return 0


async def _media_playing():
    """any tab playing a video or sound right now? (don't yank a movie out from under you)"""
    try:
        from aiohttp import ClientSession as CS, ClientTimeout as CT
        async with CS(timeout=CT(total=6)) as s:
            async with s.get(f"http://127.0.0.1:{_DEVTOOLS}/json") as r:
                pages = [t for t in await r.json() if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
            for t in pages:
                try:
                    async with s.ws_connect(t["webSocketDebuggerUrl"], timeout=3) as ws:
                        await ws.send_json({"id": 1, "method": "Runtime.evaluate", "params": {"returnByValue": True,
                            "expression": "[...document.querySelectorAll('video,audio')].some(v => !v.paused && !v.muted && v.currentTime > 0)"}})
                        m = await ws.receive_json(timeout=3)
                        if ((m.get("result") or {}).get("result") or {}).get("value"):
                            return True
                except Exception:
                    pass
    except Exception:
        return False
    return False


def log(msg):
    f = D.get("log")
    (f or print)(msg)


async def _restart_when_idle():
    """🔄 new WiBro built: once you've left the PC alone for a bit (and no music's playing), swap the app onto the new version.
    Your tabs come back by themselves."""
    if not IS_WIN:
        return
    _restart["waiting"] = True
    try:
        while True:
            await asyncio.sleep(20)
            if not await asyncio.to_thread(_app_running):
                return                                         # not open - the new one opens next time anyway
            try:
                import f35music
                playing = bool(f35music.STATE.get("playing"))
            except Exception:
                playing = False
            if _idle_secs() >= 45 and not playing and not await _media_playing():
                break
        await asyncio.to_thread(subprocess.run, ["taskkill", "/IM", "FreedomOS.exe", "/F"], capture_output=True, creationflags=_NOWIN)
        await asyncio.sleep(1.5)
        exe = f35_browser_exe()
        if exe:
            subprocess.Popen([str(exe), "--restore"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=0x00000008 | 0x00000200)
            log("🔄 WiBro restarted itself onto the new version (tabs restored)")
    except Exception as e:
        log(f"(WiBro restart hiccup: {e})")
    finally:
        _restart["waiting"] = False


def _src_hash():
    import hashlib
    h = hashlib.md5()
    for p in sorted(list(BSRC.glob("*.cs")) + list(BSRC.glob("*.csproj")) + list(BSRC.glob("*.ico"))):
        h.update(p.name.encode()); h.update(p.read_bytes())
    return h.hexdigest()[:12]


def _current():
    try:
        name, hsh = (BUILDS / "current.txt").read_text(encoding="utf-8").split()[:2]
        exe = BUILDS / name / "FreedomOS.exe"
        return (exe if exe.exists() else None), hsh
    except Exception:
        return None, ""


def f35_browser_exe():
    return _current()[0]


def open_app_tab(app):
    """🎧 / 🎨 as a tab in the FreedomOS app ("close:music" closes it). False if the app isn't built yet."""
    mine = f35_browser_exe()
    if not mine:
        return False
    kw = {"creationflags": 0x00000008 | 0x00000200} if IS_WIN else {"start_new_session": True}
    subprocess.Popen([str(mine), f"--app={app}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    return True


def open_app():
    """FreedomOS's own app window (Home tab + browser tabs). False if it isn't built yet."""
    mine = f35_browser_exe()
    if not mine:
        return False
    kw = {"creationflags": 0x00000008 | 0x00000200} if IS_WIN else {"start_new_session": True}
    subprocess.Popen([str(mine), "--show"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    return True


def _dotnet():
    for c in (shutil.which("dotnet"), r"C:\Program Files\dotnet\dotnet.exe"):
        if c and Path(c).exists():
            try:
                r = subprocess.run([c, "--list-sdks"], capture_output=True, text=True, timeout=20,
                                   **({"creationflags": 0x08000000} if IS_WIN else {}))
                if re.search(r"^\d+\.", r.stdout, re.M):
                    return c
            except Exception:
                pass
    return None


async def ensure_built(why="startup"):
    """Build WiBro if its code is newer than the last build. Old builds go to todelete. A browser that's open
    keeps running; the new version is what opens next time."""
    log = D.get("log", print)
    if not IS_WIN or not (BSRC / "FreedomOS.csproj").exists() or _build["busy"]:
        return
    want = await asyncio.to_thread(_src_hash)
    exe, have = _current()
    if exe and have == want:
        return
    _build.update(busy=True, state="building")
    try:
        dn = await asyncio.to_thread(_dotnet)
        if not dn:
            log("🌐 WiBro: getting the free .NET 8 builder from Microsoft (one time, couple minutes)...")
            await asyncio.to_thread(subprocess.run, ["winget", "install", "-e", "--id", "Microsoft.DotNet.SDK.8", "--silent",
                                                     "--accept-package-agreements", "--accept-source-agreements"],
                                    capture_output=True, timeout=1200, creationflags=0x08000000)
            dn = await asyncio.to_thread(_dotnet)
            if not dn:
                log("🌐 WiBro: the .NET builder didn't install - can't build the browser yet")
                _build["state"] = "no builder"
                return
        out = BUILDS / f"b{int(time.time())}"
        log(f"🌐 WiBro: building the new version ({why})...")
        def run():
            r = subprocess.run([dn, "publish", str(BSRC / "FreedomOS.csproj"), "-c", "Release", "-r", "win-x64",
                                "--self-contained", "false", "-o", str(out)], capture_output=True, text=True, timeout=900,
                               creationflags=0x08000000)
            (BROWSER / "build.log").write_text((r.stdout or "") + "\n" + (r.stderr or ""), encoding="utf-8")
            return r.returncode
        rc = await asyncio.to_thread(run)
        if rc != 0 or not (out / "FreedomOS.exe").exists():
            log("🌐 WiBro: build hit a snag - details in FreedomOS\\browser\\build.log")
            _build["state"] = "build failed"
            return
        (BUILDS / "current.txt").write_text(f"{out.name} {want}", encoding="utf-8")
        _build.update(state="ready", when=time.time())
        log("🌐 WiBro updated - it'll restart itself onto the new version once you're not busy")
        await asyncio.to_thread(_tidy, out.name)
        if not _restart["waiting"]:
            asyncio.get_running_loop().create_task(_restart_when_idle())
    except Exception as e:
        log(f"🌐 WiBro build hiccup: {e}")
    finally:
        _build["busy"] = False


def _tidy(keep):
    """Old builds -> Claude\\todelete (never wiped). One still open stays put till next time."""
    claude = (pixlite.documents() / "FreedomOS")
    trash = claude / "todelete" / "WiBro old builds"
    olds = sorted([p for p in BUILDS.iterdir() if p.is_dir() and p.name != keep], key=lambda p: p.stat().st_mtime)
    for p in olds[:-1]:                                # keep the one before too, in case it's still open
        try:
            trash.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(trash / p.name))
        except Exception:
            pass


def open_browser(url=""):
    mine = f35_browser_exe()
    if not mine and (BSRC / "FreedomOS.csproj").exists() and IS_WIN:
        if not _build["busy"]:
            try:
                asyncio.get_running_loop().create_task(ensure_built("you opened it"))
            except RuntimeError:
                pass
    if mine:
        kw = {"creationflags": 0x00000008 | 0x00000200} if IS_WIN else {"start_new_session": True}
        subprocess.Popen([str(mine), url or "--newtab"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        return {"ok": True, "app": "WiBro"}
    exe = edge_exe()
    if not exe:
        return {"ok": False, "error": "Edge isn't on this PC"}
    prof = _home() / "profile"
    first = not prof.exists()
    prof.mkdir(parents=True, exist_ok=True)
    urls = [url or "https://duckduckgo.com/"] + ([UBO] if first else [])        # first time: the ad blocker's install page too
    args = [exe, f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check", "--new-window" if not url else "", *urls]
    kw = {"creationflags": 0x00000008 | 0x00000200} if IS_WIN else {"start_new_session": True}
    subprocess.Popen([a for a in args if a], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    return {"ok": True, "first": first}


# ---------------------------------------------------------------- pages for WiBro (served by FreedomOS on this PC)
PAGE_CSS = """body{background:#12161f;color:#e6ebf5;font:15px/1.55 'Segoe UI',system-ui,sans-serif;margin:0}
.w{max-width:820px;margin:0 auto;padding:22px 18px 60px} a{color:#9cc4ff} form input{width:100%;box-sizing:border-box;padding:12px 16px;border-radius:12px;
border:1px solid #2a3245;background:#1b2130;color:#e6ebf5;font-size:16px} .ans{background:#1b2130;border:1px solid #4b8fe8;border-radius:12px;padding:12px 14px;margin:16px 0}
.ans .h{font-size:12px;color:#8b96ad;margin-bottom:4px} .src{color:#7fb2ff;font-weight:700;text-decoration:none} .r{padding:12px 0;border-bottom:1px solid #2a3245}
.r .t{font-size:17px;font-weight:600;text-decoration:none} .r .s{font-size:12px;color:#8b96ad} .r .n{font-size:14px;opacity:.85;margin:3px 0}
.r .c{font-size:12px;margin-left:8px} .dim{color:#8b96ad} img{max-width:100%;height:auto;border-radius:8px} table{border-collapse:collapse}
td,th{border:1px solid #2a3245;padding:4px 8px} pre{white-space:pre-wrap} h1,h2{line-height:1.25}"""


def _shell(title, body, script=""):
    return web.Response(text=f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                             f"<title>{_h.escape(title)}</title><style>{PAGE_CSS}</style></head><body><div class=w>{body}</div>"
                             f"<script>{script}</script></body></html>", content_type="text/html")


async def h_page(request):
    """🧠 search results page: straight answer + clean links (the browser's address bar + start page land here)."""
    q = request.query.get("q", "").strip()
    body = (f"<form action='/web/page'><input name=q value=\"{_h.escape(q, True)}\" placeholder='Search' autofocus></form>"
            "<div id=a class=ans style='display:none'></div><div id=l class=dim style='margin-top:14px'>🔎 searching + the brain's reading the top pages...</div>")
    js = r"""const q = %s; const esc = s => String(s || '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'})[c]);
fetch('/web/search', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({q, brain:true})}).then(r => r.json()).then(d => {
  const R = d.results || [];
  if (d.answer) { const a = document.getElementById('a'); a.style.display = 'block';
    a.innerHTML = `<div class=h>🧠 Straight answer${d.by ? ' (' + esc(d.by) + "'s brain)" : ''}</div>` + esc(d.answer).replace(/\[(\d+)\]/g, (m, n) => R[n-1] ? `<a class=src href="${esc(R[n-1].url)}" title="${esc(R[n-1].site)}">[${n}]</a>` : m); }
  document.getElementById('l').className = '';
  document.getElementById('l').innerHTML = (d.answer_note ? `<div class=dim>${esc(d.answer_note)}</div>` : '') + (R.length ? R.map((r, i) => `<div class=r>
    <a class=t href="${esc(r.url)}">${esc(r.title)}</a><div class=s>${esc(r.site)} <a class=c href="/web/reader?url=${encodeURIComponent(r.url)}">📖 read clean</a></div>
    <div class=n>${esc(r.snippet)}</div></div>`).join('') : '<div class=dim>Nothin\' came back. Try other words.</div>');
}).catch(() => { document.getElementById('l').textContent = "couldn't search right now"; });""" % json.dumps(q)
    return _shell(f"{q} - F35 search" if q else "F35 search", body, js if q else "")


async def h_reader(request):
    """📖 any page, cleaned: words, pictures, tables. No ads, scripts or junk."""
    d = await read(request.query.get("url", ""))
    if d.get("error"):
        return _shell("Couldn't load it", f"<p>{_h.escape(d['error'])}</p><p><a href=\"{_h.escape(d.get('url', ''), True)}\">Open the real page</a></p>")
    top = f"<div class=dim>📖 {_h.escape(d['site'])} · <a href=\"{_h.escape(d['url'], True)}\">open the real page</a></div><h1>{_h.escape(d['title'])}</h1>"
    return _shell(d["title"], top + d["html"])          # d["html"] is rebuilt from a short safe-tag list - no scripts, no styles, no event handlers


async def h_sum(request):
    """🧠 sum up a page in plain words."""
    url = request.query.get("url", "")
    body = f"<div class=dim>🧠 summing up <a href=\"{_h.escape(url, True)}\">{_h.escape(site_of(url))}</a>...</div><div id=a class=ans>reading it...</div>"
    js = """fetch('/web/sumapi?url=' + encodeURIComponent(%s)).then(r => r.json()).then(d => { const a = document.getElementById('a');
  a.innerHTML = '<div class=h>🧠 ' + (d.title || '').replace(/</g,'&lt;') + '</div>' + String(d.sum || d.error || '').replace(/</g,'&lt;').replace(/\\n/g,'<br>'); });""" % json.dumps(url)
    return _shell("Sum up", body, js)


async def h_sumapi(request):
    d = await read(request.query.get("url", ""))
    if d.get("error"):
        return web.json_response({"error": d["error"]})
    text = re.sub(r"<[^>]+>", " ", d["html"]); text = re.sub(r"\s+", " ", _h.unescape(text))[:9000]
    async with ClientSession() as s:
        if not await D["ensure_engine"](s):
            return web.json_response({"error": "the brain's not available right now", "title": d["title"]})
        msgs = [{"role": "system", "content": "Sum up this web page for a busy mechanic: 3 to 6 short bullet points in plain words, "
                 "keep real numbers, specs and part names, skip fluff and ads. Start each bullet with '- '."},
                {"role": "user", "content": f"PAGE: {d['title']}\n\n{text}"}]
        try:
            out = (await D["chat"](s, msgs, max_tokens=450, temp=.2)).strip()
        except Exception as e:
            return web.json_response({"error": f"brain hiccup: {str(e)[:80]}", "title": d["title"]})
    return web.json_response({"sum": out, "title": d["title"]})


# ---------------------------------------------------------------- FreedomOS hooks
async def h_search(request):
    d = await request.json()
    out = await search(str(d.get("q", "")), bool(d.get("brain", True)), bool(d.get("from_peer")))
    return web.json_response(out)


async def h_read(request):
    u = request.query.get("url", "")
    return web.json_response(await read(u))


async def h_browse(request):
    if request.remote not in ("127.0.0.1", "::1"):
        return web.json_response({"ok": False, "where": "phone"})
    d = await request.json()
    return web.json_response(await asyncio.to_thread(open_browser, str(d.get("url", ""))))


def routes(app):
    app.add_routes([web.post("/web/search", h_search), web.get("/web/read", h_read), web.post("/web/browse", h_browse),
                    web.get("/web/page", h_page), web.get("/web/reader", h_reader), web.get("/web/sum", h_sum), web.get("/web/sumapi", h_sumapi)])
