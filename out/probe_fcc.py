import json
import os
import sys

sys.path.insert(0, r"C:\Users\jpana\Documents\HermesTools\trenchnet")
os.chdir(r"C:\Users\jpana\Documents\HermesTools\trenchnet")

from trenchnet.secrets import get_secret, secret_present  # noqa: E402
import httpx  # noqa: E402

BASE = "http://127.0.0.1:8082"
results = []


def note(name, r):
    body = (r.text or "")[:400]
    try:
        body = json.dumps(r.json())[:400]
    except Exception:
        pass
    results.append({"probe": name, "status": r.status_code, "body": body})
    print(f"[{name}] HTTP {r.status_code}: {body[:300]}", flush=True)


has = secret_present("FCC_API_KEY")
print("FCC_API_KEY present:", has, flush=True)
key = get_secret("FCC_API_KEY") or ""
H = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
MODEL = "anthropic/cloudflare/@cf/moonshotai/kimi-k2.7-code"

with httpx.Client(timeout=30) as c:
    try:
        r = c.get(f"{BASE}/v1/models", headers=H)
        note("GET /v1/models", r)
        ids = []
        try:
            j = r.json()
            ids = [m.get("id") for m in j.get("data", [])]
        except Exception:
            pass
        print("models count:", len(ids), flush=True)
        anth = [i for i in ids if "anthropic" in (i or "").lower()][:3]
        simple = [i for i in ids if "/" not in (i or "") and "@" not in (i or "")][:5]
        print("anthropic-ish:", anth, flush=True)
        print("simple:", simple[:10], flush=True)
        cands = list(dict.fromkeys([MODEL] + anth[:2] + simple[:2]))
        try:
            note("GET /v1/models/anthropic", c.get(f"{BASE}/v1/models/anthropic"))
        except Exception as e:
            print("models/anthropic err:", e, flush=True)
        try:
            note("GET /api/v0/models", c.get(f"{BASE}/api/v0/models"))
        except Exception as e:
            print("api/v0 err:", e, flush=True)
        for m in cands[:5]:
            try:
                note(
                    f"chat {m}",
                    c.post(
                        f"{BASE}/v1/chat/completions",
                        headers=H,
                        json={"model": m, "messages": [{"role": "user", "content": "Reply with exactly: OK"}], "max_tokens": 16},
                    ),
                )
            except Exception as e:
                print(f"chat {m} err: {e}", flush=True)
        try:
            note("messages (bearer)", c.post(f"{BASE}/v1/messages", headers=H, json={"model": MODEL, "max_tokens": 32, "messages": [{"role": "user", "content": "Reply with exactly: OK"}]}))
        except Exception as e:
            print("messages bearer err:", e, flush=True)
        try:
            note("messages (x-api-key)", c.post(f"{BASE}/v1/messages", headers={"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}, json={"model": MODEL, "max_tokens": 32, "messages": [{"role": "user", "content": "Reply with exactly: OK"}]}))
        except Exception as e:
            print("messages x-api-key err:", e, flush=True)
        try:
            note("messages claude-3-5-sonnet", c.post(f"{BASE}/v1/messages", headers={"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}, json={"model": "claude-3-5-sonnet", "max_tokens": 32, "messages": [{"role": "user", "content": "Reply with exactly: OK"}]}))
        except Exception as e:
            print("messages sonnet err:", e, flush=True)
        try:
            note("ollama api/chat", c.post(f"{BASE}/api/chat", json={"model": MODEL, "messages": [{"role": "user", "content": "Reply with exactly: OK"}], "stream": False}))
        except Exception as e:
            print("api/chat err:", e, flush=True)
        try:
            note("v1/completions", c.post(f"{BASE}/v1/completions", headers=H, json={"model": MODEL, "prompt": "Say OK", "max_tokens": 8}))
        except Exception as e:
            print("completions err:", e, flush=True)
    except Exception as exc:
        print("FCC unreachable:", exc, flush=True)
        results.append({"probe": "connection", "status": 0, "body": str(exc)})

with open("out/fcc_probe_results.json", "w") as f:
    json.dump(results, f, indent=2)
print("DONE", flush=True)
