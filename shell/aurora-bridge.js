/* aurora-bridge.js — wires the concept shell to the real system via aurorad.
   Loaded after the shell's own script; degrades silently in a plain browser. */
(function () {
  const API = "http://127.0.0.1:7212";
  const $ = (s) => document.querySelector(s);
  let live = false;

  async function j(path, opts) {
    const r = await fetch(API + path, opts);
    return r.json();
  }

  /* ---- status poll: battery / net / brightness ---- */
  async function poll() {
    try {
      const s = await j("/status");
      live = true;
      const b = s.battery || {};
      const battTxt = b.percent != null ? `🔋 ${b.percent}%` : "🔌";
      const netTxt = s.net ? "📶" : "⚠️";
      const tray = $("#b-qs");
      if (tray) tray.textContent = `${netTxt} 🔊 ${battTxt}`;
      const foot = document.querySelector(".qs-foot span");
      if (foot && b.percent != null)
        foot.textContent = `🔋 ${b.percent}% · ${b.status || ""} · ${s.os}`;
      if (s.brightness != null && $("#sl-bright")) $("#sl-bright").value = s.brightness;
    } catch { live = false; }
  }
  poll(); setInterval(poll, 10000);

  /* ---- brightness: real backlight instead of CSS filter ---- */
  const sl = $("#sl-bright");
  if (sl) sl.addEventListener("input", (e) => {
    if (live) j("/brightness", { method: "POST", body: JSON.stringify({ percent: +e.target.value }) }).catch(() => {});
  });

  /* ---- power buttons: real systemctl ---- */
  const wire = (id, action) => {
    const el = $(id); if (!el) return;
    el.addEventListener("click", () => {
      if (live) j("/power", { method: "POST", body: JSON.stringify({ action }) }).catch(() => {});
    }, { capture: true });
  };
  wire("#p-off", "poweroff");
  wire("#p-restart", "reboot");

  /* ---- Files app: real home directory ---- */
  const origOpen = window.openApp;
  if (typeof origOpen === "function") {
    window.openApp = function (id) {
      origOpen(id);
      if (id === "files" && live) {
        j("/files").then((d) => {
          const win = document.querySelector('.win[data-app="files"] .main');
          if (!win || d.error) return;
          win.querySelector("h2").textContent = d.path;
          win.querySelector(".fgrid").innerHTML = d.items.map((it) =>
            `<div class="fit"><span class="ic">${it.dir ? "📁" : "📄"}</span>${it.name}</div>`).join("") ||
            "<i style='color:#888;font-size:13px'>empty</i>";
        }).catch(() => {});
      }
    };
  }

  /* ---- Aura assistant: try aurorad first, fall back to canned ---- */
  const origAsk = window.cpAsk;
  if (typeof origAsk === "function") {
    window.cpAsk = function (q) {
      if (!live) return origAsk(q);
      window.cpMsg(q, "u");
      j("/ask", { method: "POST", body: JSON.stringify({ q }) })
        .then((d) => window.cpMsg(d.a, "a"))
        .catch(() => window.cpReply(q.toLowerCase()));
    };
  }
})();
