# FreedomOS - the full setup guide

This guide walks through **installing FreedomOS and every single feature**, one step at a time, in plain words.
Skip around with the list below.

1. [What you need](#1-what-you-need)
2. [Install](#2-install)
3. [The first start](#3-the-first-start)
4. [Getting around: the Home screen and the top bar](#4-getting-around-the-home-screen-and-the-top-bar)
5. [Desktop mode (FreedomOS behind all your apps)](#5-desktop-mode)
6. [👥 The crew and 🧠 the brain](#6-the-crew-and-the-brain)
7. [⚡ Quick Ask](#7-quick-ask)
8. [🧰 Jobs](#8-jobs)
9. [💬 Chats: Claude, Web, Ask](#9-chats-claude-web-ask)
10. [🌐 WiBro, the browser](#10-wibro-the-browser)
11. [⊞ Snap layouts (quadrant apps)](#11-snap-layouts-quadrant-apps)
12. [🎧 WiMix (YouTube Music)](#12-wimix-youtube-music)
13. [👾 Discord + 🎙 the overlay](#13-discord-and-the-overlay)
14. [🎨 Pixel Shop and Pixel Shop Lite](#14-pixel-shop-and-pixel-shop-lite)
15. [📁 Files on all your devices](#15-files-on-all-your-devices)
16. [🖼 Live wallpapers](#16-live-wallpapers)
17. [📱 Your phone + other PCs (Tailscale)](#17-your-phone-and-other-pcs)
18. [🤖 Claude desktop can boss your crew around](#18-claude-desktop-can-boss-your-crew-around)
19. [📝 The crew handbook and settings](#19-the-crew-handbook-and-settings)
20. [Tablet mode and touch screens](#20-tablet-mode-and-touch-screens)
21. [Updates](#21-updates)
22. [Keyboard shortcuts](#22-keyboard-shortcuts)
23. [Where everything lives](#23-where-everything-lives)
24. [Troubleshooting](#24-troubleshooting)
25. [Uninstall](#25-uninstall)

---

## 1. What you need

| | Minimum | Better |
|---|---|---|
| Windows | Windows 10 (version 1809 or newer) or Windows 11, 64-bit | Windows 11 |
| Memory (RAM) | 16 GB | 32 GB |
| Disk space | 15 GB free | 50 GB+ if you want the big brains and the Pixel Shop |
| Graphics | Any (Intel / AMD graphics work through Vulkan) | An NVIDIA card with 8 GB+ (12 GB+ for the big brain) |
| Internet | Needed for setup and the first brain download | - |

Optional extras (the setup asks about each one):
- **Tailscale** (free) - to use FreedomOS from your phone and your other PCs. See the [Tailscale guide](TAILSCALE.md).
- **Claude Code** - for the 💬 Claude chat window. Needs your own Claude account (Pro or Max plan).
- **The Claude desktop app** - FreedomOS plugs itself in so Claude can hand jobs to your crew.
- **Discord desktop app** - only needed for the "Playing FreedomOS" status. Discord itself runs inside FreedomOS.

---

## 2. Install

1. Go to the [Releases page](../../../releases/latest) and download **`FreedomOS-Setup-x.y.z.exe`**.
2. Double-click it.
   - Windows may show **"Windows protected your PC"**. That's because the installer isn't paid-for code-signed.
     Click **More info → Run anyway**.
3. Click through the installer. Tick **"Put a FreedomOS shortcut on the desktop"** if you want one.
   - No admin password needed - FreedomOS installs just for your Windows user, in `%LOCALAPPDATA%\FreedomOS`.
4. On the last page leave **"Finish setup and start FreedomOS"** ticked and hit **Finish**.

### The setup window

A black window opens and does the one-time setup. It takes about 5-15 minutes depending on your internet.
It answers its own questions where it can, and asks you **Y or N** for the optional bits:

| Step | What happens | Your choice |
|---|---|---|
| 1 | Installs **Python 3.12** (from Microsoft's winget) and builds FreedomOS's Python toolbox | automatic |
| 2 | Downloads the **llama.cpp brain engine** - the NVIDIA (CUDA) build if you have an NVIDIA card, the Vulkan build if not | automatic |
| 3 | **Pixel Shop** (NVIDIA cards only) - installs PyTorch + the picture tools (~3 GB) | **Y / N** |
| 4 | **Tailscale** - private link to your phone + other PCs. Signs you in, and adds ONE firewall rule that only lets Tailscale devices in (Windows asks for permission once) | **Y / N** |
| 5 | **Claude Code** - for the 💬 Claude chat window | **Y / N** |
| 6 | Plugs the crew into the **Claude desktop app** (if it's installed) | automatic |
| 7 | **Starts FreedomOS** | automatic |

Said N to something and changed your mind? Run **Start menu → FreedomOS → FreedomOS Setup (repair or add features)**.
To get asked about Tailscale or Claude Code again, delete `no_remote.txt` / `no_claude.txt` in `%LOCALAPPDATA%\FreedomOS` first.

---

## 3. The first start

- FreedomOS opens **full screen as your desktop** (see [Desktop mode](#5-desktop-mode)). You'll see a live wallpaper.
- From now on it **starts with Windows** by itself, quietly, with an icon in the tray (by the clock).
- A fresh start always begins **cool and quiet**: the 🧠 brain is **off** and the Home screen shows just the wallpaper.
- **The first time you ask a question or give a job, the brain downloads** (about 6 GB for the default brain).
  Watch the 🧠 line in the top bar - it shows the download, then "loading", then "ready".
  After that it only loads from disk (a few seconds to a minute).

> 💡 Closing the window with ✕ doesn't quit FreedomOS - it keeps running in the tray. To really quit:
> right-click the tray icon → **Quit FreedomOS (for real)**. To shut down the brain and free the graphics card: 🧰 → **Shut down**.

---

## 4. Getting around: the Home screen and the top bar

FreedomOS's window has three rows at the top that **slide away** after 1 second with no mouse up there
(like an auto-hide taskbar). **Push the mouse to the very top of the screen** to bring them back.

1. **The tab row** - 🏠 Home is always first. Browser tabs and app tabs (🎧 WiMix, 🎨 Pixel Shop, 👾 Discord) sit next to it.
   ─ ▢ ✕ in the top-right corner only show when the mouse is near them.
2. **The toolbar** (like a bookmarks bar) - the FreedomOS buttons:

| Button | What it is |
|---|---|
| 👥 | **The crew** - who's on your team. "Show the crew board" puts live cards for every agent on the Home screen. |
| 🖼 | **Wallpaper** - pick a live wallpaper. |
| 🧠 | **The brain** - **click** = switch on/off. **Hover** = brain options (pick a brain, brain race, GPU meters). |
| 💬 | **Chats** - ⚡ Ask, 💬 Claude, 🔎 Web, each on its own tab. |
| 🧰 | **Jobs** - give the crew a big job, see past jobs, Shut down. |
| 🎨 | **Pixel Shop** - make pictures. |
| 🌐 | **WiBro** - open a browser tab. |
| 📁 | **Files** - your files on all your devices. |
| 👾 | **Discord** - opens the Discord tab. A number = new pings. |
| 🎙 | **Discord overlay** on/off. |
| 🎧 | **WiMix** - your music. |

   - **Hover a button for 1 second** = a quick peek at its panel. **Click** = keep it open (click again or click elsewhere to close).
   - **Drag a button** left or right to put it where you want. FreedomOS remembers the order.
   - On the right: **RAM used / total**, CPU temperature and GPU use.
3. **The address bar** (only on browser tabs) with your bookmark logos under it.

The **Home** tab is the FreedomOS page itself: wallpaper, the crew board, and the panels. In a regular web browser (or on your phone) the same buttons sit in a slim strip at the top that tucks itself away.

---

## 5. Desktop mode

Desktop mode makes FreedomOS **your desktop**: it lives full screen *behind* all your other apps, like a wallpaper that does stuff.

- **It's on by default.** Turn it on/off: browser tab → ☰ menu → **🖥 Desktop mode**.
- Your **auto-hide Windows taskbar still pops up** over the bottom edge.
- **Get back to FreedomOS** from anywhere:
  - **Win + D** (show desktop), or click the far bottom-right corner of the taskbar
  - Click the **tray icon**
  - Press the **Copilot key** (on newer keyboards)
- **Games and full-screen apps:** FreedomOS notices, goes **black and pauses itself** so it doesn't eat any power or frames. It wakes up when you come back.
- The desktop can't be dragged around by accident - it always stays put.
- Tip: in Windows Settings → Personalization → Taskbar → Taskbar behaviors, turn on **"Automatically hide the taskbar"** for the cleanest look.

---

## 6. The crew and the brain

### The crew

FreedomOS's crew is a team of AI agents that all run on **your PC's brain**:

| Agent | Job |
|---|---|
| 🧭 **Atlas** - the planner | Splits a big job into pieces, hands them out, glues the answers together at the end. |
| 🤖 **Nova, Bolt, Echo, Sage, Rook** - the workers | Each takes a piece and works on it **at the same time** as the others. Stations: 📚 read, 💻 code, ✍️ write, 🗂 sort. |
| 🛡 **Sentry** - the checker | Grades every piece. Not good enough? It goes back once with notes. Code and failed pieces get flagged for a second look. |

Open 👥 → **Show the crew board** to watch them work live on the Home screen (press **Z** to show/hide it).
Rename them, add or remove workers in [the settings](#19-the-crew-handbook-and-settings).

### The brain switch (🧠)

- **Click 🧠** = brain **on** (stays loaded, fastest answers) or **off** (😴, unloaded - the PC stays cool and quiet).
- Even when it's **off**, a question or a job **wakes it up by itself**, and it goes back to sleep a minute after it's done.

### Picking a brain (hover 🧠)

| Brain | Download | Runs on | Good for |
|---|---|---|---|
| **Small 9B** (default) | ~5.6 GB | any PC | everyday questions and jobs |
| **Big 35B** | ~23 GB | NVIDIA card | the smartest answers |
| **Bonsai 27B** | ~7.6 GB | any PC | a big brain squeezed small |
| **Arete 27B** | ~15 GB | NVIDIA card | strong all-rounder |

Click one to swap. A new brain downloads the first time you pick it. Brains that need NVIDIA are greyed out on PCs without one.
The exact models are listed in `config.json` under `"brains"` - you can add your own from Hugging Face the same way.

- **🥊 Brain race** - hover 🧠 → **Race 'em**: every brain your PC can run answers the same question and you get a speed chart.
- **🖥 Borrow another PC's brain** - if you linked your PCs ([Files](#15-files-on-all-your-devices)), a laptop can use the desktop's big NVIDIA brain over Tailscale. Hover 🧠 and pick the other PC under the brain list.

---

## 7. Quick Ask

For quick questions where you just want **the answer** - a spec, a number, a size, what an error code means.

1. 💬 → **⚡ Ask** (or press **/** on the Home screen).
2. Type the question, hit **Enter**.
3. FreedomOS searches the web (DuckDuckGo, with Bing as a backup), the brain reads the top pages and gives you **just the answer**, with the source sites under it.
   - **✔ sources agree** = several sites gave the same answer and it matches what the brain remembers.
   - **⚠ double-check** = the sites disagree, or the brain remembers something different. It tells you the other values.
4. **🔍 crew check** - every agent looks it up **their own way** (manuals, forums, spec charts, comparison tables...) and they **vote**. Most of them agree → it turns ✔.
5. **👍 / 👎** - saves the answer as a training example (in `%LOCALAPPDATA%\FreedomOS\training`) so you could teach a brain later. 👎 asks you for the right answer.

Answers you've asked before (and that came back ✔) come back **instantly**. Old questions show under the box while you type.

> Typing a quick question into the 🧰 Jobs box works too - FreedomOS spots it and sends it down the fast lane instead.

---

## 8. Jobs

For **big stuff** that takes minutes: summaries, writing, plans, code, sorting lists, reading a whole folder.

1. Click **🧰**.
2. Type the job in plain words. Example: *"Read every .txt in this folder and make a list of anything with a due date."*
3. **Folder (optional)** - paste a folder path if the crew should read files. The crew can only read inside your
   **Documents\FreedomOS**, **Desktop** and **Downloads** folders (you can add more in [settings](#19-the-crew-handbook-and-settings)). They never change your files.
4. Hit **Get to work**. Watch the progress bar (and the crew board, if it's showing).
5. Click a finished job to see the **final answer**, every worker's piece, the checker's notes, and anything flagged **🔍 for Claude to check**.
   Every answer is also saved as a file in `%LOCALAPPDATA%\FreedomOS\outputs`.

- **Picture jobs** ("draw a...", "make a picture of...") go straight to the [Pixel Shop](#14-pixel-shop-and-pixel-shop-lite) - the crew never fakes a picture.
- **Shut down** (red button) stops FreedomOS and the brain, freeing the graphics card + RAM. Open FreedomOS from the Start menu to bring it back.

---

## 9. Chats: Claude, Web, Ask

Click **💬** - three tabs:

### ⚡ Ask
See [Quick Ask](#7-quick-ask).

### 💬 Claude
A straight line to **Claude** (it runs Claude Code on your PC with **your own Claude account and plan** - no extra bill).

1. First time only: open the chat window → **🔑 Log in** and sign in with your Claude account.
2. **＋ New Claude chat**, type, **Enter** to send (**Shift+Enter** = new line).
3. **📷** takes a picture with your camera (great on a phone or tablet), **🖼** picks one, or just **paste** a picture. Claude looks at it.
4. Every chat is kept on its own and **remembered** - come back to it any time. **📌 Pin** your favourites to the top.
5. Claude works in your **Documents\FreedomOS** folder, so it can make and read files there for you.

### 🔎 Web
Search the web **without the ads and junk**.
- Type a search → clean list of results. Click one to **read it clean** (just the text).
- Tick **🧠 answer** and the brain reads the top pages and writes you a straight answer.
- 🌐 opens the real page in a WiBro tab.

---

## 10. WiBro, the browser

WiBro is FreedomOS's own browser (it uses the same engine as Microsoft Edge, so every site and login works).

- **New tab:** the **+** button, **Ctrl+T**, or **B** on the Home screen.
- **Tear a tab off** into its own window: drag it out of the tab row. **Drag it back** onto the tab row to put it back.
- **Close a tab:** the ✕ on it, **Ctrl+W**, or middle-click.
- **Bookmarks:** ☆ (or **Ctrl+D**). Bookmarks show as **site logos** under the address bar and on the start page.
- **🛡 Ad blocker:** on by default (blocks ~100,000 ad + tracker sites). ☰ menu → flip it, or *"Let ads through on this site"* if a site breaks.
- **🧠** on the address bar = the brain sums up the page. **📖** = read the page clean.
- **🧠 Brain search:** typing a search in the address bar can get a brain answer (☰ menu to turn it on/off).
- **Full screen:** **F11** or maximize. **Esc** brings it back. Videos that go full screen stay in their tab or quadrant, and the top bar still slides down if you push the mouse to the top.
- **Black-screen fix:** if pages show black, ☰ menu → **Black-screen fix**.
- **Downloads** go to your normal Downloads folder (☰ → Downloads folder).
- Open tabs **come back** after FreedomOS updates or restarts.

---

## 11. Snap layouts (quadrant apps)

Put several tabs side by side **inside FreedomOS**, Windows 11 style - edge to edge, no borders.

1. **Right-click a tab** → **⊞ Snap this tab** → pick a layout (halves, thirds, quarters...) and the spot.
   Or **drag a tab** and drop it onto the snap bar that pops up near the top.
2. Empty spots fill with your next open tabs. The Home tab, WiMix and Discord can be snapped too.
3. **▣ Unsnap** (right-click a tab) = back to one tab at a time.

---

## 12. WiMix (YouTube Music)

WiMix is YouTube Music as a FreedomOS app tab.

1. Click **🎧** (or press **Y**). The first time, **sign in to YouTube Music** in the WiMix tab.
2. Clicking 🎧 when nothing's playing **starts your music** (your Supermix or Liked songs) and **tucks WiMix away** so you can keep working.
3. The 🎧 panel shows what's playing with ⏮ ⏯ ⏭ 👍. The small 🎧 icon in the panel header shows WiMix, ✕ closes it.
4. Extras:
   - **Music video** plays behind the player when the song has one.
   - **🎤 Karaoke lyrics** - lines light up in time with the song (lyrics from LRCLIB). They show in the 🎧 panel and the now-playing card.
   - Your **live wallpaper** shows behind WiMix.

---

## 13. Discord and the overlay

### The Discord tab
- Click **👾**. Sign in to Discord the first time. It starts with FreedomOS, **tucked away**, so you're online without it being in the way.
- **👾 + a number** = you have new pings.

### 🎙 The overlay (like the in-game Discord overlay, but for everything)
Little see-through widgets that float **on top of all your apps and games**:

| Widget | Shows |
|---|---|
| 🎙 **Voice** | who's in your voice channel, who's talking (lights up), who's muted |
| 💬 **Chat** | the latest messages in the channel you have open |
| 🔔 **Notifications** | new pings |
| **Action bar** | mute, deafen, leave call, 🎵 share the song you're playing, ⛶ full overlay |

- **Ctrl + Alt + D** - overlay on/off (works anywhere). Or click **🎙** in the toolbar.
- **Shift + `** (the key under Esc) - **unlock** the widgets to **drag them, pin them, change how see-through they are**. Press it again to lock them (clicks go through them to your game). Positions are saved.
- **⛶ Full overlay** - the whole Discord pops up on top of your game. Close it to go back.
- **🎵 Share song** - posts the WiMix song you're listening to in your open channel.

### "Playing FreedomOS" status (optional)
Discord can show **"Playing FreedomOS"** under your name. It needs the **Discord desktop app** running and your own (free) Discord "application":

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and sign in.
2. **New Application** → name it **FreedomOS** (that's the name people will see) → Create.
3. Copy the **Application ID** from the General Information page.
4. Start menu → FreedomOS → **Settings (config.json)** → paste it between the quotes: `"discord_app_id": "123456789..."` → save.
5. Restart FreedomOS (tray → Quit, then open it again). Your status shows what WiMix is playing.

---

## 14. Pixel Shop and Pixel Shop Lite

### 🎨 Pixel Shop (NVIDIA cards)
Makes AI pictures on your own graphics card with **FLUX.2 klein** or **Z-Image Turbo**.

1. Say **Y** to the Pixel Shop in setup (or run *FreedomOS Setup* again).
2. Click **🎨 → Start work**. This **pauses the crew's brain** so the graphics card is free, and starts the Pixel Shop. The first start downloads the picture models.
3. **Open shop** - it opens as an app tab. Type what you want, or **drop a picture** to have it redrawn.
4. **Your own style:** drop 4-8 of your own drawings into a style pack - klein copies the style right away.
   **TRAIN IT** learns your style for real (takes the graphics card for an hour or two).
5. **Close shop** gives the graphics card back to the crew.
6. Every picture also lands in **Documents\FreedomOS Pictures**.
7. **Friends:** the Pixel Shop has its own **friends link** (in `Documents\FreedomOS\Pixel Shop friends link.txt`) that ONLY opens the Pixel Shop - never your jobs or files. Your friends need to reach your PC over Tailscale (see the [Tailscale guide](TAILSCALE.md#6-let-a-friend-use-your-pixel-shop)).

### 🖌 Pixel Shop Lite (no NVIDIA needed)
On PCs without NVIDIA, the 🎨 panel shows **Pixel Shop Lite** instead (FLUX.2 klein through stable-diffusion.cpp, runs on Intel/AMD graphics).

1. 🎨 → **Set up** (one time, ~5.5 GB download).
2. Type a prompt, pick a look (**Pixel art**, **Sprite** or **Regular picture**), hit **Make it** (about a minute).
3. **Drop up to 4 reference pictures** to guide it.
4. **Your style:** put your own drawings in `%LOCALAPPDATA%\FreedomOS\my style` and tick **+ my style**.
5. Pictures save to **Documents\FreedomOS Pictures** (📂 Open folder).

---

## 15. Files on all your devices

The **📁** button keeps the same files on all your PCs, and lets your phone send and browse files.

Shared spaces:

| Space | Folder | For |
|---|---|---|
| 🗂 **FreedomOS** | Documents\FreedomOS | your work folder (the crew and Claude work here too) |
| 🤝 **Shared** | Documents\Shared | drop anything |
| 📱 **Phone** | Documents\Phone | pictures + files sent from your phone land here |
| 🎨 **Pictures** | Documents\FreedomOS Pictures | Pixel Shop pictures |

### Link two PCs (one time)
Both PCs need FreedomOS running and **Tailscale signed in to the same account** ([Tailscale guide](TAILSCALE.md)).

1. On PC #1: **📁 → 🔗 Link PCs** → **📋 Copy code**. Send that code to PC #2 (it's in your clipboard - paste it into a note, a message to yourself, etc.).
2. On PC #2: **📁 → 🔗 Link PCs** → paste it into **"Paste the other PC's code here"** → **🔗 Link them**.
3. Do the same the other way round (PC #2's code into PC #1).
4. Hit **Start** the first time - it **shows you what will copy** before anything moves.

How it stays in sync: every couple of minutes each PC asks the other "what's new?" and pulls it over.
- **Deleted on one PC** → moved to `todelete\sync trash` on the other (never wiped for good).
- **Changed on both** → the newer one wins, the older one is kept as a "(conflict ...)" copy.
- **⟳ Sync now** syncs right away. The on/off button pauses it.

### From your phone
Open FreedomOS on your phone ([section 17](#17-your-phone-and-other-pcs)) → 📁 → **⬆ Upload** or **📷 Send photos**. Browse any space and tap a file to download it.

---

## 16. Live wallpapers

- **🖼** → pick one of the built-in **live wallpapers** (aurora lake, neon galaxy, rain city, fractal dive, and more) - or **No wallpaper**.
- The wallpaper shows behind the Home screen, WiMix and the Pixel Shop.
- **Add your own:** any self-contained `.html` animation works. Drop it in `%LOCALAPPDATA%\FreedomOS\widget\walls\`, then add it to the `WALLS` list near the bottom of `widget\index.html` (`["my-wall", "My wallpaper"]` for `my-wall.html`).
- Wallpapers pause when you're in a game or another full-screen app.

---

## 17. Your phone and other PCs

With **Tailscale** (free), you can open FreedomOS from your phone, tablet or another PC - from anywhere - and it never touches the open internet.

**👉 The full walkthrough is in the [Tailscale guide](TAILSCALE.md).** The short version:

1. Say **Y** to Tailscale in setup and sign in.
2. Install Tailscale on your phone and sign in to the **same account**.
3. Turn on **MagicDNS** and **HTTPS** in the Tailscale admin console (one time).
4. Open **Documents\FreedomOS\FreedomOS phone link.txt** on your PC - open that link on your phone.
5. Phone browser menu → **Install app / Add to Home screen**.

---

## 18. Claude desktop can boss your crew around

If you have the **Claude desktop app**, setup plugs FreedomOS in as a tool (an MCP server called `freedomos`). Restart Claude desktop after setup. Then Claude can:

| Tool | What Claude can do |
|---|---|
| `crew_give_job` | hand your crew a job (with an optional folder) |
| `crew_wait` | wait for the answer |
| `crew_check` | look at a job's result and what to double-check |
| `crew_status` | see the brain, the graphics card and running jobs |
| `crew_open_widget` | open the FreedomOS Home screen |

Just ask Claude something like *"have my FreedomOS crew summarize the files in my Downloads folder"*.
It saves your Claude usage: the local crew does the heavy lifting, Claude checks the result.

---

## 19. The crew handbook and settings

### 📝 The crew handbook
**Start menu → FreedomOS → Edit the crew handbook.** Every brain reads it before it works.
Tell it who you are, how you like answers, what your PCs are. Plain words, short lines. Saves take effect right away.

### ⚙ Settings (config.json)
**Start menu → FreedomOS → Settings (config.json).** Open it in Notepad, change it, save, then restart FreedomOS (tray → Quit, open it again).
Updates never overwrite your config.json.

| Setting | What it does |
|---|---|
| `boss_name`, `checker_name`, `workers` | the crew's names. Fewer workers = less memory used. |
| `allowed_folders` | folders the crew may read for jobs |
| `brain` | which brain to start with (`small`, `big`, `bonsai`, `arete`) |
| `brains` | the brain list - add your own Hugging Face GGUF models here |
| `review` / `max_redo` | checker on/off, and how many redos it may ask for |
| `max_subtasks` | most pieces the planner may split a job into |
| `idle_shutdown_minutes` | when the tray icon isn't running: shut down after this long with nothing going on and no window open |
| `shop_hours` | e.g. `"07:00-18:00"` = never idle-shut-down between those times (`""` = off) |
| `remote_watch` | `false` = never listen on Tailscale, even if it's installed |
| `discord_app_id` | for the "Playing FreedomOS" status ([section 13](#playing-freedomos-status-optional)) |
| `port` | FreedomOS's address on your PC (`7777`) |

---

## 20. Tablet mode and touch screens

- In **tablet mode** (2-in-1 laptops folded back) buttons get **bigger** for fingers.
- The top bar is hidden like usual - **swipe down from the very top edge** (or tap the top edge) to bring it back.
- Rotating the screen re-fits FreedomOS automatically.
- Tap any text box and the on-screen keyboard pops up.

---

## 21. Updates

- New FreedomOS versions come as a new installer on the [Releases page](../../../releases). Run it over the top - your settings, handbook, chats, crew key and files stay.
- FreedomOS **restarts itself onto new versions** of its own parts only when you're **not busy** (no job running, nothing playing, 45 seconds idle). Your browser tabs come back.

---

## 22. Keyboard shortcuts

**Anywhere in Windows**

| Keys | Does |
|---|---|
| **Win + D** / tray icon / Copilot key | show FreedomOS (desktop mode) |
| **Ctrl + Alt + D** | Discord overlay on/off |
| **Shift + `** | unlock / lock the overlay widgets (while FreedomOS or the overlay is the active app) |

**Home screen** (not while typing in a box)

| Key | Does | | Key | Does |
|---|---|---|---|---|
| **/** | ⚡ Quick Ask | | **B** | new WiBro tab |
| **Z** | crew board on/off | | **G** | 🔎 web search |
| **H** | hide everything | | **Y** | 🎧 WiMix |
| **F** | 📁 files | | **C** | 💬 Claude chat |

**WiBro**

| Keys | Does |
|---|---|
| Ctrl+T / Ctrl+W | new tab / close tab |
| Ctrl+Tab / Ctrl+Shift+Tab | next / previous tab |
| Ctrl+L or F6 | jump to the address bar |
| F5 or Ctrl+R | reload |
| Alt+Left / Alt+Right | back / forward |
| Ctrl+D | bookmark |
| F11 / Esc | full screen / back |

---

## 23. Where everything lives

| What | Where |
|---|---|
| The program (and its Python toolbox, engine) | `%LOCALAPPDATA%\FreedomOS` |
| Your settings + handbook | `%LOCALAPPDATA%\FreedomOS\config.json`, `crew handbook.txt` |
| Job answers | `%LOCALAPPDATA%\FreedomOS\outputs` |
| Chats, quick-ask history | `%LOCALAPPDATA%\FreedomOS\memory` |
| The log (for troubleshooting) | `%LOCALAPPDATA%\FreedomOS\logs\boss.log` |
| The secret key for your phone / other devices | `%LOCALAPPDATA%\FreedomOS\crew_key.txt` |
| Downloaded brains | `%LOCALAPPDATA%\llama.cpp` |
| Browser data (logins, cookies, bookmarks) | `%LOCALAPPDATA%\FreedomOS Browser` |
| Your work folder | `Documents\FreedomOS` |
| Pictures | `Documents\FreedomOS Pictures` |

Tip: paste `%LOCALAPPDATA%\FreedomOS` into File Explorer's address bar to jump there.

---

## 24. Troubleshooting

| Problem | Fix |
|---|---|
| "Windows protected your PC" when installing | More info → Run anyway (the installer isn't code-signed). |
| The setup window says Python didn't install | Install Python 3.12 from [python.org](https://www.python.org/downloads/) (tick *Add python.exe to PATH*), then run *FreedomOS Setup* again. |
| 🧠 says **failed** or **engine missing** | Run *FreedomOS Setup* again (it re-downloads the engine). Then check `logs\boss.log`. |
| The brain download stopped halfway | Just ask a question again - it carries on where it left off. |
| Answers are slow | Pick the **Small 9B** brain, close other heavy apps, or switch 🧠 on so it stays loaded. On NVIDIA, close the Pixel Shop. |
| "FreedomOS isn't running yet" in the window | Wait 30 seconds. Still stuck? Start menu → FreedomOS. Still stuck? Check `logs\boss.log`. |
| Pages show black in WiBro | ☰ menu → Black-screen fix. |
| My phone can't connect | See [Tailscale troubleshooting](TAILSCALE.md#9-troubleshooting). |
| 💬 Claude says Claude Code isn't installed | Run *FreedomOS Setup* again and say Y to Claude Code, then 🔑 Log in. |
| I want FreedomOS to stop starting with Windows | Task Manager → Startup apps → FreedomOS → Disable. |
| I want a normal window, not the desktop | Browser tab → ☰ → 🖥 Desktop mode (untick). |

Still stuck? [Open an issue](../../../issues) with the end of `logs\boss.log` (remove anything private first).

---

## 25. Uninstall

**Start menu → FreedomOS → Uninstall FreedomOS** (or Windows Settings → Apps).

It stops FreedomOS and removes the program, its Python toolbox, the engine and the start-with-Windows entry.
It **keeps** your `Documents\FreedomOS` and `Documents\FreedomOS Pictures` folders, and WiBro's logins in `%LOCALAPPDATA%\FreedomOS Browser` (delete that folder to sign out of everything).
The downloaded brains stay in `%LOCALAPPDATA%\llama.cpp` (delete that folder to get the space back), and Tailscale stays installed (uninstall it from Windows Settings → Apps if you don't need it).
