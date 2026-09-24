/* TRENCHNET Pass 9 interactive desk — local only, no CDN, paper/backtest labels. */
(function () {
  const D = () => window.TRENCHNET_DATA || {};
  const DEFAULT_VIEW = {
    filters: { qWallet: "", qToken: "", minSol: 0, source: "all", t0: null, t1: null },
    selected: null,
    layout: "columns",
    backtest: { delay: 60, sizeSol: 0.25, slipMult: 1, tp: 0.5, sl: 0.25, tstop: 3600, mode: "fixed" },
    tab: "overview"
  };
  const LS_KEY = "trenchnet_view_v1";
  const state = {
    filters: Object.assign({}, DEFAULT_VIEW.filters),
    page: { buy: 0, score: 0, events: 0 },
    pageSize: 12,
    selected: null, // {kind:'wallet'|'token', id}
    layout: DEFAULT_VIEW.layout, // columns | force
    tab: DEFAULT_VIEW.tab,
    pollTimer: null,
    lastVersion: null,
    backtest: Object.assign({}, DEFAULT_VIEW.backtest),
    htCollapsed: false
  };

  function cloneDefault() {
    return {
      filters: Object.assign({}, DEFAULT_VIEW.filters),
      selected: null,
      layout: DEFAULT_VIEW.layout,
      backtest: Object.assign({}, DEFAULT_VIEW.backtest),
      tab: DEFAULT_VIEW.tab
    };
  }
  function applyView(o) {
    if (!o) return;
    if (o.filters) Object.assign(state.filters, o.filters);
    state.selected = o.selected != null ? o.selected : state.selected;
    if (o.layout) state.layout = o.layout;
    if (o.backtest) Object.assign(state.backtest, o.backtest);
    if (o.tab) state.tab = o.tab;
  }
  function loadLocal() {
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (e) { return null; }
  }
  function saveLocal() {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify({
        filters: state.filters,
        selected: state.selected,
        layout: state.layout,
        backtest: state.backtest,
        tab: state.tab || "overview"
      }));
    } catch (e) { /* private mode */ }
  }
  function clearLocal() {
    try { localStorage.removeItem(LS_KEY); } catch (e) {}
  }
  function resetToDefaultView() {
    clearLocal();
    const d = cloneDefault();
    state.filters = d.filters;
    state.selected = null;
    state.layout = d.layout;
    state.backtest = d.backtest;
    state.tab = d.tab;
    state.page = { buy: 0, score: 0, events: 0 };
    // clear hash so a fresh load stays on defaults
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);
    // sync inputs
    if ($("fWallet")) $("fWallet").value = "";
    if ($("fToken")) $("fToken").value = "";
    if ($("fMinSol")) $("fMinSol").value = "0";
    if ($("fSource")) $("fSource").value = "all";
    if ($("fT0")) $("fT0").value = "";
    if ($("fT1")) $("fT1").value = "";
    if ($("graphLayout")) $("graphLayout").value = state.layout;
    syncBacktestSliders();
    writeHash();
    setTab("overview");
    renderAll();
    loadCopyDesk();
    window.dispatchEvent(new CustomEvent("trenchnet:layout", { detail: state.layout }));
  }
  function syncBacktestSliders() {
    const map = {btDelay:["delay", v=>v], btSize:["sizeSol", v=>Number(v).toFixed(2)], btSlip:["slipMult", v=>Number(v).toFixed(1)], btTp:["tp", v=>Math.round(v*100)+"%"], btSl:["sl", v=>Math.round(v*100)+"%"], btTstop:["tstop", v=>v]};
    Object.keys(map).forEach(id => {
      const el = $(id); if (!el) return;
      const [key, fmt] = map[id];
      el.value = state.backtest[key];
      const lab = $(id+"V"); if (lab) lab.textContent = fmt(state.backtest[key]);
    });
    if ($("btMode")) $("btMode").value = state.backtest.mode || "fixed";
  }

  function $(id) { return document.getElementById(id); }
  function fmt(n, d) {
    if (n == null || isNaN(n)) return "—";
    return Number(n).toFixed(d == null ? 3 : d);
  }
  function short(a) { return a ? (a.slice(0, 4) + "…" + a.slice(-4)) : "—"; }

  function parseHash() {
    try {
      const h = (location.hash || "").replace(/^#/, "");
      if (!h) return false;
      const o = JSON.parse(decodeURIComponent(h));
      applyView(o);
      return true;
    } catch (e) { return false; }
  }
  function writeHash() {
    const o = {
      filters: state.filters,
      selected: state.selected,
      layout: state.layout,
      backtest: state.backtest,
      tab: state.tab || "overview"
    };
    const next = "#" + encodeURIComponent(JSON.stringify(o));
    if (location.hash !== next) history.replaceState(null, "", next);
    saveLocal();
  }

  function eventPass(e) {
    const f = state.filters;
    if (f.source !== "all" && (e.source || "") !== f.source) return false;
    if (f.qWallet) {
      const q = f.qWallet.toLowerCase();
      const lab = ((D().profiles || []).find(p => p.wallet === e.wallet) || {}).label || "";
      if (!(String(e.wallet || "").toLowerCase().includes(q) || String(lab).toLowerCase().includes(q))) return false;
    }
    if (f.qToken) {
      const q = f.qToken.toLowerCase();
      if (!(String(e.token_mint || "").toLowerCase().includes(q))) return false;
    }
    const sol = e.amount_sol;
    if (f.minSol > 0 && (sol == null || sol < f.minSol)) return false;
    if (f.t0 != null && e.block_time != null && e.block_time < f.t0) return false;
    if (f.t1 != null && e.block_time != null && e.block_time > f.t1) return false;
    return true;
  }

  function filteredEvents() {
    return (D().events || []).filter(eventPass);
  }

  function ensureChrome() {
    if ($("filterBar")) return;
    const bar = document.createElement("div");
    bar.id = "filterBar";
    bar.className = "panel";
    bar.style.cssText = "margin:12px 18px 0;display:grid;grid-template-columns:repeat(6,minmax(0,1fr)) auto;gap:10px;align-items:end";
    bar.innerHTML = `
      <label>Wallet search<input id="fWallet" placeholder="label or address"/></label>
      <label>Token search<input id="fToken" placeholder="mint"/></label>
      <label>Min SOL<input id="fMinSol" type="number" min="0" step="0.01" value="0"/></label>
      <label>Source<select id="fSource"><option value="all">all</option><option>helius</option><option>birdeye</option><option>rpc</option><option>derived</option></select></label>
      <label>From (unix)<input id="fT0" type="number" placeholder="optional"/></label>
      <label>To (unix)<input id="fT1" type="number" placeholder="optional"/></label>
      <div style="display:flex;gap:8px;align-items:center">
        <button type="button" id="fApply">Apply filters</button>
        <button type="button" id="fClear">Clear</button>
        <span id="freshness" class="muted">static</span>
        <button type="button" id="btnRefresh">Refresh</button>
      </div>`;
    const hero = $("hero");
    if (hero && hero.parentNode) hero.parentNode.insertBefore(bar, hero.nextSibling);

    // Drawer overlay (richer than side panel)
    if (!$("drawer")) {
      const dr = document.createElement("div");
      dr.id = "drawer";
      dr.innerHTML = `<div class="drawerInner"><button type="button" id="drawerClose">✕</button><div id="drawerBody"></div></div>`;
      document.body.appendChild(dr);
    }

    // Backtest section
    if (!$("backtestSection")) {
      const sec = document.createElement("div");
      sec.id = "backtestSection";
      sec.className = "panel";
      sec.style.cssText = "margin:14px 18px;grid-column:1/-1";
      sec.innerHTML = `
        <h2>Backtest &amp; Scores <span class="badge">PAPER / BACKTEST — not a promise</span></h2>
        <p class="muted" id="btCoverage"></p>
        <div class="btControls">
          <label>Copy delay (s) <input id="btDelay" type="range" min="0" max="120" step="10" value="60"/><span id="btDelayV">60</span></label>
          <label>Position SOL <input id="btSize" type="range" min="0.05" max="1" step="0.05" value="0.25"/><span id="btSizeV">0.25</span></label>
          <label>Slippage × <input id="btSlip" type="range" min="0" max="3" step="0.1" value="1"/><span id="btSlipV">1.0</span></label>
          <label>Take profit % <input id="btTp" type="range" min="0.05" max="2" step="0.05" value="0.50"/><span id="btTpV">50%</span></label>
          <label>Stop loss % <input id="btSl" type="range" min="0.05" max="0.9" step="0.05" value="0.25"/><span id="btSlV">25%</span></label>
          <label>Time stop (s) <input id="btTstop" type="range" min="300" max="7200" step="300" value="3600"/><span id="btTstopV">3600</span></label>
          <label>Exit mode <select id="btMode"><option value="fixed">fixed rules</option><option value="mirror">mirror sell</option></select></label>
        </div>
        <div class="btGrid">
          <div><h3>Wallet leaderboard</h3><div id="scoreTableWrap"></div></div>
          <div><h3>Returns vs delay (live recompute)</h3><canvas id="delayChart" width="640" height="220"></canvas><div id="delayTable"></div></div>
          <div><h3>Walk-forward</h3><div id="wfPanel"></div></div>
          <div><h3>Live slider summary</h3><div id="btLiveSummary"></div></div>
        </div>`;
      const lower = $("lower");
      if (lower) lower.parentNode.insertBefore(sec, lower);
      else document.body.appendChild(sec);
    }


    // ---- Pass 7: Top Pick card + Coin Desk tab ----
    if (!$("topPickCard")) {
      const card = document.createElement("div");
      card.id = "topPickCard";
      card.className = "panel";
      card.style.cssText = "margin:12px 18px 0;cursor:pointer;border:1px solid rgba(0,180,255,.45);box-shadow:0 0 24px rgba(176,38,255,.12)";
      card.innerHTML = `<div id="topPickBody"><span class="muted">Loading Top Pick…</span></div>`;
      const hero = $("hero");
      if (hero && hero.parentNode) hero.parentNode.insertBefore(card, hero);
      else document.body.insertBefore(card, document.body.firstChild);
    }
    if (!$("deskTabs")) {
      const tabs = document.createElement("div");
      tabs.id = "deskTabs";
      tabs.style.cssText = "margin:10px 18px 0;display:flex;gap:8px;flex-wrap:wrap;align-items:center";
      tabs.innerHTML = `
        <button type="button" class="tabBtn active" data-tab="overview">Overview</button>
        <button type="button" class="tabBtn" data-tab="coindesk">Coin Desk <span class="badge">Base / hood.fun</span></button>
        <button type="button" class="tabBtn" data-tab="backtest">Backtest</button>
        <span class="muted" style="margin-left:8px">PAPER only · Coin Desk is observe-only (no start/stop)</span>`;
      const tp = $("topPickCard");
      if (tp && tp.parentNode) tp.parentNode.insertBefore(tabs, tp.nextSibling);
      else document.body.insertBefore(tabs, document.body.firstChild);
    }

    // Pass 9: Reset to default view
    if ($("deskTabs") && !$("btnResetView")) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.id = "btnResetView";
      btn.textContent = "Reset to default view";
      btn.title = "Clear hash + localStorage and restore Jeremy's default Overview";
      btn.style.cssText = "margin-left:auto;background:rgba(0,180,255,.12);border:1px solid rgba(0,180,255,.45);color:#dfe9ff;border-radius:999px;padding:6px 14px;cursor:pointer;font-weight:600";
      $("deskTabs").appendChild(btn);
      btn.addEventListener("click", () => resetToDefaultView());
    }

    // Pass 9: Copy Wallets command center (Overview, under banner)
    if (!$("copydeskPanel")) {
      const cd = document.createElement("div");
      cd.id = "copydeskPanel";
      cd.className = "panel";
      cd.style.cssText = "margin:12px 18px 0;border:1px solid rgba(0,180,255,.4);box-shadow:0 0 28px rgba(0,180,255,.08)";
      cd.innerHTML = `
        <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:baseline;justify-content:space-between">
          <h2 style="margin:0">Copy Wallets command center <span class="badge">PAPER · 60s · 0.25 SOL</span></h2>
          <span class="muted" id="cdeskMeta">Loading…</span>
        </div>
        <p class="caption">What am I looking at? Paper copy-trading the roster after a 60s delay at 0.25 SOL with costs. Verdicts are heuristics on score + simulated P&amp;L — not financial advice. LIVE stays disarmed.</p>
        <div class="legendBox" style="margin-top:8px">
          <span><b>COPY-WORTHY</b> = score≥0.6 and +P&amp;L @60s</span>
          <span><b>WATCH</b> = borderline</span>
          <span><b>AVOID</b> = weak / negative</span>
          <span><b>not enough trades</b> = &lt;5 priced sims</span>
          <span class="mk" style="color:#39ffb0">▲ BOUGHT</span>
          <span class="mk" style="color:#ff5d8f">▼ SOLD</span>
          <span>Times = America/Chicago (CT)</span>
          <span>Equity Y = SOL cumulative paper P&amp;L</span>
        </div>
        <div id="cdeskGrid" class="cdeskGrid">
          <div><h3>Leaderboard <span class="infoTip" data-tip="Score from out/scores.json. Copy P&amp;L = paper backtest at 60s delay / 0.25 SOL after costs.">i</span></h3><div id="cdeskLead" style="max-height:340px;overflow:auto"></div></div>
          <div><h3>Live feed <span class="infoTip" data-tip="Recent real buys/sells from history. #top = how many high-score wallets also bought that mint.">i</span></h3><div id="cdeskFeed" style="max-height:340px;overflow:auto"></div></div>
          <div style="grid-column:1/-1"><h3>If you'd copied them (top 5 + combined) <span class="infoTip" data-tip="Paper equity in SOL over time (CT). Combined = sum of top-5 wallet curves.">i</span></h3>
            <canvas id="cdeskEquity" width="1100" height="260" style="width:100%;max-height:280px;background:rgba(4,8,18,.5);border-radius:10px"></canvas>
            <div class="axisNote">X = time (CT) · Y = cumulative paper P&amp;L (SOL) · legend on chart</div>
            <div id="cdeskEqLegend" class="legendBox"></div>
          </div>
          <div style="grid-column:1/-1"><h3>Hot tokens (multi top-wallet) <span class="infoTip" data-tip="Mints bought by 2+ high-score wallets in the last 7 days. Safety flags are rough heuristics from trade sizes.">i</span></h3><div id="cdeskHot"></div></div>
        </div>`;
      const tabs = $("deskTabs");
      if (tabs && tabs.parentNode) tabs.parentNode.insertBefore(cd, tabs.nextSibling);
      else document.body.insertBefore(cd, document.body.firstChild);
    }
    if (!$("pass9css")) {
      const st = document.createElement("style");
      st.id = "pass9css";
      st.textContent = `
        .cdeskGrid{display:grid;grid-template-columns:1.2fr 1fr;gap:14px;margin-top:12px}
        @media(max-width:1400px){.cdeskGrid{grid-template-columns:1fr}}
        .cdeskGrid h3{margin:0 0 8px;font-size:13px;letter-spacing:.4px;color:#00B4FF}
        .verd{font-weight:800;font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid}
        .verd.COPY-WORTHY{color:#39ffb0;border-color:#39ffb0}
        .verd.WATCH{color:#ffd166;border-color:#ffd166}
        .verd.AVOID{color:#ff5d8f;border-color:#ff5d8f}
        .verd.ne{color:#8aa0c0;border-color:#8aa0c0}
        .feedRow{display:flex;gap:8px;align-items:center;padding:6px 4px;border-bottom:1px solid rgba(0,180,255,.1);font-size:12px}
        .feedRow .side.buy{color:#39ffb0;font-weight:800}
        .feedRow .side.sell{color:#ff5d8f;font-weight:800}
        .hotChip{display:inline-block;margin:4px 6px 4px 0;padding:8px 10px;border-radius:10px;border:1px solid rgba(0,180,255,.28);background:rgba(8,14,28,.65);font-size:12px}
        .hotChip .bad{color:#ff5d8f} .hotChip .ok{color:#39ffb0}
      `;
      document.head.appendChild(st);
    }

    if (!$("coindeskPanel")) {
      const cd = document.createElement("div");
      cd.id = "coindeskPanel";
      cd.className = "panel";
      cd.style.cssText = "margin:14px 18px;display:none";
      cd.innerHTML = `
        <h2>Coin Desk <span class="badge">PAPER · Base / hood.fun — NOT Solana</span></h2>
        <p class="muted" id="cdStatus">Checking…</p>
        <div id="cdCards" class="cdGrid"></div>
        <p class="note">Read-only. Start Coin Desk.exe yourself if you want a live board on :3010. TRENCHNET will not start or stop it. No trade controls.</p>`;
      const lower = $("lower");
      if (lower) lower.parentNode.insertBefore(cd, lower);
      else document.body.appendChild(cd);
    }
    if (!$("pass7css")) {
      const st = document.createElement("style");
      st.id = "pass7css";
      st.textContent = `
        #deskTabs .tabBtn{background:rgba(0,180,255,.1);border:1px solid rgba(0,180,255,.35);color:#dfe9ff;border-radius:999px;padding:6px 14px;cursor:pointer;font-weight:600}
        #deskTabs .tabBtn.active{background:linear-gradient(90deg,#00B4FF,#B026FF);color:#041018;border:0}
        #topPickCard .tpHead{display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;justify-content:space-between}
        #topPickCard .tpCall{font-size:28px;font-weight:800;letter-spacing:.5px}
        #topPickCard .tpCall.buy{color:#39ffb0;text-shadow:0 0 14px rgba(57,255,176,.35)}
        #topPickCard .tpCall.watch{color:#ffd166}
        #topPickCard .tpCall.none{color:#8aa0c0}
        #topPickCard .tpMeta{color:#8aa0c0;font-size:12px;margin-top:6px;line-height:1.45}
        #topPickCard .tpStats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin-top:12px}
        #topPickCard .tpStat{background:rgba(0,180,255,.06);border:1px solid rgba(0,180,255,.2);border-radius:10px;padding:8px 10px}
        #topPickCard .tpStat .k{font-size:10px;text-transform:uppercase;color:#8aa0c0;letter-spacing:1px}
        #topPickCard .tpStat .v{font-size:16px;font-weight:700;color:#00B4FF}
        #topPickCard .caveats{margin-top:10px;font-size:11px;color:#ffd166}
        #topPickCard .candRow{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
        #topPickCard .candChip{font-size:11px;padding:4px 8px;border-radius:8px;border:1px solid rgba(0,180,255,.3);background:rgba(8,14,28,.6)}
        #topPickCard .candChip.buy{border-color:#39ffb0;color:#39ffb0}
        #topPickCard .candChip.watch{border-color:#ffd166;color:#ffd166}
        #topPickCard .candChip.avoid{border-color:#ff5d8f;color:#ff5d8f}
        .cdGrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px;margin-top:10px}
        .cdCard{background:rgba(10,18,38,.7);border:1px solid rgba(0,180,255,.22);border-radius:12px;padding:10px 12px}
        .cdCard .call{font-weight:800;font-size:14px}
        .cdCard .call.PASS{color:#39ffb0}
        .cdCard .call.WATCH{color:#ffd166}
        .cdCard .chainTag{font-size:10px;color:#B026FF;letter-spacing:1px;text-transform:uppercase}
      `;
      document.head.appendChild(st);
    }

    // Graph layout toggle
    const gp = $("graphPanel");
    if (gp && !$("graphLayout")) {
      const sel = document.createElement("select");
      sel.id = "graphLayout";
      sel.innerHTML = `<option value="columns">two-column</option><option value="force">force</option>`;
      gp.querySelector(".graphTools, .tools, div")?.appendChild(sel) || gp.appendChild(sel);
    }

    // CSS for new bits
    if (!$("pass5css")) {
      const st = document.createElement("style");
      st.id = "pass5css";
      st.textContent = `
        #filterBar label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:#9db4d8}
        #filterBar input,#filterBar select,.btControls input,.btControls select{background:#0a1226;border:1px solid rgba(0,180,255,.35);color:#dfe9ff;border-radius:8px;padding:6px 8px}
        #filterBar button,.btControls button,#drawerClose,#btnRefresh{background:linear-gradient(90deg,#00B4FF,#B026FF);border:0;color:#041018;font-weight:700;border-radius:8px;padding:8px 12px;cursor:pointer}
        .badge{font-size:11px;padding:2px 8px;border-radius:999px;background:rgba(176,38,255,.2);color:#e9d5ff;border:1px solid rgba(176,38,255,.45);margin-left:8px}
        .muted{color:#8aa0c0;font-size:12px}
        .btControls{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:10px 0}
        .btGrid{display:grid;grid-template-columns:1.2fr 1fr;gap:14px}
        @media(max-width:1200px){.btGrid{grid-template-columns:1fr}}
        #drawer{position:fixed;inset:0;background:rgba(2,4,12,.55);display:none;z-index:50;justify-content:flex-end}
        #drawer.open{display:flex}
        #drawer .drawerInner{width:min(520px,92vw);height:100%;background:linear-gradient(180deg,rgba(10,18,38,.96),rgba(8,10,24,.98));border-left:1px solid rgba(0,180,255,.35);padding:16px;overflow:auto;box-shadow:0 0 40px rgba(176,38,255,.15)}
        #drawerClose{float:right}
        table.int{width:100%;border-collapse:collapse;font-size:12px}
        table.int th,table.int td{padding:6px 8px;border-bottom:1px solid rgba(0,180,255,.15);text-align:left}
        table.int th{cursor:pointer;color:#00B4FF;position:sticky;top:0;background:#0a1226}
        table.int tr:hover{background:rgba(0,180,255,.08);cursor:pointer}
        .pager{display:flex;gap:8px;align-items:center;margin-top:8px}
        #scoreTableWrap,#delayTable,#wfPanel,#btLiveSummary{max-height:320px;overflow:auto}
      `;
      document.head.appendChild(st);
    }
  }

  function bindFilters() {
    $("fApply")?.addEventListener("click", () => {
      state.filters.qWallet = $("fWallet").value.trim();
      state.filters.qToken = $("fToken").value.trim();
      state.filters.minSol = parseFloat($("fMinSol").value || "0") || 0;
      state.filters.source = $("fSource").value;
      state.filters.t0 = $("fT0").value ? Number($("fT0").value) : null;
      state.filters.t1 = $("fT1").value ? Number($("fT1").value) : null;
      state.page.buy = 0; state.page.events = 0;
      writeHash(); renderAll();
    });
    $("fClear")?.addEventListener("click", () => {
      state.filters = { qWallet: "", qToken: "", minSol: 0, source: "all", t0: null, t1: null };
      ["fWallet","fToken","fMinSol","fT0","fT1"].forEach(id => { if ($(id)) $(id).value = id==="fMinSol"?"0":""; });
      if ($("fSource")) $("fSource").value = "all";
      writeHash(); renderAll();
    });
    $("drawerClose")?.addEventListener("click", () => closeDrawer());
    $("btnRefresh")?.addEventListener("click", () => location.reload());
    $("graphLayout")?.addEventListener("change", (e) => {
      state.layout = e.target.value; writeHash();
      window.dispatchEvent(new CustomEvent("trenchnet:layout", { detail: state.layout }));
    });
  }

  function bindBacktestSliders() {
    const map = [
      ["btDelay","btDelayV", v => (state.backtest.delay = +v, v)],
      ["btSize","btSizeV", v => (state.backtest.sizeSol = +v, Number(v).toFixed(2))],
      ["btSlip","btSlipV", v => (state.backtest.slipMult = +v, Number(v).toFixed(1))],
      ["btTp","btTpV", v => (state.backtest.tp = +v, Math.round(v*100)+"%")],
      ["btSl","btSlV", v => (state.backtest.sl = +v, Math.round(v*100)+"%")],
      ["btTstop","btTstopV", v => (state.backtest.tstop = +v, v)],
    ];
    map.forEach(([id, vid, fn]) => {
      const el = $(id); if (!el) return;
      el.value = state.backtest[{btDelay:"delay",btSize:"sizeSol",btSlip:"slipMult",btTp:"tp",btSl:"sl",btTstop:"tstop"}[id]];
      $(vid).textContent = fn(el.value);
      el.addEventListener("input", () => { $(vid).textContent = fn(el.value); writeHash(); renderBacktestLive(); });
    });
    $("btMode")?.addEventListener("change", (e) => { state.backtest.mode = e.target.value; writeHash(); renderBacktestLive(); });
  }

  function costsFrac(liq, slipMult) {
    const fee = 100 / 10000;
    let slipBps = 800;
    if (liq && liq > 0) {
      const scale = Math.max(0.25, Math.min(8, 1.0 / liq));
      slipBps = Math.min(800, 50 * scale);
    }
    slipBps *= Math.max(0, slipMult);
    return { fee, slip: slipBps / 10000, prio: 0.00005 };
  }

  function recomputeFromTrades() {
    const trades = D().backtest_trades || [];
    const bt = state.backtest;
    const byDelay = { 0: [], 30: [], 60: [], 120: [] };
    const walletPnl = {};
    let priced = 0, total = 0;
    trades.forEach(tr => {
      // filter by wallet/token if set
      if (state.filters.qWallet) {
        const q = state.filters.qWallet.toLowerCase();
        if (!(tr.wallet || "").toLowerCase().includes(q)) return;
      }
      if (state.filters.qToken) {
        const q = state.filters.qToken.toLowerCase();
        if (!(tr.token_mint || "").toLowerCase().includes(q)) return;
      }
      if (state.filters.source !== "all" && tr.buy_source && tr.buy_source !== state.filters.source) return;

      const path = tr.path || [];
      function pxAtDelay(d) {
        let best = null;
        path.forEach(p => {
          if (p.delay === d) best = p;
          else if (p.delay != null && Math.abs(p.delay - d) < 6) best = best || p;
        });
        if (best) return best;
        // nearest fwd/sell by time
        const target = (tr.buy_time || 0) + d;
        let nearest = null, dist = 1e18;
        path.forEach(p => {
          const dd = Math.abs((p.t || 0) - target);
          if (dd < dist) { dist = dd; nearest = p; }
        });
        return (nearest && dist <= 3600) ? nearest : null;
      }

      [0, 30, 60, 120].forEach(d => {
        total += 1;
        const entry = pxAtDelay(d);
        if (!entry) { byDelay[d].push(null); return; }
        let exitPx = null;
        if (bt.mode === "mirror") {
          const sells = path.filter(p => p.kind === "sell");
          if (!sells.length) { byDelay[d].push(null); return; }
          // pick sell closest after entry
          const after = sells.filter(s => s.t >= entry.t).sort((a,b)=>a.t-b.t);
          exitPx = (after[0] || sells[sells.length - 1]).px;
        } else {
          const deadline = entry.t + bt.tstop;
          const fwd = path.filter(p => p.t >= entry.t && p.t <= deadline).sort((a,b)=>a.t-b.t);
          let hit = null;
          for (let i = 0; i < fwd.length; i++) {
            const ret = fwd[i].px / entry.px - 1;
            if (ret >= bt.tp) { hit = fwd[i]; break; }
            if (ret <= -bt.sl) { hit = fwd[i]; break; }
          }
          if (hit) exitPx = hit.px;
          else if (fwd.length) exitPx = fwd[fwd.length - 1].px;
        }
        if (exitPx == null || !(entry.px > 0)) { byDelay[d].push(null); return; }
        const gross = exitPx / entry.px - 1;
        const c = costsFrac(tr.liq_proxy_sol, bt.slipMult);
        const pos = bt.sizeSol;
        const costs = pos * (c.fee + c.slip) + Math.abs(pos * (1 + gross)) * (c.fee + c.slip) + 2 * c.prio;
        const pnl = pos * gross - costs;
        const net = pnl / pos;
        priced += 1;
        byDelay[d].push(net);
        if (d === bt.delay) {
          walletPnl[tr.wallet] = (walletPnl[tr.wallet] || 0) + pnl;
        }
      });
    });
    return { byDelay, walletPnl, priced, total };
  }

  function renderBacktestLive() {
    const bt = D().backtest || {};
    const sc = D().scores || {};
    const cov = bt.overall || {};
    if ($("btCoverage")) {
      const cb = (bt.coverage_by || {});
      const tok = (cb.tokens || []).slice(0, 5).map(x =>
        (x.token_mint || "").slice(0, 6) + "… " + fmt(x.coverage_pct, 1) + "%" + (x.has_pool_series ? " pool" : "")
      ).join("; ");
      const pool = D().pool_coverage || {};
      const poolNote = pool.ok ? (`pool mints ok=${(pool.ok||[]).length||pool.ok} failed=${(pool.failed||[]).length||0}`) :
        (typeof pool.ok === "number" ? `pool ok=${pool.ok} failed=${pool.failed||0}` :
        `pool ok=${(pool.ok||[]).length} failed=${(pool.failed||[]).length}`);
      $("btCoverage").innerHTML =
        `Server coverage <b>${fmt(cov.coverage_pct, 2)}%</b> priceable ` +
        `(${cov.n_priced || 0}/${cov.n_copies || 0}). Sources: ${JSON.stringify(cov.price_sources || {})}. ` +
        `${poolNote}. Unpriceable excluded — never invented. ` +
        (tok ? `<div class="muted">Top token coverage @60s: ${tok}</div>` : "");
    }
    const live = recomputeFromTrades();
    const rows = [0, 30, 60, 120].map(d => {
      const xs = (live.byDelay[d] || []).filter(x => x != null);
      const mean = xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
      const wins = xs.filter(x => x > 0).length;
      return { d, n: xs.length, mean, wr: xs.length ? wins / xs.length : null };
    });
    if ($("delayTable")) {
      $("delayTable").innerHTML = `<table class="int"><thead><tr><th>delay</th><th>n</th><th>mean ret</th><th>win</th></tr></thead><tbody>` +
        rows.map(r => `<tr><td>${r.d}s</td><td>${r.n}</td><td>${fmt(r.mean, 4)}</td><td>${fmt(r.wr, 3)}</td></tr>`).join("") +
        `</tbody></table>`;
    }
    const cv = $("delayChart");
    if (cv && window.TrenchCharts) {
      const chart = cv._chart || (cv._chart = new TrenchCharts.Chart(cv, { color: "#B026FF" }));
      chart.setSeries(rows.filter(r => r.mean != null).map(r => ({ x: r.d, y: r.mean, label: r.d + "s" })));
    }
    const liveN = (live.byDelay[state.backtest.delay] || []).filter(x => x != null);
    const livePnl = Object.values(live.walletPnl).reduce((a, b) => a + b, 0);
    if ($("btLiveSummary")) {
      $("btLiveSummary").innerHTML =
        `<p><b>Delay ${state.backtest.delay}s</b> · size ${state.backtest.sizeSol} SOL · mode ${state.backtest.mode}</p>` +
        `<p>Priced copies (browser): ${liveN.length} · mean ret ${fmt(liveN.length? liveN.reduce((a,b)=>a+b,0)/liveN.length: null,4)} · Σ wallet PnL ${fmt(livePnl,4)} SOL</p>` +
        `<p class="muted">Browser recompute uses precomputed per-trade price paths only. No Helius/Birdeye calls from the browser.</p>`;
    }
    // WF panel
    const wf = bt.walk_forward || {};
    if ($("wfPanel")) {
      if (wf.status === "ok") {
        $("wfPanel").innerHTML = `<p>status ok · mean Spearman ${fmt(wf.mean_spearman, 3)} · span ${fmt(wf.span_days, 1)}d</p>` +
          `<pre style="white-space:pre-wrap;font-size:11px">${JSON.stringify(wf.folds || [], null, 2)}</pre>`;
      } else {
        $("wfPanel").innerHTML = `<p><b>insufficient data</b></p><p class="muted">${wf.reason || "n/a"}</p>` +
          (wf.span_days != null ? `<p>span_days=${fmt(wf.span_days, 2)} n_pairs=${wf.n_pairs || "?"}</p>` : "");
      }
    }
    // score leaderboard with live pnl overlay
    renderScoreTable(live.walletPnl);
  }

  function renderScoreTable(livePnlMap) {
    const wallets = (D().scores || {}).wallets || [];
    const q = (state.filters.qWallet || "").toLowerCase();
    let rows = wallets.filter(w => !q || (w.label || "").toLowerCase().includes(q) || (w.wallet || "").toLowerCase().includes(q));
    const sortKey = state._scoreSort || "score";
    const dir = state._scoreDir || -1;
    rows = rows.slice().sort((a, b) => {
      const av = sortKey === "live_pnl" ? (livePnlMap[a.wallet] || 0) : (a[sortKey] ?? a.raw?.[sortKey] ?? 0);
      const bv = sortKey === "live_pnl" ? (livePnlMap[b.wallet] || 0) : (b[sortKey] ?? b.raw?.[sortKey] ?? 0);
      return (av === bv ? 0 : (av > bv ? 1 : -1)) * dir;
    });
    const start = state.page.score * state.pageSize;
    const page = rows.slice(start, start + state.pageSize);
    const html = `<table class="int"><thead><tr>
      <th data-k="rank">#</th><th data-k="label">wallet</th><th data-k="score">score</th>
      <th data-k="copy_pnl">copy PnL 60s</th><th data-k="live_pnl">live slider PnL</th><th data-k="oos_flag">OOS</th>
    </tr></thead><tbody>` + page.map(r => `<tr data-wallet="${r.wallet}">
      <td>${r.rank}</td><td>${r.label}<div class="muted">${short(r.wallet)}</div></td>
      <td>${fmt(r.score, 3)}</td><td>${fmt(r.raw?.copy_pnl_60s_sol, 4)}</td>
      <td>${fmt(livePnlMap[r.wallet], 4)}</td><td>${r.oos_flag}</td></tr>`).join("") +
      `</tbody></table>
      <div class="pager"><button type="button" id="scorePrev">Prev</button>
      <span>${start + 1}–${Math.min(start + state.pageSize, rows.length)} / ${rows.length}</span>
      <button type="button" id="scoreNext">Next</button></div>`;
    const wrap = $("scoreTableWrap");
    if (!wrap) return;
    wrap.innerHTML = html;
    wrap.querySelectorAll("th").forEach(th => th.addEventListener("click", () => {
      const k = th.getAttribute("data-k");
      if (k === "label" || k === "oos_flag") state._scoreSort = k;
      else if (k === "copy_pnl") state._scoreSort = "copy_pnl";
      else state._scoreSort = k;
      // map
      if (k === "copy_pnl") {
        rows.sort((a,b)=> ((a.raw?.copy_pnl_60s_sol||0)-(b.raw?.copy_pnl_60s_sol||0)) * (state._scoreDir|| -1));
      }
      state._scoreDir = (state._scoreSort === k) ? -(state._scoreDir || -1) : -1;
      state._scoreSort = k === "copy_pnl" ? "score" : k; // simplify
      if (k === "live_pnl") state._scoreSort = "live_pnl";
      if (k === "score") state._scoreSort = "score";
      if (k === "rank") state._scoreSort = "rank";
      renderScoreTable(livePnlMap);
    }));
    wrap.querySelectorAll("tr[data-wallet]").forEach(tr => tr.addEventListener("click", () => openDrawer("wallet", tr.getAttribute("data-wallet"))));
    $("scorePrev")?.addEventListener("click", () => { state.page.score = Math.max(0, state.page.score - 1); renderScoreTable(livePnlMap); });
    $("scoreNext")?.addEventListener("click", () => { state.page.score++; renderScoreTable(livePnlMap); });
  }

  function openDrawer(kind, id) {
    state.selected = { kind, id };
    writeHash();
    const dr = $("drawer"); const body = $("drawerBody");
    if (!dr || !body) return;
    const evs = filteredEvents().filter(e => kind === "wallet" ? e.wallet === id : e.token_mint === id).slice(0, 80);
    const score = ((D().scores || {}).wallets || []).find(w => w.wallet === id);
    const btW = ((D().backtest || {}).wallets || []).find(w => w.wallet === id);
    let html = `<h2>${kind}: ${score?.label || short(id)}</h2><p class="muted">${id}</p>`;
    if (score) {
      html += `<h3>Score ${fmt(score.score, 3)} (rank ${score.rank}) · OOS ${score.oos_flag}</h3>
        <pre style="font-size:11px;white-space:pre-wrap">${JSON.stringify(score.features, null, 2)}</pre>
        <pre style="font-size:11px;white-space:pre-wrap">${JSON.stringify(score.raw, null, 2)}</pre>`;
    }
    if (btW) {
      html += `<h3>Backtest @60s</h3><p>copy PnL ${fmt(btW.copy_pnl_60s,4)} SOL · win ${fmt(btW.win_rate_60s,3)} · coverage ${fmt(btW.coverage_60s,1)}%</p>`;
    }
    html += `<h3>Trades (filtered)</h3><table class="int"><thead><tr><th>time</th><th>side</th><th>mint</th><th>SOL</th><th>src</th></tr></thead><tbody>` +
      evs.map(e => `<tr><td>${e.block_time||""}</td><td>${e.side}</td><td>${short(e.token_mint)}</td><td>${fmt(e.amount_sol,4)}</td><td>${e.source||""}</td></tr>`).join("") +
      `</tbody></table>`;
    html += `<h3>Price path</h3><canvas id="drawerChart" width="460" height="200"></canvas>`;
    body.innerHTML = html;
    dr.classList.add("open");
    // chart from backtest trade paths for this wallet/token
    const paths = (D().backtest_trades || []).filter(t => kind === "wallet" ? t.wallet === id : t.token_mint === id);
    const pts = [];
    const markers = [];
    paths.slice(0, 5).forEach(tr => {
      (tr.path || []).forEach(p => pts.push({ x: p.t, y: p.px, label: p.source }));
    });
    evs.forEach(e => {
      if (e.block_time && e.amount_sol && e.amount_token) {
        markers.push({ x: e.block_time, y: e.amount_sol / e.amount_token, side: e.side });
      }
    });
    const cv = $("drawerChart");
    if (cv && window.TrenchCharts) {
      const ch = new TrenchCharts.Chart(cv, { color: "#00B4FF", markers });
      ch.setSeries(pts);
    }
  }
  function closeDrawer() {
    $("drawer")?.classList.remove("open");
    state.selected = null; writeHash();
  }

  function enhanceBuyTable() {
    const table = $("buyTable");
    if (!table) return;
    // rebuild from filtered events aggregation
    const buys = {};
    filteredEvents().filter(e => e.side === "buy").forEach(e => {
      const m = e.token_mint; if (!m) return;
      if (!buys[m]) buys[m] = { mint: m, n: 0, sol: 0, wallets: new Set() };
      buys[m].n += 1;
      buys[m].sol += e.amount_sol || 0;
      buys[m].wallets.add(e.wallet);
    });
    let rows = Object.values(buys).map(r => ({ ...r, wc: r.wallets.size }));
    rows.sort((a, b) => b.n - a.n);
    const start = state.page.buy * state.pageSize;
    const page = rows.slice(start, start + state.pageSize);
    const thead = table.querySelector("thead");
    if (thead) thead.innerHTML = `<tr><th>token</th><th>buys</th><th>Σ SOL</th><th>wallets</th></tr>`;
    let tb = table.querySelector("tbody");
    if (!tb) { tb = document.createElement("tbody"); table.appendChild(tb); }
    tb.innerHTML = page.map(r => `<tr data-token="${r.mint}"><td>${short(r.mint)}</td><td>${r.n}</td><td>${fmt(r.sol,3)}</td><td>${r.wc}</td></tr>`).join("");
    tb.querySelectorAll("tr").forEach(tr => tr.addEventListener("click", () => openDrawer("token", tr.getAttribute("data-token"))));
  }

  function renderAll() {
    enhanceBuyTable();
    renderBacktestLive();
    // expose filter to graph via event
    window.dispatchEvent(new CustomEvent("trenchnet:filters", { detail: { ...state.filters, events: filteredEvents() } }));
    if (state.selected) openDrawer(state.selected.kind, state.selected.id);
  }

  function startPolling() {
    const served = location.protocol.startsWith("http");
    if (!served) {
      if ($("freshness")) $("freshness").textContent = "file:// static · sliders use baked data";
      return;
    }
    const tick = async () => {
      try {
        const r = await fetch("/api/data-version");
        const j = await r.json();
        const ver = j.version;
        const ago = j.mtime?.data_js ? Math.round((Date.now() / 1000) - j.mtime.data_js) : null;
        if ($("freshness")) $("freshness").textContent = ago != null ? `updated ${ago}s ago · v ${ver}` : `v ${ver}`;
        if (state.lastVersion && ver && ver !== state.lastVersion) {
          if ($("freshness")) $("freshness").textContent += " · refresh available";
        }
        state.lastVersion = ver || state.lastVersion;
      } catch (e) {
        if ($("freshness")) $("freshness").textContent = "poll failed (local only)";
      }
    };
    tick();
    state.pollTimer = setInterval(tick, 45000);
  }

  // Hook existing graph hover tip to open drawer on click if possible
  function hookGraphClicks() {
    const cv = $("graph");
    if (!cv) return;
    cv.addEventListener("click", () => {
      const tip = $("graphTip");
      // best-effort: if selection API exposed
      if (window.__TN_HOVER_NODE) {
        const n = window.__TN_HOVER_NODE;
        openDrawer(n.kind === "token" ? "token" : "wallet", n.id);
      }
    });
  }


  function setTab(name) {
    state.tab = name || "overview";
    document.querySelectorAll("#deskTabs .tabBtn").forEach(b => {
      b.classList.toggle("active", b.getAttribute("data-tab") === state.tab);
    });
    const overview = [$("filterBar"), $("hero"), document.querySelector(".grid"), $("lower"), $("copydeskPanel"), $("nowStrip")];
    overview.forEach(el => { if (el) el.style.display = (state.tab === "overview") ? "" : "none"; });
    const honesty = $("honesty");
    if (honesty) honesty.style.display = (state.tab === "overview") ? "" : "none";
    const bt = $("backtestSection");
    if (bt) bt.style.display = (state.tab === "backtest" || state.tab === "overview") ? "" : "none";
    if (bt && state.tab === "coindesk") bt.style.display = "none";
    const cd = $("coindeskPanel");
    if (cd) cd.style.display = (state.tab === "coindesk") ? "" : "none";
    // Top pick always visible
    const tp = $("topPickCard");
    if (tp) tp.style.display = "";
    writeHash();
  }

  function fmtPct(x) {
    if (x == null || isNaN(x)) return "—";
    return (Number(x) * 100).toFixed(1) + "%";
  }

  function renderTopPick(payload) {
    const body = $("topPickBody");
    if (!body) return;
    const P = payload || (D().top_pick) || {};
    const headline = P.headline || "No buy right now";
    const reason = P.headline_reason || P.reason || "Waiting for pick engine.";
    const callClass = headline.startsWith("BUY") ? "buy" : (headline.includes("WATCH") ? "watch" : "none");
    const tp = P.top_pick || null;
    const bt = P.backtested_track_record || {};
    const live = P.live_logged_track_record || {};
    const cd = P.coindesk_summary || {};
    const byH = bt.by_horizon || {};
    const hOrder = ["900", "3600", "14400", "86400"];
    const hLabel = { "900": "+15m", "3600": "+1h", "14400": "+4h", "86400": "+24h" };
    let stats = "";
    stats += `<div class="tpStat"><div class="k">Backtested picks</div><div class="v">${bt.n != null ? bt.n : (P.backtested_n || 0)}</div></div>`;
    stats += `<div class="tpStat"><div class="k">Win rate (1h)</div><div class="v">${bt.win_rate == null ? "—" : fmtPct(bt.win_rate)}</div></div>`;
    hOrder.forEach(h => {
      const cell = byH[h] || {};
      stats += `<div class="tpStat"><div class="k">Med ${hLabel[h]}</div><div class="v">${fmtPct(cell.median)}</div></div>`;
      stats += `<div class="tpStat"><div class="k">Mean ${hLabel[h]}</div><div class="v">${fmtPct(cell.mean)}</div></div>`;
    });
    const worst = (bt.worst || {}).token_mint;
    stats += `<div class="tpStat"><div class="k">Worst pick</div><div class="v" style="font-size:12px">${worst ? short(worst) : "—"}</div></div>`;
    stats += `<div class="tpStat"><div class="k">Live-logged</div><div class="v">${live.n_logged != null ? live.n_logged : (P.live_logged_n || 0)}</div></div>`;
    stats += `<div class="tpStat"><div class="k">Coin Desk</div><div class="v" style="font-size:12px">${cd.status || "—"} · Base</div></div>`;

    let chips = "";
    (P.candidates || []).slice(0, 12).forEach(c => {
      const cls = (c.call || "").startsWith("BUY") ? "buy" : (c.call === "WATCH" ? "watch" : "avoid");
      chips += `<span class="candChip ${cls}" data-mint="${c.token_mint || ""}">${c.call}: ${short(c.token_mint)} · conf ${fmt(c.confidence, 2)}</span>`;
    });

    const entry = tp ? `Entry ${tp.entry_price != null ? Number(tp.entry_price).toExponential(3) : "—"} ${tp.entry_unit || ""} @ ${tp.call_time_iso || tp.call_time || "—"}` : "";
    const caveats = (P.caveats || [
      "PAPER only — not financial advice.",
      "Small sample.",
      "Walk-forward: " + (P.walk_forward_status || "unknown"),
    ]).map(c => "• " + c).join("<br/>");

    body.innerHTML = `
      <div class="tpHead">
        <div>
          <div class="k" style="color:#8aa0c0;font-size:11px;letter-spacing:1px;text-transform:uppercase">Top Pick · Solana / pump.fun · PAPER</div>
          <div class="tpCall ${callClass}">${headline}</div>
        </div>
        <div class="muted">WF: ${P.walk_forward_status || "—"} · click opens drawer</div>
      </div>
      <div class="tpMeta">${reason}${entry ? "<br/>" + entry : ""}</div>
      <div class="tpStats">${stats}</div>
      <div class="candRow">${chips || '<span class="muted">No candidate chips</span>'}</div>
      <div class="caveats">${caveats}<br/>• Coin Desk PASS/WATCH is a separate Base-chain input (not merged into Solana BUY).</div>`;

    body.querySelectorAll(".candChip[data-mint]").forEach(el => {
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const m = el.getAttribute("data-mint");
        if (m) openDrawer("token", m);
      });
    });
  }

  async function loadTopPick() {
    try {
      const r = await fetch("/api/picks");
      if (!r.ok) throw new Error("picks " + r.status);
      const j = await r.json();
      window.__TN_TOP_PICK = j;
      renderTopPick(j);
    } catch (e) {
      renderTopPick(D().top_pick || { headline: "No buy right now", headline_reason: "Top Pick API unavailable: " + e, caveats: ["PAPER only"] });
    }
  }

  async function loadCoinDesk() {
    const stEl = $("cdStatus");
    const wrap = $("cdCards");
    if (!stEl || !wrap) return;
    try {
      const r = await fetch("/api/coindesk/state");
      const j = await r.json();
      const status = j.status || "unknown";
      const asof = j.as_of_utc || "";
      stEl.textContent = status === "live"
        ? `LIVE on :3010 · as of ${asof} · ${j.label || "Base / hood.fun"}`
        : `${j.note || ("offline, data as of " + asof)}`;
      const cards = j.cards || [];
      if (!cards.length) {
        wrap.innerHTML = `<div class="empty">No Coin Desk cards. Desk offline and no decisions.jsonl rows.</div>`;
        return;
      }
      wrap.innerHTML = cards.slice(0, 40).map(c => {
        const call = c.call || "UNKNOWN";
        return `<div class="cdCard">
          <div class="chainTag">Base / hood.fun · PAPER</div>
          <div class="call ${call}">${call}</div>
          <div><b>${c.symbol || "—"}</b> · ${c.name || ""}</div>
          <div class="muted mono" style="font-size:11px">${c.address || ""}</div>
          <div class="muted" style="margin-top:6px;font-size:12px">${c.reason || ""}</div>
          <div class="muted" style="font-size:11px">age ${c.age_sec != null ? c.age_sec + "s" : "—"} · eth ${c.real_eth != null ? c.real_eth : "—"} · ${c.logged_at_iso || ""}</div>
          <div style="margin-top:6px">${c.link_basescan ? `<a href="${c.link_basescan}" target="_blank" rel="noopener">BaseScan</a>` : ""} ${c.link_hood ? ` · <a href="${c.link_hood}" target="_blank" rel="noopener">hood.fun</a>` : ""}</div>
        </div>`;
      }).join("");
    } catch (e) {
      stEl.textContent = "Coin Desk fetch error: " + e;
    }
  }


  function ensureHotTakesPanel() {
    if ($("hotTakesPanel")) return;
    const panel = document.createElement("aside");
    panel.id = "hotTakesPanel";
    panel.className = "htPanel";
    panel.innerHTML = `
      <div class="htHead">
        <button type="button" id="htToggle" title="Collapse">⟨</button>
        <div>
          <div class="htTitle">Hot Takes <span class="badge">PAPER</span></div>
          <div class="muted" style="font-size:11px">Opportunity side window · not advice</div>
        </div>
      </div>
      <div class="htBody">
        <p class="htUpfront" id="htUpfront">Checks for new Hot Takes every 5 minutes, so alerts can lag up to 5 min. Paper tracking only.</p>
        <div class="htTiming" id="htTiming"><span id="htNext">Next check: —</span> · <span id="htLast">Last checked: —</span></div>
        <p class="htCaption">Paper tracking only. Not financial advice.</p>
        <div id="htScoreboard" class="htBoard"></div>
        <div class="htFilters">
          <button type="button" class="htFilt active" data-f="all">All</button>
          <button type="button" class="htFilt" data-f="open">Open</button>
          <button type="button" class="htFilt" data-f="closed">Closed</button>
          <button type="button" class="htFilt" data-f="wins">Wins</button>
          <button type="button" class="htFilt" data-f="losses">Losses</button>
        </div>
        <div id="htFeed" class="htFeed"></div>
        <div class="muted" id="htTracker" style="font-size:11px;margin-top:8px"></div>
      </div>`;
    document.body.appendChild(panel);
    if (!$("pass8css")) {
      const st = document.createElement("style");
      st.id = "pass8css";
      st.textContent = `
        .htPanel{position:fixed;top:48px;right:0;width:min(420px,36vw);max-height:calc(100vh - 56px);
          background:linear-gradient(180deg,rgba(10,18,38,.97),rgba(6,8,20,.98));border:1px solid rgba(0,180,255,.35);
          border-right:0;border-radius:14px 0 0 14px;z-index:45;display:flex;flex-direction:column;
          box-shadow:0 0 40px rgba(176,38,255,.18);backdrop-filter:blur(10px);transition:transform .2s ease}
        .htPanel.collapsed{transform:translateX(calc(100% - 42px))}
        .htPanel.collapsed .htBody{opacity:0;pointer-events:none}
        .htHead{display:flex;gap:10px;align-items:center;padding:10px 12px;border-bottom:1px solid rgba(0,180,255,.2)}
        .htTitle{font-weight:800;color:#00B4FF;letter-spacing:.5px}
        #htToggle{background:rgba(0,180,255,.15);border:1px solid rgba(0,180,255,.4);color:#dfe9ff;border-radius:8px;width:32px;height:32px;cursor:pointer;font-weight:700}
        .htBody{padding:10px 12px 14px;overflow:auto;flex:1}
        .htCaption{color:#ffd166;font-size:11px;margin:0 0 8px}
        .htUpfront{color:#00B4FF;font-size:12px;font-weight:700;margin:0 0 6px;line-height:1.35;padding:8px 10px;border:1px solid rgba(0,180,255,.4);border-radius:10px;background:rgba(0,180,255,.08)}
        .htTiming{color:#8aa0c0;font-size:11px;margin:0 0 8px;font-variant-numeric:tabular-nums}
        .htBoard{display:grid;grid-template-columns:repeat(2,1fr);gap:6px;margin-bottom:10px}
        .htStat{background:rgba(0,180,255,.06);border:1px solid rgba(0,180,255,.2);border-radius:10px;padding:6px 8px}
        .htStat .k{font-size:9px;text-transform:uppercase;color:#8aa0c0;letter-spacing:1px}
        .htStat .v{font-size:14px;font-weight:700;color:#00B4FF}
        .htFilters{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
        .htFilt{background:rgba(0,180,255,.08);border:1px solid rgba(0,180,255,.3);color:#dfe9ff;border-radius:999px;padding:3px 9px;font-size:11px;cursor:pointer}
        .htFilt.active{background:linear-gradient(90deg,#00B4FF,#B026FF);border:0;color:#041018;font-weight:700}
        .htFeed{display:flex;flex-direction:column;gap:8px;max-height:55vh;overflow:auto}
        .htCard{border:1px solid rgba(0,180,255,.22);border-radius:12px;padding:8px 10px;background:rgba(8,14,28,.75)}
        .htCard .mint{font-family:Consolas,monospace;font-size:11px;color:#B026FF}
        .htChips{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
        .htChip{font-size:10px;padding:2px 6px;border-radius:999px;border:1px solid rgba(0,180,255,.3);color:#8aa0c0}
        .htChip.WIN{border-color:#39ffb0;color:#39ffb0;background:rgba(57,255,176,.08)}
        .htChip.LOSS{border-color:#ff5d8f;color:#ff5d8f;background:rgba(255,93,143,.08)}
        .htChip.UNPRICED{border-color:#8aa0c0;color:#8aa0c0}
        .htChip.pending{border-color:#ffd166;color:#ffd166}
        .htFlag{font-size:10px;padding:1px 6px;border-radius:6px;margin-right:4px}
        .htFlag.bad{background:rgba(255,93,143,.15);color:#ff5d8f;border:1px solid rgba(255,93,143,.4)}
        .htFlag.warn{background:rgba(255,209,102,.12);color:#ffd166;border:1px solid rgba(255,209,102,.35)}
        .htFlag.ok{background:rgba(57,255,176,.1);color:#39ffb0;border:1px solid rgba(57,255,176,.35)}
        .htWallets{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
        .htWallets button{font-size:10px;padding:2px 6px;border-radius:6px;border:1px solid rgba(0,180,255,.35);background:rgba(0,180,255,.08);color:#00B4FF;cursor:pointer}
        @media (max-width:1920px){
          .htPanel{width:min(380px,42vw)}
        }
        @media (max-width:1400px){
          .htPanel{top:auto;bottom:0;right:0;left:0;width:100%;max-height:48vh;border-radius:14px 14px 0 0;border-right:1px solid rgba(0,180,255,.35)}
          .htPanel.collapsed{transform:translateY(calc(100% - 44px))}
          .htFeed{max-height:28vh}
        }
      `;
      document.head.appendChild(st);
    }
    state.htFilter = "all";
    state.htCollapsed = false;
  }

  function htHorizonLabel(h) {
    const m = { "900": "+15m", "3600": "+1h", "14400": "+4h", "86400": "+24h" };
    return m[String(h)] || ("+" + h + "s");
  }

  function renderHotTakes(payload) {
    ensureHotTakesPanel();
    const P = payload || window.__TN_HOTTAKES || {};
    const live = P.live_scoreboard || {};
    const bt = P.backtested_scoreboard || {};
    const byH = live.by_horizon || {};
    const board = $("htScoreboard");
    if (board) {
      const h1 = byH["3600"] || {};
      board.innerHTML = `
        <div class="htStat"><div class="k">Total live</div><div class="v">${live.total || 0}</div></div>
        <div class="htStat"><div class="k">Open</div><div class="v">${live.open || 0}</div></div>
        <div class="htStat"><div class="k">Closed</div><div class="v">${live.closed || 0}</div></div>
        <div class="htStat"><div class="k">Win rate 1h</div><div class="v">${h1.win_rate == null ? "—" : (h1.win_rate*100).toFixed(0)+"%"}</div></div>
        <div class="htStat"><div class="k">Med net 1h</div><div class="v">${h1.median_net == null ? "—" : (h1.median_net*100).toFixed(1)+"%"}</div></div>
        <div class="htStat"><div class="k">Mean net 1h</div><div class="v">${h1.mean_net == null ? "—" : (h1.mean_net*100).toFixed(1)+"%"}</div></div>
        <div class="htStat"><div class="k">Best 1h</div><div class="v">${h1.best == null ? "—" : (h1.best*100).toFixed(1)+"%"}</div></div>
        <div class="htStat"><div class="k">Worst 1h</div><div class="v">${h1.worst == null ? "—" : (h1.worst*100).toFixed(1)+"%"}</div></div>
        <div class="htStat" style="grid-column:1/-1"><div class="k">Backtested Hot Takes (ref)</div><div class="v" style="font-size:12px">n=${P.backtested_n || bt.total || 0} · 1h WR ${(bt.by_horizon&&bt.by_horizon["3600"]&&bt.by_horizon["3600"].win_rate)!=null ? ((bt.by_horizon["3600"].win_rate)*100).toFixed(0)+"%" : "—"}</div></div>`;
    }
    const filt = state.htFilter || "all";
    const takes = (P.takes || []).filter(t => {
      if (filt === "open") return t.status === "open";
      if (filt === "closed") return t.status === "closed";
      if (filt === "wins") {
        const o = t.outcomes || {};
        return Object.values(o).some(c => c && c.result === "WIN");
      }
      if (filt === "losses") {
        const o = t.outcomes || {};
        return Object.values(o).some(c => c && c.result === "LOSS");
      }
      return true;
    });
    const feed = $("htFeed");
    if (feed) {
      if (!takes.length) {
        feed.innerHTML = `<div class="empty">No Hot Takes yet — tracker is watching. Zero is honest.</div>`;
      } else {
        const hOrder = ["900","3600","14400","86400"];
        feed.innerHTML = takes.map(t => {
          const flags = t.flags || {};
          let flagHtml = "";
          Object.keys(flags).forEach(k => {
            const f = flags[k] || {};
            const cls = f.ok === true ? "ok" : (f.ok === false ? "bad" : "warn");
            flagHtml += `<span class="htFlag ${cls}">${k}:${f.ok===true?"pass":(f.ok===false?"fail":"?")}</span>`;
          });
          const outcomes = t.outcomes || {};
          const chips = hOrder.map(h => {
            const c = outcomes[h];
            if (!c) return `<span class="htChip pending">${htHorizonLabel(h)} …</span>`;
            return `<span class="htChip ${c.result}">${htHorizonLabel(h)} ${c.result}</span>`;
          }).join("");
          const wallets = (t.trigger_wallets || []).map(w =>
            `<button type="button" data-w="${w}">${short(w)}</button>`).join("");
          const livePnL = t.live_gross != null ? ((t.live_gross*100).toFixed(1)+"%") : "—";
          const age = t.flagged_at ? Math.max(0, Math.floor((Date.now()/1000 - t.flagged_at)/60)) + "m" : "—";
          return `<div class="htCard" data-mint="${t.token_mint || ""}">
            <div style="display:flex;justify-content:space-between;gap:8px">
              <div class="mint">${short(t.token_mint)} · ${t.status || "?"}</div>
              <div class="muted" style="font-size:11px">age ${age}</div>
            </div>
            <div class="muted" style="font-size:11px;margin-top:4px">${t.reason || ""}</div>
            <div style="font-size:12px;margin-top:4px">entry ${t.entry_price != null ? Number(t.entry_price).toExponential(3) : "—"} · live P/L ${livePnL}</div>
            <div class="htChips">${chips}</div>
            <div style="margin-top:6px">${flagHtml}</div>
            <div class="htWallets">${wallets}</div>
          </div>`;
        }).join("");
        feed.querySelectorAll(".htWallets button[data-w]").forEach(b => {
          b.addEventListener("click", (ev) => {
            ev.stopPropagation();
            openDrawer("wallet", b.getAttribute("data-w"));
          });
        });
        feed.querySelectorAll(".htCard[data-mint]").forEach(card => {
          card.addEventListener("click", () => {
            const m = card.getAttribute("data-mint");
            if (m) openDrawer("token", m);
          });
        });
      }
    }
    const tr = P.tracker || {};
    const trEl = $("htTracker");
    const interval = Number(tr.poll_interval_seconds || 300);
    window.__TN_HT_TRACKER = tr;
    window.__TN_HT_INTERVAL = interval;
    if ($("htUpfront")) {
      const mins = Math.round(interval / 60);
      $("htUpfront").textContent = "Checks for new Hot Takes every " + mins + " minute" + (mins === 1 ? "" : "s") + ", so alerts can lag up to " + mins + " min. Paper tracking only.";
    }
    if ($("htLast")) {
      $("htLast").textContent = "Last checked: " + (tr.last_poll_iso || "—");
    }
    if (trEl) {
      const pagesPerHour = (5 * 1 * (3600 / interval));
      const credPerHour = Math.round(pagesPerHour * 100);
      trEl.textContent = "Tracker " + (tr.running ? "ON" : "off") + " · every " + interval + "s · last " + (tr.last_poll_iso || "—") + " · ~" + (tr.credits_estimate_this_hour || 0) + " credits this hour (≈" + credPerHour + "/h at full pace) · session logged " + (tr.n_logged_session || 0);
    }
  }

  async function loadHotTakes() {
    try {
      const r = await fetch("/api/hottakes");
      if (!r.ok) throw new Error("ht " + r.status);
      const j = await r.json();
      window.__TN_HOTTAKES = j;
      renderHotTakes(j);
    } catch (e) {
      ensureHotTakesPanel();
      const feed = $("htFeed");
      if (feed) feed.innerHTML = `<div class="empty">Hot Takes API: ${e}</div>`;
    }
  }

  function bindHotTakes() {
    ensureHotTakesPanel();
    $("htToggle")?.addEventListener("click", () => {
      state.htCollapsed = !state.htCollapsed;
      $("hotTakesPanel")?.classList.toggle("collapsed", !!state.htCollapsed);
      const btn = $("htToggle");
      if (btn) btn.textContent = state.htCollapsed ? "⟩" : "⟨";
    });
    document.querySelectorAll(".htFilt").forEach(b => {
      b.addEventListener("click", () => {
        state.htFilter = b.getAttribute("data-f") || "all";
        document.querySelectorAll(".htFilt").forEach(x => x.classList.toggle("active", x === b));
        renderHotTakes(window.__TN_HOTTAKES);
      });
    });
    // dock vs drawer: auto-collapse on narrow
    if (window.innerWidth < 1400) {
      state.htCollapsed = false;
    }
    loadHotTakes();
    setInterval(loadHotTakes, 30000);
    function tickHtCountdown() {
      const tr = window.__TN_HT_TRACKER || {};
      const nextAt = tr.next_poll_at;
      const el = $("htNext");
      if (!el) return;
      if (!nextAt) {
        const interval = Number(window.__TN_HT_INTERVAL || 300);
        // estimate from last_poll_iso if next missing
        if (tr.last_poll_iso) {
          const last = Date.parse(tr.last_poll_iso);
          if (!isNaN(last)) {
            const rem = Math.max(0, Math.floor((last/1000 + interval) - Date.now()/1000));
            const mm = String(Math.floor(rem/60)).padStart(1,"0");
            const ss = String(rem%60).padStart(2,"0");
            el.textContent = "Next check in " + mm + ":" + ss;
            return;
          }
        }
        el.textContent = "Next check: —";
        return;
      }
      const rem = Math.max(0, Math.floor(Number(nextAt) - Date.now()/1000));
      const mm = String(Math.floor(rem/60));
      const ss = String(rem%60).padStart(2,"0");
      el.textContent = "Next check in " + mm + ":" + ss;
    }
    tickHtCountdown();
    setInterval(tickHtCountdown, 1000);
  }


  function verdClass(v) {
    if (v === "COPY-WORTHY") return "COPY-WORTHY";
    if (v === "WATCH") return "WATCH";
    if (v === "AVOID") return "AVOID";
    return "ne";
  }

  function renderCopyDesk(doc) {
    const meta = $("cdeskMeta");
    if (!doc) {
      if (meta) meta.textContent = "No copydesk data yet — run scores/backtest.";
      return;
    }
    if (meta) {
      const a = doc.copy_assumptions || {};
      meta.textContent = (doc.generated_at_ct || doc.generated_at_utc || "—")
        + " · delay " + (a.delay_seconds || 60) + "s · size " + (a.position_sol || 0.25) + " SOL · PAPER";
    }
    const lead = $("cdeskLead");
    if (lead) {
      const rows = doc.leaderboard || [];
      let html = `<table class="int"><thead><tr>
        <th>Wallet</th><th>Score <span class="infoTip" data-tip="Composite score 0–1 from trenchnet scores.">i</span></th>
        <th>Copy P&amp;L @60s (SOL)</th><th>Win rate</th><th>n</th><th>Median ret</th>
        <th>Last trade (CT)</th><th>Verdict</th></tr></thead><tbody>`;
      rows.forEach(r => {
        const verd = r.verdict || "not enough trades";
        html += `<tr data-wallet="${r.wallet||""}" title="${(r.verdict_reason||"").replace(/"/g,"&quot;")}">
          <td>${r.label || short(r.wallet)}</td>
          <td>${fmt(r.score, 3)}</td>
          <td>${r.copy_pnl_60s_sol==null?"—":((r.copy_pnl_60s_sol>=0?"+":"")+fmt(r.copy_pnl_60s_sol,4))}</td>
          <td>${r.win_rate_60s==null?"—":(Number(r.win_rate_60s)*100).toFixed(0)+"%"}</td>
          <td>${r.n_trades_60s!=null?r.n_trades_60s:"—"}</td>
          <td>${r.median_return_60s==null?"—":(Number(r.median_return_60s)*100).toFixed(1)+"%"}</td>
          <td>${r.last_trade_ct || "—"}</td>
          <td><span class="verd ${verdClass(verd)}">${verd}</span></td></tr>`;
      });
      html += `</tbody></table>`;
      if (!rows.length) html = `<p class="muted">No scored wallets yet.</p>`;
      lead.innerHTML = html;
      lead.querySelectorAll("tr[data-wallet]").forEach(tr => {
        tr.addEventListener("click", () => openDrawer("wallet", tr.getAttribute("data-wallet")));
      });
    }
    const feed = $("cdeskFeed");
    if (feed) {
      const items = doc.activity_feed || [];
      feed.innerHTML = items.length ? items.map(e => {
        const tri = e.side === "buy" ? "▲" : "▼";
        const cls = e.side === "buy" ? "buy" : "sell";
        const sol = e.amount_sol==null ? "—" : fmt(e.amount_sol, 3) + " SOL";
        const mint = short(e.token_mint);
        return `<div class="feedRow"><span class="side ${cls}">${tri} ${e.label||cls.toUpperCase()}</span>
          <span>${e.wallet_label||short(e.wallet)}</span>
          <span class="muted">${mint}</span>
          <span>${sol}</span>
          <span class="muted">${e.time_ago||""}</span>
          <span class="muted" title="${e.time_ct||""}">#top ${e.top_wallets_in_token||0}</span></div>`;
      }).join("") : `<p class="muted">No recent activity.</p>`;
    }
    const hot = $("cdeskHot");
    if (hot) {
      const items = doc.hot_tokens || [];
      hot.innerHTML = items.length ? items.map(h => {
        const liq = (h.safety&&h.safety.liquidity) || {};
        const flag = liq.ok ? `<span class="ok">liq ok</span>` : `<span class="bad">liq flag</span>`;
        return `<div class="hotChip"><b>${short(h.token_mint)}</b> · ${h.n_top_wallets} top wallets
          · med buy ${h.median_buy_sol==null?"—":fmt(h.median_buy_sol,3)} SOL · ${flag}
          <div class="muted">${h.last_buy_ct||""}</div></div>`;
      }).join("") : `<p class="muted">No multi-wallet hot tokens in the last 7 days.</p>`;
    }
    drawEquity(doc.equity_curves || {});
  }

  function drawEquity(curves) {
    const cv = $("cdeskEquity");
    if (!cv) return;
    const ctx = cv.getContext("2d");
    const W = cv.width, H = cv.height;
    ctx.clearRect(0, 0, W, H);
    const colors = ["#00B4FF","#B026FF","#39ffb0","#ffd166","#ff5d8f","#ffffff"];
    const keys = Object.keys(curves).filter(k => (curves[k]||[]).length);
    const leg = $("cdeskEqLegend");
    if (leg) {
      leg.innerHTML = keys.map((k,i) => `<span><i class="sw" style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${colors[i%colors.length]};margin-right:4px"></i>${k==="ALL_TOP5"?"Combined top 5":short(k)}</span>`).join("");
    }
    let all = [];
    keys.forEach(k => all = all.concat(curves[k]));
    if (!all.length) {
      ctx.fillStyle = "#8aa0c0";
      ctx.font = "13px sans-serif";
      ctx.fillText("No equity points yet (need priced backtest / walk-forward).", 20, H/2);
      return;
    }
    const pad = {l:56, r:16, t:18, b:36};
    const ts = all.map(p => p.t);
    const ys = all.map(p => p.equity_sol);
    const t0 = Math.min(...ts), t1 = Math.max(...ts);
    let y0 = Math.min(...ys), y1 = Math.max(...ys);
    if (y0 === y1) { y0 -= 0.1; y1 += 0.1; }
    const x = t => pad.l + ((t - t0) / Math.max(1, t1 - t0)) * (W - pad.l - pad.r);
    const y = v => pad.t + (1 - (v - y0) / (y1 - y0)) * (H - pad.t - pad.b);
    ctx.strokeStyle = "rgba(0,180,255,.25)";
    ctx.beginPath();
    ctx.moveTo(pad.l, y(0)); ctx.lineTo(W - pad.r, y(0)); ctx.stroke();
    ctx.fillStyle = "#8aa0c0";
    ctx.font = "11px sans-serif";
    ctx.fillText("SOL", 8, pad.t + 8);
    ctx.fillText(y1.toFixed(3), 8, pad.t + 14);
    ctx.fillText(y0.toFixed(3), 8, H - pad.b);
    ctx.fillText("time CT →", W/2 - 30, H - 8);
    keys.forEach((k, i) => {
      const pts = curves[k];
      if (!pts || pts.length < 1) return;
      ctx.strokeStyle = colors[i % colors.length];
      ctx.lineWidth = k === "ALL_TOP5" ? 2.4 : 1.5;
      ctx.beginPath();
      pts.forEach((p, j) => {
        const xx = x(p.t), yy = y(p.equity_sol);
        if (j === 0) ctx.moveTo(xx, yy); else ctx.lineTo(xx, yy);
      });
      ctx.stroke();
    });
  }

  async function loadCopyDesk() {
    try {
      const r = await fetch("/api/copydesk", { cache: "no-store" });
      if (r.ok) {
        const doc = await r.json();
        window.__TN_COPYDESK = doc;
        renderCopyDesk(doc);
        return;
      }
    } catch (e) { /* fall through */ }
    renderCopyDesk((D().copydesk) || window.__TN_COPYDESK || null);
  }

  function bindPass7() {
    document.querySelectorAll("#deskTabs .tabBtn").forEach(b => {
      b.addEventListener("click", () => setTab(b.getAttribute("data-tab")));
    });
    $("topPickCard")?.addEventListener("click", () => {
      const P = window.__TN_TOP_PICK || D().top_pick || {};
      const mint = (P.top_pick || {}).token_mint || ((P.candidates || [])[0] || {}).token_mint;
      if (mint) openDrawer("token", mint);
    });
    setTab(state.tab || "overview");
    loadTopPick();
    loadCoinDesk();
    setInterval(loadCoinDesk, 10000);
    bindHotTakes();
  }

  function boot() {
    // Defaults → localStorage → hash (hash wins). Fresh load with neither = Jeremy's default view.
    applyView(cloneDefault());
    const ls = loadLocal();
    if (ls) applyView(ls);
    parseHash();
    ensureChrome();
    bindFilters();
    bindBacktestSliders();
    syncBacktestSliders();
    hookGraphClicks();
    // sync filter inputs from state
    if ($("fWallet")) $("fWallet").value = state.filters.qWallet || "";
    if ($("fToken")) $("fToken").value = state.filters.qToken || "";
    if ($("fMinSol")) $("fMinSol").value = state.filters.minSol || 0;
    if ($("fSource")) $("fSource").value = state.filters.source || "all";
    if ($("graphLayout")) $("graphLayout").value = state.layout;
    renderAll();
    startPolling();
    bindPass7();
    loadCopyDesk();
    setInterval(loadCopyDesk, 60000);
    // expose for template graph code
    window.TrenchInteractive = { openDrawer, state, filteredEvents, eventPass, loadTopPick, loadCoinDesk, setTab, resetToDefaultView, DEFAULT_VIEW, loadCopyDesk };
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else setTimeout(boot, 0);
})();
