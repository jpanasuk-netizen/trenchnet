from pathlib import Path
import re

tpl = Path("docs/dashboard_template.html")
text = tpl.read_text(encoding="utf-8")

# 1) CSS: big graph + legend + table
old_css = """#graph{width:100%;height:460px;display:block;border-radius:12px;
  background:linear-gradient(180deg,rgba(0,180,255,.05),rgba(176,38,255,.05))}"""
new_css = """#graphWrap{position:relative;width:100%}
#graph{width:100%;height:70vh;min-height:520px;display:block;border-radius:12px;
  background:linear-gradient(180deg,rgba(0,180,255,.05),rgba(176,38,255,.05));cursor:grab}
#graph.fs{position:fixed;inset:12px;z-index:80;height:auto;min-height:0;box-shadow:0 0 0 9999px rgba(0,0,0,.72)}
.graphBar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 10px}
.graphBar label{font-size:12px;color:var(--dim)}
.graphBar select, .graphBar button{font:inherit}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:var(--dim);margin:8px 0 0}
.legend .sw{display:inline-block;width:12px;height:12px;border-radius:50%;vertical-align:middle;margin-right:6px}
.legend .sq{border-radius:3px}
#buyTable{width:100%;border-collapse:collapse;font-size:12px;margin-top:10px}
#buyTable th,#buyTable td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left}
#buyTable th{color:var(--dim);font-weight:600}
#buyTable a{color:var(--blue)}
.graphTip{position:absolute;pointer-events:none;display:none;z-index:40;max-width:320px;
  background:rgba(8,14,28,.95);border:1px solid var(--line);border-radius:10px;padding:8px 10px;font-size:11px}
"""
if old_css not in text:
    # try flexible
    text2, n = re.subn(
        r"#graph\{width:100%;height:460px;display:block;border-radius:12px;\s*background:linear-gradient\(180deg,rgba\(0,180,255,\.05\),rgba\(176,38,255,\.05\)\)}",
        new_css.replace("\\", "\\\\"),
        text,
        count=1,
    )
    if n != 1:
        raise SystemExit(f"CSS replace failed n={n}")
    text = text2
else:
    text = text.replace(old_css, new_css, 1)

# 2) HTML panel
old_html = """    <div class="panel">
      <h2>Wallet—token graph (co-entry)</h2>
      <canvas id="graph"></canvas>
      <p class="note">Observational timing patterns only — never ownership claims. Drag nodes; they glide (damped).</p>
    </div>"""
# tolerate encoding variants of dash
m = re.search(
    r'<div class="panel">\s*<h2>Wallet.+?graph.*?</h2>\s*<canvas id="graph"></canvas>\s*<p class="note">.*?</p>\s*</div>',
    text,
    flags=re.S,
)
if not m:
    raise SystemExit("HTML graph panel not found")
new_html = """    <div class="panel" id="graphPanel">
      <div class="graphBar">
        <h2 style="margin:0;flex:1">Who bought what <span class="note">(frozen layout — drag to move)</span></h2>
        <label>Group by
          <select id="graphGroup">
            <option value="bipartite" selected>wallet | token columns</option>
            <option value="wallet">cluster by wallet</option>
            <option value="token">cluster by token</option>
          </select>
        </label>
        <button type="button" id="graphFs" title="Expand graph">Fullscreen</button>
      </div>
      <div id="graphWrap">
        <canvas id="graph"></canvas>
        <div class="graphTip" id="graphTip"></div>
      </div>
      <div class="legend">
        <span><i class="sw" style="background:#00B4FF"></i>Wallet (circle, electric blue)</span>
        <span><i class="sw sq" style="background:#B026FF"></i>Token (rounded square, purple)</span>
        <span style="color:#3dffb5">Green edge = buys</span>
        <span style="color:#ff5d8f">Magenta edge = sells</span>
        <span>Thicker edge = more SOL · arrow wallet → token</span>
      </div>
      <p class="note">Observational only — never ownership claims. Layout is precomputed then frozen (no wobble). Hover token → wallets in entry order; hover wallet → its tokens. Click opens side panel. Labels always on.</p>
      <h2 style="margin-top:14px">What people are buying</h2>
      <div style="overflow:auto;max-height:280px"><table id="buyTable"><thead><tr>
        <th>Token</th><th>Symbol</th><th># wallets</th><th>SOL in</th><th>SOL out</th>
        <th>First buyer</th><th>First time</th><th>Latest</th><th>Links</th>
      </tr></thead><tbody></tbody></table></div>
    </div>"""
text = text[: m.start()] + new_html + text[m.end() :]

# 3) Replace force-graph IIFE
m2 = re.search(
    r"// ---------- force graph \(damped, DPR canvas, visual-only smoothing\) ----------\s*\(function\(\)\{.*?\n\}\)\(\);\s*\n(?=// ---------- timeline lanes)",
    text,
    flags=re.S,
)
if not m2:
    raise SystemExit("force graph IIFE not found")

new_js = r'''// ---------- bipartite who-bought-what graph (PRECOMPUTE + FREEZE — no wobble) ----------
(function(){
  const REDUCED = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const cv = document.getElementById("graph");
  const tip = document.getElementById("graphTip");
  const wrap = document.getElementById("graphWrap");
  if(!cv) return;
  const ctx = cv.getContext("2d");
  const edges = (D.graph||{}).edges_sample || [];
  const profiles = D.profiles || [];
  const tctx = D.token_context || {};
  const labelOf = {};
  profiles.forEach(p => { if(p.wallet) labelOf[p.wallet] = p.label || p.wallet.slice(0,6); });

  function tokMeta(mint){
    const tc = tctx[mint] || {};
    const pair = ((tc.dexscreener||{}).pair) || {};
    const base = pair.baseToken || {};
    const sym = base.symbol || (tc.symbol) || (mint||"").slice(0,6);
    const name = base.name || sym;
    const px = pair.priceChange ? pair.priceChange.h24 : null;
    const mcap = pair.marketCap || pair.fdv || null;
    const url = pair.url || ("https://dexscreener.com/solana/"+mint);
    return {sym, name, px, mcap, url, source: ((tc.dexscreener||{}).meta||{}).source_url || url};
  }

  // Aggregate wallet↔token from REAL edges only
  const pairKey = (w,t)=>w+"|"+t;
  const pairs = new Map();
  const walletSet = new Set();
  const tokenSet = new Set();
  edges.forEach(e=>{
    const w=e.wallet, t=e.token; if(!w||!t) return;
    walletSet.add(w); tokenSet.add(t);
    const k=pairKey(w,t);
    let p=pairs.get(k);
    if(!p){ p={wallet:w,token:t,buy_sol:0,sell_sol:0,buys:0,sells:0,first_buy:null,last:null,sigs:[]}; pairs.set(k,p); }
    const side=(e.side||"").toLowerCase();
    const sol=Number(e.size_sol||0)||0;
    const tm=e.time||null;
    if(side==="buy"){ p.buy_sol+=sol; p.buys+=1; if(tm && (p.first_buy==null || tm<p.first_buy)) p.first_buy=tm; }
    else if(side==="sell"){ p.sell_sol+=sol; p.sells+=1; }
    if(tm && (p.last==null || tm>p.last)) p.last=tm;
    if(e.signature) p.sigs.push(e.signature);
  });
  const pairList=[...pairs.values()];
  if(!pairList.length){
    const r=cv.getBoundingClientRect(); const dpr=window.devicePixelRatio||1;
    cv.width=Math.max(1,r.width)*dpr; cv.height=Math.max(1,r.height||400)*dpr;
    ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.fillStyle="#8ba3c7"; ctx.font="13px sans-serif";
    ctx.fillText("no graph data yet — run replay with roster trades", 20, 30);
    return;
  }

  // Token rollups for table + node size
  const tokRoll = new Map();
  pairList.forEach(p=>{
    let tr=tokRoll.get(p.token);
    if(!tr){ tr={token:p.token, wallets:new Set(), buy_sol:0, sell_sol:0, first_buyer:null, first_time:null, latest:null, latest_side:null}; tokRoll.set(p.token,tr); }
    tr.wallets.add(p.wallet); tr.buy_sol+=p.buy_sol; tr.sell_sol+=p.sell_sol;
    if(p.first_buy!=null && (tr.first_time==null || p.first_buy<tr.first_time)){ tr.first_time=p.first_buy; tr.first_buyer=p.wallet; }
    if(p.last!=null && (tr.latest==null || p.last>tr.latest)){ tr.latest=p.last; tr.latest_side = p.sells && p.last ? (p.buy_sol>=p.sell_sol?"buy":"sell") : (p.buys?"buy":"sell"); }
  });

  // Entry order per token (first_buy ascending)
  const entryOrder = new Map(); // token -> [wallet,...]
  [...tokenSet].forEach(t=>{
    const rows=pairList.filter(p=>p.token===t && p.first_buy!=null).sort((a,b)=>a.first_buy-b.first_buy);
    entryOrder.set(t, rows.map(p=>p.wallet));
  });

  const nodes = new Map(); // id -> {id,kind,x,y,fx,fy}
  function ensure(id, kind){
    if(!nodes.has(id)) nodes.set(id,{id,kind,x:0.5,y:0.5,fx:0.5,fy:0.5});
    return nodes.get(id);
  }
  walletSet.forEach(w=>ensure(w,"wallet"));
  tokenSet.forEach(t=>ensure(t,"token"));

  let groupMode = "bipartite";
  function layout(){
    const wallets=[...walletSet];
    const tokens=[...tokenSet];
    if(groupMode==="bipartite"){
      wallets.forEach((w,i)=>{ const n=nodes.get(w); n.fx=0.14; n.fy = wallets.length===1?0.5: (0.08+0.84*(i/(wallets.length-1||1))); n.x=n.fx; n.y=n.fy; });
      tokens.forEach((t,i)=>{ const n=nodes.get(t); n.fx=0.82; n.fy = tokens.length===1?0.5: (0.08+0.84*(i/(tokens.length-1||1))); n.x=n.fx; n.y=n.fy; });
    } else if(groupMode==="wallet"){
      wallets.forEach((w,i)=>{
        const n=nodes.get(w); const ang=-Math.PI/2 + (i/wallets.length)*Math.PI*2;
        n.fx=0.5+0.18*Math.cos(ang); n.fy=0.5+0.28*Math.sin(ang); n.x=n.fx; n.y=n.fy;
        const toks=[...tokenSet].filter(t=>pairs.has(pairKey(w,t)));
        toks.forEach((t,j)=>{ const tn=nodes.get(t); const a=ang + (j-(toks.length-1)/2)*0.18;
          tn.fx=0.5+0.38*Math.cos(a); tn.fy=0.5+0.42*Math.sin(a); tn.x=tn.fx; tn.y=tn.fy; });
      });
    } else {
      tokens.forEach((t,i)=>{
        const n=nodes.get(t); const ang=-Math.PI/2 + (i/tokens.length)*Math.PI*2;
        n.fx=0.5+0.16*Math.cos(ang); n.fy=0.5+0.26*Math.sin(ang); n.x=n.fx; n.y=n.fy;
        const ws=entryOrder.get(t)||[...walletSet].filter(w=>pairs.has(pairKey(w,t)));
        ws.forEach((w,j)=>{ const wn=nodes.get(w); const a=ang + (j-(ws.length-1)/2)*0.2;
          wn.fx=0.5+0.40*Math.cos(a); wn.fy=0.5+0.42*Math.sin(a); wn.x=wn.fx; wn.y=wn.fy; });
      });
    }
  }
  layout(); // PRECOMPUTE once — then FREEZE (no ongoing force sim)

  // Buy table
  const tb = document.querySelector("#buyTable tbody");
  if(tb){
    const rows=[...tokRoll.values()].sort((a,b)=> (b.wallets.size-a.wallets.size) || (b.buy_sol-a.buy_sol));
    const fmtT = ts => { if(!ts) return "—"; try{ return new Date(ts*1000).toISOString().replace("T"," ").slice(0,19)+"Z"; }catch(e){ return String(ts);} };
    tb.innerHTML = rows.map(tr=>{
      const meta=tokMeta(tr.token);
      const fb = labelOf[tr.first_buyer] || (tr.first_buyer||"").slice(0,6) || "—";
      const badge = meta.px!=null ? (`${Number(meta.px)>=0?"+":""}${Number(meta.px).toFixed(1)}% 24h`) : "thin price";
      const mcap = meta.mcap!=null ? (`mcap $${Number(meta.mcap).toLocaleString(undefined,{maximumFractionDigits:0})}`) : "";
      return `<tr>
        <td class="mono" title="${tr.token}">${(tr.token||"").slice(0,6)}…</td>
        <td><b>${meta.sym}</b><div class="note">${badge} ${mcap}</div></td>
        <td>${tr.wallets.size}</td>
        <td>${tr.buy_sol.toFixed(3)}</td>
        <td>${tr.sell_sol.toFixed(3)}</td>
        <td>${fb}</td>
        <td class="mono">${fmtT(tr.first_time)}</td>
        <td class="mono">${fmtT(tr.latest)}</td>
        <td><a href="https://solscan.io/token/${tr.token}" target="_blank" rel="noopener">Solscan</a>
         · <a href="${meta.url}" target="_blank" rel="noopener">Dex</a></td>
      </tr>`;
    }).join("") || `<tr><td colspan="9" class="note">no token buys in sample</td></tr>`;
  }

  let hoverId=null, drag=null, moved=false;
  const hiWallets=new Set(); // highlighted wallets when token hovered
  const hiTokens=new Set();

  function size(){
    const r=cv.getBoundingClientRect(); const dpr=window.devicePixelRatio||1;
    cv.width=Math.max(1,r.width)*dpr; cv.height=Math.max(1,r.height)*dpr;
    ctx.setTransform(dpr,0,0,dpr,0,0);
    return r;
  }

  function nearest(p, W){
    let best=null, bd=22*22;
    nodes.forEach(n=>{
      const dx=n.x*W.width-p.x, dy=n.y*W.height-p.y, d=dx*dx+dy*dy;
      if(d<bd){ bd=d; best=n; }
    });
    return best;
  }

  function draw(){
    const W=size();
    ctx.clearRect(0,0,W.width,W.height);
    // column guides in bipartite mode
    if(groupMode==="bipartite"){
      ctx.fillStyle="rgba(0,180,255,.08)"; ctx.fillRect(W.width*0.02, 8, W.width*0.28, W.height-16);
      ctx.fillStyle="rgba(176,38,255,.08)"; ctx.fillRect(W.width*0.70, 8, W.width*0.28, W.height-16);
      ctx.fillStyle="#8ba3c7"; ctx.font="11px sans-serif";
      ctx.fillText("WALLETS", W.width*0.05, 22);
      ctx.fillText("TOKENS", W.width*0.74, 22);
    }
    const maxFlow = Math.max(0.01, ...pairList.map(p=>p.buy_sol+p.sell_sol));
    // edges
    pairList.forEach(p=>{
      const a=nodes.get(p.wallet), b=nodes.get(p.token); if(!a||!b) return;
      const dim = hoverId && !(
        (hoverId===p.wallet || hoverId===p.token) ||
        (hiWallets.has(p.wallet) && hoverId && tokenSet.has(hoverId)) ||
        (hiTokens.has(p.token) && hoverId && walletSet.has(hoverId))
      );
      const buyish = p.buy_sol >= p.sell_sol;
      const flow = p.buy_sol + p.sell_sol;
      ctx.lineWidth = 1 + 5*(flow/maxFlow);
      ctx.strokeStyle = buyish ? (dim?"rgba(61,255,181,.12)":"rgba(61,255,181,.75)") : (dim?"rgba(255,93,143,.12)":"rgba(255,93,143,.75)");
      const x1=a.x*W.width, y1=a.y*W.height, x2=b.x*W.width, y2=b.y*W.height;
      ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
      // arrow head at token
      const ang=Math.atan2(y2-y1,x2-x1);
      const ah=7;
      ctx.beginPath();
      ctx.moveTo(x2,y2);
      ctx.lineTo(x2-ah*Math.cos(ang-0.4), y2-ah*Math.sin(ang-0.4));
      ctx.lineTo(x2-ah*Math.cos(ang+0.4), y2-ah*Math.sin(ang+0.4));
      ctx.closePath(); ctx.fillStyle=ctx.strokeStyle; ctx.fill();
    });
    // nodes
    const maxTok = Math.max(0.01, ...[...tokRoll.values()].map(t=>t.buy_sol+t.sell_sol));
    nodes.forEach(n=>{
      const x=n.x*W.width, y=n.y*W.height;
      const active = !hoverId || n.id===hoverId || hiWallets.has(n.id) || hiTokens.has(n.id);
      if(n.kind==="wallet"){
        const R=9;
        ctx.globalAlpha = active?1:0.18;
        if(!REDUCED){ ctx.shadowBlur=12; ctx.shadowColor="#00B4FF"; }
        ctx.fillStyle="#00B4FF";
        ctx.beginPath(); ctx.arc(x,y,R,0,7); ctx.fill();
        ctx.shadowBlur=0; ctx.globalAlpha=1;
        // entry rank badge when token hovered
        if(hoverId && tokenSet.has(hoverId)){
          const ord=(entryOrder.get(hoverId)||[]).indexOf(n.id);
          if(ord>=0){
            ctx.fillStyle="#041018"; ctx.beginPath(); ctx.arc(x+10,y-10,8,0,7); ctx.fill();
            ctx.strokeStyle="#00B4FF"; ctx.stroke();
            ctx.fillStyle="#dfe9ff"; ctx.font="9px sans-serif"; ctx.textAlign="center";
            ctx.fillText(String(ord+1), x+10, y-7); ctx.textAlign="left";
          }
        }
        const lab = labelOf[n.id] || n.id.slice(0,6);
        ctx.fillStyle="#dfe9ff"; ctx.font="bold 12px Inter,sans-serif";
        ctx.fillText(lab, x+12, y+4);
      } else {
        const tr=tokRoll.get(n.id); const flow=(tr?(tr.buy_sol+tr.sell_sol):0);
        const R=8+10*(flow/maxTok);
        ctx.globalAlpha = active?1:0.18;
        if(!REDUCED){ ctx.shadowBlur=12; ctx.shadowColor="#B026FF"; }
        ctx.fillStyle="#B026FF";
        const rr=5;
        ctx.beginPath();
        ctx.moveTo(x-R+rr,y-R); ctx.arcTo(x+R,y-R,x+R,y+R,rr); ctx.arcTo(x+R,y+R,x-R,y+R,rr);
        ctx.arcTo(x-R,y+R,x-R,y-R,rr); ctx.arcTo(x-R,y-R,x+R,y-R,rr); ctx.closePath(); ctx.fill();
        ctx.shadowBlur=0; ctx.globalAlpha=1;
        const meta=tokMeta(n.id);
        ctx.fillStyle="#f0e9ff"; ctx.font="bold 12px Inter,sans-serif";
        ctx.fillText(meta.sym, x+R+6, y+4);
        if(meta.px!=null){
          ctx.fillStyle = Number(meta.px)>=0 ? "#3dffb5" : "#ff5d8f";
          ctx.font="10px sans-serif";
          ctx.fillText(`${Number(meta.px)>=0?"+":""}${Number(meta.px).toFixed(1)}%`, x+R+6, y+16);
        }
      }
    });
  }

  function setHover(n, clientX, clientY){
    hiWallets.clear(); hiTokens.clear();
    hoverId = n? n.id : null;
    if(n && n.kind==="token"){
      (entryOrder.get(n.id)||[]).forEach(w=>hiWallets.add(w));
      const meta=tokMeta(n.id); const tr=tokRoll.get(n.id);
      const order=(entryOrder.get(n.id)||[]).map((w,i)=>`${i+1}. ${labelOf[w]||w.slice(0,6)}`).join("<br>");
      tip.innerHTML = `<b>${meta.sym}</b> · ${meta.name}<br>wallets in: ${tr?tr.wallets.size:0}<br>SOL in/out: ${(tr?tr.buy_sol:0).toFixed(3)} / ${(tr?tr.sell_sol:0).toFixed(3)}<br>${order||"—"}<br><span class="note">Dex: ${meta.source||meta.url}</span>`;
      tip.style.display="block"; tip.style.left=(clientX - wrap.getBoundingClientRect().left + 14)+"px"; tip.style.top=(clientY - wrap.getBoundingClientRect().top + 14)+"px";
    } else if(n && n.kind==="wallet"){
      pairList.filter(p=>p.wallet===n.id).forEach(p=>hiTokens.add(p.token));
      const toks=[...hiTokens].map(t=>tokMeta(t).sym).join(", ");
      tip.innerHTML = `<b>${labelOf[n.id]||n.id.slice(0,6)}</b><br>tokens: ${toks||"—"}<br><span class="mono note">${n.id}</span>`;
      tip.style.display="block"; tip.style.left=(clientX - wrap.getBoundingClientRect().left + 14)+"px"; tip.style.top=(clientY - wrap.getBoundingClientRect().top + 14)+"px";
    } else {
      tip.style.display="none";
    }
    draw();
  }

  cv.addEventListener("mousemove", e=>{
    const W=cv.getBoundingClientRect();
    const p={x:e.clientX-W.left,y:e.clientY-W.top};
    if(drag){
      moved=true;
      drag.x = Math.min(0.98, Math.max(0.02, p.x/W.width));
      drag.y = Math.min(0.96, Math.max(0.04, p.y/W.height));
      drag.fx=drag.x; drag.fy=drag.y;
      draw(); return;
    }
    setHover(nearest(p,W), e.clientX, e.clientY);
  });
  cv.addEventListener("mouseleave", ()=>{ if(!drag) setHover(null); });
  cv.addEventListener("mousedown", e=>{
    const W=cv.getBoundingClientRect();
    const n=nearest({x:e.clientX-W.left,y:e.clientY-W.top}, W);
    if(n){ drag=n; moved=false; cv.style.cursor="grabbing"; }
  });
  window.addEventListener("mouseup", ()=>{
    if(drag && !moved && typeof select==="function" && drag.kind==="wallet") select(drag.id);
    if(drag && !moved && drag.kind==="token"){
      // open side with token blurb via tip already; also try select first wallet
      const ord=entryOrder.get(drag.id)||[];
      if(ord[0] && typeof select==="function") select(ord[0]);
    }
    drag=null; cv.style.cursor="grab";
  });

  document.getElementById("graphGroup")?.addEventListener("change", e=>{
    groupMode = e.target.value; layout(); draw();
  });
  document.getElementById("graphFs")?.addEventListener("click", ()=>{
    cv.classList.toggle("fs");
    const on=cv.classList.contains("fs");
    document.getElementById("graphFs").textContent = on?"Exit fullscreen":"Fullscreen";
    draw();
  });
  window.addEventListener("resize", ()=>draw());

  // Single paint after layout — NO perpetual simulation. Redraw only on interaction/resize.
  draw();
})();

'''
text = text[: m2.start()] + new_js + text[m2.end() :]

tpl.write_text(text, encoding="utf-8")
# sync to out/dashboard.html — keep data.js script tag as in out
out = Path("out/dashboard.html")
# Prefer regenerating from template: copy template structure but fix asset path if needed
out_text = text
# template uses assets/data.js — out uses same relative
out.write_text(out_text, encoding="utf-8")
print("patched template + out/dashboard.html")
print("graph IIFE frozen bipartite OK")
