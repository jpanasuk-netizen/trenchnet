from pathlib import Path
p = Path("trenchnet/data_solana.py")
t = p.read_text(encoding="utf-8")
old = '''                if "error" in data:
                    # rate limit style
                    msg = str(data["error"])
                    if "429" in msg or "rate" in msg.lower():
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    raise RuntimeError(msg)'''
new = '''                if "error" in data:
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
if old not in t:
    raise SystemExit("patch target missing")
p.write_text(t.replace(old, new), encoding="utf-8")
print("patched data_solana soft-fail")
