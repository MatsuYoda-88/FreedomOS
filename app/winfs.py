"""Maximize the FreedomOS window -> borderless fullscreen (Windows only).

Edge won't let a page go fullscreen by itself - it needs a real key press or click.
So this watches for YOU hitting maximize on the FreedomOS window, then taps F13
(a key nobody uses) on it. The page sees that key and jumps to fullscreen.
Esc gets the minimize/maximize/close bar back (Edge does that part).
"""
import asyncio
import os

VK_F13 = 0x7C


async def loop(log):
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = wintypes.HWND
    was = {}

    def look():
        h = u.GetForegroundWindow()
        if not h:
            return None, False
        buf = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(h, buf, 256)
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(h, cls, 64)
        if not buf.value.startswith("FreedomOS") or not cls.value.startswith("Chrome_WidgetWin"):
            return None, False
        return h, bool(u.IsZoomed(h))

    told = False
    while True:
        await asyncio.sleep(0.35)
        try:
            h, zoomed = look()
            if not h:
                continue
            if zoomed and not was.get(h):                 # just got maximized
                await asyncio.sleep(0.25)                 # let the window finish growing
                u.keybd_event(VK_F13, 0, 0, 0)
                u.keybd_event(VK_F13, 0, 2, 0)            # key up
                if not told:
                    log("🖥 Window maximized - going borderless fullscreen (Esc to get the bar back)")
                    told = True
            was[h] = zoomed
        except Exception as e:
            log(f"🖥 fullscreen helper hiccup: {e}")
            await asyncio.sleep(5)


# ---------------------------------------------------------------- compact mode -> small window (like WiFile), and back
_saved = {}


def _windows():
    """Every FreedomOS app window (Edge app windows are 'Chrome_WidgetWin_1')."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    found = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _):
        if u.IsWindowVisible(h):
            buf = ctypes.create_unicode_buffer(256)
            u.GetWindowTextW(h, buf, 256)
            cls = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(h, cls, 64)
            if buf.value.startswith("FreedomOS") and cls.value.startswith("Chrome_WidgetWin"):
                found.append(h)
        return True
    u.EnumWindows(proc(cb), 0)
    return found


def compact(on, w=900, h=760):
    """on: remember where each window was, then shrink it to WiFile's size (centered where it was). off: put it back."""
    if os.name != "nt":
        return 0
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    n = 0
    for hw in _windows():
        r = wintypes.RECT()
        u.GetWindowRect(hw, ctypes.byref(r))
        if on:
            if hw not in _saved:
                _saved[hw] = (r.left, r.top, r.right - r.left, r.bottom - r.top, bool(u.IsZoomed(hw)))
            if u.IsZoomed(hw):
                u.ShowWindow(hw, 9)                       # SW_RESTORE (un-maximize first)
            cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
            u.SetWindowPos(hw, 0, max(0, cx - w // 2), max(0, cy - h // 2), w, h, 0x0004 | 0x0010)   # NOZORDER | NOACTIVATE
        else:
            s = _saved.pop(hw, None)
            if s:
                x, y, ww, hh, zoomed = s
                u.SetWindowPos(hw, 0, x, y, ww, hh, 0x0004 | 0x0010)
                if zoomed:
                    u.ShowWindow(hw, 3)                   # SW_MAXIMIZE (the fullscreen helper takes it from there)
        n += 1
    return n
