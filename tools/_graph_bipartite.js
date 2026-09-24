// ---------- bipartite who-bought-what graph (PRECOMPUTE + FREEZE - no wobble) ----------
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
    return {
      sym: base.symbol || tc.symbol || (mint||"").slice(0,6),
      name: base.name || base.symbol || (mint||"").slice(0,6),
      px: pair.priceChange ? pair.priceChange.h24 : null,
      mcap: pair.marketCap || pair.fdv || null,
      url: pair.url || ("https://dexscreener.com/solana/"+mint),
      source: ((tc.dexscreener||{}).meta||{}).source_url || pair.url || ("https://dexscreener.com/solana/"+mint)
    };
  }

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
    if(side==="buy"){ p.buy_sol+=sol; p.buys+=1; if(tm!=null && (p.first_buy==null || tm<p.first_buy)) p.first_buy=tm; }
    else if(side==="sell"){ p.sell_sol+=sol; p.sells+=1; }
    if(tm!=null && (p.last==null || tm>p.last)) p.last=tm;
    if(e.signature) p.sigs.push(e.signature);
  });
  const pairList=[...pairs.values()];
  if(!pairList.length){
    const r=cv.getBoundingClientRect(); const dpr=window.devicePixelRatio||1;
    cv.width=Math.max(1,r.width)*dpr; cv.height=Math.max(1,r.height||400)*dpr;
    ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.fillStyle="#8ba3c7"; ctx.font="13px sans-serif";
    ctx.fillText("no graph data yet - run replay with roster trades", 20, 30);
    return;
  }

  const tokRoll = new Map();
  pairList.forEach(p=>{
    let tr=tokRoll.get(p.token);
    if(!tr){ tr={token:p.token, wallets:new Set(), buy_sol:0, sell_sol:0, first_buyer:null, first_time:null, latest:null}; tokRoll.set(p.token,tr); }
    tr.wallets.add(p.wallet); tr.buy_sol+=p.buy_sol; tr.sell_sol+=p.sell_sol;
    if(p.first_buy!=null && (tr.first_time==null || p.first_buy<tr.first_time)){ tr.first_time=p.first_buy; tr.first_buyer=p.wallet; }
    if(p.last!=null && (tr.latest==null || p.last>tr.latest)) tr.latest=p.last;
  });

  const entryOrder = new Map();
  [...tokenSet].forEach(t=>{
    entryOrder.set(t, pairList.filter(p=>p.token===t && p.first_buy!=null).sort((a,b)=>a.first_buy-b.first_buy).map(p=>p.wallet));
  });

  const nodes = new Map();
  function ensure(id, kind){ if(!nodes.has(id)) nodes.set(id,{id,kind,x:0.5,y:0.5,fx:0.5,fy:0.5}); return nodes.get(id); }
  walletSet.forEach(w=>ensure(w,"wallet"));
  tokenSet.forEach(t=>ensure(t,"token"));

  let groupMode = "bipartite";
  function layout(){
    const wallets=[...walletSet], tokens=[...tokenSet];
    if(groupMode==="bipartite"){
      wallets.forEach((w,i)=>{ const n=nodes.get(w); n.fx=0.14; n.fy=wallets.length===1?0.5:(0.08+0.84*(i/(wallets.length-1||1))); n.x=n.fx; n.y=n.fy; });
      tokens.forEach((t,i)=>{ const n=nodes.get(t); n.fx=0.82; n.fy=tokens.length===1?0.5:(0.08+0.84*(i/(tokens.length-1||1))); n.x=n.fx; n.y=n.fy; });
    } else if(groupMode==="wallet"){
      wallets.forEach((w,i)=>{
        const n=nodes.get(w); const ang=-Math.PI/2+(i/Math.max(1,wallets.length))*Math.PI*2;
        n.fx=0.5+0.18*Math.cos(ang); n.fy=0.5+0.28*Math.sin(ang); n.x=n.fx; n.y=n.fy;
        const toks=[...tokenSet].filter(t=>pairs.has(pairKey(w,t)));
        toks.forEach((t,j)=>{ const tn=nodes.get(t); const a=ang+(j-(toks.length-1)/2)*0.18; tn.fx=0.5+0.38*Math.cos(a); tn.fy=0.5+0.42*Math.sin(a); tn.x=tn.fx; tn.y=tn.fy; });
      });
    } else {
      tokens.forEach((t,i)=>{
        const n=nodes.get(t); const ang=-Math.PI/2+(i/Math.max(1,tokens.length))*Math.PI*2;
        n.fx=0.5+0.16*Math.cos(ang); n.fy=0.5+0.26*Math.sin(ang); n.x=n.fx; n.y=n.fy;
        const ws=entryOrder.get(t)||[];
        ws.forEach((w,j)=>{ const wn=nodes.get(w); const a=ang+(j-(ws.length-1)/2)*0.2; wn.fx=0.5+0.40*Math.cos(a); wn.fy=0.5+0.42*Math.sin(a); wn.x=wn.fx; wn.y=wn.fy; });
      });
    }
  }
  layout();

  const tb=document.querySelector("#buyTable tbody");
  if(tb){
    const rows=[...tokRoll.values()].sort((a,b)=>(b.wallets.size-a.wallets.size)||(b.buy_sol-a.buy_sol));
    const fmtT=ts=>{ if(ts==null) return "-"; try{return new Date(ts*1000).toISOString().replace("T"," ").slice(0,19)+"Z";}catch(e){return String(ts);} };
    tb.innerHTML = rows.map(tr=>{
      const meta=tokMeta(tr.token);
      const fb=labelOf[tr.first_buyer]||(tr.first_buyer||"").slice(0,6)||"-";
      const badge=meta.px!=null?((Number(meta.px)>=0?"+":"")+Number(meta.px).toFixed(1)+"% 24h"):"thin price";
      const mcap=meta.mcap!=null?("mcap $"+Number(meta.mcap).toLocaleString(undefined,{maximumFractionDigits:0})):"";
      return "<tr>"+
        "<td class='mono' title='"+tr.token+"'>"+(tr.token||"").slice(0,6)+"...</td>"+
        "<td><b>"+meta.sym+"</b><div class='note'>"+badge+" "+mcap+"</div></td>"+
        "<td>"+tr.wallets.size+"</td>"+
        "<td>"+tr.buy_sol.toFixed(3)+"</td>"+
        "<td>"+tr.sell_sol.toFixed(3)+"</td>"+
        "<td>"+fb+"</td>"+
        "<td class='mono'>"+fmtT(tr.first_time)+"</td>"+
        "<td class='mono'>"+fmtT(tr.latest)+"</td>"+
        "<td><a href='https://solscan.io/token/"+tr.token+"' target='_blank' rel='noopener'>Solscan</a> · <a href='"+meta.url+"' target='_blank' rel='noopener'>Dex</a></td>"+
      "</tr>";
    }).join("") || "<tr><td colspan='9' class='note'>no token buys in sample</td></tr>";
  }

  let hoverId=null, drag=null, moved=false;
  const hiWallets=new Set();
  const hiTokens=new Set();

  function size(){
    const r=cv.getBoundingClientRect(); const dpr=window.devicePixelRatio||1;
    cv.width=Math.max(1,r.width)*dpr; cv.height=Math.max(1,r.height)*dpr;
    ctx.setTransform(dpr,0,0,dpr,0,0); return r;
  }
  function nearest(p,W){
    let best=null, bd=22*22;
    nodes.forEach(n=>{ const dx=n.x*W.width-p.x, dy=n.y*W.height-p.y, d=dx*dx+dy*dy; if(d<bd){bd=d;best=n;} });
    return best;
  }

  function draw(){
    const W=size();
    ctx.clearRect(0,0,W.width,W.height);
    if(groupMode==="bipartite"){
      ctx.fillStyle="rgba(0,180,255,.08)"; ctx.fillRect(W.width*0.02,8,W.width*0.28,W.height-16);
      ctx.fillStyle="rgba(176,38,255,.08)"; ctx.fillRect(W.width*0.70,8,W.width*0.28,W.height-16);
      ctx.fillStyle="#8ba3c7"; ctx.font="11px sans-serif";
      ctx.fillText("WALLETS", W.width*0.05, 22);
      ctx.fillText("TOKENS", W.width*0.74, 22);
    }
    const maxFlow=Math.max(0.01, ...pairList.map(p=>p.buy_sol+p.sell_sol));
    pairList.forEach(p=>{
      const a=nodes.get(p.wallet), b=nodes.get(p.token); if(!a||!b) return;
      const related=!hoverId || hoverId===p.wallet || hoverId===p.token || hiWallets.has(p.wallet) || hiTokens.has(p.token);
      const dim=hoverId && !related;
      const buyish=p.buy_sol>=p.sell_sol; const flow=p.buy_sol+p.sell_sol;
      ctx.lineWidth=1+5*(flow/maxFlow);
      ctx.strokeStyle=buyish?(dim?"rgba(61,255,181,.12)":"rgba(61,255,181,.75)"):(dim?"rgba(255,93,143,.12)":"rgba(255,93,143,.75)");
      const x1=a.x*W.width,y1=a.y*W.height,x2=b.x*W.width,y2=b.y*W.height;
      ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
      const ang=Math.atan2(y2-y1,x2-x1), ah=7;
      ctx.beginPath(); ctx.moveTo(x2,y2);
      ctx.lineTo(x2-ah*Math.cos(ang-0.4), y2-ah*Math.sin(ang-0.4));
      ctx.lineTo(x2-ah*Math.cos(ang+0.4), y2-ah*Math.sin(ang+0.4));
      ctx.closePath(); ctx.fillStyle=ctx.strokeStyle; ctx.fill();
    });
    const maxTok=Math.max(0.01, ...[...tokRoll.values()].map(t=>t.buy_sol+t.sell_sol));
    nodes.forEach(n=>{
      const x=n.x*W.width, y=n.y*W.height;
      const active=!hoverId || n.id===hoverId || hiWallets.has(n.id) || hiTokens.has(n.id);
      if(n.kind==="wallet"){
        ctx.globalAlpha=active?1:0.18;
        if(!REDUCED){ ctx.shadowBlur=12; ctx.shadowColor="#00B4FF"; }
        ctx.fillStyle="#00B4FF"; ctx.beginPath(); ctx.arc(x,y,9,0,Math.PI*2); ctx.fill();
        ctx.shadowBlur=0; ctx.globalAlpha=1;
        if(hoverId && tokenSet.has(hoverId)){
          const ord=(entryOrder.get(hoverId)||[]).indexOf(n.id);
          if(ord>=0){
            ctx.fillStyle="#041018"; ctx.beginPath(); ctx.arc(x+10,y-10,8,0,Math.PI*2); ctx.fill();
            ctx.strokeStyle="#00B4FF"; ctx.stroke();
            ctx.fillStyle="#dfe9ff"; ctx.font="9px sans-serif"; ctx.textAlign="center";
            ctx.fillText(String(ord+1), x+10, y-7); ctx.textAlign="left";
          }
        }
        ctx.fillStyle="#dfe9ff"; ctx.font="bold 12px Inter,sans-serif";
        ctx.fillText(labelOf[n.id]||n.id.slice(0,6), x+12, y+4);
      } else {
        const tr=tokRoll.get(n.id); const flow=tr?(tr.buy_sol+tr.sell_sol):0; const R=8+10*(flow/maxTok);
        ctx.globalAlpha=active?1:0.18;
        if(!REDUCED){ ctx.shadowBlur=12; ctx.shadowColor="#B026FF"; }
        ctx.fillStyle="#B026FF";
        const rr=5; ctx.beginPath();
        ctx.moveTo(x-R+rr,y-R); ctx.arcTo(x+R,y-R,x+R,y+R,rr); ctx.arcTo(x+R,y+R,x-R,y+R,rr);
        ctx.arcTo(x-R,y+R,x-R,y-R,rr); ctx.arcTo(x-R,y-R,x+R,y-R,rr); ctx.closePath(); ctx.fill();
        ctx.shadowBlur=0; ctx.globalAlpha=1;
        const meta=tokMeta(n.id);
        ctx.fillStyle="#f0e9ff"; ctx.font="bold 12px Inter,sans-serif"; ctx.fillText(meta.sym, x+R+6, y+4);
        if(meta.px!=null){ ctx.fillStyle=Number(meta.px)>=0?"#3dffb5":"#ff5d8f"; ctx.font="10px sans-serif";
          ctx.fillText((Number(meta.px)>=0?"+":"")+Number(meta.px).toFixed(1)+"%", x+R+6, y+16); }
      }
    });
  }

  function setHover(n, cx, cy){
    hiWallets.clear(); hiTokens.clear(); hoverId=n?n.id:null;
    if(n && n.kind==="token"){
      (entryOrder.get(n.id)||[]).forEach(w=>hiWallets.add(w));
      const meta=tokMeta(n.id), tr=tokRoll.get(n.id);
      const order=(entryOrder.get(n.id)||[]).map((w,i)=>(i+1)+". "+(labelOf[w]||w.slice(0,6))).join("<br>");
      if(tip){ tip.innerHTML="<b>"+meta.sym+"</b> · "+meta.name+"<br>wallets: "+(tr?tr.wallets.size:0)+
        "<br>SOL in/out: "+(tr?tr.buy_sol:0).toFixed(3)+" / "+(tr?tr.sell_sol:0).toFixed(3)+
        "<br>"+(order||"-")+"<br><span class='note'>source: "+(meta.source||meta.url)+"</span>";
        tip.style.display="block";
        const wr=(wrap||cv).getBoundingClientRect();
        tip.style.left=(cx-wr.left+14)+"px"; tip.style.top=(cy-wr.top+14)+"px"; }
    } else if(n && n.kind==="wallet"){
      pairList.filter(p=>p.wallet===n.id).forEach(p=>hiTokens.add(p.token));
      const toks=[...hiTokens].map(t=>tokMeta(t).sym).join(", ");
      if(tip){ tip.innerHTML="<b>"+(labelOf[n.id]||n.id.slice(0,6))+"</b><br>tokens: "+(toks||"-")+
        "<br><span class='mono note'>"+n.id+"</span>";
        tip.style.display="block";
        const wr=(wrap||cv).getBoundingClientRect();
        tip.style.left=(cx-wr.left+14)+"px"; tip.style.top=(cy-wr.top+14)+"px"; }
    } else if(tip){ tip.style.display="none"; }
    draw();
  }

  cv.addEventListener("mousemove", e=>{
    const W=cv.getBoundingClientRect(); const p={x:e.clientX-W.left,y:e.clientY-W.top};
    if(drag){ moved=true; drag.x=Math.min(0.98,Math.max(0.02,p.x/W.width)); drag.y=Math.min(0.96,Math.max(0.04,p.y/W.height)); drag.fx=drag.x; drag.fy=drag.y; draw(); return; }
    setHover(nearest(p,W), e.clientX, e.clientY);
  });
  cv.addEventListener("mouseleave", ()=>{ if(!drag) setHover(null); });
  cv.addEventListener("mousedown", e=>{
    const W=cv.getBoundingClientRect();
    const n=nearest({x:e.clientX-W.left,y:e.clientY-W.top}, W);
    if(n){ drag=n; moved=false; cv.style.cursor="grabbing"; }
  });
  window.addEventListener("mouseup", ()=>{
    if(drag && !moved && typeof select==="function"){
      if(drag.kind==="wallet") select(drag.id);
      else { const ord=entryOrder.get(drag.id)||[]; if(ord[0]) select(ord[0]); }
    }
    drag=null; cv.style.cursor="grab";
  });

  const grp=document.getElementById("graphGroup");
  if(grp) grp.addEventListener("change", e=>{ groupMode=e.target.value; layout(); draw(); });
  const fsBtn=document.getElementById("graphFs");
  if(fsBtn) fsBtn.addEventListener("click", ()=>{
    cv.classList.toggle("fs");
    fsBtn.textContent = cv.classList.contains("fs") ? "Exit fullscreen" : "Fullscreen";
    draw();
  });
  window.addEventListener("resize", ()=>draw());

  // One paint after layout. No rAF simulation loop = no wobble.
  draw();
})();

