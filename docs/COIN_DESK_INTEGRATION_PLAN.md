# Coin Desk → TRENCHNET Integration Plan

**Status:** investigation only (2026-09-24 CT). No processes started/stopped; no code changed except this doc.  
**Kalshi live stack:** left untouched (ports 8765/8787/8788/8790/8791 not modified).

---

## 1. What Coin Desk is

| Item | Finding |
|------|---------|
| Desktop path | `C:\Users\jpana\OneDrive\Attachments\Desktop\Coin Desk.exe` (also `C:\Users\jpana\Desktop\Coin Desk.exe`) |
| Type | **Real PE exe**, not a `.lnk`. OneDrive **reparse/cloud** tag present; file is present on disk (~8.74 MB). |
| Size / mtime | **9,169,274 bytes**; LastWriteTime **2026-09-22 4:17:39 AM CT** (matches build `dist\`) |
| Framework | **PyInstaller one-file** (`MEIPASS` / `pyi_` / `_MEIPASS` in binary; console EXE) |
| Build tree | `%LOCALAPPDATA%\token-desk-build\` — `Coin Desk.spec`, `coins_launcher.py`, `desk.py`, `dist\Coin Desk.exe` |
| Running now? | **No.** No `Coin Desk` process; **port 3010 not listening**. |
| LIVE trading? | **None.** Paper-only by design. `gate()` always sets `execute: false`, `approved: false`, `max_loss_usd: 0`. No wallet, order, or exchange APIs. |

**Source project (canonical):** WSL Ubuntu `~/token-desk` → `\\wsl.localhost\Ubuntu\home\jpanasuk\token-desk`  
Files: `desk.py` (431 lines), `coins_launcher.py` (in build dir), `start.sh`, `check_judge.py`, `peek.py`, `data/`.

**Sibling (consumer, not the exe source):** `C:\Users\jpana\Documents\HermesVault\60-Trading\memecoin-desk\` — Flask enrichment UI on **3011** that *pulls* Coin Desk `http://127.0.0.1:3010/api/state`. Documented in `docs/LESSONS.md` #11–12.

---

## 2. What it does (from source)

### Purpose
Watch **hood.fun** Base-chain style token launches. Show a dark PAPER desk. **PASS/WATCH is a note, not a buy.**

### Data source
- Public HTTP: `https://hood.fun/api/board` (User-Agent `token-desk-paper`)
- Poll every **45s**; UI refreshes every **5s** via `/api/state`

### UI screens (single page)
1. Status tile (board up / token count / newest age)
2. **Inside the last hour** (`fresh`) — judged launches
3. **Newest on the board** (`newest`, top 8, may be stale)

### Judge / gates (all non-spending)
`judge()` → `PASS` or `SKIP` (age ≤1h, name/symbol present, not graduated, not spam HOODW/HOODCL fillers, unique symbol this hour, `realEth` ≥ 0.001).  
`gate()` → stage `WATCH` or `STOP`; always `execute: false`; reasons include “approval required and none granted”, “not a Robinhood brokerage pair”.

### Local HTTP
- Bind: `0.0.0.0:3010` (browser uses `http://127.0.0.1:3010`)
- Routes: `GET /`, `GET /api/state`, 404 else
- Stack: **stdlib only** (`ThreadingHTTPServer`, `urllib`) — no Flask/FastAPI in the exe itself

### Data files
| Path | Format | Role |
|------|--------|------|
| `%LOCALAPPDATA%\token-desk\data\decisions.jsonl` | append-only JSONL | Logged fresh cards (frozen exe root) |
| `%LOCALAPPDATA%\token-desk\data\ready.txt` | text | `token desk paper http://127.0.0.1:3010` |
| WSL `~/token-desk/data/*` | same names | Dev/WSL runs (currently empty decisions) |
| `desk.err` (on bind fail) | text | Bind errors |

JSONL fields (example keys): `logged_at`, `name`, `symbol`, `address`, `creator`, `age_sec`, `ts`, `real_eth`, `graduated`, `fee_bps`, `verdict`, `reason`. Live `/api/state` also adds nested `gate`.

### Env var **names** (values not logged)
| Name | Used by | Present in process env? |
|------|---------|-------------------------|
| `LOCALAPPDATA` | frozen `_root()` for data dir | has_value=True |
| `COIN_DESK_SOURCE` | memecoin-desk only (default `http://127.0.0.1:3010/api/state`) | has_value=False |
| `BLOCKSCOUT_API_KEY` | memecoin-desk Blockscout enrichment | has_value=False |

Coin Desk core has **no** API-key / private-key env vars. `LIVE_TRADING` / `PRIVATE_KEY` / `WALLET_KEY` / `API_SECRET`: has_value=False on this shell.

### Tech stack
Python 3 (WSL build host 3.12; TRENCHNET desk uses 3.13 venv). PyInstaller one-file. Zero third-party deps in `desk.py`.

---

## 3. Git / GitHub

| Item | Status |
|------|--------|
| `~/token-desk` git | **No** `.git` / no `git remote` |
| Build dir git | None observed |
| GitHub `jpanasuk-netizen` | Repo search for token-desk / coin desk / `hood.fun/api/board` → **0 hits** |
| TRENCHNET | `origin https://github.com/jpanasuk-netizen/trenchnet.git` (separate product) |

---

## 4. Relation to TRENCHNET

| | Coin Desk | TRENCHNET |
|--|-----------|-----------|
| Chain / venue | hood.fun board (EVM/`0x…`, `real_eth`) | Solana pump.fun wallets |
| Mode | PAPER watch board | WATCH-ONLY + PAPER fills; LIVE GUI **disarmed by default** |
| UI port | **3010** | **8791** (`trenchnet.cli ui` / stdlib `webui.py`) |
| Theme | Dark zinc tiles | Liquid blue/purple space (`out/dashboard.html` + webui) |
| Lessons | Source of LESSONS #11–12 (PAPER badge, PyInstaller desk) | Already ported patterns; does not embed Coin Desk yet |

**Reusable:** hygiene/verdict labeling, append-only JSONL decisions, stdlib HTTP desk pattern, PAPER badge copy.  
**Not reusable as-is:** hood.fun board client, ETH curve fields, Base Blockscout enrichment — wrong chain for Solana paper fills.  
**Conflicts:** none on ports if Coin Desk stays on 3010 and TRENCHNET on 8791. Do **not** reuse 8765/8787/8788/8790/8791 for Coin Desk. Deps: Coin Desk needs none; importing it into TRENCHNET’s `.venv` is unnecessary for option A.

---

## 5. Integration options

### (A) Read-only “Coin Desk” tab in TRENCHNET UI — **RECOMMENDED**
Proxy/display only:
- If `127.0.0.1:3010/api/state` responds → show `fresh` / `newest` / gate stages.
- Else → fall back to read-only `%LOCALAPPDATA%\token-desk\data\decisions.jsonl` + “desk offline” banner.
- Optional: deep-link button `Open Coin Desk` → `http://127.0.0.1:3010` (no process control).
- **Do not** surface TRENCHNET `/live` arming, Coin Desk has nothing to arm anyway; keep TRENCHNET LIVE disarmed.

**Effort (rough steps):**
1. Add `GET /api/coindesk/state` in `webui.py` that GETs 3010 with short timeout (or reads JSONL).
2. Add nav tab + panel in desk HTML (theme-matched; badge `PAPER · hood.fun · Base`).
3. Poll every 5–10s client-side; label mocks/offline honestly.
4. Tests: mock 3010 JSON + empty/missing JSONL.
5. Doc one-liner in README: “Coin Desk tab is observe-only; start `Coin Desk.exe` separately if you want live board.”

### (B) Import `desk` as a package
Copy/symlink `desk.py` into TRENCHNET or add path. Pull board inside TRENCHNET process.  
**Downside:** couples Solana desk to Base board polling, second background thread, bind/port ownership fights if exe also runs. Little gain vs (A). **Not recommended.**

### (C) Launcher panel (start/stop Coin Desk.exe)
Start is low risk (paper-only). **Stop/kill is discouraged** on this machine while Kalshi/other desks are live — easy to mis-target PIDs. If ever added: start-only via `Start-Process` on the known exe path; never `taskkill` by port; never touch 8765/8787/8788/8790/8791. Prefer (A) first.

### Explicit non-goals
- Do **not** expose TRENCHNET LIVE controls through a Coin Desk tab.
- Do **not** auto-enable memecoin-desk trading (it also has $0 capital / no orders).
- Do **not** merge hood.fun tokens into Solana paper fill paths.

---

## 6. Risks

| Risk | Mitigation |
|------|------------|
| Operator confuses Base hood.fun tokens with Solana mints | Hard label chain/venue on every card |
| Hitting wrong ports / killing Kalshi | Never bind/stop 8765/8787/8788/8790/8791; Coin Desk stays 3010 |
| Stale JSONL presented as live | Show `fetched_at` / “offline fallback” |
| OneDrive reparse exe missing offline | Prefer build `dist\` or Desktop copy; tab tolerates offline |
| Parallel `Coin Desk.exe` + WSL `start.sh` both on 3010 | Launcher already detects “already running”; document single instance |
| Scope creep into LIVE | Keep tab GET-only; no POST to `/api/live/*` |

---

## 7. Recommendation

Ship **option (A)** only: a read-only Coin Desk panel/tab that consumes `/api/state` or JSONL. Reuse verdict/PAPER UX lessons already in `LESSONS.md`. Leave process lifecycle to the existing desktop exe. Revisit a start-only launcher later if Jeremy wants one-click board bring-up.

