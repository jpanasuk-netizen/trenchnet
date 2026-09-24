/* TRENCHNET Pass 9 — What's happening now strip + explainability helpers */
(function () {
  function $(id) { return document.getElementById(id); }
  function D() { return window.TRENCHNET_DATA || {}; }
  function short(a) { return a ? (a.slice(0, 4) + "…" + a.slice(-4)) : "—"; }
  function ctFromIso(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      if (isNaN(d.getTime())) return String(iso);
      return d.toLocaleString("en-US", { timeZone: "America/Chicago" }) + " CT";
    } catch (e) { return String(iso); }
  }

  function renderNowStrip() {
    const el = $("nowStrip");
    if (!el) return;
    const data = D();
    const tp = window.__TN_TOP_PICK || data.top_pick || {};
    const ht = window.__TN_HOTTAKES || {};
    const tr = (window.__TN_HT_TRACKER || ht.tracker || {});
    const cd = window.__TN_COPYDESK || data.copydesk || {};
    const paper = data.paper || {};
    const headline = tp.headline || "No buy right now";
    const takes = ht.takes || [];
    const latest = takes[0] || null;
    const nW = (data.profiles || []).length || cd.n_wallets || 0;
    const nTok = cd.n_tokens_watched != null ? cd.n_tokens_watched : ((data.graph || {}).token_summaries || []).length;
    const refreshed = ctFromIso(data.generated_at_utc || cd.generated_at_utc);
    const nextHt = tr.next_poll_at ? ("unix " + tr.next_poll_at) : (tr.next_poll_iso ? ctFromIso(tr.next_poll_iso) : "—");
    const liveOff = true;
    el.innerHTML = `
      <div class="nsTitle">What's happening now</div>
      <div class="nsItem"><div class="k">Desk refreshed</div><div class="v">${refreshed}</div></div>
      <div class="nsItem"><div class="k">Hot Takes next check</div><div class="v" id="nsHtNext">${nextHt}</div></div>
      <div class="nsItem"><div class="k">Wallets / tokens</div><div class="v">${nW} / ${nTok}</div></div>
      <div class="nsItem"><div class="k">Top Pick</div><div class="v">${headline}</div></div>
      <div class="nsItem"><div class="k">Latest Hot Take</div><div class="v">${latest ? (short(latest.token_mint) + " · " + (latest.call || latest.side || "—")) : "—"}</div></div>
      <div class="nsItem"><div class="k">Mode</div><div class="badgeRow">
        <span class="badge">PAPER</span>
        <span class="badge">${liveOff ? "LIVE OFF" : "LIVE"}</span>
        <span class="badge">kill ${paper.kill_switch ? "ON" : "off"}</span>
      </div></div>`;
  }

  function boot() {
    renderNowStrip();
    setInterval(renderNowStrip, 5000);
    window.TrenchExplain = { renderNowStrip };
    // Re-render when picks/hottakes load
    const orig = window.TrenchInteractive;
    // poll lightly
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else setTimeout(boot, 50);
})();
