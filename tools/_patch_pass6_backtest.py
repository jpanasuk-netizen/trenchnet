from pathlib import Path

p = Path("trenchnet/backtest.py")
src = p.read_text(encoding="utf-8")

old_sig = '''def simulate_copy_trade(
    pair: dict[str, Any],
    *,
    delay_s: int,
    exit_mode: str,
    prices: dict[str, list[PricePoint]],
    all_events: list[dict[str, Any]],
    cfg: dict[str, Any],
    position_sol: float | None = None,
    slippage_mult: float = 1.0,
    take_profit_pct: float | None = None,
    stop_loss_pct: float | None = None,
    time_stop_seconds: int | None = None,
) -> CopyTradeResult:'''

new_sig = '''def simulate_copy_trade(
    pair: dict[str, Any],
    *,
    delay_s: int,
    exit_mode: str,
    prices: dict[str, list[PricePoint]],
    all_events: list[dict[str, Any]],
    cfg: dict[str, Any],
    position_sol: float | None = None,
    slippage_mult: float = 1.0,
    take_profit_pct: float | None = None,
    stop_loss_pct: float | None = None,
    time_stop_seconds: int | None = None,
    families: dict[str, dict[str, list[PricePoint]]] | None = None,
) -> CopyTradeResult:'''

if old_sig not in src:
    raise SystemExit("sig not found")
src = src.replace(old_sig, new_sig, 1)

start = src.find("    entry_t = buy_t + int(delay_s)")
end = src.find("    gross = (exit_px / entry_px) - 1.0")
if start < 0 or end < 0:
    raise SystemExit(f"markers missing start={start} end={end}")

new_body = '''    entry_t = buy_t + int(delay_s)
    pricing_cfg = cfg.get("pricing") or {}
    max_staleness = int(pricing_cfg.get("max_staleness_seconds", 60))
    mode_out = exit_mode

    fams = families
    if fams is None:
        fams = {"derived": prices, "helius_pool": {}, "birdeye": {}}

    if exit_mode == "mirror":
        if not (sell and sell.get("block_time") is not None):
            return CopyTradeResult(
                wallet=wallet, token_mint=mint, buy_sig=str(buy.get("signature") or ""),
                buy_time=buy_t, delay_s=delay_s, exit_mode=exit_mode,
                entry_px=None, exit_px=None, entry_source="", exit_source="",
                position_sol=pos, gross_return=None, net_return=None, pnl_sol=None,
                costs_sol=None, unpriceable=True, reason="no_mirror_sell",
            )
        exit_t = int(sell["block_time"]) + int(delay_s)
        if exit_t <= entry_t:
            exit_t = entry_t + 1
        entry_px, exit_px, entry_src, exit_src = lookup_entry_exit(
            mint, entry_t, exit_t, fams, max_staleness_s=max_staleness,
        )
        if entry_px is None or exit_px is None:
            return CopyTradeResult(
                wallet=wallet, token_mint=mint, buy_sig=str(buy.get("signature") or ""),
                buy_time=buy_t, delay_s=delay_s, exit_mode=exit_mode,
                entry_px=entry_px, exit_px=exit_px, entry_source=entry_src or "", exit_source=exit_src or "",
                position_sol=pos, gross_return=None, net_return=None, pnl_sol=None,
                costs_sol=None, unpriceable=True,
                reason="no_entry_price" if entry_px is None else "no_exit_price_mirror",
            )
    else:
        entry_px = None
        entry_src = ""
        series: list[PricePoint] = []
        for fam in ("helius_pool", "derived", "birdeye"):
            series = (fams.get(fam) or {}).get(mint) or []
            entry_px, entry_src = price_at(series, entry_t, max_gap_s=max_staleness)
            if entry_px is not None:
                break
        if entry_px is None:
            return CopyTradeResult(
                wallet=wallet, token_mint=mint, buy_sig=str(buy.get("signature") or ""),
                buy_time=buy_t, delay_s=delay_s, exit_mode=exit_mode,
                entry_px=None, exit_px=None, entry_source="", exit_source="",
                position_sol=pos, gross_return=None, net_return=None, pnl_sol=None,
                costs_sol=None, unpriceable=True, reason="no_entry_price",
            )
        deadline = entry_t + tstop
        hit = None
        for pt in series:
            if pt.t < entry_t:
                continue
            if pt.t > deadline:
                break
            ret = (pt.px / entry_px) - 1.0
            if ret >= tp:
                hit = (pt, "take_profit")
                break
            if ret <= -sl:
                hit = (pt, "stop_loss")
                break
        if hit:
            exit_px, exit_src = hit[0].px, hit[0].source
            mode_out = f"fixed:{hit[1]}"
        else:
            exit_px, exit_src = price_at(series, deadline, max_gap_s=max_staleness)
            mode_out = "fixed:time_stop"
            if exit_px is None and entry_src != "birdeye":
                for fam in ("helius_pool", "derived"):
                    alt = (fams.get(fam) or {}).get(mint) or []
                    exit_px, exit_src = price_at(alt, deadline, max_gap_s=max_staleness)
                    if exit_px is not None:
                        break
            if exit_px is None:
                return CopyTradeResult(
                    wallet=wallet, token_mint=mint, buy_sig=str(buy.get("signature") or ""),
                    buy_time=buy_t, delay_s=delay_s, exit_mode=mode_out,
                    entry_px=entry_px, exit_px=None, entry_source=entry_src, exit_source="",
                    position_sol=pos, gross_return=None, net_return=None, pnl_sol=None,
                    costs_sol=None, unpriceable=True, reason="no_exit_price_fixed",
                )

'''

src = src[:start] + new_body + src[end:]

old_rb = '''    events = load_all_history_events(root)
    derived = build_derived_price_index(events)
    birdeye = load_birdeye_ohlcv(root)
    prices = merge_price_indexes(birdeye, derived)
    pairs = _pair_buys_sells(events)'''

new_rb = '''    events = load_all_history_events(root)
    derived = build_derived_price_index(events)
    birdeye = load_birdeye_ohlcv(root)
    pool = load_helius_pool_pricepoints(root)
    prices: dict[str, list[PricePoint]] = {}
    for m in set(pool) | set(derived):
        if m in pool and len(pool[m]) >= 1:
            prices[m] = pool[m]
        elif m in derived:
            prices[m] = derived[m]
    for m, series in birdeye.items():
        if m not in prices:
            prices[m] = series
    families = {
        "helius_pool": pool,
        "derived": derived,
        "birdeye": birdeye,
    }
    pairs = _pair_buys_sells(events)'''

if old_rb not in src:
    raise SystemExit("run_backtest load block missing")
src = src.replace(old_rb, new_rb, 1)

src = src.replace(
    '''                r = simulate_copy_trade(
                    pair, delay_s=delay, exit_mode=mode, prices=prices,
                    all_events=events, cfg=cfg,
                )''',
    '''                r = simulate_copy_trade(
                    pair, delay_s=delay, exit_mode=mode, prices=prices,
                    all_events=events, cfg=cfg, families=families,
                )''',
)

old_wf_call = '        "walk_forward": run_walk_forward(pairs, prices, events, cfg),'
new_wf_call = '        "walk_forward": run_walk_forward(pairs, prices, events, cfg, families=families),'
if old_wf_call not in src:
    raise SystemExit("wf call missing")
src = src.replace(old_wf_call, new_wf_call, 1)

old_wf_def = '''def run_walk_forward(
    pairs: list[dict[str, Any]],
    prices: dict[str, list[PricePoint]],
    events: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[str, Any]:'''
new_wf_def = '''def run_walk_forward(
    pairs: list[dict[str, Any]],
    prices: dict[str, list[PricePoint]],
    events: list[dict[str, Any]],
    cfg: dict[str, Any],
    families: dict[str, dict[str, list[PricePoint]]] | None = None,
) -> dict[str, Any]:'''
if old_wf_def not in src:
    raise SystemExit("wf def missing")
src = src.replace(old_wf_def, new_wf_def, 1)

src = src.replace(
    '''                r = simulate_copy_trade(
                    p, delay_s=60, exit_mode="fixed", prices=prices, all_events=events, cfg=cfg,
                )''',
    '''                r = simulate_copy_trade(
                    p, delay_s=60, exit_mode="fixed", prices=prices, all_events=events, cfg=cfg,
                    families=families,
                )''',
)

src = src.replace(
    '''        "price_index": {
            "birdeye_mints": len(birdeye),
            "derived_mints": len(derived),
            "merged_mints": len(prices),
            "source_tags": ["helius", "birdeye", "rpc", "derived"],
        },''',
    '''        "price_index": {
            "helius_pool_mints": len(pool),
            "birdeye_mints": len(birdeye),
            "derived_mints": len(derived),
            "merged_mints": len(prices),
            "source_tags": ["helius_pool", "helius", "birdeye", "rpc", "derived"],
            "max_staleness_seconds": int((cfg.get("pricing") or {}).get("max_staleness_seconds", 60)),
        },''',
)

p.write_text(src, encoding="utf-8")
import ast
ast.parse(src)
print("patched OK", len(src))
