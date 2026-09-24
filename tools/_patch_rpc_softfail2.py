from pathlib import Path
p = Path("trenchnet/data_solana.py")
t = p.read_text(encoding="utf-8")
# Revert broad soft-fail in call() if present
bad = '''                if "error" in data:
                    # rate limit style
                    err = data["error"]
                    msg = str(err)
                    if "429" in msg or "rate" in msg.lower():
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    # missing/pruned tx — caller should skip
                    code = err.get("code") if isinstance(err, dict) else None
                    low = msg.lower()
                    if code in (-32020, -32009, -32007) or "not found" in low or "missing" in low:
                        return None
                    raise RuntimeError(msg)'''
good = '''                if "error" in data:
                    # rate limit style
                    msg = str(data["error"])
                    if "429" in msg or "rate" in msg.lower():
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    raise RuntimeError(msg)'''
if bad in t:
    t = t.replace(bad, good)
    print("reverted broad soft-fail")
else:
    print("broad soft-fail already absent or different")

# Patch rpc_get_transaction to catch not-found
old_fn = '''def rpc_get_transaction(rpc: SolanaRPC, signature: str) -> dict[str, Any] | None:
    """getTransaction (jsonParsed); re-raises on repeated rate limits."""
    return rpc.call(
        "getTransaction",
        [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}],
    )'''
new_fn = '''def rpc_get_transaction(rpc: SolanaRPC, signature: str) -> dict[str, Any] | None:
    """getTransaction (jsonParsed); missing/pruned txs return None."""
    try:
        return rpc.call(
            "getTransaction",
            [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}],
        )
    except RuntimeError as exc:
        msg = str(exc).lower()
        if "not found" in msg or "missing" in msg or "-32020" in msg or "-32009" in msg:
            return None
        raise'''
if old_fn not in t:
    raise SystemExit("rpc_get_transaction block not found")
t = t.replace(old_fn, new_fn)
p.write_text(t, encoding="utf-8")
print("patched rpc_get_transaction soft-fail")
