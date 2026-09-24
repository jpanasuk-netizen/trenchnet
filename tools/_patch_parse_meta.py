from pathlib import Path
p = Path("trenchnet/helius_client.py")
t = p.read_text(encoding="utf-8")
start = t.find("def parse_enhanced_swap")
end = t.find("\ndef rpc_url_for_solana")
assert start > 0 and end > start
new_fn = Path("tools/_parse_fn.py.txt")
# embed via separate write below
print(start, end)
