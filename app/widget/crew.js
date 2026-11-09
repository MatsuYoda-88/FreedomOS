/* FreedomOS - the crew board on the Home screen.
   Shows your local AI agents (planner, workers, checker) as live cards over your wallpaper:
   who's working, on which station, and what they're saying about the job right now.
   Hide it (👥 button or Z key) for wallpaper only. */
class Crew {
  constructor(el) {
    this.el = el; this.agents = {}; this.info = null; this.says = {};
    let hid = true;                                   // fresh start = wallpaper only
    try { hid = localStorage.getItem("fos_crew_hidden") !== "0"; } catch (e) {}
    this.asleep = hid;
    this.css();
    this.draw();
  }
  css() {
    if (document.getElementById("crewCss")) return;
    const st = document.createElement("style"); st.id = "crewCss";
    st.textContent = `
      #cv{position:absolute;inset:0;overflow:auto;padding:calc(var(--hudH,0px) + 70px) 4vw 110px;display:flex;flex-direction:column;align-items:center}
      #cv .cwTitle{font:800 clamp(20px,2.4vw,34px) "Segoe UI",system-ui;letter-spacing:.5px;color:#eaf2ff;text-shadow:0 2px 18px rgba(0,0,0,.7);margin-bottom:4px}
      #cv .cwSub{color:#b9c6da;font-size:13px;margin-bottom:18px;text-shadow:0 1px 8px rgba(0,0,0,.8)}
      #cv .cwGrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px;width:min(1200px,100%)}
      #cv .ag{background:rgba(14,18,28,.55);border:1px solid rgba(255,255,255,.12);border-radius:16px;padding:12px 14px;
        backdrop-filter:blur(12px) saturate(1.2);-webkit-backdrop-filter:blur(12px);transition:border-color .3s, transform .3s;min-height:118px}
      #cv .ag.busy{border-color:#7cc4ff;transform:translateY(-2px);box-shadow:0 0 22px rgba(124,196,255,.25)}
      #cv .ag.failed{border-color:#ff6b6b} #cv .ag.done{border-color:#5fd38d}
      #cv .ag .hd{display:flex;align-items:center;gap:10px}
      #cv .ag .av{width:40px;height:40px;border-radius:12px;display:grid;place-items:center;font-size:22px;flex:none}
      #cv .ag .nm{font:700 15px "Segoe UI";color:#fff} #cv .ag .rl{font-size:11.5px;color:#9aa4b2}
      #cv .ag .st{margin-left:auto;font-size:10.5px;padding:2px 8px;border-radius:9px;background:rgba(255,255,255,.08);color:#cfd8e6;text-transform:uppercase;letter-spacing:.4px}
      #cv .ag.busy .st{background:#2a6bd1;color:#fff}
      #cv .ag .tx{margin-top:9px;font-size:12.5px;color:#dbe4f2;line-height:1.35;max-height:5.4em;overflow:hidden;white-space:pre-wrap;word-break:break-word}
      #cv .ag .tx:empty::before{content:"standing by";color:#7d8798;font-style:italic}`;
    document.head.appendChild(st);
  }
  look(a) {
    const role = a.role || "worker";
    const icon = { boss: "🧭", checker: "🛡", worker: { read: "📚", code: "💻", write: "✍️", sort: "🗂", boss: "🤝", idle: "🤖" }[a.station] || "🤖" }[role] || "🤖";
    const hue = [...(a.name || "x")].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
    return { icon, bg: `linear-gradient(135deg,hsl(${hue} 70% 45%),hsl(${(hue + 40) % 360} 70% 32%))` };
  }
  roleName(a) { return { boss: "Planner", checker: "Checker", worker: "Worker", keeper: "Helper", bench: "On the bench" }[a.role] || "Agent"; }
  event(ev) {
    if (ev.type === "snapshot") { this.agents = {}; (ev.agents || []).forEach(a => this.agents[a.name] = a); this.info = ev.crew || null; }
    else if (ev.type === "agent") this.agents[ev.name] = Object.assign(this.agents[ev.name] || {}, ev);
    else if (ev.type === "say" && ev.name) { this.says[ev.name] = { text: ev.text, until: Date.now() + (ev.secs || 4) * 1000 }; }
    else return;
    this.draw();
  }
  sleep(on) {
    this.asleep = !!on;
    try { localStorage.setItem("fos_crew_hidden", on ? "1" : "0"); } catch (e) {}
    this.draw();
  }
  esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
  listHTML() {
    const L = Object.values(this.agents);
    if (!L.length) return "connecting...";
    return L.map(a => `<div>${this.look(a).icon} <b>${this.esc(a.name)}</b> - ${this.roleName(a)}${this.info && this.info.persona && this.info.persona[a.name] ? ": " + this.esc(this.info.persona[a.name]) : ""}</div>`).join("");
  }
  draw() {
    if (!this.el) return;
    if (this.asleep) { this.el.innerHTML = ""; return; }
    const order = { boss: 0, worker: 1, checker: 2, keeper: 3, bench: 4 };
    const L = Object.values(this.agents).sort((a, b) => (order[a.role] ?? 9) - (order[b.role] ?? 9));
    const busy = L.filter(a => a.status && !["idle", "done"].includes(a.status)).length;
    const now = Date.now();
    this.el.innerHTML = `<div class="cwTitle">The Crew</div><div class="cwSub">${busy ? `${busy} agent${busy > 1 ? "s" : ""} working` : "Everyone's standing by - give them a job from 🧰 or ask a quick question"}</div>
      <div class="cwGrid">${L.map(a => {
        const lk = this.look(a), say = this.says[a.name] && this.says[a.name].until > now ? this.says[a.name].text : "";
        const st = a.status || "idle", cls = ["working", "planning", "checking", "merging", "reading", "waiting"].includes(st) ? "busy" : st === "failed" ? "failed" : st === "done" ? "done" : "";
        return `<div class="ag ${cls}"><div class="hd"><div class="av" style="background:${lk.bg}">${lk.icon}</div>
          <div><div class="nm">${this.esc(a.name)}</div><div class="rl">${this.roleName(a)}${a.job ? " · job #" + this.esc(a.job) : ""}</div></div>
          <span class="st">${this.esc(st)}</span></div><div class="tx">${this.esc(say || a.text || "")}</div></div>`;
      }).join("")}</div>`;
  }
}
window.Crew = Crew;
