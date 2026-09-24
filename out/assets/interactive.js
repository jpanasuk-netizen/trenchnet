/* TRENCHNET Pass 5 interactive desk — local only, no CDN, paper/backtest labels. */
(function () {
  const D = () => window.TRENCHNET_DATA || {};
  const state = {
    filters: { qWallet: "", qToken: "", minSol: 0, source: "all", t0: null, t1: null },
    page: { buy: 0, score: 0, events: 0 },
    pageSize: 12,
    selected: null, // {kind:'wallet'|'token', id}
    layout: "columns", // columns | force
    pollTimer: null,
    lastVersion: null,
    backtest: {
      delay: 60, sizeSol: 0.25, slipMult: 1, tp: 0.5, sl: 0.25, tstop: 3600, mode: "fixed"
    }
  };

  function $(id) { return document.getElementById(id); }
  function fmt(n, d) {
    if (n == null || isNaN(n)) return "—";
    return Number(n).toFixed(d == null ? 3 : d);
  }
  function short(a) { return a ? (a.slice(0, 4) + "…" + a.slice(-4)) : "—"; }

  function parseHash() {
    try {
      const h = (location.hash || "").replace(/^#/, "");
      if (!h) return;
      const o = JSON.parse(decodeURIComponent(h));
      if (o.filters) Object.assign(state.filters, o.filters);
      if (o.selected) state.selected = o.selected;
      if (o.layout) state.layout = o.layout;
      if (o.backtest) Object.assign(state.backtest, o.backtest);
    } catch (e) { /* ignore bad hash */ }
  }
  function writeHash() {
    const o = {
      filters: state.filters,
      selected: state.selected,
      layout: state.layout,
      backtest: state.backtest
    };
    const next = "#" + encodeURIComponent(JSON.stringify(o));
    if (location.hash !== next) history.replaceState(null, "", next);
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
      $("btCoverage").textContent =
        `Server coverage ${fmt(cov.coverage_pct, 2)}% of copy sims priceable ` +
        `(${cov.n_priced || 0}/${cov.n_copies || 0}). Sources: ${JSON.stringify(cov.price_sources || {})}. ` +
        `Unpriceable trades are excluded — never filled with invented prices.`;
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

  function boot() {
    parseHash();
    ensureChrome();
    bindFilters();
    bindBacktestSliders();
    hookGraphClicks();
    // sync filter inputs from state
    if ($("fWallet")) $("fWallet").value = state.filters.qWallet || "";
    if ($("fToken")) $("fToken").value = state.filters.qToken || "";
    if ($("fMinSol")) $("fMinSol").value = state.filters.minSol || 0;
    if ($("fSource")) $("fSource").value = state.filters.source || "all";
    if ($("graphLayout")) $("graphLayout").value = state.layout;
    renderAll();
    startPolling();
    // expose for template graph code
    window.TrenchInteractive = { openDrawer, state, filteredEvents, eventPass };
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else setTimeout(boot, 0);
})();
