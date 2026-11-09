# Tailscale + FreedomOS - the full guide

Tailscale gives your devices (PCs, phone, tablet) their own **private network** that works from anywhere: home Wi-Fi, mobile data, work.
FreedomOS uses it so you can:

- 📱 open FreedomOS on your **phone** and install it like an app
- 💻 use it from your **work laptop** or any other PC
- 📁 keep **files in sync** between your PCs
- 🧠 let a laptop **borrow the desktop's big NVIDIA brain**
- 🎨 let **friends** use your Pixel Shop

Nothing is put on the open internet. Only devices signed in to **your** Tailscale account (plus anyone you choose to share with) can reach FreedomOS - and even they need FreedomOS's secret key.

Tailscale's free **Personal** plan is plenty for this.

---

**Contents**

1. [Make a Tailscale account](#1-make-a-tailscale-account)
2. [Install Tailscale on your FreedomOS PC](#2-install-tailscale-on-your-freedomos-pc)
3. [Turn on MagicDNS + HTTPS (one time)](#3-turn-on-magicdns--https-one-time)
4. [Put FreedomOS on your phone](#4-put-freedomos-on-your-phone)
5. [Open FreedomOS from another PC or a work laptop](#5-open-freedomos-from-another-pc-or-a-work-laptop)
6. [Let a friend use your Pixel Shop](#6-let-a-friend-use-your-pixel-shop)
7. [Link two FreedomOS PCs (file sync + brain borrowing)](#7-link-two-freedomos-pcs)
8. [Keeping it safe](#8-keeping-it-safe)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Make a Tailscale account

1. Go to **[tailscale.com](https://tailscale.com)** → **Get started**.
2. Sign up with Google, Microsoft, Apple or GitHub. Pick the one you'll remember -
   **every one of your devices must sign in with this same account.**
3. Your private network (Tailscale calls it a *tailnet*) is made automatically.

## 2. Install Tailscale on your FreedomOS PC

**Easiest:** say **Y** to Tailscale when *FreedomOS Setup* asks. It:

1. installs Tailscale (from Microsoft's winget),
2. opens the Tailscale sign-in - log in with the account from step 1,
3. adds **one Windows firewall rule** that lets **only Tailscale addresses** (100.64.0.0/10) reach FreedomOS's port 7777.
   Windows asks for permission once for this.

Already said no? Run **Start menu → FreedomOS → FreedomOS Setup**. (If it doesn't ask about Tailscale, delete `%LOCALAPPDATA%\FreedomOS\no_remote.txt` and run it again.)

**By hand:** download Tailscale from [tailscale.com/download](https://tailscale.com/download), install, click the Tailscale icon by the clock → **Log in**. Then run *FreedomOS Setup* once so it adds the firewall rule.

Tailscale starts with Windows by itself (FreedomOS makes sure of it).

**Check it worked:** restart FreedomOS (tray → Quit, then open it). In `%LOCALAPPDATA%\FreedomOS\logs\boss.log` you should see:

```
Remote watching ON at http://100.x.y.z:7777
```

## 3. Turn on MagicDNS + HTTPS (one time)

This gives your PC a proper `https://` address - your phone needs it to **install FreedomOS as an app**.

1. Open the **[DNS page](https://login.tailscale.com/admin/dns)** of the Tailscale admin console (sign in with your Tailscale account).
2. **MagicDNS** - if it isn't on already, click **Enable MagicDNS**. (New tailnets have it on already.)
3. Under **HTTPS Certificates**, click **Enable HTTPS**.
4. Restart FreedomOS (tray → Quit, then open it).

> ℹ️ Tailscale's note: with HTTPS on, your **machine names** are published in a public certificate log.
> If your PC's name has your real name or anything private in it, rename it first: [Machines page](https://login.tailscale.com/admin/machines) → your PC → **⋯ → Edit machine name** (something like `gaming-pc`).

What FreedomOS does with it: it runs `tailscale serve --bg 7777`, which puts FreedomOS at
`https://<your-pc-name>.<your-tailnet>.ts.net` - reachable **only inside your tailnet**.

If the HTTPS step isn't done yet, FreedomOS still works over plain `http://100.x.y.z:7777`, it just can't be installed as a phone app.

## 4. Put FreedomOS on your phone

1. Install the **Tailscale app** on your phone ([Android](https://play.google.com/store/apps/details?id=com.tailscale.ipn) / [iPhone](https://apps.apple.com/app/tailscale/id1470499037)).
2. Open it and **sign in with the same account**. Turn the connection **on** (the toggle at the top).
3. On your PC, open **`Documents\FreedomOS\FreedomOS phone link.txt`**. It has a link like:
   ```
   https://gaming-pc.tail1234.ts.net/?key=AbCdEf...
   ```
4. Get that link to your phone (email it to yourself, a note app, Tailscale's own **Taildrop**, etc.) and open it in **Chrome** (Android) or **Safari** (iPhone).
5. Install it as an app:
   - **Android / Chrome:** menu ⋮ → **Install app** (or *Add to Home screen*).
   - **iPhone / Safari:** Share button → **Add to Home Screen**.
6. Done - the FreedomOS icon on your phone opens it full screen. The key is remembered, so you only use the long link once.

On the phone you get the same Home screen: ⚡ Quick Ask, 🧰 Jobs, 💬 Claude chat (with the 📷 camera), 🔎 Web, 📁 Files (send photos straight to your PC), 🎧 music controls and the 🧠 brain status.

> The Tailscale app must be **connected** on the phone for FreedomOS to load. On Android you can set Tailscale to **always-on VPN** so you never have to think about it.

## 5. Open FreedomOS from another PC or a work laptop

1. Install Tailscale on that computer and sign in with the **same account**.
2. Open the same link from `FreedomOS phone link.txt` in any browser. Bookmark it.

> **Work laptop?** Check your workplace allows Tailscale before installing it. If it doesn't, your phone is the way to go.

## 6. Let a friend use your Pixel Shop

Your friends can make pictures on **your** NVIDIA card - and **only** that. The Pixel Shop has its own key that never opens your jobs, chats or files.

1. **Share your PC with your friend in Tailscale** (they don't join your whole network - they only see this one PC):
   1. Your friend makes their own free Tailscale account and installs Tailscale.
   2. You open the **[Machines page](https://login.tailscale.com/admin/machines)** → your FreedomOS PC → **⋯ → Share**.
   3. Either type their email to send an invite, or **Copy share link** and send it to them. (Unused invite links expire after 30 days.)
   4. They open the invite and **accept** it while signed in to their Tailscale.
2. Send your friend the link from **`Documents\FreedomOS\Pixel Shop friends link.txt`** (FreedomOS writes it every time it starts with Tailscale connected).
3. They open it in their browser (with Tailscale on) and make pictures. The shop has to be open (🎨 → Start work) on your PC.

**Kick everyone out:** delete `%LOCALAPPDATA%\FreedomOS\pixelshop\crew_key.txt` and restart FreedomOS - it makes a new key. Send the new link only to people you still want in.
**Stop sharing your PC:** Machines page → your PC → ⋯ → Share → revoke their share.

## 7. Link two FreedomOS PCs

For **file sync** (📁) and **brain borrowing** (🧠), two PCs running FreedomOS need to know each other.

1. Both PCs: FreedomOS installed, Tailscale on and signed in to the **same account**, FreedomOS restarted once after Tailscale was set up.
2. PC #1: **📁 → 🔗 Link PCs → 📋 Copy code**. Get the code to PC #2 (paste it into a note / message to yourself).
3. PC #2: **📁 → 🔗 Link PCs** → paste it under *"Paste the other PC's code here"* → **🔗 Link them**.
4. Do it the other way too: PC #2's code into PC #1.
5. 📁 → **Start**. The first time it **shows you what will copy** before anything moves.

The link code holds that PC's private Tailscale address and its FreedomOS key, so **treat it like a password** - only paste it into your own PCs.

**Borrow the big brain:** on the laptop, hover 🧠 → pick the desktop under the brain list. The laptop now sends its questions and jobs to the desktop's brain. Pick a local brain again to stop.

## 8. Keeping it safe

How FreedomOS keeps other people out:

- **Not on the internet.** FreedomOS only listens on your PC itself and on its Tailscale address. Your home Wi-Fi neighbours and the internet can't reach it.
- **Firewall rule** only allows Tailscale addresses (100.64.0.0/10) on port 7777.
- **Secret key.** Even on your tailnet, every request from another device needs FreedomOS's key (it's in the link). Your phone remembers it after the first visit.
- **The Pixel Shop key** only opens the Pixel Shop.

Good habits:

- Don't post your links or the `crew_key.txt` file anywhere public.
- **New key** (if a link got out): delete `%LOCALAPPDATA%\FreedomOS\crew_key.txt` and restart FreedomOS. Then open the new link from `FreedomOS phone link.txt` on each device again.
- Use Tailscale's [Machines page](https://login.tailscale.com/admin/machines) to see every device on your tailnet, and remove ones you don't use any more.
- Turn remote access off completely: set `"remote_watch": false` in **Settings (config.json)** and restart FreedomOS.

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| The log says *"Remote watching off - Tailscale isn't installed/signed in"* | Click the Tailscale icon by the clock → make sure you're **logged in** and **connected**. Then restart FreedomOS. |
| `FreedomOS phone link.txt` isn't there | Same as above - it's written when FreedomOS starts with Tailscale connected. |
| The link file says the https link isn't switched on | Do [step 3](#3-turn-on-magicdns--https-one-time), then restart FreedomOS. |
| Phone shows "site can't be reached" | Is the **Tailscale app on and connected** on the phone? Same account as the PC? Is the PC awake with FreedomOS running? |
| Phone shows **"Wrong key."** | Open the full link (with `?key=...`) from the link file again. Maybe the key was changed. |
| `http://100.x.y.z:7777` works but `https://...ts.net` doesn't | HTTPS isn't enabled yet (step 3), or the first certificate is still being made - give it a minute and try again. |
| "Install app" doesn't show on the phone | You need the **https://** link, not the http one. |
| Other PC can reach it but my phone can't (or the other way round) | The firewall rule may be missing: run *FreedomOS Setup* again, or delete `%LOCALAPPDATA%\FreedomOS\firewall_done.txt` first. |
| File sync says it can't reach the other PC | Both PCs on and connected to Tailscale? Both running FreedomOS? Try 📁 → ⟳ Sync now. |
| The PC went to sleep | Tailscale can't wake a sleeping PC. Windows Settings → System → Power → set **Sleep** to *Never* while plugged in if you want it reachable all the time. |

More help: [Tailscale's docs](https://tailscale.com/kb) · [FreedomOS issues](../../../issues)
