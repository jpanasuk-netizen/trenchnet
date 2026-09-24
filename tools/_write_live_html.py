from pathlib import Path
Path("out/live.html").write_text("""<!DOCTYPE html>
<html lang='en'><head><meta charset='utf-8'/>
<meta name='viewport' content='width=device-width, initial-scale=1'/>
<title>TRENCHNET LIVE — DISARMED BY DEFAULT</title>
<style>
:root{--bg:#05060f;--panel:rgba(10,18,38,.72);--blue:#00B4FF;--purple:#B026FF;--text:#dfe9ff;--danger:#ff3b6b}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 Inter,system-ui,sans-serif;color:var(--text);background:radial-gradient(1200px 600px at 10% -10%,#1a0a3a,transparent 50%),radial-gradient(1000px 500px at 90% 0%,#062a4a,transparent 45%),var(--bg)}
a{color:var(--blue)}header{display:flex;gap:14px;align-items:center;padding:16px 24px;border-bottom:1px solid #1c2a4a;position:sticky;top:0;backdrop-filter:blur(10px);z-index:5}
.brand{font-weight:800}.brand span{color:var(--blue)}.badge{padding:4px 10px;border-radius:999px;border:1px solid #334;font-size:11px;font-weight:700}
.badge.live{background:rgba(255,59,107,.15);border-color:var(--danger);color:#ff9db4}.badge.paper{background:rgba(0,180,255,.12);border-color:var(--blue);color:var(--blue)}
main{display:grid;grid-template-columns:1.1fr 1fr 1fr;gap:16px;padding:20px 24px 80px;max-width:1800px;margin:0 auto}
@media(max-width:1100px){main{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid #1c2a4a;border-radius:16px;padding:16px}h2{margin:0 0 10px;font-size:15px}
.row{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}input,select,button{font:inherit;border-radius:10px;border:1px solid #2a3a5a;background:#0a1226;color:var(--text);padding:8px 12px}
input,select{flex:1;min-width:120px}button{cursor:pointer;font-weight:700}button.primary{background:linear-gradient(90deg,var(--blue),var(--purple));border:0;color:#041018}
button.danger{background:var(--danger);border:0;color:#fff}.mono{font-family:ui-monospace,Consolas,monospace;font-size:12px;word-break:break-all}
.warnbox{border:1px solid var(--danger);background:rgba(255,59,107,.08);padding:12px;border-radius:12px;margin:8px 0}
.okbox{border:1px solid #1c4;background:rgba(61,255,181,.06);padding:10px;border-radius:12px;white-space:pre-wrap}
.small{opacity:.75;font-size:12px}#killbar{position:fixed;right:18px;bottom:18px;z-index:30}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.65);display:none;align-items:center;justify-content:center;z-index:40}
.modal.open{display:flex}.modal .box{background:#0b1428;border:1px solid var(--purple);border-radius:16px;padding:20px;max-width:560px;width:92%}
table{width:100%;border-collapse:collapse;font-size:12px}td,th{padding:6px;border-bottom:1px solid #1c2a4a;text-align:left}
</style></head><body>
<header>
  <div class='brand'>TRENCH<span>NET</span> · LIVE</div>
  <span class='badge live' id='armBadge'>DISARMED</span>
  <span class='badge paper'>PAPER stays separate</span>
  <a href='/' style='margin-left:auto'>← Watch / Paper desk</a>
</header>
<main>
<section class='card'><h2>1) Dedicated wallet</h2>
<div class='warnbox'>Generate a <b>fresh</b> Solana keypair or import one used ONLY for this desk. Encrypted with Windows DPAPI under %LOCALAPPDATA%\\trenchnet\\. Secret never shown, logged, or put in data.js. <b>Never use main MetaMask/Coinbase wallet.</b></div>
<div class='row'><button class='primary' onclick='genWallet()'>Generate new keypair</button>
<button onclick="document.getElementById('importBox').style.display='flex'">Import secret (local)</button></div>
<div class='row' id='importBox' style='display:none'><input id='importSecret' type='password' placeholder='base58 or JSON byte array'/>
<button onclick='importWallet()'>Store encrypted</button></div>
<p class='small'>Public address</p><div class='mono' id='pubkey'>—</div>
<div class='row'><canvas id='qr' width='160' height='160' style='background:#fff;border-radius:8px'></canvas>
<div>SOL: <b id='solBal'>?</b><div class='small'>Fund only what you can lose.</div>
<a id='solscanW' target='_blank' rel='noopener'>Solscan →</a></div></div>
</section>
<section class='card'><h2>2) Limits (0 = disarmed)</h2>
<div class='row'><label>max SOL/trade <input id='lim_sol' type='number' step='0.001' value='0'/></label>
<label>daily loss SOL <input id='lim_loss' type='number' step='0.01' value='0'/></label></div>
<div class='row'><label>max trades/day <input id='lim_trades' type='number' value='0'/></label>
<label>max open <input id='lim_open' type='number' value='0'/></label></div>
<div class='row'><label>max slip % <input id='lim_slip' type='number' step='0.1' value='0'/></label>
<label>max tip lamports <input id='lim_prio' type='number' value='0'/></label></div>
<div class='row'><label>RPC URL <input id='rpc' value='https://api.mainnet-beta.solana.com'/></label></div>
<div class='row'><label><input type='checkbox' id='pumpportal'/> Opt-in PumpPortal (may take per-trade fee) — prefer OFF</label></div>
<button onclick='saveLimits()'>Save limits</button>
<p class='small'>Route: Jupiter lite (lite-api.jup.ag) — free public, no TRENCHNET fee. Network fees still apply.</p>
</section>
<section class='card'><h2>3) Arm / Kill</h2>
<div class='warnbox'>Default DISARMED. Agent never arms. Type exactly <b>ARM LIVE</b> after limits &gt; 0 and wallet exists. Auto requires <b>ARM AUTO</b>.</div>
<div class='row'><input id='armPhrase' placeholder='ARM LIVE'/><button class='primary' onclick='arm(false)'>Arm LIVE</button></div>
<div class='row'><input id='autoPhrase' placeholder='ARM AUTO'/><button onclick='arm(true)'>Arm AUTO</button></div>
<div class='row'><button onclick='disarm()'>Disarm</button></div>
<div id='armStatus' class='okbox'>…</div>
</section>
<section class='card' style='grid-column:1/-1'><h2>4) Manual Buy / Sell</h2>
<div class='row'>
<input id='mint' placeholder='token mint'/>
<select id='side'><option>buy</option><option>sell</option></select>
<input id='amt' type='number' step='0.001' placeholder='SOL amount'/>
<input id='slip' type='number' step='0.1' value='2'/>
<input id='prio' type='number' value='10000'/>
<button class='primary' onclick='preview()'>Preview (simulate)</button>
</div>
<div id='previewBox' class='small'></div>
</section>
<section class='card' style='grid-column:1/3'><h2>LIVE ledger</h2><div id='ledger' class='small'>No live fills yet (expected).</div></section>
<section class='card'><h2>How to go live (Jeremy)</h2>
<ol class='small'><li>Generate wallet → fund tiny SOL (dedicated only).</li>
<li>Set all caps &gt; 0 → Save.</li>
<li>Type ARM LIVE → Arm.</li>
<li>Preview → confirm modal → type CONFIRM LIVE ORDER yourself.</li>
<li>Big red KILL anytime. App restart auto-disarms.</li></ol>
<p class='small'>Optional free RPC signup (agent did NOT sign up): Helius / QuickNode free tier — paste URL above.</p>
</section>
</main>
<div id='killbar'><button class='danger' onclick='kill()'>KILL LIVE</button></div>
<div class='modal' id='modal'><div class='box'>
<h2>Confirm LIVE order</h2><div id='modalBody' class='mono'></div>
<p class='small'>Type <b>CONFIRM LIVE ORDER</b> to sign+send. Cancel = simulate only.</p>
<div class='row'><input id='confirmPhrase'/><button class='danger' onclick='confirmSend()'>Sign &amp; send</button><button onclick='closeModal()'>Cancel</button></div>
</div></div>
<script>
let S=null, pending=null;
async function j(url, opts){ const r=await fetch(url, opts); return r.json(); }
function drawQR(text){ const c=document.getElementById('qr'); const ctx=c.getContext('2d'); ctx.fillStyle='#fff'; ctx.fillRect(0,0,160,160); ctx.fillStyle='#000'; if(!text){ctx.fillText('no wallet',20,80);return;} let h=0; for(const ch of text) h=(h*31+ch.charCodeAt(0))>>>0; for(let y=0;y<16;y++) for(let x=0;x<16;x++) if((h^(x*7+y*13))&1) ctx.fillRect(x*10,y*10,10,10); }
async function refresh(){
  S = await j('/api/live/state');
  const w=S.wallet||{};
  document.getElementById('pubkey').textContent = w.pubkey || '— none —';
  document.getElementById('armBadge').textContent = S.armed ? (S.auto_armed?'ARMED AUTO':'ARMED') : 'DISARMED';
  document.getElementById('armStatus').textContent = JSON.stringify({armed:S.armed,auto:S.auto_armed,kill:S.kill_switch,reason:S.disarm_reason,limits:S.limits},null,2);
  const L=S.limits||{};
  lim_sol.value=L.max_sol_per_trade||0; lim_loss.value=L.daily_loss_cap_sol||0; lim_trades.value=L.max_trades_per_day||0;
  lim_open.value=L.max_open_positions||0; lim_slip.value=L.max_slippage_pct||0; lim_prio.value=L.max_priority_fee_lamports||0;
  rpc.value=S.rpc_url||rpc.value; pumpportal.checked=!!S.pumpportal_opt_in;
  drawQR(w.qr_fund_uri||w.pubkey||'');
  solscanW.href = w.pubkey ? ('https://solscan.io/account/'+w.pubkey) : '#';
  const bal=await j('/api/live/balances'); solBal.textContent = (bal.sol!=null? bal.sol : '?') + (bal.error? (' ('+bal.error+')'):'');
  const led=await j('/api/live/ledger');
  if(led.rows&&led.rows.length){
    ledger.innerHTML='<table><tr><th>ts</th><th>mode</th><th>side</th><th>sol</th><th>sig</th></tr>'+led.rows.slice().reverse().slice(0,40).map(function(r){
      var sig=r.signature?('<a target=_blank href=\"https://solscan.io/tx/'+r.signature+'\">'+r.signature.slice(0,12)+'…</a>'):(r.reason||'');
      return '<tr><td>'+(r.ts||'')+'</td><td>'+(r.mode||'')+'</td><td>'+(r.side||'')+'</td><td>'+(r.sol_amount!=null?r.sol_amount:'')+'</td><td>'+sig+'</td></tr>';
    }).join('')+'</table>';
  }
}
async function genWallet(){ const r=await j('/api/live/wallet/generate',{method:'POST'}); alert((r.ok||r.pubkey)?'Wallet created — pubkey only':'ERR '+JSON.stringify(r)); refresh(); }
async function importWallet(){ const r=await j('/api/live/wallet/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({secret:importSecret.value})}); importSecret.value=''; alert((r.ok||r.pubkey)?'Imported':'ERR '+JSON.stringify(r)); refresh(); }
async function saveLimits(){ await j('/api/live/limits',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({max_sol_per_trade:+lim_sol.value,daily_loss_cap_sol:+lim_loss.value,max_trades_per_day:+lim_trades.value,max_open_positions:+lim_open.value,max_slippage_pct:+lim_slip.value,max_priority_fee_lamports:+lim_prio.value,rpc_url:rpc.value,pumpportal_opt_in:pumpportal.checked})}); refresh(); }
async function arm(auto){ const phrase=auto?autoPhrase.value:armPhrase.value; const r=await j('/api/live/arm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phrase:phrase,auto:auto})}); alert(JSON.stringify(r)); refresh(); }
async function disarm(){ await j('/api/live/disarm',{method:'POST'}); refresh(); }
async function kill(){ await j('/api/live/kill',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({on:true})}); refresh(); }
async function preview(){
  const body={side:side.value,token_mint:mint.value.trim(),sol_amount:+amt.value,slippage_pct:+slip.value,priority_fee_lamports:+prio.value,mode:'simulate',confirm_phrase:''};
  const r=await j('/api/live/order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  previewBox.innerHTML='<pre class=\"mono\">'+JSON.stringify(r,null,2)+'</pre>';
  if(r.ok && S && S.armed){ pending=body; modalBody.textContent=JSON.stringify({side:body.side,mint:body.token_mint,sol:body.sol_amount,slip:body.slippage_pct,prio:body.priority_fee_lamports,route:'jupiter_lite',fee:'no TRENCHNET fee; network fees apply'},null,2); modal.classList.add('open'); }
}
function closeModal(){ modal.classList.remove('open'); pending=null; }
async function confirmSend(){ if(!pending) return; pending.mode='send'; pending.confirm_phrase=confirmPhrase.value; const r=await j('/api/live/order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pending)}); alert(JSON.stringify(r)); closeModal(); refresh(); }
refresh();
</script>
</body></html>
""", encoding="utf-8")
print("bytes", Path("out/live.html").stat().st_size)
