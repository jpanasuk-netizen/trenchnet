def parse_enhanced_swap(tx: dict[str, Any], wallet: str) -> list[TradeEvent]:
    """Convert one Helius enhanced tx into TradeEvent(s) for wallet."""
    if not isinstance(tx, dict):
        return []
    sig = tx.get("signature") or ""
    if not sig:
        return []
    src = str(tx.get("source") or "")
    slot = tx.get("slot")
    ts = tx.get("timestamp") or tx.get("blockTime")
    try:
        block_time = int(ts) if ts is not None else None
    except Exception:
        block_time = None
    events: list[TradeEvent] = []

    def _add(mint: str, side: str, amt: float, sol: float | None = None, note: str = "") -> None:
        if not mint or mint == WSOL:
            return
        events.append(TradeEvent(
            signature=sig,
            wallet=wallet,
            token_mint=str(mint),
            side=side,  # type: ignore[arg-type]
            amount_token=abs(float(amt or 0)),
            amount_sol=sol,
            slot=int(slot) if slot is not None else None,
            block_time=block_time,
            program_id=src or str(tx.get("type") or "HELIUS"),
            raw_note=note or f"helius type={tx.get('type')} source={src}",
            source="helius",
        ))

    swap = ((tx.get("events") or {}) if isinstance(tx.get("events"), dict) else {}).get("swap")
    if isinstance(swap, dict):
        for side_key, side in (("tokenInputs", "sell"), ("tokenOutputs", "buy")):
            for item in swap.get(side_key) or []:
                if not isinstance(item, dict):
                    continue
                mint = item.get("mint") or item.get("tokenMint")
                raw_amt = item.get("tokenAmount") or item.get("rawTokenAmount") or {}
                if isinstance(raw_amt, dict):
                    try:
                        amt = float(raw_amt.get("tokenAmount") or raw_amt.get("uiAmount") or 0)
                    except Exception:
                        amt = 0.0
                else:
                    try:
                        amt = float(raw_amt or 0)
                    except Exception:
                        amt = 0.0
                sol = None
                if side == "buy":
                    ni = swap.get("nativeInput") or {}
                    if isinstance(ni, dict):
                        try:
                            sol = abs(float(ni.get("amount") or 0)) / 1e9
                        except Exception:
                            sol = None
                else:
                    no = swap.get("nativeOutput") or {}
                    if isinstance(no, dict):
                        try:
                            sol = abs(float(no.get("amount") or 0)) / 1e9
                        except Exception:
                            sol = None
                _add(str(mint or ""), side, amt, sol, "helius_events.swap")
        if events:
            return events

    for tr in tx.get("tokenTransfers") or []:
        if not isinstance(tr, dict):
            continue
        mint = tr.get("mint")
        frm = tr.get("fromUserAccount")
        to = tr.get("toUserAccount")
        try:
            amt = float(tr.get("tokenAmount") or tr.get("amount") or 0)
        except Exception:
            amt = 0.0
        if to == wallet:
            _add(str(mint or ""), "buy", amt, None, "helius_tokenTransfer")
        elif frm == wallet:
            _add(str(mint or ""), "sell", amt, None, "helius_tokenTransfer")
    if events:
        return events

    for acc in tx.get("accountData") or []:
        if not isinstance(acc, dict):
            continue
        for tb in acc.get("tokenBalanceChanges") or []:
            if not isinstance(tb, dict):
                continue
            user = tb.get("userAccount")
            if user and user != wallet and acc.get("account") != wallet:
                continue
            if not user and acc.get("account") != wallet:
                continue
            mint = tb.get("mint")
            raw = tb.get("rawTokenAmount") or {}
            amt = 0.0
            try:
                if isinstance(raw, dict):
                    if raw.get("uiAmount") is not None:
                        amt = float(raw.get("uiAmount") or 0)
                    else:
                        token_amount = float(raw.get("tokenAmount") or 0)
                        dec = int(raw.get("decimals") or 0)
                        amt = token_amount / (10 ** dec) if dec else token_amount
            except Exception:
                amt = 0.0
            if abs(amt) < 1e-18:
                continue
            side = "buy" if amt > 0 else "sell"
            _add(str(mint or ""), side, abs(amt), None, "helius_accountData")
    return events

