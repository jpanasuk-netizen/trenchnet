"""Expand roster with on-chain co-buyers of Doji token mints (free RPC).
Also seeds data/raw/history for top cobuyers using observed TradeEvents
from the same mint txs (real data only).
"""
from __future__ import annotations
import json, sys, time
from datetime import datetime, timezone
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trenchnet.data_solana import (
    SolanaRPC,
    get_signatures_page,
    rpc_get_transaction,
    parse_trades_from_tx,
)
from trenchnet.history import history_dir
from trenchnet.config_load import load_settings

MAX_TOTAL = 40
RPC = 'https://solana-rpc.publicnode.com'


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def doji_mints(hdir: Path, doji: str) -> list[str]:
    p = hdir / f'{doji}.json'
    if not p.is_file():
        return []
    st = json.loads(p.read_text(encoding='utf-8'))
    seen, out = set(), []
    for e in st.get('events') or []:
        m = e.get('token_mint') or e.get('token')
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def harvest_mint(rpc: SolanaRPC, mint: str, exclude: set[str], max_pages=3, max_tx=25):
    found: dict[str, int] = {}
    events_by: dict[str, list] = {}
    before = None
    pages = txs = 0
    while pages < max_pages and txs < max_tx:
        try:
            sigs = get_signatures_page(rpc, mint, before=before, limit=40)
        except Exception as exc:
            print('sig_fail', mint[:8], exc, flush=True)
            break
        if not sigs:
            break
        pages += 1
        for s in sigs:
            if txs >= max_tx:
                break
            if s.get('err'):
                continue
            sig = s.get('signature')
            if not sig:
                continue
            try:
                tx = rpc_get_transaction(rpc, sig)
            except Exception:
                continue
            txs += 1
            if not tx:
                continue
            meta = tx.get('meta') or {}
            owners: set[str] = set()
            for bal in meta.get('postTokenBalances') or []:
                if bal.get('mint') != mint:
                    continue
                owner = bal.get('owner')
                if owner and owner not in exclude:
                    owners.add(owner)
                    found[owner] = found.get(owner, 0) + 1
            for owner in owners:
                try:
                    parsed = parse_trades_from_tx(tx, sig, owner)
                except Exception:
                    parsed = []
                for ev in parsed:
                    events_by.setdefault(owner, []).append(ev.to_dict())
            time.sleep(0.22)
        before = (sigs[-1] or {}).get('signature')
        time.sleep(0.35)
    return found, events_by


def merge_history(hdir: Path, addr: str, new_events: list, note: str) -> int:
    path = hdir / f'{addr}.json'
    st: dict = {}
    if path.is_file():
        try:
            st = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            st = {}
    st.setdefault('wallet', addr)
    st.setdefault('seen', [])
    st.setdefault('events', [])
    st.setdefault('pages_fetched', int(st.get('pages_fetched') or 0))
    st.setdefault('txs_fetched', int(st.get('txs_fetched') or 0))
    st['source_note'] = note
    existing = {e.get('signature') for e in st['events'] if e.get('signature')}
    added = 0
    for e in new_events:
        sig = e.get('signature')
        if sig and sig in existing:
            continue
        st['events'].append(e)
        if sig:
            existing.add(sig)
            if sig not in st['seen']:
                st['seen'].append(sig)
        added += 1
    st['updated_at'] = now()
    st['complete'] = False
    st['cobuy_seeded'] = True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(st, indent=1), encoding='utf-8')
    return added


def main() -> None:
    settings = load_settings()
    roster_path = ROOT / 'config' / 'roster.yaml'
    doc = yaml.safe_load(roster_path.read_text(encoding='utf-8')) or {}
    wallets = list(doc.get('wallets') or [])
    seeds = [w for w in wallets if (w.get('role') or '') == 'seed']
    seed_addrs = {w['address'] for w in seeds}
    doji = next((w['address'] for w in seeds if (w.get('label') or '').lower() == 'doji'), None)
    raw = ROOT / (settings.get('paths') or {}).get('raw_dir', 'data/raw')
    hdir = history_dir(raw)
    mints = doji_mints(hdir, doji)[:5] if doji else []
    rpc = SolanaRPC(RPC, sleep_ms=280)
    hits: dict[str, dict] = {}
    all_events: dict[str, list] = {}
    used = []
    for mint in mints:
        found, evs = harvest_mint(rpc, mint, seed_addrs)
        used.append({'mint': mint, 'found': len(found), 'rpc': RPC, 'event_wallets': len(evs)})
        print(f'mint {mint[:8]}... cobuyers={len(found)} ev_wallets={len(evs)}', flush=True)
        for addr, n in found.items():
            if addr not in hits:
                hits[addr] = {'address': addr, 'overlap_hits': 0, 'mints': []}
            hits[addr]['overlap_hits'] += n
            if mint not in hits[addr]['mints']:
                hits[addr]['mints'].append(mint)
        for addr, elist in evs.items():
            all_events.setdefault(addr, []).extend(elist)

    candidates = []
    for addr, info in sorted(hits.items(), key=lambda kv: -kv[1]['overlap_hits']):
        if addr in seed_addrs:
            continue
        src = f'https://solscan.io/token/{info["mints"][0]}'
        candidates.append({
            'address': addr,
            'label': f'cobuy_{addr[:6]}',
            'role': 'expanded',
            'overlap_hits': info['overlap_hits'],
            'source_name': 'on-chain co-traders of Doji mints',
            'source_url': src,
            'provenance': {
                'source_url': src,
                'fetched_at': now(),
                'role': 'expanded',
                'method': 'rpc_mint_cobuyers',
                'mints': info['mints'],
                'hits': info['overlap_hits'],
            },
            'notes': 'Co-buyer of Doji-traded token(s) via free public Solana RPC',
        })

    prior_exp = [
        w for w in wallets
        if w.get('role') == 'expanded' and w['address'] not in {c['address'] for c in candidates}
    ]
    room = max(0, MAX_TOTAL - len(seeds))
    chosen = candidates[:room]
    for w in prior_exp:
        if len(chosen) >= room:
            break
        chosen.append(w)
    for w in seeds:
        w['role'] = 'seed'
        w.setdefault('provenance', {})
        w['provenance'].setdefault('role', 'seed')
    doc['wallets'] = seeds + chosen
    doc['roster_meta'] = {
        'seed_count': len(seeds),
        'expanded_count': len(chosen),
        'total': len(seeds) + len(chosen),
        'updated_at': now(),
        'cobuy_used': used,
        'sources_blocked': [
            {'source': 'pump.fun frontend API', 'why': 'JWT/auth — needs Jeremy free signup; NOT signed up'},
            {'source': 'X/Twitter API', 'why': 'balance ~ / policy — NOT used'},
        ],
    }
    roster_path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding='utf-8')

    seeded = []
    top_addrs = [c['address'] for c in chosen if c['address'] in all_events][:12]
    for addr in top_addrs:
        added = merge_history(hdir, addr, all_events[addr], 'cobuy_mint_harvest')
        seeded.append({'address': addr, 'added_events': added, 'harvest_events': len(all_events[addr])})
        print(f'seeded history {addr[:8]} +{added}', flush=True)

    rep = {
        'seed': len(seeds),
        'expanded': len(chosen),
        'total': len(seeds) + len(chosen),
        'cobuy_candidates': len(candidates),
        'used': used,
        'history_seeded': seeded,
    }
    (ROOT / 'out' / 'expand_cobuy_pass3.json').write_text(json.dumps(rep, indent=2), encoding='utf-8')
    print(json.dumps(rep, indent=2))


if __name__ == '__main__':
    main()
