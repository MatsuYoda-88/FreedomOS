// WiBro - your own browser, part of FreedomOS.
// Runs on the same engine as Edge (WebView2), so every site and login works.
// Ours: the tabs, the bar, the buttons, the look, the ad blocker, the brain + reader buttons.
using System.Diagnostics;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace F35Browser;

static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        string url = args.Length > 0 ? args[0] : "";
        using var mutex = new Mutex(true, "FreedomOS_single_" + Ports.App, out bool first);
        if (!first)
        {   // already open? hand the link to it (opens as a new tab) and quit
            try
            {
                using var c = new NamedPipeClientStream(".", "FreedomOS_pipe_" + Ports.App, PipeDirection.Out);
                c.Connect(2000);
                var b = Encoding.UTF8.GetBytes(string.IsNullOrEmpty(url) || url == "--show" ? "\u0002" : url == "--newtab" ? "\u0001" : url.StartsWith("--app=") ? "\u0003" + url[6..] : url);
                c.Write(b, 0, b.Length);
                c.Flush();
            }
            catch { }
            return;
        }
        Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        BrowserForm.StartShow = url == "--show";
        BrowserForm.Restore = url == "--restore";
        BrowserForm.MainWin = new BrowserForm(true, url == "--show" || url == "--boot" || url == "--restore" ? "" : url, null);
        Application.Run(BrowserForm.MainWin);
    }
}

static class Theme
{
    public static readonly Color Bg = Color.FromArgb(18, 22, 31);
    public static readonly Color Bar = Color.FromArgb(27, 33, 48);
    public static readonly Color Edge = Color.FromArgb(42, 50, 69);
    public static readonly Color Accent = Color.FromArgb(75, 143, 232);
    public static readonly Color Text = Color.FromArgb(230, 235, 245);
    public static readonly Color Dim = Color.FromArgb(139, 150, 173);
    public static readonly Color TabOn = Color.FromArgb(36, 44, 63);
}

class OvlCfg
{
    public int X { get; set; } = -1; public int Y { get; set; } = -1;
    public int W { get; set; } public int H { get; set; }
    public double Op { get; set; } = 0.9;
    public bool Pin { get; set; }
    public bool On { get; set; } = true;
}

// a widget window: resizable from its edges while the overlay is unlocked, click-through when it's locked
class WidgetForm : Form
{
    public bool Unlocked; public string Kind = ""; public WebView2 V;
    protected override CreateParams CreateParams { get { var cp = base.CreateParams; cp.ExStyle |= 0x80; return cp; } }   // not in Alt+Tab
    protected override void WndProc(ref Message m)
    {
        base.WndProc(ref m);
        if (m.Msg == 0x84 && Unlocked && Kind != "bar")
        {
            var p = PointToClient(new Point((short)((long)m.LParam & 0xFFFF), (short)(((long)m.LParam >> 16) & 0xFFFF)));
            int g = Padding.Right + 2; bool R = p.X >= ClientSize.Width - g, B = p.Y >= ClientSize.Height - g, L = p.X < g, T = p.Y < g;
            if (R && B) m.Result = (IntPtr)17; else if (L && B) m.Result = (IntPtr)16; else if (R) m.Result = (IntPtr)11; else if (L) m.Result = (IntPtr)10; else if (B) m.Result = (IntPtr)15; else if (T) m.Result = (IntPtr)12;
        }
    }
}

class Settings
{
    public bool AdBlock { get; set; } = true;
    public bool GpuFix { get; set; } = false;
    public bool BrainSearch { get; set; } = true;
    public List<string> AdAllow { get; set; } = new();
    public List<string> Bookmarks { get; set; } = new();
    public List<string> BarOrder { get; set; } = new();
    public bool Floor { get; set; } = true;
    public Dictionary<string, OvlCfg> Ovl { get; set; } = new();   // 🎙 overlay widgets: where they sit, how see-through, pinned or not
    public List<string> Session { get; set; } = new();      // your open browser tabs - they come back after an auto-update restart                  // 🖥 desktop mode: FreedomOS lives behind all your apps like a wallpaper     // your order for the toolbar buttons under the tabs

    public static string Home => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "FreedomOS Browser");
    static string FilePath => Path.Combine(Home, "settings.json");

    public static Settings Load()
    {
        try { return JsonSerializer.Deserialize<Settings>(File.ReadAllText(FilePath)) ?? new Settings(); }
        catch { return new Settings(); }
    }
    public void Save()
    {
        try { Directory.CreateDirectory(Home); File.WriteAllText(FilePath, JsonSerializer.Serialize(this, new JsonSerializerOptions { WriteIndented = true })); }
        catch { }
    }
}

// ---------------------------------------------------------------- the ad blocker: a big list of ad + tracker sites, refreshed weekly
static class AdBlock
{
    static HashSet<string> blocked = new(StringComparer.OrdinalIgnoreCase)
    {   // a starter list so it works the very first second, before the big list lands
        "doubleclick.net", "googlesyndication.com", "googleadservices.com", "adservice.google.com", "google-analytics.com",
        "googletagmanager.com", "adnxs.com", "taboola.com", "outbrain.com", "criteo.com", "criteo.net", "amazon-adsystem.com",
        "scorecardresearch.com", "quantserve.com", "moatads.com", "pubmatic.com", "rubiconproject.com", "openx.net",
        "advertising.com", "adsrvr.org", "casalemedia.com", "zedo.com", "media.net", "popads.net", "propellerads.com",
        "hotjar.com", "facebook.net", "ads.yahoo.com", "adform.net", "smartadserver.com", "teads.tv", "33across.com"
    };
    public static int Count => blocked.Count;
    static string ListFile => Path.Combine(Settings.Home, "adlist.txt");
    const string ListUrl = "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts";

    public static async Task LoadAsync()
    {
        try
        {
            var f = new FileInfo(ListFile);
            if (!f.Exists || f.LastWriteTimeUtc < DateTime.UtcNow.AddDays(-7))
            {
                using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(30) };
                var txt = await http.GetStringAsync(ListUrl);
                Directory.CreateDirectory(Settings.Home);
                await File.WriteAllTextAsync(ListFile, txt);
            }
        }
        catch { }
        try
        {
            var set = new HashSet<string>(blocked, StringComparer.OrdinalIgnoreCase);
            foreach (var line in await File.ReadAllLinesAsync(ListFile))
            {
                if (line.Length == 0 || line[0] == '#') continue;
                var parts = line.Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length >= 2 && (parts[0] == "0.0.0.0" || parts[0] == "127.0.0.1") && parts[1].Contains('.') && parts[1] != "0.0.0.0")
                    set.Add(parts[1]);
            }
            blocked = set;
        }
        catch { }
    }

    public static bool IsBlocked(string host)
    {
        if (string.IsNullOrEmpty(host)) return false;
        var h = host;
        while (true)
        {   // ads.tracker.example.com -> tracker.example.com -> example.com
            if (blocked.Contains(h)) return true;
            int dot = h.IndexOf('.');
            if (dot < 0 || h.IndexOf('.', dot + 1) < 0) return false;
            h = h.Substring(dot + 1);
        }
    }

    // hides the empty boxes ads leave behind + the usual cookie-nag junk
    public const string CosmeticJs = @"(() => { const css = `
      [id^='google_ads'], [id^='div-gpt-ad'], ins.adsbygoogle, .adsbygoogle, [class*='ad-slot'], [class*='adslot'], [class*='AdSlot'],
      [data-ad], [data-ad-slot], [data-google-query-id], .ad-container, .ad-wrapper, .advertisement, [aria-label='Advertisement'],
      [class*='sponsored-'], .taboola, [id^='taboola'], .OUTBRAIN, [id^='outbraing], #onetrust-banner-sdk, .cc-window, .cookie-banner
      { display: none !important; }`;
      const add = () => { if (document.getElementById('f35-cosmetic')) return; const s = document.createElement('style'); s.id = 'f35-cosmetic'; s.textContent = css;
        (document.head || document.documentElement).appendChild(s); };
      if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add(); })();";
}

// ---------------------------------------------------------------- one tab
class Tab
{
    public WebView2 View;
    public Panel Chip;
    public Label TitleLbl, CloseLbl;
    public string Title = "New tab";
    public string Url = "";
    public bool IsHome;
    public string App = "";                             // "music" / "pixel" - an app tab: ▁ tucks it back into the toolbar                                   // the FreedomOS tab - always there, can't close or drag it
    public Point DownAt; public bool Dragging;
}

// FreedomOS's ports come from app\config.json ("port", "devtools_port") so two copies never fight over them
static class Ports
{
    public static readonly int App = 7777, DevTools = 9343;
    static Ports()
    {
        try
        {
            var dir = new DirectoryInfo(AppContext.BaseDirectory);                      // app\browser\builds\b0\
            var cfg = Path.Combine(dir.Parent.Parent.Parent.FullName, "config.json");
            using var doc = JsonDocument.Parse(File.ReadAllText(cfg));
            if (doc.RootElement.TryGetProperty("port", out var p)) App = p.GetInt32();
            if (doc.RootElement.TryGetProperty("devtools_port", out var d)) DevTools = d.GetInt32();
        }
        catch { }
    }
}

class BrowserForm : Form
{
    static readonly string F35 = "http://127.0.0.1:" + Ports.App;
    public static BrowserForm MainWin;
    public static bool StartShow, Restore;
    static readonly List<BrowserForm> All = new();
    static readonly Dictionary<string, (string name, string url)> Apps = new()
    {
        ["music"] = ("🎧 WiMix", "https://music.youtube.com/"),
        ["pixel"] = ("🎨 Pixel Shop", "http://127.0.0.1:" + Ports.App + "/pixel/app/"),
        ["discord"] = ("👾 Discord", "https://discord.com/app"),
    };
    static readonly Settings S = Settings.Load();
    static Task<CoreWebView2Environment> envTask;
    static bool adStarted;
    CoreWebView2Environment env;
    readonly bool isMain;
    readonly Point? openAt;
    bool inMax;
    bool bigFull;                                       // F11 = covers the whole screen, taskbar too
    bool full;                                          // F11 or a full screen video
    readonly Panel topRow = new();
    readonly Panel hud = new();
    readonly Panel grab = new();                       // 📱 tablet: thin handle up top when the bars are hidden - tap / swipe down = they come back                        // all the bars up top - glides away when you're not using it
    int hudY, hudTarget; DateTime hudTouch = DateTime.Now; readonly System.Windows.Forms.Timer hudAnim = new() { Interval = 12 };
    // 🖥 desktop mode
    bool floor, paused;
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint f);
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
    [System.Runtime.InteropServices.DllImport("user32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder sb, int n);
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    struct RECT { public int L, T, R, B; }
    // ⌨ the Copilot key (it sends Win+Shift+F23) = show FreedomOS
    delegate IntPtr LLProc(int n, IntPtr w, IntPtr l);
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern IntPtr SetWindowsHookEx(int id, LLProc fn, IntPtr mod, uint tid);
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern IntPtr CallNextHookEx(IntPtr h, int n, IntPtr w, IntPtr l);
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern bool UnhookWindowsHookEx(IntPtr h);
    [System.Runtime.InteropServices.DllImport("kernel32.dll")] static extern IntPtr GetModuleHandle(string name);
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
    static LLProc keyProc; static IntPtr keyHook;
    IntPtr KeyHook(int n, IntPtr w, IntPtr l)
    {
        if (n >= 0 && System.Runtime.InteropServices.Marshal.ReadInt32(l) == 0x86)     // F23 = the Copilot key
        {
            int msg = (int)w;
            if (msg == 0x100 || msg == 0x104) { keybd_event(0xE8, 0, 0, UIntPtr.Zero); keybd_event(0xE8, 0, 2, UIntPtr.Zero); }   // stops the Start menu popping from the Win part
            else BeginInvoke(new Action(ShowF35));
            return (IntPtr)1;                                                          // Windows doesn't get it (no Copilot)
        }
        return CallNextHookEx(keyHook, n, w, l);
    }
    readonly FlowLayoutPanel favBar = new();           // your bookmarks: just the site logos, under the address bar
    static readonly HttpClient iconHttp = new() { Timeout = TimeSpan.FromSeconds(6) };
    readonly Panel bookBar = new();                    // the Home page's toolbar, under the tabs like bookmarks
    readonly FlowLayoutPanel bookBtns = new();
    readonly Label bookInfo = new();
    readonly Dictionary<string, Button> bookMap = new();
    readonly Dictionary<string, string> bookPop = new();
    string barInfo = "";
    Rectangle popRect = Rectangle.Empty;               // where the Home page's pop-up is (on the Home page view), empty = none
    bool popPinned; string hoverKey = ""; DateTime hoverAt, popAwayAt = DateTime.MaxValue;
    [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
    struct MEMSTAT { public uint len, load; public ulong total, avail, tp, ap, tv, av, ae; }
    [System.Runtime.InteropServices.DllImport("kernel32.dll")] static extern bool GlobalMemoryStatusEx(ref MEMSTAT m);
    static string Ram()
    {
        var m = new MEMSTAT { len = (uint)System.Runtime.InteropServices.Marshal.SizeOf<MEMSTAT>() };
        if (!GlobalMemoryStatusEx(ref m)) return "";
        double gb = 1024.0 * 1024 * 1024;
        return $"🐏 RAM {(m.total - m.avail) / gb:0.0}/{m.total / gb:0.0} GB";
    }
    readonly FlowLayoutPanel winBtns = new();
    Button bMin, bMax, bX;
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern bool ReleaseCapture();
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr h, int msg, IntPtr w, IntPtr l);
    readonly List<Tab> tabs = new();
    Tab cur;
    readonly FlowLayoutPanel tabBar = new();
    readonly Panel nav = new(), content = new();
    readonly TextBox addr = new();
    Button bBack, bFwd, bReload, bHome, bStar, bBrain, bRead, bMenu, bNew;
    readonly Label status = new();
    readonly string firstUrl;
    bool fullScreen;
    FormWindowState preFullState;
    float k = 1f;                                       // screen scaling (laptop at 250% = 2.5) - every size goes through P()
    int P(int px) => (int)Math.Round(px * k * (slate ? 1.3f : 1f));
    bool slate;                                         // 📱 tablet mode (keyboard flipped back) = bigger tabs + buttons for fingers
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern int GetSystemMetrics(int i);
    static bool IsSlate() { try { return GetSystemMetrics(0x2003) == 0; } catch { return false; } }   // SM_CONVERTIBLESLATEMODE: 0 = tablet
    void SlateCheck()
    {
        bool now = IsSlate();
        if (now == slate) return;
        slate = now;
        ApplySizes();
        foreach (Control c in favBar.Controls) c.Size = new Size(P(32), P(28));
        if (floor) ReFloor();
    }
    readonly List<Button> allBtns = new();
    FlowLayoutPanel leftBox, rightBox;
    Panel addrWrap;

    void ApplySizes()
    {
        tabBar.Height = P(38); tabBar.Padding = new Padding(P(6), P(5), P(6), 0);
        bookBar.Height = P(34); bookBtns.Padding = new Padding(P(6), P(2), 0, 0); bookInfo.Padding = new Padding(0, P(2), P(10), 0);
        foreach (var b in bookMap.Values) { b.Size = new Size(P(36), P(28)); b.Margin = new Padding(P(1), 0, P(1), 0); }
        favBar.Height = P(32); favBar.Padding = new Padding(P(8), 0, P(8), P(2));
        foreach (Control c in favBar.Controls) { c.Size = new Size(P(32), P(28)); c.Margin = new Padding(P(1), 0, P(1), 0); }
        if (IsHandleCreated) BeginInvoke(new Action(HudLayout));
        topRow.Height = P(38); winBtns.Padding = new Padding(0, P(3), P(2), 0);
        Padding = WindowState == FormWindowState.Maximized ? new Padding(0) : new Padding(P(4));
        nav.Height = P(46); nav.Padding = new Padding(P(6), P(6), P(6), P(6));
        status.Height = P(22); status.Padding = new Padding(P(8), P(2), 0, 0);
        addrWrap.Padding = new Padding(P(8), P(3), P(8), P(3));
        foreach (var b in allBtns) { b.Size = new Size(b == bNew ? P(32) : P(38), P(32)); b.Margin = new Padding(P(2), 0, P(2), 0); }
        bNew.Height = P(28);
        foreach (var t in tabs) { t.Chip.Height = P(28); t.CloseLbl.Width = P(26); t.TitleLbl.Padding = new Padding(P(8), 0, 0, 0); }
        LayoutTabs();
    }

    public BrowserForm(bool main, string url, Point? at)
    {
        isMain = main; openAt = at;
        firstUrl = url;
        k = DeviceDpi / 96f; slate = IsSlate();
        // 📱 rotate the screen / plug in a monitor / change scaling = fit the whole screen again
        Microsoft.Win32.SystemEvents.DisplaySettingsChanged += OnDisplayChanged;
        FormClosed += (s, e) => Microsoft.Win32.SystemEvents.DisplaySettingsChanged -= OnDisplayChanged;
        DpiChanged += (s, e) => { k = e.DeviceDpiNew / 96f; BeginInvoke(new Action(ApplySizes)); };   // dragged to another screen
        Text = isMain ? "FreedomOS" : "WiBro";
        BackColor = Theme.Bar;
        ForeColor = Theme.Text;
        FormBorderStyle = FormBorderStyle.Sizable;                       // a real Windows window (snap, Win+arrows, resize) - we just hide its title bar
        Size = isMain ? new Size(P(1280), P(860)) : new Size(P(1100), P(760));
        if (openAt.HasValue) { StartPosition = FormStartPosition.Manual; Location = new Point(Math.Max(0, openAt.Value.X - P(120)), Math.Max(0, openAt.Value.Y - P(18))); }
        else StartPosition = FormStartPosition.CenterScreen;
        KeyPreview = true;
        try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

        // --- tab strip
        tabBar.Dock = DockStyle.Fill; tabBar.BackColor = Theme.Bg; tabBar.WrapContents = false; tabBar.AutoScroll = false;
        // grab the empty part of the tab row to move the window, double-click it to make it big / small
        tabBar.MouseDown += (s, e) => { if (e.Button == MouseButtons.Left && e.Clicks == 1) DragWindow(); };
        tabBar.DoubleClick += (s, e) => ToggleMax();
        winBtns.Dock = DockStyle.Right; winBtns.AutoSize = true; winBtns.AutoSizeMode = AutoSizeMode.GrowAndShrink; winBtns.WrapContents = false; winBtns.BackColor = Theme.Bg;
        winBtns.MouseDown += (s, e) => { if (e.Button == MouseButtons.Left && e.Clicks == 1) DragWindow(); };
        bMin = MkBtn("─", "Minimize", (s, e) => WindowState = FormWindowState.Minimized);
        bMax = MkBtn("▢", "Make it big / small (double-click the tab row too)", (s, e) => ToggleMax());
        bX = MkBtn("✕", isMain ? "Close FreedomOS (it keeps running in the tray)" : "Close this window", (s, e) => Close());
        foreach (var b in new[] { bMin, bMax, bX }) { b.BackColor = Theme.Bg; b.FlatAppearance.BorderSize = 0; }
        bX.FlatAppearance.MouseOverBackColor = Color.FromArgb(196, 43, 28);
        winBtns.Controls.AddRange(new Control[] { bMin, bMax, bX });
        bookBar.Dock = DockStyle.Top; bookBar.BackColor = Theme.Bg; bookBar.Visible = isMain;
        bookBtns.Dock = DockStyle.Fill; bookBtns.WrapContents = false; bookBtns.BackColor = Theme.Bg; bookBtns.AutoScroll = false;
        bookInfo.Dock = DockStyle.Right; bookInfo.AutoSize = true; bookInfo.ForeColor = Theme.Dim; bookInfo.BackColor = Theme.Bg;
        bookInfo.Font = new Font("Segoe UI Emoji", 9f); bookInfo.TextAlign = ContentAlignment.MiddleRight;
        bookBar.Controls.Add(bookBtns); bookBar.Controls.Add(bookInfo);
        bookBtns.MouseDown += (s, e) => { if (e.Button == MouseButtons.Left && e.Clicks == 1) DragWindow(); };
        favBar.Dock = DockStyle.Top; favBar.BackColor = Theme.Bar; favBar.WrapContents = false; favBar.AutoScroll = false; favBar.Visible = false;
        topRow.Dock = DockStyle.Top; topRow.BackColor = Theme.Bg;
        topRow.Controls.Add(tabBar); topRow.Controls.Add(winBtns);
        bNew = MkBtn("+", "New tab (Ctrl+T)", (s, e) => _ = NewTab(""));
        tabBar.Controls.Add(bNew);

        // --- the bar: back, forward, reload, home, address, star, brain, reader, menu
        nav.Dock = DockStyle.Top; nav.BackColor = Theme.Bar;
        var right = rightBox = new FlowLayoutPanel { Dock = DockStyle.Right, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, WrapContents = false, BackColor = Theme.Bar, Padding = new Padding(0) };
        var left = leftBox = new FlowLayoutPanel { Dock = DockStyle.Left, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, WrapContents = false, BackColor = Theme.Bar, Padding = new Padding(0) };
        bBack = MkBtn("◀", "Back (Alt+Left)", (s, e) => { if (cur?.View.CoreWebView2?.CanGoBack == true) cur.View.CoreWebView2.GoBack(); });
        bFwd = MkBtn("▶", "Forward (Alt+Right)", (s, e) => { if (cur?.View.CoreWebView2?.CanGoForward == true) cur.View.CoreWebView2.GoForward(); });
        bReload = MkBtn("⟳", "Reload (F5)", (s, e) => cur?.View.CoreWebView2?.Reload());
        bHome = MkBtn("⌂", "Start page", (s, e) => GoHome(cur));
        left.Controls.AddRange(new Control[] { bBack, bFwd, bReload, bHome });
        bStar = MkBtn("☆", "Bookmark this page", (s, e) => ToggleBookmark());
        bBrain = MkBtn("🧠", "Ask the brain to sum up this page", (s, e) => BrainThisPage());
        bRead = MkBtn("📖", "Read this page clean (no ads)", (s, e) => ReaderThisPage());
        bMenu = MkBtn("☰", "Menu", (s, e) => ShowMenu());
        right.Controls.AddRange(new Control[] { bStar, bBrain, bRead, bMenu });
        addrWrap = new Panel { Dock = DockStyle.Fill, BackColor = Theme.Bar };
        addr.Dock = DockStyle.Fill; addr.BorderStyle = BorderStyle.FixedSingle; addr.BackColor = Theme.Bg; addr.ForeColor = Theme.Text;
        addr.Font = new Font("Segoe UI", 11f); addr.PlaceholderText = "Search with the brain, or type a web address";
        addr.KeyDown += (s, e) => { if (e.KeyCode == Keys.Enter) { e.SuppressKeyPress = true; Go(addr.Text); } };
        addr.Enter += (s, e) => BeginInvoke(new Action(() => addr.SelectAll()));
        addrWrap.Controls.Add(addr);
        nav.Controls.Add(addrWrap); nav.Controls.Add(right); nav.Controls.Add(left);

        // --- the page area + a little status line at the bottom
        content.Dock = DockStyle.Fill; content.BackColor = Theme.Bg;
        content.Resize += (s, e) => { if (snap != null) SnapLayout(); };
        status.Dock = DockStyle.None; status.AutoSize = true; status.Visible = false; status.BackColor = Theme.Bg; status.ForeColor = Theme.Dim; status.Font = new Font("Segoe UI", 8.5f);
        hud.BackColor = Theme.Bg;
        hud.Controls.Add(favBar); hud.Controls.Add(nav); hud.Controls.Add(bookBar); hud.Controls.Add(topRow);
        foreach (Control c in hud.Controls) c.VisibleChanged += (s, e) => HudLayout();
        Controls.Add(content); content.Controls.Add(status); Controls.Add(hud);   // status floats over the page now - no bottom bar
        if (!isMain) hud.Dock = DockStyle.Top;
        else
        {   // main window: the HUD floats over the page (like the taskbar), content gets the whole screen
            ShowInTaskbar = false;
            grab.BackColor = Theme.Bg; grab.Visible = false; grab.Cursor = Cursors.Hand;
            grab.Paint += (s, e) =>
            {   // a little pill in the middle, like a phone's pull-down handle
                e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                int w = P(64), h = Math.Max(3, grab.Height / 3), x = (grab.Width - w) / 2, y = (grab.Height - h) / 2;
                using var br = new SolidBrush(Mix(Theme.Text, Theme.Bg, .55f));
                using var gp = new System.Drawing.Drawing2D.GraphicsPath();
                gp.AddArc(x, y, h, h, 90, 180); gp.AddArc(x + w - h, y, h, h, 270, 180); gp.CloseFigure();
                e.Graphics.FillPath(br, gp);
            };
            grab.MouseDown += (s, e) => ShowHud();                   // touch counts as a click - tap or swipe down, same thing
            grab.MouseMove += (s, e) => { if (e.Button != MouseButtons.None) ShowHud(); };
            Controls.Add(grab);
            hudAnim.Tick += (s, e) =>
            {
                int step = Math.Max(2, Math.Abs(hudTarget - hudY) / 4);
                hudY = hudY < hudTarget ? Math.Min(hudTarget, hudY + step) : Math.Max(hudTarget, hudY - step);
                hud.Top = hudY;
                if (hudY == hudTarget) { hudAnim.Stop(); TellHud(); PlaceGrab(); }
            };
        }
        ApplySizes();

        All.Add(this);
        FormClosed += (s, e) => All.Remove(this);
        Load += async (s, e) => await Init();
        Shown += (s, e) =>
        {
            if (!isMain) return;
            if (S.Floor) { EnterFloor(); if (StartShow) ShowF35(); }               // 🖥 lives behind your apps, like a wallpaper
            else { FitMax(); WindowState = FormWindowState.Maximized; }           // or just full screen (Esc = smaller)
            HudLayout();
        };
        Activated += (s, e) => { if (paused) Resume(); FullHotkey(true); };
        Deactivate += (s, e) => BeginInvoke(new Action(() => { if (Form.ActiveForm == null) FullHotkey(false); }));
        HandleCreated += (s, e) => { if (isMain) RegisterHotKey(Handle, 35, 0x0001 | 0x0002 | 0x4000, 0x44); };   // Ctrl+Alt+D, no repeat
        if (isMain)
        {
            keyProc = KeyHook;
            keyHook = SetWindowsHookEx(13, keyProc, GetModuleHandle(null), 0);
            FormClosed += (s, e) => { if (keyHook != IntPtr.Zero) UnhookWindowsHookEx(keyHook); };
        }
        if (isMain)
        {   // 🎮 a game or full-screen app on top = go black + stop everything till you come back
            var gameT = new System.Windows.Forms.Timer { Interval = 1500 };
            gameT.Tick += (s, e) => { if (floor && !paused && CoveredByFullScreenApp()) Pause(); };
            gameT.Start();
            FormClosed += (s, e) => gameT.Dispose();
        }
        FormClosing += (s, e) => S.Save();
        Resize += (s, e) =>
        {
            if (floor)
            {   // Win+D / show desktop minimizes everything - FreedomOS IS the desktop, so it comes right back
                if (WindowState == FormWindowState.Minimized) BeginInvoke(new Action(() => { WindowState = FormWindowState.Normal; ReFloor(); if (paused) Resume(); }));
                Padding = new Padding(0); LayoutTabs(); HudLayout();
                return;
            }
            if (!inMax)
            {
                if (WindowState == FormWindowState.Maximized && FormBorderStyle != FormBorderStyle.None)
                { inMax = true; FitMax(); FormBorderStyle = FormBorderStyle.None; WindowState = FormWindowState.Normal; WindowState = FormWindowState.Maximized; inMax = false; }
                else if (WindowState == FormWindowState.Normal && FormBorderStyle == FormBorderStyle.None)
                { inMax = true; FormBorderStyle = FormBorderStyle.Sizable; inMax = false; }
            }
            Padding = WindowState == FormWindowState.Maximized ? new Padding(0) : new Padding(P(4));   // the thin edge you grab to resize
            if (bMax != null) bMax.Text = WindowState == FormWindowState.Maximized ? "❐" : "▢";
            LayoutTabs(); HudLayout();
        };
        Move += (s, e) =>
        {
            if (WindowState == FormWindowState.Normal) FitMax();
            if (floor && WindowState == FormWindowState.Normal && !inMax)
            {   // something nudged the desktop (Win+arrows, a drag)? snap it right back
                var b = Screen.FromHandle(Handle).Bounds;
                if (Left != b.X || Top != b.Y) BeginInvoke(new Action(ReFloor));
            }
        };
        var hoverT = new System.Windows.Forms.Timer { Interval = 100 };
        hoverT.Tick += (s, e) =>
        {
            if (!topRow.Visible) return;
            var cp = Cursor.Position;
            if (floor) { bMin.Visible = bMax.Visible = false; }
            var r = topRow.RectangleToScreen(topRow.ClientRectangle);
            if (bookBar.Visible) r = Rectangle.Union(r, bookBar.RectangleToScreen(bookBar.ClientRectangle));
            r.Inflate(0, P(8));
            bool h = r.Contains(cp) || tabs.Any(x => x.Dragging) || PopScreen().Contains(cp);
            if (h != hot) { hot = h; PaintTabs(); }
            // full screen: ─ ▢ ✕ only show up when the mouse goes near the top-right corner
            bool showWin = (WindowState != FormWindowState.Maximized && !floor) || new Rectangle(Right - P(220), Top, P(220), P(60)).Contains(cp);
            HudTick(cp);
            if (winBtns.Visible != showWin) { winBtns.Visible = showWin; LayoutTabs(); }
            BarTick(cp);
        };
        hoverT.Start();
        FormClosed += (s, e) => hoverT.Dispose();
    }

    Button MkBtn(string text, string tip, EventHandler click)
    {
        var b = new Button
        {
            Text = text, FlatStyle = FlatStyle.Flat, BackColor = Theme.Bar, ForeColor = Theme.Text,
            Font = new Font("Segoe UI Emoji", 10f), Cursor = Cursors.Hand, TabStop = false, Padding = new Padding(0),
            TextAlign = ContentAlignment.MiddleCenter, UseCompatibleTextRendering = false
        };
        b.Size = new Size(P(38), P(32));
        allBtns.Add(b);
        b.FlatAppearance.BorderColor = Theme.Edge; b.FlatAppearance.MouseOverBackColor = Theme.TabOn; b.FlatAppearance.BorderSize = 0;
        b.Click += click;
        new ToolTip().SetToolTip(b, tip);
        return b;
    }

    async Task Init()
    {
        var opts = new CoreWebView2EnvironmentOptions();
        opts.AdditionalBrowserArguments = "--remote-debugging-port=" + Ports.DevTools + " --remote-debugging-address=127.0.0.1 --autoplay-policy=no-user-gesture-required" + (S.GpuFix ? " --disable-gpu --disable-gpu-compositing" : "");
        try
        {
            envTask ??= CoreWebView2Environment.CreateAsync(null, Path.Combine(Settings.Home, "data"), opts);
            env = await envTask;
        }
        catch (Exception ex)
        {
            MessageBox.Show("WiBro needs the Microsoft Edge WebView2 Runtime (it's built into Windows 10/11).\n\n" + ex.Message, "WiBro");
            Close();
            return;
        }
        if (!adStarted) { adStarted = true; _ = Task.Run(async () => { await AdBlock.LoadAsync(); BeginInvoke(new Action(() => SetStatus($"🛡 ad blocker ready: {AdBlock.Count:N0} ad + tracker sites blocked"))); }); }
        DrawFavs();
        if (isMain)
        {
            StartPipe();
            await NewTab(F35 + "/", select: string.IsNullOrEmpty(firstUrl), home: true);
            _ = ShowApp("discord-bg");                       // 👾 online from the get-go
            var ot = new System.Windows.Forms.Timer { Interval = 6000 };   // pinned overlay widgets come up once Discord's loaded
            ot.Tick += (s, e) => { ot.Dispose(); ApplyOvl(); };
            ot.Start();
            if (Restore)
            {   // 🔄 just updated: put your tabs back
                foreach (var u in S.Session.ToList()) if (!string.IsNullOrEmpty(u)) await NewTab(u, select: false);
            }
            if (firstUrl == "--newtab") await NewTab("");
            else if (firstUrl.StartsWith("--app=")) { Select(tabs[0]); await ShowApp(firstUrl[6..]); }
            else if (!string.IsNullOrEmpty(firstUrl)) await NewTab(firstUrl);
        }
        else await NewTab(firstUrl);
    }

    // ---------------------------------------------------------------- tabs
    public async Task<Tab> NewTab(string url, bool select = true, bool home = false, string app = "")
    {
        var t = new Tab { IsHome = home, App = app, View = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = Theme.Bg, Visible = false } };
        content.Controls.Add(t.View);
        t.Chip = new Panel { Height = P(28), Width = P(200), BackColor = Theme.Bar, Margin = new Padding(0, 0, P(4), 0), Cursor = Cursors.Hand };
        t.TitleLbl = new Label { Text = "New tab", ForeColor = Theme.Text, AutoSize = false, Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft,
            Font = new Font("Segoe UI", 9f), Padding = new Padding(P(8), 0, 0, 0), AutoEllipsis = true, Cursor = Cursors.Hand };
        t.CloseLbl = new Label { Text = "✕", ForeColor = Theme.Dim, Dock = DockStyle.Right, Width = P(26), TextAlign = ContentAlignment.MiddleCenter, Cursor = Cursors.Hand };
        t.Chip.Controls.Add(t.TitleLbl);
        if (home) { t.Title = "🏠 Home"; t.TitleLbl.Text = t.Title; t.TitleLbl.Font = new Font("Segoe UI Emoji", 9.5f, FontStyle.Bold); }
        else if (app != "") { t.Title = Apps[app].name; t.TitleLbl.Text = t.Title; t.CloseLbl.Text = "▁"; t.Chip.Controls.Add(t.CloseLbl); }
        else t.Chip.Controls.Add(t.CloseLbl);
        // click = pick it, middle-click = close it, drag it OUT of the window = it gets its own window
        MouseEventHandler down = (s, e) => { if (e.Button == MouseButtons.Left) { t.DownAt = Control.MousePosition; t.Dragging = false; } };
        MouseEventHandler move = (s, e) =>
        {
            if (e.Button != MouseButtons.Left || t.IsHome) return;
            var m = Control.MousePosition;
            if (!t.Dragging && (Math.Abs(m.X - t.DownAt.X) > P(14) || Math.Abs(m.Y - t.DownAt.Y) > P(14))) { t.Dragging = true; Cursor.Current = Cursors.SizeAll; }
            if (t.Dragging) { Cursor.Current = Bounds.Contains(m) ? Cursors.SizeAll : Cursors.UpArrow; SnapBarTrack(m); }
        };
        MouseEventHandler up = (s, e) =>
        {
            if (e.Button == MouseButtons.Middle) { if (t.App != "") Tuck(t); else if (!t.IsHome) CloseTab(t); return; }
            if (t.Dragging)
            {
                t.Dragging = false; Cursor.Current = Cursors.Default;
                var m = Control.MousePosition;
                if (SnapBarDrop(t, m)) return;                               // dropped on the snap bar = snapped
                if (t.App != "") return;
                var into = All.FirstOrDefault(f => f != this && f.Visible && f.WindowState != FormWindowState.Minimized && f.Bounds.Contains(m));
                if (into != null) { DropInto(t, into); return; }          // dragged onto another window = it joins that one
                if (!Bounds.Contains(m)) { TearOff(t); return; }           // dragged out into nothing = its own window
            }
            Select(t);
        };
        foreach (Control c in new Control[] { t.Chip, t.TitleLbl }) { c.MouseDown += down; c.MouseMove += move; c.MouseUp += up; }
        if (true)
        {   // right-click a tab = Snap it (Windows 11 layouts)
            MouseEventHandler rc = (s, e) => { if (e.Button == MouseButtons.Right) SnapMenu(t, (Control)s, e.Location); };
            t.Chip.MouseUp += rc; t.TitleLbl.MouseUp += rc;
        }
        t.CloseLbl.Click += (s, e) => { if (t.App != "") Tuck(t); else CloseTab(t); };
        tabBar.Controls.Add(t.Chip);
        tabBar.Controls.SetChildIndex(bNew, tabBar.Controls.Count - 1);
        tabs.Add(t);
        LayoutTabs();
        if (select) Select(t);

        t.View.GotFocus += (s, e) => { if (snap != null && cur != t && snapTabs.Contains(t)) { cur = t; AfterFocus(t); } };
        await t.View.EnsureCoreWebView2Async(env);
        var w = t.View.CoreWebView2;
        w.Settings.IsStatusBarEnabled = true;
        w.Settings.AreDefaultContextMenusEnabled = true;
        if (app == "discord")
            w.PermissionRequested += (s, e) => { if (e.Uri.StartsWith("https://discord.com")) e.State = CoreWebView2PermissionState.Allow; };
        if (home)
        {   // the FreedomOS page: camera/mic for Claude chat pictures, and if FreedomOS's not up yet, keep trying
            w.PermissionRequested += (s, e) => { if (e.Uri.StartsWith(F35)) e.State = CoreWebView2PermissionState.Allow; };
            w.NavigationCompleted += (s, e) =>
            {
                if (!e.IsSuccess && w.Source.StartsWith(F35))
                    w.NavigateToString("<html><body style='background:#12161f;color:#cfe3ff;font:16px Segoe UI;display:flex;align-items:center;justify-content:center;height:90vh'>" +
                        "<div>FreedomOS isn't running yet - waiting for it...</div><script>setTimeout(()=>location.href='" + F35 + "/', 4000)</script></body></html>");
            };
        }
        w.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
        w.WebResourceRequested += (s, e) =>
        {
            if (!S.AdBlock) return;
            try
            {
                var host = new Uri(e.Request.Uri).Host;
                var top = string.IsNullOrEmpty(t.Url) ? "" : new Uri(t.Url).Host;
                if (S.AdAllow.Contains(top)) return;
                if (AdBlock.IsBlocked(host) && !host.EndsWith(top, StringComparison.OrdinalIgnoreCase))
                    e.Response = env.CreateWebResourceResponse(null, 403, "Blocked by WiBro", "");
            }
            catch { }
        };
        await w.AddScriptToExecuteOnDocumentCreatedAsync(AdBlock.CosmeticJs);
        // 📱 tablet: swipe down from the top (or tap the very top edge) = tabs + toolbar come back. Plus: no scroll bars anywhere in FreedomOS.
        await w.AddScriptToExecuteOnDocumentCreatedAsync(@"(() => {
          const css = () => { const st = document.createElement('style'); st.textContent = '*{scrollbar-width:none!important}*::-webkit-scrollbar{display:none!important;width:0!important;height:0!important}';
            (document.head || document.documentElement).appendChild(st); };
          if (document.documentElement) css(); else addEventListener('DOMContentLoaded', css);
          let y0 = -1, x0 = 0;
          const hud = () => { y0 = -1; try { chrome.webview.postMessage('hud:show'); } catch (_) {} };
          const start = (x, y) => { y0 = y <= 64 ? y : -1; x0 = x; };
          const move = (x, y) => { if (y0 >= 0 && y - y0 > 18 && Math.abs(x - x0) < 140) hud(); };
          const o = { capture: true, passive: true };
          addEventListener('pointerdown', e => { if (e.pointerType !== 'mouse') start(e.clientX, e.clientY); }, o);
          addEventListener('pointermove', e => { if (e.pointerType !== 'mouse') move(e.clientX, e.clientY); }, o);
          addEventListener('pointerup', e => { if (e.pointerType !== 'mouse' && e.clientY <= 16) hud(); }, o);
          addEventListener('touchstart', e => { const t = e.touches[0]; if (t) start(t.clientX, t.clientY); }, o);
          addEventListener('touchmove', e => { const t = e.touches[0]; if (t) move(t.clientX, t.clientY); }, o);
        })();");
        w.WebMessageReceived += (s, e) => { string m = ""; try { m = e.TryGetWebMessageAsString(); } catch { } if (m == "hud:show") { ShowHud(); hudTouch = DateTime.Now.AddSeconds(3); } };   // a finger needs a sec more to reach a tab
        w.DocumentTitleChanged += (s, e) =>
        {
            if (t.App == "discord")
            {   // Discord puts "(3)" in front of the title when you've got pings
                var mm = System.Text.RegularExpressions.Regex.Match(w.DocumentTitle ?? "", @"^\((\d+)\)");
                int n = mm.Success ? int.Parse(mm.Groups[1].Value) : 0;
                if (n != discordUnread)
                {
                    discordUnread = n;
                    t.TitleLbl.Text = n > 0 ? $"👾 Discord ({n})" : "👾 Discord";
                    _ = iconHttp.PostAsync(F35 + "/discord/ping", new StringContent("{\"n\":" + n + "}", Encoding.UTF8, "application/json"));
                }
                return;
            }
            if (t.IsHome || t.App != "") return;
            t.Title = string.IsNullOrWhiteSpace(w.DocumentTitle) ? "New tab" : w.DocumentTitle; t.TitleLbl.Text = t.Title;
            if (t == cur && !isMain) Text = t.Title + " - WiBro";
        };
        w.SourceChanged += (s, e) => { if (!t.IsHome && t.App == "") SaveSessionSoon(); };
        w.SourceChanged += (s, e) => { t.Url = t.IsHome || t.App != "" || w.Source.StartsWith("data:") || w.Source.StartsWith("about:") ? "" : w.Source; if (t == cur) ShowUrl(t); };
        w.HistoryChanged += (s, e) => { if (t == cur) UpdateButtons(); };
        w.NavigationStarting += (s, e) => { if (t == cur) SetStatus("loading..."); };
        w.NavigationCompleted += (s, e) => { if (t == cur) { SetStatus(""); UpdateButtons(); } };
        w.NewWindowRequested += async (s, e) =>
        {   // links that open new windows (and login pop-ups) become tabs that still talk to the page that opened them
            var d = e.GetDeferral();
            try
            {
                var nt = await NewTab(null);
                e.NewWindow = nt.View.CoreWebView2;
                e.Handled = true;
            }
            finally { d.Complete(); }
        };
        w.ContainsFullScreenElementChanged += (s, e) => SetFullScreen(w.ContainsFullScreenElement);
        w.FaviconChanged += (s, e) => { if (!t.IsHome && t.App == "" && S.Bookmarks.Contains(t.Url) && !File.Exists(IconFile(t.Url))) _ = GrabIcon(t); };
        if (home)
        {   // the Home page tells us when an app should come up as a tab: chrome.webview.postMessage("app:pixel")
            w.NavigationCompleted += (s, e) => { lastTold = -1; TellHud(); };
            w.WebMessageReceived += (s, e) =>
            {
                string m = ""; try { m = e.TryGetWebMessageAsString(); } catch { }
                if (m.StartsWith("app:")) _ = ShowApp(m[4..]);
                else if (m == "ovl:toggle") ToggleOverlay();
                else if (m == "ovl:full") ToggleFull();
                else if (m.StartsWith("bar:")) OnBar(m[4..]);
                else if (m.StartsWith("pop:")) OnPop(m[4..]);
            };
            w.Navigate(url);
        }
        else if (app != "")
        {
            if (app == "pixel")
            {   // 🖼 your wallpaper behind the Pixel Shop too (WiMix gets it from FreedomOS itself)
                await w.AddScriptToExecuteOnDocumentCreatedAsync(@"addEventListener('DOMContentLoaded', () => {
                  fetch('http://127.0.0.1:" + Ports.App + @"/music/wall').then(r => r.json()).then(d => { if (!d.url) return;
                    const st = document.createElement('style'); st.textContent = 'html,body{background:transparent!important}'; document.head.appendChild(st);
                    const f = document.createElement('iframe'); f.src = d.url; f.tabIndex = -1; f.setAttribute('aria-hidden','true');
                    f.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;border:0;z-index:-1;pointer-events:none;background:#000';
                    document.documentElement.appendChild(f); }).catch(() => {}); });");
            }
            w.Navigate(url);
        }
        else if (url != null) Go(url, t);
        return t;
    }

    void Select(Tab t)
    {
        if (t == null) return;
        if (popRect != Rectangle.Empty && t != cur) HomeJs("f35NativePop('', true)");
        if (snap != null)
        {
            if (t.IsHome && !snapTabs.Contains(t)) SnapOff();               // Home (not snapped) = back to full screen
            else if (!snapTabs.Contains(t))
            {   // a tab that's not snapped goes into the pane you're working in
                int z = Math.Max(0, Array.IndexOf(snapTabs, cur));
                snapTabs[z] = t;
            }
        }
        cur = t;
        if (snap != null) SnapLayout();
        else foreach (var x in tabs) { x.View.Visible = x == t; if (x.IsHome) x.View.Region = null; }
        PaintTabs();
        t.Chip.Visible = true;
        if (snap == null) t.View.BringToFront();
        AfterFocus(t);
    }
    void AfterFocus(Tab t)
    {
        PaintTabs();
        nav.Visible = !t.IsHome && t.App == "";
        favBar.Visible = nav.Visible && S.Bookmarks.Count > 0;
        Text = isMain ? "FreedomOS" : t.Title + " - WiBro";
        ShowUrl(t);
        UpdateButtons();
        if (nav.Visible && string.IsNullOrEmpty(t.Url)) addr.Focus(); else t.View.Focus();
    }

    // the tab row dims like the Home page's toolbar - mouse up there and it lights back up
    bool hot = true;
    static Color Mix(Color a, Color b, float f) => Color.FromArgb((int)(a.R + (b.R - a.R) * f), (int)(a.G + (b.G - a.G) * f), (int)(a.B + (b.B - a.B) * f));
    Color Dimmed(Color c) => hot ? c : Mix(c, Theme.Bg, .6f);
    void PaintTabs()
    {
        foreach (var x in tabs)
        {
            bool on = x == cur;
            x.Chip.BackColor = Dimmed(on ? Theme.TabOn : snap != null && snapTabs.Contains(x) ? Mix(Theme.TabOn, Theme.Bar, .45f) : Theme.Bar);
            x.TitleLbl.ForeColor = Dimmed(on ? Theme.Text : Theme.Dim);
            x.CloseLbl.ForeColor = Dimmed(Theme.Dim);
        }
        if (bNew != null) { bNew.BackColor = Dimmed(Theme.Bar); bNew.ForeColor = Dimmed(Theme.Text); bNew.FlatAppearance.BorderColor = Dimmed(Theme.Edge); }
        foreach (var b in new[] { bMin, bMax, bX }) if (b != null) b.ForeColor = Dimmed(Theme.Text);
        foreach (var kv in bookMap) { bool on = bookPop.ContainsKey(kv.Key) && popPinned && popKey == kv.Key; kv.Value.BackColor = Dimmed(on ? Theme.TabOn : Theme.Bg); kv.Value.ForeColor = Dimmed(Theme.Text); kv.Value.FlatAppearance.BorderColor = Dimmed(Theme.Edge); }
        bookInfo.ForeColor = Dimmed(Theme.Dim);
    }

    System.Windows.Forms.Timer sessT;
    void SaveSessionSoon()
    {
        if (!isMain) return;
        sessT ??= new System.Windows.Forms.Timer { Interval = 1500 };
        sessT.Stop();
        sessT.Tick -= SessTick; sessT.Tick += SessTick;
        sessT.Start();
    }
    void SessTick(object s, EventArgs e)
    {
        sessT.Stop();
        S.Session = tabs.Where(x => !x.IsHome && x.App == "" && !string.IsNullOrEmpty(x.Url)).Select(x => x.Url).Distinct().ToList();
        S.Save();
    }

    void CloseTab(Tab t)
    {
        int i = tabs.IndexOf(t);
        if (i < 0 || t.IsHome) return;
        tabs.Remove(t);
        SaveSessionSoon();
        if (snap != null && snapTabs.Contains(t)) SnapRemove(t);
        tabBar.Controls.Remove(t.Chip);
        content.Controls.Remove(t.View);
        t.View.Dispose();
        if (tabs.Count == 0) { Close(); return; }            // a popped-out window closes with its last tab
        if (t == cur) Select(tabs[Math.Max(0, i - 1)]);
        LayoutTabs();
    }

    void LayoutTabs()
    {
        if (tabs.Count == 0) return;
        int room = Math.Max(P(200), tabBar.ClientSize.Width - P(60));
        int n = Math.Max(1, tabs.Count(x => x.Chip.Visible));
        int w = Math.Max(P(70), Math.Min(P(220), room / n - P(4)));
        foreach (var t in tabs) t.Chip.Width = w;
        PaintTabs();
    }

    void ShowUrl(Tab t) { if (!addr.Focused) addr.Text = t.Url; bStar.Text = S.Bookmarks.Contains(t.Url) ? "★" : "☆"; }

    void UpdateButtons()
    {
        var w = cur?.View.CoreWebView2;
        bBack.Enabled = w?.CanGoBack == true;
        bFwd.Enabled = w?.CanGoForward == true;
    }

    System.Windows.Forms.Timer statusT;
    void SetStatus(string s)
    {   // little link-preview tag that floats bottom-left, only while there's something to say
        if (string.IsNullOrEmpty(s) || s.StartsWith("loading")) { status.Visible = false; return; }
        status.Text = s.Length > 120 ? s[..120] + "…" : s;
        status.Location = new Point(P(6), content.ClientSize.Height - status.Height - P(6));
        status.Visible = true; status.BringToFront();
        statusT ??= new System.Windows.Forms.Timer { Interval = 2500 };
        statusT.Tick -= StatusHide; statusT.Tick += StatusHide; statusT.Stop(); statusT.Start();
    }
    void StatusHide(object s, EventArgs e) { statusT.Stop(); status.Visible = false; }

    // ---------------------------------------------------------------- going places
    static bool LooksLikeUrl(string s) =>
        s.StartsWith("http://") || s.StartsWith("https://") || s.StartsWith("localhost") ||
        (!s.Contains(' ') && s.Contains('.') && !s.EndsWith("."));

    bool F35Up()
    {
        try { using var c = new System.Net.Sockets.TcpClient(); var r = c.BeginConnect("127.0.0.1", Ports.App, null, null); return r.AsyncWaitHandle.WaitOne(250) && c.Connected; }
        catch { return false; }
    }

    void Go(string text, Tab t = null)
    {
        t ??= cur;
        text = (text ?? "").Trim();
        if (t?.View.CoreWebView2 == null) return;
        if (text.Length == 0 || text == "\u0001") { GoHome(t); return; }
        string url;
        if (LooksLikeUrl(text)) url = text.StartsWith("http") ? text : "https://" + text;
        else if (S.BrainSearch && F35Up()) url = F35 + "/web/page?q=" + Uri.EscapeDataString(text);
        else url = "https://duckduckgo.com/?q=" + Uri.EscapeDataString(text);
        t.View.CoreWebView2.Navigate(url);
    }

    void GoHome(Tab t)
    {
        if (t?.View.CoreWebView2 == null) return;
        t.View.CoreWebView2.NavigateToString(StartPage(S.BrainSearch && F35Up()));
        if (t == cur) { addr.Text = ""; addr.Focus(); }
    }

    string StartPage(bool brain)
    {   // your start page: one search box (the brain answers when FreedomOS is on) + your bookmarks
        var marks = new StringBuilder();
        foreach (var b in S.Bookmarks) marks.Append($"<a href=\"{System.Net.WebUtility.HtmlEncode(b)}\">{System.Net.WebUtility.HtmlEncode(new Uri(b).Host.Replace("www.", ""))}</a>");
        return "<!doctype html><html><head><meta charset=utf-8><title>New tab</title><style>body{background:#12161f;color:#e6ebf5;font:15px 'Segoe UI';display:flex;flex-direction:column;align-items:center;padding-top:16vh}" +
               "h1{font-weight:800;letter-spacing:1px}form{width:min(640px,90vw)}input{width:100%;padding:14px 18px;border-radius:14px;border:1px solid #2a3245;background:#1b2130;color:#e6ebf5;font-size:17px}" +
               ".m{margin-top:26px;display:flex;gap:8px;flex-wrap:wrap;justify-content:center}.m a{color:#9cc4ff;background:#1b2130;border:1px solid #2a3245;padding:8px 12px;border-radius:10px;text-decoration:none}</style></head>" +
               "<body><h1>🌐 WiBro</h1>" + (brain ? $"<form action='{F35}/web/page'><input name=q autofocus placeholder='🧠 Search - the brain reads the pages and gives you a straight answer'></form>"
                       : "<form action='https://duckduckgo.com/'><input name=q autofocus placeholder='Search (brain search is off, or FreedomOS isn&#39;t running)'></form>") +
               "<div class=m>" + marks + "</div><p style='margin-top:30px;color:#8b96ad;font-size:12px'>🛡 ads + trackers blocked · ☆ to bookmark · 🧠 sums up a page · 📖 reads it clean</p></body></html>";
    }

    // ---------------------------------------------------------------- FreedomOS buttons
    void BrainThisPage()
    {
        if (cur == null || string.IsNullOrEmpty(cur.Url) || cur.Url.StartsWith(F35)) { addr.Focus(); SetStatus("type a search up top - the brain answers it"); return; }
        if (!F35Up()) { SetStatus("🧠 needs FreedomOS running"); return; }
        _ = NewTab(F35 + "/web/sum?url=" + Uri.EscapeDataString(cur.Url));
    }

    void ReaderThisPage()
    {
        if (cur == null || string.IsNullOrEmpty(cur.Url) || cur.Url.StartsWith(F35)) return;
        if (!F35Up()) { SetStatus("📖 needs FreedomOS running"); return; }
        cur.View.CoreWebView2.Navigate(F35 + "/web/reader?url=" + Uri.EscapeDataString(cur.Url));
    }

    void ToggleBookmark()
    {
        if (cur == null || string.IsNullOrEmpty(cur.Url)) return;
        if (S.Bookmarks.Contains(cur.Url)) S.Bookmarks.Remove(cur.Url); else { S.Bookmarks.Add(cur.Url); _ = GrabIcon(cur); }
        S.Save(); ShowUrl(cur);
        foreach (var f in All) f.DrawFavs();
        SetStatus(S.Bookmarks.Contains(cur.Url) ? "★ saved - it shows on your start page" : "bookmark removed");
    }

    // ---------------------------------------------------------------- ★ bookmark bar: just the logos
    static string IconDir => Path.Combine(Settings.Home, "icons");
    static string IconFile(string url)
    {
        try { var h = new Uri(url).Host.ToLowerInvariant(); if (h.StartsWith("www.")) h = h[4..]; return Path.Combine(IconDir, string.Concat(h.Split(Path.GetInvalidFileNameChars())) + ".png"); }
        catch { return ""; }
    }
    async Task GrabIcon(Tab t)
    {   // the logo of the page you're on, saved so the bar has it forever
        try
        {
            var w = t.View.CoreWebView2; if (w == null || string.IsNullOrEmpty(t.Url)) return;
            using var st = await w.GetFaviconAsync(CoreWebView2FaviconImageFormat.Png);
            if (st == null || st.Length < 60) return;
            Directory.CreateDirectory(IconDir);
            using (var fs = File.Create(IconFile(t.Url))) await st.CopyToAsync(fs);
            foreach (var f in All) f.DrawFavs();
        }
        catch { }
    }
    async Task FetchIcon(string url)
    {   // no logo saved yet? ask the site itself for its little icon (nobody else sees your bookmarks)
        try
        {
            var u = new Uri(url);
            var bytes = await iconHttp.GetByteArrayAsync($"{u.Scheme}://{u.Host}/favicon.ico");
            using var ms = new MemoryStream(bytes);
            using var ico = new Icon(ms, 32, 32);
            using var bmp = ico.ToBitmap();
            Directory.CreateDirectory(IconDir);
            bmp.Save(IconFile(url), System.Drawing.Imaging.ImageFormat.Png);
            foreach (var f in All) f.DrawFavs();
        }
        catch { }
    }
    readonly HashSet<string> iconTried = new();
    public void DrawFavs()
    {
        foreach (Control c in favBar.Controls) c.Dispose();
        favBar.Controls.Clear();
        int px = P(18);
        foreach (var url in S.Bookmarks)
        {
            var b = new Button { FlatStyle = FlatStyle.Flat, BackColor = Theme.Bar, ForeColor = Theme.Text, Size = new Size(P(32), P(28)), Margin = new Padding(P(1), 0, P(1), 0),
                Cursor = Cursors.Hand, TabStop = false, Font = new Font("Segoe UI", 10f, FontStyle.Bold), Padding = new Padding(0) };
            b.FlatAppearance.BorderSize = 0; b.FlatAppearance.MouseOverBackColor = Theme.TabOn;
            var file = IconFile(url);
            if (file != "" && File.Exists(file))
            {
                try { using var raw = Image.FromFile(file); b.Image = new Bitmap(raw, new Size(px, px)); } catch { }
            }
            if (b.Image == null)
            {   // first letter till the logo shows up
                try { var h = new Uri(url).Host; if (h.StartsWith("www.")) h = h[4..]; b.Text = h.Substring(0, 1).ToUpper(); } catch { b.Text = "★"; }
                if (iconTried.Add(url)) _ = FetchIcon(url);
            }
            string host = url; try { host = new Uri(url).Host.Replace("www.", ""); } catch { }
            tip.SetToolTip(b, host + "\n" + url);
            string u = url;
            b.MouseUp += (s, e) =>
            {
                if (e.Button == MouseButtons.Middle) _ = NewTab(u, select: false);            // middle-click = open in a new tab
                else if (e.Button == MouseButtons.Right)
                {
                    var m = new ContextMenuStrip { BackColor = Theme.Bar, ForeColor = Theme.Text, ShowImageMargin = false };
                    m.Items.Add("Open in a new tab", null, (s2, e2) => _ = NewTab(u));
                    m.Items.Add("Remove bookmark", null, (s2, e2) => { S.Bookmarks.Remove(u); S.Save(); foreach (var f in All) f.DrawFavs(); if (cur != null) ShowUrl(cur); });
                    m.Show(b, new Point(0, b.Height));
                }
            };
            b.Click += (s, e) => { if (cur != null && !cur.IsHome && cur.App == "") Go(u, cur); else _ = NewTab(u); };
            favBar.Controls.Add(b);
        }
        favBar.Visible = nav.Visible && S.Bookmarks.Count > 0 && !fullScreen;
    }

    void ShowMenu()
    {
        var m = new ContextMenuStrip { BackColor = Theme.Bar, ForeColor = Theme.Text, ShowImageMargin = false, Font = new Font("Segoe UI", 10f) };
        var top = cur != null && !string.IsNullOrEmpty(cur.Url) ? new Uri(cur.Url).Host : "";
        m.Items.Add("New tab   (Ctrl+T)", null, (s, e) => _ = NewTab(""));
        if (isMain) m.Items.Add((S.Floor ? "✓ " : "") + "🖥 Desktop mode (FreedomOS lives behind your apps)", null, (s, e) =>
        {
            S.Floor = !S.Floor; S.Save();
            if (S.Floor) EnterFloor(); else ExitFloor();
        });
        m.Items.Add(new ToolStripSeparator());
        m.Items.Add((S.AdBlock ? "🛡 Ad blocker: ON" : "🛡 Ad blocker: OFF") + "  (click to flip)", null, (s, e) => { S.AdBlock = !S.AdBlock; S.Save(); cur?.View.CoreWebView2?.Reload(); });
        if (top.Length > 0)
        {
            bool allowed = S.AdAllow.Contains(top);
            m.Items.Add(allowed ? $"Block ads on {top} again" : $"Let ads through on {top} (if the site breaks)", null, (s, e) =>
            { if (allowed) S.AdAllow.Remove(top); else S.AdAllow.Add(top); S.Save(); cur?.View.CoreWebView2?.Reload(); });
        }
        m.Items.Add((S.BrainSearch ? "🧠 Brain search: ON" : "🧠 Brain search: OFF") + "  (address bar searches)", null, (s, e) => { S.BrainSearch = !S.BrainSearch; S.Save(); });
        m.Items.Add(new ToolStripSeparator());
        m.Items.Add("Downloads folder", null, (s, e) => Process.Start("explorer.exe", Environment.GetFolderPath(Environment.SpecialFolder.UserProfile) + "\\Downloads"));
        m.Items.Add((S.GpuFix ? "✔ " : "") + "Black-screen fix (restarts the browser)", null, (s, e) =>
        { S.GpuFix = !S.GpuFix; S.Save(); Process.Start(Application.ExecutablePath, cur?.Url ?? ""); Application.Exit(); });
        m.Items.Add(new ToolStripSeparator());
        m.Items.Add("About WiBro", null, (s, e) => MessageBox.Show("FreedomOS app + WiBro 1.0.6\nYour own browser, part of FreedomOS.\nEngine: Microsoft Edge WebView2\nAd blocker: " + AdBlock.Count.ToString("N0") + " sites", "WiBro"));
        m.Show(bMenu, new Point(bMenu.Width - m.Width, bMenu.Height));
    }

    // ---------------------------------------------------------------- drag a tab out of the window = its own window
    void TearOff(Tab t)
    {
        var url = t.Url;
        var f = new BrowserForm(false, string.IsNullOrEmpty(url) ? "" : url, Control.MousePosition);
        f.Show();
        CloseTab(t);
    }

    // dragged onto another F35 window = it moves in there
    void DropInto(Tab t, BrowserForm f)
    {
        var url = t.Url;
        _ = f.NewTab(string.IsNullOrEmpty(url) ? "" : url);
        f.Activate();
        CloseTab(t);
    }

    // ---------------------------------------------------------------- app tabs (🎧 Music, 🎨 Pixel Shop): ▁ tucks 'em back into the toolbar, still running
    Tab musicBack;
    int discordUnread = -1;                                       // the tab you were on before WiMix popped up to start the music
    public async Task ShowApp(string app)
    {
        if (app == "browser") { await NewTab(""); return; }
        if (app == "discord-bg")
        {   // 👾 starts with FreedomOS, tucked away - you're online, it's out of the way
            if (tabs.Any(x => x.App == "discord")) return;
            var dt = await NewTab(Apps["discord"].url, select: false, app: "discord");
            Tuck(dt);
            return;
        }
        if (app == "music-bg")
        {   // 🎧 button: WiMix shows for a sec (YouTube won't start music in a hidden tab), then FreedomOS tucks it away
            // hidden for real: WiMix sits "showing" BEHIND the tab you're on - YouTube thinks it's on screen and plays, you never see it
            var mt = tabs.FirstOrDefault(x => x.App == "music") ?? await NewTab(Apps["music"].url, select: false, app: "music");
            if (mt != cur)
            {
                mt.Chip.Visible = false; LayoutTabs();
                mt.View.Visible = true; mt.View.SendToBack();
            }
            return;
        }
        if (app.StartsWith("tuck:"))
        {
            var tt = tabs.FirstOrDefault(x => x.App == app[5..]);
            if (tt != null && tt != cur) { tt.Chip.Visible = false; tt.View.Visible = false; LayoutTabs(); }
            musicBack = null;
            return;
        }
        if (app.StartsWith("close:")) { var c = tabs.FirstOrDefault(x => x.App == app[6..]); if (c != null) { c.App = ""; CloseTab(c); } return; }
        if (!Apps.ContainsKey(app)) return;
        var t = tabs.FirstOrDefault(x => x.App == app);
        if (t == null)
        {
            t = await NewTab(Apps[app].url, select: true, app: app);
            var homeT = tabs.FirstOrDefault(x => x.IsHome);              // app tabs sit right after Home
            if (homeT != null) tabBar.Controls.SetChildIndex(t.Chip, tabBar.Controls.GetChildIndex(homeT.Chip) + 1);
        }
        else Select(t);
        LayoutTabs();
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        Activate();
    }
    void Tuck(Tab t)
    {
        if (snap != null && snapTabs.Contains(t)) SnapRemove(t);
        t.Chip.Visible = false;
        if (t == cur) Select(tabs.FirstOrDefault(x => x.IsHome) ?? tabs.FirstOrDefault(x => x != t));
        t.Chip.Visible = false;                                         // Select shows the one it picks, not this one
        t.View.Visible = false;
        LayoutTabs();
    }

    // ---------------------------------------------------------------- 🧭 the Home page toolbar under the tabs (like bookmarks)
    string popKey = "";
    Tab HomeTab => tabs.FirstOrDefault(x => x.IsHome);
    void HomeJs(string js) { try { HomeTab?.View.CoreWebView2?.ExecuteScriptAsync(js); } catch { } }
    void OnBar(string json)
    {
        try
        {
            using var d = JsonDocument.Parse(json);
            barInfo = d.RootElement.GetProperty("info").GetString() ?? "";
            var seen = new HashSet<string>(); bool madeNew = false;
            foreach (var b in d.RootElement.GetProperty("btns").EnumerateArray())
            {
                string id = b.GetProperty("id").GetString() ?? "", pop = b.GetProperty("pop").GetString() ?? "";
                string key = pop != "" ? pop : id; if (key == "") continue;
                seen.Add(key);
                if (!bookMap.TryGetValue(key, out var btn))
                {
                    btn = new Button { FlatStyle = FlatStyle.Flat, Font = new Font("Segoe UI Emoji", 11f), TabStop = false, Cursor = Cursors.Hand,
                        TextAlign = ContentAlignment.MiddleCenter, Padding = new Padding(0), Size = new Size(P(36), P(28)), Margin = new Padding(P(1), 0, P(1), 0) };
                    btn.FlatAppearance.BorderSize = 0; btn.FlatAppearance.MouseOverBackColor = Theme.TabOn;
                    string k = key, bid = id;
                    btn.MouseEnter += (s, e) => { hoverKey = k; hoverAt = DateTime.Now; };
                    btn.MouseLeave += (s, e) => { if (hoverKey == k) hoverKey = ""; };
                    btn.Click += (s, e) => { if (barDragged) { barDragged = false; return; } BarClick(k, bid); };
                    // click + drag a button to a new spot - it remembers
                    btn.MouseDown += (s, e) => { if (e.Button == MouseButtons.Left) { barDragBtn = btn; barDownAt = Control.MousePosition; barDragged = false; } };
                    btn.MouseMove += (s, e) =>
                    {
                        if (barDragBtn != btn || e.Button != MouseButtons.Left) return;
                        if (!barDragged && Math.Abs(Control.MousePosition.X - barDownAt.X) > P(10)) { barDragged = true; hoverKey = ""; btn.BackColor = Theme.Accent; }
                        if (barDragged) { Cursor.Current = Cursors.SizeWE; BarDropAt(btn, false); }
                    };
                    btn.MouseUp += (s, e) => { if (barDragBtn == btn && barDragged) { BarDropAt(btn, true); BeginInvoke(new Action(() => barDragged = false)); } barDragBtn = null; };
                    bookMap[key] = btn; bookBtns.Controls.Add(btn);
                    madeNew = true;
                    if (pop != "") bookPop[key] = pop;
                }
                btn.Text = b.GetProperty("t").GetString();
                tip.SetToolTip(btn, b.GetProperty("tip").GetString());
                if (pop != "" && b.GetProperty("on").GetBoolean()) { popPinned = true; popKey = key; }
                else if (popKey == key && popPinned && !b.GetProperty("on").GetBoolean()) popPinned = false;
            }
            foreach (var gone in bookMap.Keys.Where(x => !seen.Contains(x)).ToList()) { bookBtns.Controls.Remove(bookMap[gone]); bookMap.Remove(gone); bookPop.Remove(gone); }
            if (madeNew) ApplyBarOrder();                                   // your saved order
            PaintTabs();
        }
        catch { }
    }
    readonly ToolTip tip = new() { InitialDelay = 900 };
    Button barDragBtn; Point barDownAt; bool barDragged;
    void BarDropAt(Button btn, bool done)
    {
        var p = bookBtns.PointToClient(Control.MousePosition);
        int idx = 0;
        foreach (Control c in bookBtns.Controls) { if (c != btn && p.X > c.Left + c.Width / 2) idx++; }
        idx = Math.Max(0, Math.Min(idx, bookBtns.Controls.Count - 1));
        if (bookBtns.Controls.GetChildIndex(btn) != idx) bookBtns.Controls.SetChildIndex(btn, idx);
        if (!done) return;
        Cursor.Current = Cursors.Default;
        S.BarOrder = bookBtns.Controls.Cast<Control>().Select(c => bookMap.FirstOrDefault(x => x.Value == c).Key).Where(k => k != null).ToList();
        S.Save();
        PaintTabs();
        foreach (var f in All) if (f != this) f.ApplyBarOrder();
    }
    public void ApplyBarOrder()
    {
        for (int i = 0; i < S.BarOrder.Count; i++)
            if (bookMap.TryGetValue(S.BarOrder[i], out var b)) bookBtns.Controls.SetChildIndex(b, Math.Min(i, bookBtns.Controls.Count - 1));
    }
    void BarClick(string key, string id)
    {
        hoverKey = "";
        if (id == "brainBtn") { HomeJs("f35NativeClick('brainBtn')"); return; }       // 🧠 click = on/off (hover = options)
        if (bookPop.ContainsKey(key)) { popPinned = !(popPinned && popKey == key); popKey = popPinned ? key : ""; HomeJs($"f35NativePop('{key}', true)"); return; }   // click = keep it open (click again = close)
        if (id == "browserBtn") { _ = NewTab(""); return; }
        if (id == "discordBtn") { _ = ShowApp("discord"); return; }
        if (id == "dcOvlBtn") { ToggleOverlay(); return; }
        if (id != "voiceBtn" && id != "sfxBtn" && id != "sleepBtn" && HomeTab != null) Select(HomeTab);   // chat, store, search, files open on the Home page
        HomeJs($"f35NativeClick('{id}')");
    }
    void BarTick(Point cp)
    {
        if (!bookBar.Visible) return;
        bookInfo.Text = (barInfo + "   " + Ram()).Trim();
        // hover a toolbar button for a second = quick look (not so touchy when you're just going for a tab)
        if (hoverKey != "" && bookPop.ContainsKey(hoverKey) && (DateTime.Now - hoverAt).TotalMilliseconds > 900 && !(popPinned) && popKey != hoverKey)
        { popKey = hoverKey; HomeJs($"f35NativePop('{hoverKey}', false)"); }
        if (popRect == Rectangle.Empty) { popAwayAt = DateTime.MaxValue; return; }
        var barR = bookBar.RectangleToScreen(bookBar.ClientRectangle); barR.Inflate(0, P(6));
        bool over = barR.Contains(cp) || PopScreen().Contains(cp);
        if (!popPinned)
        {   // a quick look closes once you've moved off it for a bit
            if (over) popAwayAt = DateTime.MaxValue;
            else if (popAwayAt == DateTime.MaxValue) popAwayAt = DateTime.Now;
            else if ((DateTime.Now - popAwayAt).TotalMilliseconds > 500) { popAwayAt = DateTime.MaxValue; popKey = ""; HomeJs("f35NativePop('', false)"); }
        }
        else if (cur != HomeTab && Control.MouseButtons == MouseButtons.Left && !over && ContainsFocus)
        { popPinned = false; popKey = ""; HomeJs("f35NativePop('', true)"); }   // kept open: click somewhere else to close it
    }
    Rectangle PopScreen()
    {
        var p = HomeTab; if (p == null || popRect == Rectangle.Empty) return Rectangle.Empty;
        var r = p.View.RectangleToScreen(popRect); r.Inflate(P(6), P(6)); return r;
    }
    void OnPop(string r)
    {
        var p = HomeTab; if (p == null) return;
        if (r == "none")
        {
            popRect = Rectangle.Empty; if (!popPinned) popKey = "";
            p.View.Region = null; if (cur != p && !(snap != null && snapTabs.Contains(p))) p.View.Visible = false;
            PaintTabs(); return;
        }
        var a = r.Split(',').Select(int.Parse).ToArray();
        popRect = new Rectangle(a[0], a[1], a[2], a[3]);
        if (snap != null && snapTabs.Contains(p)) { PaintTabs(); return; }
        if (cur != p)
        {   // on a browser tab: show just the pop-up part of the Home page over it
            // rounded like the panel, so no black corners poke out
            var gp = new System.Drawing.Drawing2D.GraphicsPath(); int rd = P(14) * 2, x = popRect.X, y = popRect.Y, w = popRect.Width + 1, h = popRect.Height + 1;
            gp.AddArc(x, y, rd, rd, 180, 90); gp.AddArc(x + w - rd, y, rd, rd, 270, 90); gp.AddArc(x + w - rd, y + h - rd, rd, rd, 0, 90); gp.AddArc(x, y + h - rd, rd, rd, 90, 90); gp.CloseFigure();
            p.View.Region = new Region(gp);
            p.View.Visible = true; p.View.BringToFront();
        }
        PaintTabs();
    }

    // ---------------------------------------------------------------- 🎙 Discord overlay: a little card that floats on top of everything
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern bool RegisterHotKey(IntPtr h, int id, uint mods, uint vk);
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern bool UnregisterHotKey(IntPtr h, int id);
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern int GetWindowLong(IntPtr h, int i);
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern int SetWindowLong(IntPtr h, int i, int v);

    // ---------------------------------------------------------------- 🎙 Discord overlay, 2025 style: separate widgets + an action bar
    static readonly string[] WKinds = { "voice", "chat", "notes", "bar" };
    readonly Dictionary<string, WidgetForm> wids = new();
    readonly Dictionary<string, bool> wEmpty = new();
    Form ovlBack; bool ovlUnlocked;
    System.Windows.Forms.Timer ovlSaveT;
    OvlCfg Cfg(string kind)
    {
        if (!S.Ovl.TryGetValue(kind, out var c)) { c = new OvlCfg { Pin = kind == "voice" || kind == "notes", Op = kind == "chat" ? .85 : .92 }; S.Ovl[kind] = c; }
        return c;
    }
    void SaveOvlSoon()
    {
        ovlSaveT ??= new System.Windows.Forms.Timer { Interval = 800 };
        ovlSaveT.Stop(); ovlSaveT.Tick -= OvlSaveTick; ovlSaveT.Tick += OvlSaveTick; ovlSaveT.Start();
    }
    void OvlSaveTick(object s, EventArgs e) { ovlSaveT.Stop(); S.Save(); }
    WidgetForm EnsureWidget(string kind)
    {
        if (wids.TryGetValue(kind, out var have) && !have.IsDisposed) return have;
        var c = Cfg(kind);
        var wa = Screen.FromControl(this).WorkingArea; int m = P(20);
        var size = kind switch { "voice" => new Size(P(280), P(230)), "chat" => new Size(P(380), P(430)), "notes" => new Size(P(340), P(300)), _ => new Size(P(640), P(64)) };
        var pos = kind switch
        {
            "voice" => new Point(wa.Left + m, wa.Top + m + P(140)),
            "chat" => new Point(wa.Left + m, wa.Top + wa.Height / 2 - P(80)),
            "notes" => new Point(wa.Right - size.Width - m, wa.Top + m + P(140)),
            _ => new Point(wa.Left + (wa.Width - size.Width) / 2, wa.Top + m)
        };
        if (c.X >= 0)
        {   // right where you left it (pulled back on screen if a monitor's gone)
            pos = new Point(c.X, c.Y); if (kind != "bar" && c.W > 50) size = new Size(c.W, c.H);
            var vis = Screen.AllScreens.Any(sc => sc.WorkingArea.IntersectsWith(new Rectangle(pos, new Size(P(60), P(40)))));
            if (!vis) pos = new Point(wa.Left + m, wa.Top + m);
        }
        var f = new WidgetForm { Kind = kind, FormBorderStyle = FormBorderStyle.None, TopMost = true, ShowInTaskbar = false, StartPosition = FormStartPosition.Manual,
                                 BackColor = Theme.Bg, Bounds = new Rectangle(pos, size), Text = "F35 overlay " + kind };
        var v = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = Theme.Bg };
        f.V = v; f.Controls.Add(v);
        void Round() { using var gp = new System.Drawing.Drawing2D.GraphicsPath(); int r = P(12) * 2, w = f.Width, h = f.Height;
            gp.AddArc(0, 0, r, r, 180, 90); gp.AddArc(w - r, 0, r, r, 270, 90); gp.AddArc(w - r, h - r, r, r, 0, 90); gp.AddArc(0, h - r, r, r, 90, 90); gp.CloseFigure(); f.Region = new Region(gp); }
        f.Resize += (s, e) => { Round(); if (kind != "bar" && f.Visible) { c.W = f.Width; c.H = f.Height; SaveOvlSoon(); } };
        f.Move += (s, e) => { if (f.Visible) { c.X = f.Left; c.Y = f.Top; SaveOvlSoon(); } };
        f.ResizeEnd += (s, e) => { c.X = f.Left; c.Y = f.Top; if (kind != "bar") { c.W = f.Width; c.H = f.Height; } S.Save(); };   // let go = saved right now
        f.Activated += (s, e) => FullHotkey(true);
        f.Deactivate += (s, e) => BeginInvoke(new Action(() => { if (Form.ActiveForm == null) FullHotkey(false); }));
        Round();
        f.Shown += async (s, e) =>
        {
            await v.EnsureCoreWebView2Async(env);
            v.CoreWebView2.Settings.AreDefaultContextMenusEnabled = false;
            v.CoreWebView2.WebMessageReceived += (s2, e2) => { string msg = ""; try { msg = e2.TryGetWebMessageAsString(); } catch { } WidgetMsg(kind, f, msg); };
            v.CoreWebView2.NavigationCompleted += (s2, e2) => TellWidget(kind);
            v.CoreWebView2.Navigate(F35 + "/widget/dc_overlay.html?w=" + kind);
        };
        wids[kind] = f;
        return f;
    }
    void TellWidget(string kind)
    {
        if (!wids.TryGetValue(kind, out var f) || f.IsDisposed || f.V?.CoreWebView2 == null) return;
        var c = Cfg(kind);
        var on = string.Join(",", WKinds.Select(x => $"\"{x}\":{(Cfg(x).On ? "true" : "false")}"));
        _ = f.V.CoreWebView2.ExecuteScriptAsync($"window.setMode && setMode({(ovlUnlocked ? "true" : "false")}, {(c.Pin ? "true" : "false")}, {(int)(c.Op * 100)}, {{{on}}})");
    }
    void ClickThrough(Form f, bool on)
    {
        if (!f.IsHandleCreated) return;
        int ex = GetWindowLong(f.Handle, -20);
        ex = on ? ex | 0x20 | 0x80000 : ex & ~0x20;
        SetWindowLong(f.Handle, -20, ex);
    }
    void ApplyOvl()
    {
        if (!isMain) return;
        if (ovlUnlocked)
        {   // unlocked: the screen dims a bit and every widget you've got turned on shows, ready to move
            if (ovlBack == null || ovlBack.IsDisposed)
            {
                ovlBack = new Form { FormBorderStyle = FormBorderStyle.None, TopMost = true, ShowInTaskbar = false, StartPosition = FormStartPosition.Manual, BackColor = Color.Black, Opacity = .38 };
                ovlBack.Click += (s, e) => { ovlUnlocked = false; ApplyOvl(); };
            }
            ovlBack.Bounds = Screen.FromControl(this).Bounds;
            if (!ovlBack.Visible) ovlBack.Show();
        }
        else ovlBack?.Hide();
        foreach (var kind in WKinds)
        {
            var c = Cfg(kind);
            bool show = kind == "bar" ? ovlUnlocked : c.On && (ovlUnlocked || (c.Pin && !(wEmpty.TryGetValue(kind, out var em) && em)));
            if (!show) { if (wids.TryGetValue(kind, out var hf) && !hf.IsDisposed) hf.Hide(); TellWidget(kind); continue; }
            var f = EnsureWidget(kind);
            f.Unlocked = ovlUnlocked;
            f.Padding = ovlUnlocked && kind != "bar" ? new Padding(P(5)) : Padding.Empty;
            f.Opacity = ovlUnlocked ? 1.0 : c.Op;
            if (!f.Visible) f.Show();
            ClickThrough(f, !ovlUnlocked);                                   // locked = your clicks go right through to what's under it
            SetWindowPos(f.Handle, (IntPtr)(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010);   // stay above the dim
            TellWidget(kind);
        }
        if (ovlUnlocked && wids.TryGetValue("bar", out var bar)) bar.Activate();
    }
    public void ToggleOverlay() { ovlUnlocked = !ovlUnlocked; ApplyOvl(); S.Save(); }
    void WidgetMsg(string kind, WidgetForm f, string m)
    {
        var c = Cfg(kind);
        if (m == "w:drag" && ovlUnlocked) { ReleaseCapture(); SendMessage(f.Handle, 0xA1, (IntPtr)2, IntPtr.Zero); }
        else if (m == "w:pin") { c.Pin = !c.Pin; c.X = f.Left; c.Y = f.Top; S.Save(); TellWidget(kind); }
        else if (m.StartsWith("w:size:"))
        {   // the action bar sizes itself to fit all its buttons (no more cut-off 🔒)
            var p = m[7..].Split(':');
            if (p.Length == 2 && int.TryParse(p[0], out int cw) && int.TryParse(p[1], out int ch))
            {
                int w = (int)Math.Ceiling(cw * k) + 2, h = (int)Math.Ceiling(ch * k) + 2;
                var wa2 = Screen.FromControl(f).WorkingArea;
                w = Math.Min(w, wa2.Width - P(20));
                if (Math.Abs(f.Width - w) > 2 || Math.Abs(f.Height - h) > 2)
                {
                    bool fresh = Cfg(kind).X < 0;
                    f.Size = new Size(w, h);
                    if (fresh) f.Left = wa2.Left + (wa2.Width - w) / 2;
                }
            }
        }
        else if (m.StartsWith("w:op:") && int.TryParse(m[5..], out int op)) { c.Op = Math.Clamp(op, 20, 100) / 100.0; SaveOvlSoon(); }
        else if (m == "w:hide") { c.On = false; S.Save(); ApplyOvl(); }
        else if (m.StartsWith("w:toggle:")) { var o = Cfg(m[9..]); o.On = !o.On; S.Save(); ApplyOvl(); }
        else if (m == "w:lock") { ovlUnlocked = false; ApplyOvl(); }
        else if (m == "w:full") { ovlUnlocked = false; ApplyOvl(); ToggleFull(); }
        else if (m == "w:discord") { ovlUnlocked = false; ApplyOvl(); _ = ShowApp("discord"); }
        else if (m.StartsWith("w:empty:"))
        {   // a pinned widget with nothing to show (not in voice, no new pings) tucks itself away while locked
            bool e = m.EndsWith("1");
            if (wEmpty.TryGetValue(kind, out var was) && was == e) return;
            wEmpty[kind] = e;
            if (!ovlUnlocked) ApplyOvl();
        }
    }

    // ⛶ full overlay (Shift+` like Discord in a game): screen dims, the REAL Discord pops up big in the middle
    Form fullBack, fullPanel; Tab fullTab;
    bool hotOn;
    void FullHotkey(bool on)
    {   // Shift+` only belongs to us while FreedomOS (or its overlay) is the app you're in - typing ~ elsewhere still works
        if (!isMain || on == hotOn || !IsHandleCreated) return;
        hotOn = on;
        if (on) RegisterHotKey(Handle, 36, 0x0004 | 0x4000, 0xC0); else UnregisterHotKey(Handle, 36);
    }
    public async void ToggleFull()
    {
        if (fullBack != null && !fullBack.IsDisposed) { CloseFull(); return; }
        var dt = tabs.FirstOrDefault(x => x.App == "discord");
        if (dt == null) { await ShowApp("discord-bg"); dt = tabs.FirstOrDefault(x => x.App == "discord"); }
        if (dt == null) return;
        if (snap != null && snapTabs.Contains(dt)) SnapRemove(dt);
        var scr = Screen.FromControl(this).Bounds;
        fullBack = new Form { FormBorderStyle = FormBorderStyle.None, TopMost = true, ShowInTaskbar = false, StartPosition = FormStartPosition.Manual,
                              Bounds = scr, BackColor = Color.Black, Opacity = .62 };
        fullBack.Click += (s, e) => CloseFull();
        fullPanel = new Form { FormBorderStyle = FormBorderStyle.None, TopMost = true, ShowInTaskbar = false, StartPosition = FormStartPosition.Manual, BackColor = Theme.Bg };
        int w = (int)(scr.Width * (scr.Width > scr.Height * 2.2 ? .5 : .78)), h = (int)(scr.Height * .82);
        fullPanel.Bounds = new Rectangle(scr.X + (scr.Width - w) / 2, scr.Y + (scr.Height - h) / 2, w, h);
        var bar = new Panel { Dock = DockStyle.Top, Height = P(32), BackColor = Theme.Bar };
        var lbl = new Label { Text = "👾 Discord   ·   click outside or ✕ to close", ForeColor = Theme.Dim, Dock = DockStyle.Fill,
                              TextAlign = ContentAlignment.MiddleLeft, Padding = new Padding(P(10), 0, 0, 0), Font = new Font("Segoe UI Emoji", 9.5f) };
        var x = new Label { Text = "✕", ForeColor = Theme.Text, Dock = DockStyle.Right, Width = P(40), TextAlign = ContentAlignment.MiddleCenter, Cursor = Cursors.Hand };
        x.Click += (s, e) => CloseFull();
        bar.Controls.Add(lbl); bar.Controls.Add(x);
        fullTab = dt;
        content.Controls.Remove(dt.View);
        dt.View.Dock = DockStyle.Fill; dt.View.Visible = true;
        fullPanel.Controls.Add(dt.View); fullPanel.Controls.Add(bar);
        using (var gp = new System.Drawing.Drawing2D.GraphicsPath()) { int r = P(16) * 2;
            gp.AddArc(0, 0, r, r, 180, 90); gp.AddArc(w - r, 0, r, r, 270, 90); gp.AddArc(w - r, h - r, r, r, 0, 90); gp.AddArc(0, h - r, r, r, 90, 90); gp.CloseFigure();
            fullPanel.Region = new Region(gp); }
        fullPanel.Activated += (s, e) => FullHotkey(true);
        fullPanel.Deactivate += (s, e) => BeginInvoke(new Action(() => { if (Form.ActiveForm == null) FullHotkey(false); }));
        fullBack.Show(); fullPanel.Show(fullBack);
        fullPanel.Activate(); dt.View.Focus();
    }
    void CloseFull()
    {
        var dt = fullTab; fullTab = null;
        if (dt != null && fullPanel != null && !fullPanel.IsDisposed)
        {
            fullPanel.Controls.Remove(dt.View);
            content.Controls.Add(dt.View);
            dt.View.Dock = DockStyle.Fill; dt.View.Visible = dt == cur;
            if (dt == cur) dt.View.BringToFront();
        }
        try { fullPanel?.Close(); fullBack?.Close(); } catch { }
        fullPanel = fullBack = null;
        if (snap != null) SnapLayout();
    }
    // ---------------------------------------------------------------- ⊞ snap tabs (Windows 11 layouts, inside FreedomOS)
    static readonly (string name, RectangleF[] zones)[] Layouts =
    {
        ("Halves",          new[] { new RectangleF(0, 0, .5f, 1), new RectangleF(.5f, 0, .5f, 1) }),
        ("Big left",        new[] { new RectangleF(0, 0, .667f, 1), new RectangleF(.667f, 0, .333f, 1) }),
        ("Big right",       new[] { new RectangleF(0, 0, .333f, 1), new RectangleF(.333f, 0, .667f, 1) }),
        ("Thirds",          new[] { new RectangleF(0, 0, .3333f, 1), new RectangleF(.3333f, 0, .3334f, 1), new RectangleF(.6667f, 0, .3333f, 1) }),
        ("Big + 2 stacked", new[] { new RectangleF(0, 0, .5f, 1), new RectangleF(.5f, 0, .5f, .5f), new RectangleF(.5f, .5f, .5f, .5f) }),
        ("Quadrants",       new[] { new RectangleF(0, 0, .5f, .5f), new RectangleF(.5f, 0, .5f, .5f), new RectangleF(0, .5f, .5f, .5f), new RectangleF(.5f, .5f, .5f, .5f) }),
    };
    RectangleF[] snap; Tab[] snapTabs = Array.Empty<Tab>();
    async void SnapTo(int layout, int zone, Tab t)
    {
        var L = Layouts[layout].zones;
        var old = snapTabs.Where(x => x != null && x != t && tabs.Contains(x)).ToList();
        var pool = old.Concat(new[] { cur }).Concat(tabs.Where(x => x.Chip.Visible).OrderByDescending(x => x == cur))
                      .Where(x => x != null && x != t).Distinct().ToList();
        snap = L; snapTabs = new Tab[L.Length];
        snapTabs[Math.Min(zone, L.Length - 1)] = t;
        for (int i = 0; i < L.Length; i++) if (snapTabs[i] == null && pool.Count > 0) { snapTabs[i] = pool[0]; pool.RemoveAt(0); }
        var mine = snapTabs;
        for (int i = 0; i < L.Length; i++)
            if (mine[i] == null) { var nt = await NewTab("", select: false); if (snap == L && snapTabs == mine) mine[i] = nt; }   // empty spot = a fresh tab
        if (snap != L || snapTabs != mine) return;
        foreach (var x in snapTabs) if (x != null) x.Chip.Visible = true;
        cur = t; SnapLayout(); AfterFocus(t);
    }
    void SnapLayout()
    {
        if (snap == null) return;
        var c = content.ClientRectangle; int g = 0;                      // edgeless: panes butt right up against each other
        for (int i = 0; i < snap.Length; i++)
        {   // empty pane? the next tab that isn't up yet fills it
            if (snapTabs[i] == null || !tabs.Contains(snapTabs[i]))
                snapTabs[i] = tabs.FirstOrDefault(x => x.Chip.Visible && !snapTabs.Contains(x));
        }
        foreach (var x in tabs)
        {
            int i = Array.IndexOf(snapTabs, x);
            if (i < 0) { if (!(x.IsHome && popRect != Rectangle.Empty && cur != x)) { x.View.Visible = false; } x.View.Dock = DockStyle.Fill; continue; }
            if (x.IsHome) x.View.Region = null;
            var z = snap[i];
            x.View.Dock = DockStyle.None;
            int L = c.X + (int)Math.Round(z.X * c.Width), T = c.Y + (int)Math.Round(z.Y * c.Height);
            int R = c.X + (int)Math.Round((z.X + z.Width) * c.Width), B = c.Y + (int)Math.Round((z.Y + z.Height) * c.Height);
            x.View.Bounds = new Rectangle(L + g, T + g, R - L - g * 2, B - T - g * 2);
            x.View.Visible = true;
        }
        content.BackColor = Theme.Bg;
    }
    void SnapRemove(Tab t)
    {
        int i = Array.IndexOf(snapTabs, t); if (i >= 0) snapTabs[i] = null;
        var left = tabs.Where(x => x != t && x.Chip.Visible && !snapTabs.Contains(x)).ToList();
        if (i >= 0 && left.Count > 0) snapTabs[i] = left[0];
        if (snapTabs.Count(x => x != null && x != t) < 2) SnapOff();
        else SnapLayout();
    }
    void SnapOff()
    {
        snap = null; snapTabs = Array.Empty<Tab>();
        foreach (var x in tabs) { x.View.Dock = DockStyle.Fill; x.View.Visible = x == cur; }
        content.BackColor = Theme.Bg;
        cur?.View.BringToFront(); PaintTabs();
    }
    void SnapMenu(Tab t, Control at, Point p)
    {
        var m = new ContextMenuStrip { BackColor = Theme.Bar, ForeColor = Theme.Text, ShowImageMargin = true, Font = new Font("Segoe UI", 10f) };
        var root = new ToolStripMenuItem("⊞ Snap this tab") { ForeColor = Theme.Text };
        for (int li = 0; li < Layouts.Length; li++)
        {
            var L = Layouts[li]; var sub = new ToolStripMenuItem(L.name) { ForeColor = Theme.Text, Image = LayoutIcon(li, -1, 30) };
            for (int z = 0; z < L.zones.Length; z++)
            {
                int lz = li, zz = z;
                sub.DropDownItems.Add(new ToolStripMenuItem(L.zones.Length == 2 ? (z == 0 ? "Left" : "Right") : "Spot " + (z + 1), LayoutIcon(li, z, 30), (s, e) => SnapTo(lz, zz, t)) { ForeColor = Theme.Text });
            }
            ((ToolStripDropDownMenu)sub.DropDown).BackColor = Theme.Bar;
            root.DropDownItems.Add(sub);
        }
        ((ToolStripDropDownMenu)root.DropDown).BackColor = Theme.Bar;
        m.Items.Add(root);
        if (snap != null) m.Items.Add("▣ Unsnap - back to one tab", null, (s, e) => { SnapOff(); Select(t); });
        if (t.App == "" && !t.IsHome) m.Items.Add("✕ Close tab", null, (s, e) => CloseTab(t));
        m.Show(at, p);
    }
    Bitmap LayoutIcon(int li, int hi, int w)
    {   // a tiny picture of the layout (the spot you'd go in lit up)
        int sz = P(w), h = sz * 2 / 3; var b = new Bitmap(sz, h);
        using var gr = Graphics.FromImage(b); gr.Clear(Color.Transparent);
        var zs = Layouts[li].zones;
        for (int i = 0; i < zs.Length; i++)
        {
            var r = new Rectangle((int)(zs[i].X * (sz - 2)) + 1, (int)(zs[i].Y * (h - 2)) + 1, (int)(zs[i].Width * (sz - 2)) - 2, (int)(zs[i].Height * (h - 2)) - 2);
            using var br = new SolidBrush(i == hi ? Theme.Accent : Mix(Theme.Text, Theme.Bg, .55f)); gr.FillRectangle(br, r);
        }
        return b;
    }
    // drag a tab up to the top of the page = the Windows 11 snap bar drops down
    Panel snapBar; int sbLayout = -1, sbZone = -1; Rectangle[][] sbRects;
    void SnapBarTrack(Point m)
    {
        if (!isMain && !true) return;
        int under = isMain ? Math.Max(0, HudHeight() + hudY) : 0;            // below the tabs + toolbar
        var top = content.RectangleToScreen(new Rectangle(0, 0, content.Width, under + P(110)));
        bool near = top.Contains(m) || (snapBar != null && snapBar.Visible && snapBar.RectangleToScreen(snapBar.ClientRectangle).Contains(m));
        if (!near) { if (snapBar != null) snapBar.Visible = false; sbLayout = sbZone = -1; return; }
        if (snapBar == null)
        {
            snapBar = new Panel { BackColor = Theme.Bar, BorderStyle = BorderStyle.FixedSingle };
            typeof(Panel).GetProperty("DoubleBuffered", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)?.SetValue(snapBar, true);
            snapBar.Paint += SnapBarPaint;
            content.Controls.Add(snapBar);
        }
        int cw = P(96), ch = P(60), pad = P(10);
        int W = Layouts.Length * (cw + pad) + pad, H = ch + pad * 2;
        snapBar.SetBounds((content.Width - W) / 2, under + P(8), W, H);
        sbRects = new Rectangle[Layouts.Length][];
        for (int li = 0; li < Layouts.Length; li++)
        {
            var zs = Layouts[li].zones; sbRects[li] = new Rectangle[zs.Length];
            int x0 = pad + li * (cw + pad), y0 = pad;
            for (int z = 0; z < zs.Length; z++)
                sbRects[li][z] = new Rectangle(x0 + (int)(zs[z].X * cw) + 2, y0 + (int)(zs[z].Y * ch) + 2, (int)(zs[z].Width * cw) - 4, (int)(zs[z].Height * ch) - 4);
        }
        var lp = snapBar.PointToClient(m); sbLayout = sbZone = -1;
        for (int li = 0; li < sbRects.Length; li++) for (int z = 0; z < sbRects[li].Length; z++) if (sbRects[li][z].Contains(lp)) { sbLayout = li; sbZone = z; }
        snapBar.Visible = true; snapBar.BringToFront(); snapBar.Invalidate();
    }
    void SnapBarPaint(object s, PaintEventArgs e)
    {
        if (sbRects == null) return;
        e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        for (int li = 0; li < sbRects.Length; li++)
            for (int z = 0; z < sbRects[li].Length; z++)
            {
                bool on = li == sbLayout && z == sbZone;
                using var br = new SolidBrush(on ? Theme.Accent : Mix(Theme.Text, Theme.Bar, .7f)); e.Graphics.FillRectangle(br, sbRects[li][z]);
            }
    }
    bool SnapBarDrop(Tab t, Point m)
    {
        bool hit = snapBar != null && snapBar.Visible && sbLayout >= 0 && sbZone >= 0;
        int li = sbLayout, z = sbZone;
        if (snapBar != null) snapBar.Visible = false;
        sbLayout = sbZone = -1;
        if (!hit || t.IsHome) return false;
        SnapTo(li, z, t);
        return true;
    }

    // ---------------------------------------------------------------- 🖥 desktop mode
    [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
    struct WINDOWPOS { public IntPtr hwnd, after; public int x, y, cx, cy; public uint flags; }
    void EnterFloor()
    {
        floor = true; inMax = true;
        WindowState = FormWindowState.Normal;
        FormBorderStyle = FormBorderStyle.None;
        inMax = false;
        ReFloor();
        winBtns.Visible = false; LayoutTabs();
    }
    void OnDisplayChanged(object s, EventArgs e)
    {
        if (IsDisposed || !IsHandleCreated) return;
        Action fit = () => { if (IsDisposed) return; SlateCheck(); if (floor) ReFloor(); else if (WindowState == FormWindowState.Maximized) { FitMax(); WindowState = FormWindowState.Normal; WindowState = FormWindowState.Maximized; } if (snap != null) SnapLayout(); HudLayout(); };
        try
        {
            BeginInvoke(new Action(() =>
            {
                fit();
                var t = new System.Windows.Forms.Timer { Interval = 900 };       // Windows finishes turning the screen a beat later - check once more
                t.Tick += (s2, e2) => { t.Dispose(); fit(); };
                t.Start();
            }));
        }
        catch { }
    }
    void ReFloor()
    {   // full screen minus ONE pixel at the bottom: Windows then lets your auto-hide taskbar pop up over us
        var b = Screen.FromHandle(Handle).Bounds;
        Bounds = new Rectangle(b.X, b.Y, b.Width, b.Height - 1);
        Padding = new Padding(0);
        SetWindowPos(Handle, (IntPtr)1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010);          // HWND_BOTTOM, no move/size/activate
        if (skirt == null || skirt.IsDisposed) skirt = new Skirt();                      // black strip fills that 1px so no Windows wallpaper peeks out
        skirt.Bounds = new Rectangle(b.X, b.Bottom - 1, b.Width, 1);
        if (!skirt.Visible) skirt.Show();
        SetWindowPos(skirt.Handle, (IntPtr)1, b.X, b.Bottom - 1, b.Width, 1, 0x0010);
        HudLayout();
    }
    Skirt skirt;
    void ExitFloor()
    {
        floor = false;
        if (skirt != null && !skirt.IsDisposed) skirt.Hide();
        bMin.Visible = bMax.Visible = winBtns.Visible = true;
        FormBorderStyle = FormBorderStyle.Sizable;
        var wa = Screen.FromHandle(Handle).WorkingArea;
        Bounds = new Rectangle(wa.X + wa.Width / 8, wa.Y + wa.Height / 8, wa.Width * 3 / 4, wa.Height * 3 / 4);
        ShowHud();
    }
    public void ShowF35()
    {   // tray, show-desktop, Win+D: tuck everything else away and show FreedomOS
        if (!floor) { Activate(); return; }
        try { dynamic sh = Activator.CreateInstance(Type.GetTypeFromProgID("Shell.Application")); sh.MinimizeAll(); } catch { }
        var t = new System.Windows.Forms.Timer { Interval = 350 };
        t.Tick += (s, e) => { t.Dispose(); WindowState = FormWindowState.Normal; ReFloor(); Activate(); if (paused) Resume(); };
        t.Start();
    }
    bool CoveredByFullScreenApp()
    {
        try
        {
            var fg = GetForegroundWindow();
            if (fg == IntPtr.Zero || fg == Handle || !IsWindowVisible(fg)) return false;
            GetWindowThreadProcessId(fg, out uint pid);
            if (pid == (uint)Environment.ProcessId) return false;
            var sb = new StringBuilder(64); GetClassName(fg, sb, 64);
            var cls = sb.ToString();
            if (cls is "Progman" or "WorkerW" or "Shell_TrayWnd" or "Shell_SecondaryTrayWnd" or "Windows.UI.Core.CoreWindow") return false;
            GetWindowRect(fg, out var r);
            var b = Screen.FromHandle(Handle).Bounds;
            return r.L <= b.Left && r.T <= b.Top && r.R >= b.Right && r.B >= b.Bottom;
        }
        catch { return false; }
    }
    void Pause()
    {   // 🎮 game time: black screen, Home + wallpaper stop (they only run when they can be seen)
        paused = true;
        BackColor = Color.Black; content.Visible = false; hud.Visible = false; PlaceGrab();
    }
    void Resume()
    {
        paused = false;
        BackColor = Theme.Bar; content.Visible = true; hud.Visible = !fullScreen;
        ShowHud();
    }

    // ---------------------------------------------------------------- the HUD (tabs, toolbar, address bar) glides away like an auto-hide taskbar
    int HudHeight() => hud.Controls.Cast<Control>().Where(c => c.Visible).Sum(c => c.Height);
    void HudLayout()
    {
        int h = HudHeight();
        if (!isMain) { hud.Height = h; return; }
        bool hidden = hudTarget < 0;
        hud.SetBounds(0, hidden ? -h : hudY, ClientSize.Width, h);
        if (hidden) { hudY = hudTarget = -h; }
        hud.BringToFront();
        PlaceGrab();
        TellHud();
    }
    void PlaceGrab()
    {
        if (!isMain) return;
        bool show = false;                                           // no visible handle - touch uses the swipe-from-top gesture
        if (show) { grab.SetBounds(0, 0, ClientSize.Width, P(12)); grab.BringToFront(); }
        if (grab.Visible != show) grab.Visible = show;
        grab.Invalidate();
    }
    void ShowHud()
    {
        if (!isMain) return;
        if (grab.Visible) grab.Visible = false;
        hudTouch = DateTime.Now;
        if (hudTarget == 0 && hudY == 0) return;
        hudTarget = 0; hudAnim.Start();
    }
    void HideHud()
    {
        if (!isMain || hudTarget < 0) return;
        hudTarget = -HudHeight(); hudAnim.Start();
    }
    int lastTold = -1;
    void TellHud()
    {   // the Home page's pop-ups sit just under the HUD while it's down
        int css = (int)Math.Round(Math.Max(0, HudHeight() + hudY) / k);
        if (css == lastTold) return; lastTold = css;
        HomeJs($"document.documentElement.style.setProperty('--hudH','{css}px')");
    }
    void HudTick(Point cp)
    {
        if (!isMain || paused) return;
        var r = hud.RectangleToScreen(new Rectangle(0, 0, hud.Width, Math.Max(hud.Height + hudY, 0))); r.Inflate(0, P(6));
        bool atEdge = cp.Y <= Top + P(3) && cp.X >= Left && cp.X <= Right;
        bool busy = r.Contains(cp) || hud.ContainsFocus || popRect != Rectangle.Empty || tabs.Any(x => x.Dragging) || barDragged;
        if (atEdge) { ShowHud(); return; }
        if (busy && hudTarget == 0) { hudTouch = DateTime.Now; return; }
        if (hudTarget == 0 && (DateTime.Now - hudTouch).TotalSeconds > 1) HideHud();      // 1 sec of nothing = it glides away
    }

    // ---------------------------------------------------------------- no title bar: move, resize, make big
    void DragWindow()
    {
        if (floor || WindowState == FormWindowState.Maximized) return;      // desktop mode: FreedomOS stays put
        ReleaseCapture();
        SendMessage(Handle, 0xA1, (IntPtr)2, IntPtr.Zero);                // "you grabbed the title bar"
    }
    void FitMax()
    {   // big = the screen minus the taskbar; F11 / videos = the whole screen
        try
        {
            var scr = Screen.FromHandle(Handle);
            var r = scr.Bounds;                                         // big = TRUE full screen, taskbar and all (Esc brings it back)
            MaximizedBounds = new Rectangle(r.X - scr.Bounds.X, r.Y - scr.Bounds.Y, r.Width, r.Height);
        }
        catch { }
    }
    void ToggleMax()
    {
        if (floor) return;
        FitMax();
        WindowState = WindowState == FormWindowState.Maximized ? FormWindowState.Normal : FormWindowState.Maximized;
    }
    void EnterBigFull()
    {
        bigFull = full = true; FitMax();
        WindowState = FormWindowState.Normal; WindowState = FormWindowState.Maximized;
    }
    void ExitBigFull()
    {
        if (!bigFull) return;
        bigFull = full = false; FitMax();
        WindowState = FormWindowState.Normal;
    }
    protected override CreateParams CreateParams
    {
        get { var cp = base.CreateParams; cp.Style |= 0x20000 | 0x10000 | 0x80000; return cp; }   // taskbar click minimizes / restores
    }
    protected override void WndProc(ref Message m)
    {
        if (m.Msg == 0x83 && m.WParam != IntPtr.Zero && FormBorderStyle != FormBorderStyle.None) { m.Result = IntPtr.Zero; return; }   // no title bar / frame drawn - the window is all ours
        if (m.Msg == 0x86) { m.Result = (IntPtr)1; return; }
        if (m.Msg == 0x312 && (int)m.WParam == 35) { ToggleOverlay(); return; }        // Ctrl+Alt+D = Discord overlay
        if (m.Msg == 0x312 && (int)m.WParam == 36) { ToggleOverlay(); return; }        // Shift+` = unlock / lock the overlay (like Discord)
        if (m.Msg == 0x1A && m.LParam != IntPtr.Zero)
        {   // tablet mode on/off announces itself as "ConvertibleSlateMode"
            try { var what = System.Runtime.InteropServices.Marshal.PtrToStringUni(m.LParam); if (what == "ConvertibleSlateMode" || what == "UserInteractionMode") BeginInvoke(new Action(SlateCheck)); } catch { }
        }
        if (m.Msg == 0x46 && floor)
        {   // WM_WINDOWPOSCHANGING: whatever happens, FreedomOS stays UNDER your apps
            var wp = System.Runtime.InteropServices.Marshal.PtrToStructure<WINDOWPOS>(m.LParam);
            wp.after = (IntPtr)1; wp.flags &= ~0x0004u;
            System.Runtime.InteropServices.Marshal.StructureToPtr(wp, m.LParam, false);
        }                                                                        // don't repaint a frame on focus change
        base.WndProc(ref m);
        if (m.Msg == 0x84 && (int)m.Result == 1 && WindowState == FormWindowState.Normal)     // resize from the thin edge
        {
            var p = PointToClient(new Point((short)((long)m.LParam & 0xFFFF), (short)(((long)m.LParam >> 16) & 0xFFFF)));
            int g = P(6); bool L = p.X < g, R = p.X >= ClientSize.Width - g, T = p.Y < g, B = p.Y >= ClientSize.Height - g;
            m.Result = (IntPtr)(T && L ? 13 : T && R ? 14 : B && L ? 16 : B && R ? 17 : L ? 10 : R ? 11 : T ? 12 : B ? 15 : 1);
        }
    }

    // ---------------------------------------------------------------- full screen videos
    void SetFullScreen(bool on)
    {
        if (on == fullScreen) return;
        fullScreen = on;
        if (isMain) { if (on) HideHud(); }                                   // main window: top bar just tucks away - push the mouse to the top to get it back, even in a full-screen video
        else { topRow.Visible = !on; bookBar.Visible = false; hud.Visible = !on; }
        PlaceGrab();
        preFullState = on ? WindowState : preFullState;
        if (on) nav.Visible = favBar.Visible = false;
        else
        {
            nav.Visible = cur != null && !cur.IsHome && cur.App == "";
            favBar.Visible = nav.Visible && S.Bookmarks.Count > 0;
        }
        // already full screen (or desktop mode)? just hide/show the bars - no window jiggling
        if (floor || preFullState == FormWindowState.Maximized) return;
        FitMax();
        WindowState = on ? FormWindowState.Maximized : FormWindowState.Normal;
    }

    // ---------------------------------------------------------------- keyboard shortcuts
    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        switch (keyData)
        {
            case Keys.Control | Keys.T: ShowHud(); _ = NewTab(""); return true;
            case Keys.Control | Keys.W: if (cur != null && !cur.IsHome) CloseTab(cur); return true;
            case Keys.Control | Keys.L: case Keys.F6: ShowHud(); addr.Focus(); addr.SelectAll(); return true;
            case Keys.F5: case Keys.Control | Keys.R: cur?.View.CoreWebView2?.Reload(); return true;
            case Keys.Alt | Keys.Left: bBack.PerformClick(); return true;
            case Keys.Alt | Keys.Right: bFwd.PerformClick(); return true;
            case Keys.Control | Keys.Tab: if (tabs.Count > 1) Select(tabs[(tabs.IndexOf(cur) + 1) % tabs.Count]); return true;
            case Keys.Control | Keys.Shift | Keys.Tab: if (tabs.Count > 1) Select(tabs[(tabs.IndexOf(cur) - 1 + tabs.Count) % tabs.Count]); return true;
            case Keys.Control | Keys.D: ToggleBookmark(); return true;
            case Keys.Escape:
                if (fullScreen) { cur?.View.CoreWebView2?.ExecuteScriptAsync("document.exitFullscreen && document.exitFullscreen()"); return true; }
                if (!floor && WindowState == FormWindowState.Maximized) WindowState = FormWindowState.Normal;   // the page still gets the Esc too
                break;
            case Keys.F11:
                ToggleMax();
                return true;
        }
        return base.ProcessCmdKey(ref msg, keyData);
    }

    // ---------------------------------------------------------------- links from FreedomOS (or a second click) open as new tabs here
    void StartPipe()
    {
        var th = new Thread(() =>
        {
            while (true)
            {
                try
                {
                    using var srv = new NamedPipeServerStream("FreedomOS_pipe_" + Ports.App, PipeDirection.In, 1);
                    srv.WaitForConnection();
                    using var r = new StreamReader(srv, Encoding.UTF8);
                    var url = r.ReadToEnd();
                    BeginInvoke(new Action(() =>
                    {
                        if (url == "\u0002") { var p = tabs.FirstOrDefault(x => x.IsHome); if (p != null) Select(p); }
                        else if (url.StartsWith("\u0003")) { _ = ShowApp(url[1..]); if (url.Contains("close:") || url.Contains("music-bg") || url.Contains("tuck:")) return; }
                        else _ = NewTab(url == "\u0001" ? "" : url);
                        if (floor) { ShowF35(); return; }
                        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
                        Activate(); TopMost = true; TopMost = false;
                    }));
                }
                catch { Thread.Sleep(500); }
            }
        }) { IsBackground = true };
        th.Start();
    }
}

// 1px black strip under the desktop window: hides the Windows wallpaper but lets the auto-hide taskbar pop up
class Skirt : Form
{
    public Skirt()
    {
        FormBorderStyle = FormBorderStyle.None; ShowInTaskbar = false; BackColor = Color.Black;
        StartPosition = FormStartPosition.Manual; MinimumSize = new Size(1, 1); Size = new Size(1, 1);
    }
    protected override bool ShowWithoutActivation => true;
    protected override CreateParams CreateParams { get { var c = base.CreateParams; c.ExStyle |= 0x80 | 0x08000000; return c; } }   // tool window, never takes focus
    protected override void WndProc(ref Message m)
    {
        if (m.Msg == 0x46) { var wp = System.Runtime.InteropServices.Marshal.PtrToStructure<WP>(m.LParam); wp.after = (IntPtr)1; wp.flags &= ~0x0004u; System.Runtime.InteropServices.Marshal.StructureToPtr(wp, m.LParam, false); }   // always stay at the bottom
        if (m.Msg == 0x21) { m.Result = (IntPtr)3; return; }   // MA_NOACTIVATE
        base.WndProc(ref m);
    }
    [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
    struct WP { public IntPtr hwnd, after; public int x, y, cx, cy; public uint flags; }
}
