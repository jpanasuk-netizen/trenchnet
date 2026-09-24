from pathlib import Path
p = Path("trenchnet/history.py")
t = p.read_text(encoding="utf-8")
old = '''        try:
            sigs = get_signatures_page(rpc, wallet, before=before, limit=PAGE_LIMIT)
        except Exception as exc:
            errors.append(f"page_error@{before or 'latest'}:{exc}")
            stopped_early_reason = f"page_error:{exc}"
            break'''
new = '''        try:
            sigs = get_signatures_page(rpc, wallet, before=before, limit=PAGE_LIMIT)
        except Exception as exc:
            msg = str(exc)
            # Bad/pruned cursor: drop before and retry from tip once (seen-set skips)
            if before and ("not found" in msg.lower() or "-32020" in msg):
                errors.append(f"page_cursor_reset@{before[:16]}:{exc}")
                before = None
                st["before_cursor"] = None
                log(f"{wallet[:8]}: reset before_cursor after page error")
                continue
            errors.append(f"page_error@{before or 'latest'}:{exc}")
            stopped_early_reason = f"page_error:{exc}"
            break'''
if old not in t:
    raise SystemExit('history page_error block missing')
p.write_text(t.replace(old, new), encoding='utf-8')
print('patched history cursor reset')
