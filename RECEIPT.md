# TRENCHNET RECEIPT

---

## Freebuff PASS 3 — 2026-09-24 (RPC pool + parallel fetch + roster expansion + token context)

Rules held: watch/paper only · no keys/signing/order code written · LIVE stub untouched · **trenchnet/live/ (Jeremy's queued LIVE work) not edited by this pass** · no spend · no X API · no invented numbers · nothing signed up on Jeremy's behalf.

Note: PASS 3 modules were built **concurrently by two agents**. This pass filled gaps without overwriting the other session's code: adapted tests to the shipped `rpc_pool` interface (FREE_RPC_URLS + cooldown map + bind_wallet) instead of rewriting it.

### What exists now (verified)
- **A) `trenchnet/rpc_pool.py`** — MultiEndpointRPC across the 3 verified free no-signup URLs (`api.mainnet-beta.solana.com`, `solana-rpc.publicnode.com`, `api.mainnet.solana.com`): round-robin, per-endpoint cooldown on 429/error, `bind_wallet(i)` sticky RPCs for workers.
- **B) `tools/parallel_fetch_history.py`** — ThreadPool (3 workers), sticky endpoint per worker, resumable via history.py checkpoints, skips completed wallets, short-run caps for zero-fill spam wallets, writes `out/fetch_history_pass3.log` (110+ lines and growing from the live run) + `out/fetch_history_pass3_summary.json`. `fetch-history` keeps running in background; not killed.
- **C) `trenchnet/sources_expand.py` + CLI `expand-roster`** — free sources only: kolscan GitHub snapshot (raw.githubusercontent), on-chain mint co-buyers via `getSignaturesForAddress(mint)` on free RPC, Dexscreener token API. Caps 40 total, original 8 kept `role: seed`, expanded tagged with `source_url`+`fetched_at`, writes `config/roster.yaml` + `out/expand_roster_pass3.json`. pump.fun frontend probe recorded as blocked (needs JWT) — **NOT signed up**.
- **D) `trenchnet/token_context.py` + CLI `fetch-token-context`** — Dexscreener pair snapshot + GeckoTerminal token/OHLCV per graph mint → `data/raw/token_context/<mint>.json` with source URLs; wired into bake as `TRENCHNET_DATA.token_context` + `panels.token_context`.
- **E) Web mentions** — thin mentions (kind/type/url/source_url) extracted from Dexscreener pair socials/websites only. No X API anywhere.

### What THIS pass added
- **Dashboard**: new full-width **Token context** panel (symbol/price/liq/vol/24h% from real pair snapshots; every row links Dexscreener/GeckoTerminal/Solscan; honest empty + thin labels); **Gecko OHLCV price overlay** on flow lanes (dashed purple, normalized, drawn only when real OHLCV exists) — `docs/dashboard_template.html` → `out/dashboard.html`.
- **Tests** `tests/test_pass3.py` (9): token_context pair/mentions/thin/broken-file handling, kolscan parse + blocked-record, expand-roster seed-preservation + cap + blocked list (monkeypatched, writes to tmp), rpc_pool 429 failover + all-fail + URL set.
- **Live fetch**: `fetch-token-context` pulled **12 real mints** (e.g. `4nV5gNww…` BOBO $0.005633 liq $338k; `2r1QzuF3…` OTC $0.000008464 liq $6.6k) and rebaked `out/assets/data.js` (heatmap now 51 real trades, 6 flow lanes).
- **RECEIPT** (this section).

### Blocked / honest gaps for Jeremy
1. **pump.fun frontend API** (`frontend-api-v3.pump.fun`) — trades/holders endpoints need auth/JWT; **do NOT want signup without your OK**. Kolscan mirror + on-chain co-buyer scan used instead.
2. **GeckoTerminal OHLCV** returned no data for these 12 niche mints this run (free tier 404s) — overlay is wired and will draw automatically when OHLCV exists; token metadata also thin for some.
3. **X/Twitter API** — not used (policy). Mentions come from Dexscreener socials only.
4. `expand-roster` is **implemented but not executed** this pass (concurrent sessions both own config/roster.yaml; avoiding write conflict). Run when idle: `python -m trenchnet.cli expand-roster`.
5. Gecko/Dexscreener snapshots are point-in-time — refetch via `fetch-token-context` for fresh prices.

### Verification
- pytest: **72 passed** (54 prior + 9 PASS 3 + 9 live-module tests found on disk; full run green, 0 failed).
- Dashboard rebaked with 12 token contexts; UI on **:8791 (Jeremy's) not touched**; background fetch not killed.

---

## Freebuff PASS 2 â€” 2026-09-24 (history wiring + lower-half panels)

Same hard rules held: watch/paper only Â· no order code Â· LIVE DISABLED stub, no implementation Â· no spend Â· Hermes not started Â· no invented numbers Â· secrets never printed. Background `fetch-history` was left running and untouched; its per-wallet caches grew during the pass and flow into every bake.

### A) Full history wired into the pipeline
- `trenchnet/pipeline.py`: `run_replay` now merges `data/raw/history/*.json` (via `history_events_for_wallet`) with poll raw files, deduped by `(wallet, signature, token_mint)` â€” see new `dedupe_events` in `trenchnet/history.py`. Multiple token mints in one tx stay distinct; duplicates across poll/history are collapsed.
- Profiles, graph, routes, reports, timelines all consume the merged set (they already read `events` from `run_replay`). Every replay/fetch regenerates `out/` + `out/assets/data.js`.
- Evidence: replay run summary `events: 7` at pipeline start; dashboard bake minutes later counted 41 real events because the background fetch checkpointed new pages meanwhile (atomic `.tmp`+replace writes keep concurrent reads safe).

### B) Dashboard lower half (3440 ultrawide + responsive)
- `docs/dashboard_template.html` â†’ `out/dashboard.html`: new `.lower` grid with four panels (theme unchanged: deep space, glass, #00B4FF / #B026FF, DPR-crisp canvas, Catmull-Rom smoothing, eased reveal, prefers-reduced-motion respected):
  1. **Activity heatmap (UTC)** â€” 7x24 cells from real `block_time`s; hover tooltip per cell; thin-data labeled.
  2. **Buy/sell flow per token** â€” cumulative SOL flow; smooth curve is visual-only, markers sit only on real txs; click near a marker opens `https://solscan.io/tx/<sig>`.
  3. **Wallet co-entry matrix** â€” pairwise shared-token intensity from graph co-entries; honest empty state when 0 co-entries.
  4. **Paper ledger table** â€” FILL rows (side tag, wallet label, token, SOL, price-source sig â†’ Solscan) + REFUSED rows with reason; honest empty state when ledger empty.
- `trenchnet/dashboard.py`: new `derive_panels` + `derive_heatmap` / `derive_token_flows` / `derive_coentry_matrix` / `derive_paper_table`; baked under `TRENCHNET_DATA.panels` (keys: `heatmap`, `token_flows`, `coentry_matrix`, `paper_table`, `labels`, `thin_data`).
- First bake with panels: heatmap total **41 real trades**; token flows 6 tokens (top: `6TcFqnzyâ€¦` 14 txs, `BEkHheGKâ€¦` 8, `2r1QzuF3â€¦` 5); co-entry matrix + paper table show labeled empty states (0 co-entries yet, 0 paper fills yet).

### C) Tests
- `tests/test_dashboard.py` (new, 13 tests): dedupe identity + malformed-row handling, UTC heatmap counting, flow running-net + unknown-side exclusion, co-entry matrix indexing, paper table mapping, thin-data flag, label map.
- pytest: **54 passed** (was 41; +13).

### D) Process notes
- No long-lived UI started this pass; regenerate hooks remain on every replay/fetch (executor can re-shoot screenshots any time).
- Background fetch-history untouched; progress visible via `history-status` and the dashboard History-progress panel.

### Remaining gaps
1. Co-entry matrix empty until â‰¥2 roster wallets buy the same token inside the window (data-driven, not a bug).
2. Paper ledger empty until first desk/CLI paper fill.
3. HyperFrames video + Desk.exe still deferred (unchanged from Pass 1).

## Freebuff upgrade â€” 2026-09-24 (Chunks 1-3)

Rules held: observe/paper only Â· no order code anywhere Â· no secrets printed/committed Â· no spend Â· Hermes not started Â· no invented numbers (every paper fill cites the real price-source tx signature).

### What changed

**Chunk 1 â€” FCC client fixed (real LLM now works)**
- `trenchnet/llm_fcc.py`: primary call switched to **POST {base}/v1/messages** (Anthropic-style; proven in `out/fcc_probe_results.json`). OpenAI /chat/completions stays 404 on this server and is not used. Auth: Bearer then x-api-key fallback. Parses content[] blocks type==text (thinking blocks skipped). Labeled template fallback retained.
- Evidence: live replay now reports **`fcc_mode: "fcc"`** with model `anthropic/cloudflare/@cf/moonshotai/kimi-k2.7-code` â€” profiles + situation reports are real LLM output (was template_fallback).
- `tests/test_llm_fcc.py`: 10 mocked-HTTP tests (success, auth fallback, 404â†’template, missing key, network errors).
- `docs/LESSONS.md`: 12-row Lessons|Source|Application table ported read-only from btc-15m-typesafe (hygiene gates, thresholds, skip-streak halt), alpha-engine paper_exec/gates (LIVE abort, jsonl-only), kalshi entry_gate (price/prob skips), jev-dashboard (tiles+SSE), memecoin-desk (PAPER badge desk), 15-min-BTC-JAP README (kill-switch flag file).

**Chunk 2 â€” Paper engine + full history**
- `trenchnet/paper.py` (new): PAPER-only ledger at `data/paper/ledger.jsonl` (append-only JSONL, every row mode=PAPER). Buy/Sell/Close priced from the most recent REAL on-chain trade for the token; fills store `price_source_signature`; no price â†’ refusal with reason (refusal rows logged). Hygiene gates before any fill: kill_switch flag file `data/paper/KILL_SWITCH`, live_guard (private-key envs), no_real_price, oversized_vs_typical, skip_streak_halt (20), loss_streak_halt (5), daily_loss_cap_sol (3.0), insufficient_balance, no_open_position. Sizing min(10% balance, 1.0 SOL). **LIVE toggle: DISABLED stub, NO implementation** â€” even live_toggle:LIVE in yaml refuses.
- `trenchnet/history.py` (new): resumable full-history pager (getSignaturesForAddress + before until empty page), checkpoints after every page to `data/raw/history/<wallet>.json`, 429-safe, parse pump.fun bonding-curve + PumpSwap.
- `trenchnet/cli.py`: `fetch-history [--wallet --max-pages --max-tx]`, `history-status`, `paper-buy/sell/close`, `paper-kill on|off`, `paper-status`, `ui`.
- `config/settings.yaml`: new `paper:` block (all risk controls) + `live_toggle: DISABLED`.

**Chunk 3 â€” Static dashboard + desk UI**
- `docs/dashboard_template.html` â†’ baked to **`out/dashboard.html`** + **`out/assets/data.js`** (`window.TRENCHNET_DATA=...`, file://-friendly, no fetch). Theme: deep-space bg, glass panels, electric blue #00B4FF / purple #B026FF, ultrawide-first grid (3440 â†’ 1920 â†’ 1280), persistent WATCH-ONLY / PAPER / LIVE OFF badges, hero stat tiles, damped 60fps force graph on DPR canvas, Catmull-Rom timeline lanes (markers only on real txs), route badges, empty states labeled, prefers-reduced-motion respected.
- `trenchnet/dashboard.py`: collects REAL out/+data/ artifacts only; regenerates on every replay/fetch via CLI hooks.
- `trenchnet/webui.py` + `run_ui.bat`: stdlib desk server `python -m trenchnet.cli ui` on 127.0.0.1:8791 â€” serves dashboard + JSON API (`/api/overview`, `/health`, SSE `/api/events`, PAPER buy/sell/close, kill switch, background fetch-history/replay). PAPER endpoints write the ledger only; there is no order endpoint at all.
- `tests/test_webui.py`: 5 route tests.

### Verification
- pytest: **41 passed** (`\.venv\Scripts\python.exe -m pytest -q`): PnL/graph/routing 8, FCC 10, paper 12, history 5, webui 5, plus prior. 
- Replay: events 5 Â· profiles 8 Â· routes 8 Â· timelines 2 Â· **fcc_mode=fcc** Â· Jev dry_run_mock (TYPESAFE_API_KEY unset, not hunted) Â· focus token As2YQNcGb4faenRY6jaTq14Jy1eQhkHoineeaZxdfCa2.
- UI: `/`, `/assets/data.js`, `/paper`, `/health` all HTTP 200; health shows kill_switch state + PAPER counters; server **stopped** after verification.
- Screenshots (headless Edge): `out/dashboard_3440.png` (3440x1440) Â· `out/dashboard_1920.png` (1920x1080) Â· `out/dashboard_1280.png` (1280x800).

### FCC endpoint/model status
- `GET /v1/models` â†’ 200 (1071 models). `POST /v1/messages` (Bearer) â†’ 200 with `anthropic/cloudflare/@cf/moonshotai/kimi-k2.7-code`. `/v1/chat/completions` â†’ 404 (not implemented server-side). FCC_API_KEY loaded at runtime via `trenchnet/secrets.py` from hermes .env; never printed/committed.

### Exact output paths
- Dashboard: `out/dashboard.html` + `out/assets/data.js` (+ template `docs/dashboard_template.html`, generator `trenchnet/dashboard.py`)
- Screenshots: `out/dashboard_3440.png`, `out/dashboard_1920.png`, `out/dashboard_1280.png`
- Paper ledger: `data/paper/ledger.jsonl` (empty until first desk/CLI paper fill; kill switch `data/paper/KILL_SWITCH`)
- History caches: `data/raw/history/<wallet>.json` (per-wallet resumable progress)
- Newest situation report: `out/reports/token_As2YQNcGb4fa_latest.md` (FCC-written) Â· Timelines: `out/timelines/index.md`
- Lessons: `docs/LESSONS.md`
- Launcher: `run_ui.bat` (venv python, port 8791)

### Remaining gaps (honest)
1. Full-history fetch **not yet run live** against public RPC this session (pager is tested + resumable; run `fetch-history` and check `history-status` â€” per-wallet completeness is reported honestly, never invented).
2. History events not yet merged into profiles/graph/reports inputs (cached + parseable via `history_events_for_wallet`; wiring pending).
3. HyperFrames flythrough video skipped: timebox (session ~15 min left); wiring HTMLâ†’video export was disproportionate to the budget. No spend incurred.
4. PyInstaller Desk.exe + desktop .lnk repoint not done this session (build_desk.ps1 pending); `run_ui.bat` is the working launcher, shortcuts unchanged.
5. Dashboard is the single-page desk (hero/roster/graph/lanes/side panel); multi-page route/report/history sub-pages still fold into it via out/ artifacts.
6. Public RPC rate limits still bound bulk history pulls (small batches + sleep enforced).

---

Generated: 2026-09-24 ~03:03 CDT (LightBringer)

## Grok CLI

- Attempted: `grok` **1.0.41** (4220f3b224a6) [stable]
- Flags: `--cwd` trenchnet, `--prompt-file GROK_BUILD_PROMPT.md`, `--always-approve`, `--effort xhigh`, `--output-format streaming-json`, `--max-turns 100`, `--permission-mode bypassPermissions`
- **BLOCKED**: HTTP **402** `Grok Build usage balance exhausted`
- Build completed **directly on LightBringer** after Grok failed.

## Commands that ran

```powershell
cd C:\Users\jpana\Documents\HermesTools\trenchnet
.\\.venv\Scripts\python.exe -m trenchnet.cli replay
.\\.venv\Scripts\python.exe -m pytest -q
```

Replay summary:

```json
{
  "events": 5,
  "profiles": 8,
  "routes": 8,
  "timelines": 2,
  "fcc_mode": "template_fallback",
  "fcc_available": true,
  "fcc_model": "anthropic/cloudflare/@cf/moonshotai/kimi-k2.7-code",
  "focus_token": "As2YQNcGb4faenRY6jaTq14Jy1eQhkHoineeaZxdfCa2",
  "report_event_id": "token_As2YQNcGb4fa",
  "jev_modes": [
    "dry_run_mock"
  ],
  "observe_only": true
}
```

Tests: **8 passed** (PnL math, graph/co-entry, routing rules).

## Exact output paths

- Profiles: `C:\Users\jpana\Documents\HermesTools\trenchnet\out\profiles\`
- Graph: `C:\Users\jpana\Documents\HermesTools\trenchnet\out\graph\summary.json` (+ `.md`)
- Routes: `C:\Users\jpana\Documents\HermesTools\trenchnet\out\routes\` (+ `all_routes.json`)
- Situation report: `C:\Users\jpana\Documents\HermesTools\trenchnet\out\reports\token_As2YQNcGb4fa_latest.md` (+ timestamped JSON/MD)
- Timelines: `C:\Users\jpana\Documents\HermesTools\trenchnet\out\timelines\` (2 tokens: md/html/json + `index.md`)

## Data source that worked

- Solana public RPC `https://api.mainnet-beta.solana.com` (`getSignaturesForAddress` + `getTransaction` jsonParsed, `maxSupportedTransactionVersion=1`)
- Raw saved under `data/raw/<wallet>.json` for offline replay
- pump.fun program `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P` (ecosystem also recognizes PumpSwap `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`)
- `frontend-api-v3.pump.fun/coins` listing works free; wallet trade endpoints 400/404 (unused)

## Seed wallets

- URL: https://github.com/yksanjo/kol-tracker/blob/main/snapshots/2026-05-21_0320Z.json
- Upstream: https://kolscan.io/leaderboard
- 8 wallets = monthly ranks 1-8 in that snapshot (`config/roster.yaml`) â€” **not placeholders**
- Doji address verified equal to snapshot wallet

## Sample real tx signatures (Doji `5ZuV8eqkvzYFVEKbLvGBdexL2tFv7E5BCd2HZpjqbdg`)

- `3FiJHipH7sCf8AWrCtZRqMpDERhYVUk9JuYFgt8bTgitnu6GAQYnb77XMnrnPArzLk64R72wu1N9YNPVLrdD6Sfa`
- `26J4wigwt4EfjLVq62m6kbJq4xz1XFGx82hXpaKThjJupLohxqqZB6AdHik6MZKhRGEyvnUxyuAvV8w1zphEK8rE`
- `3JcS3dq6HJSYoCSkreysMB65khMoAYsu6U7qMPUtSNBLdHXpcXmvtXYE4oeKN4dcViB2YMdCa8fEXNVQjtWA9aMf`
- `3dRQNPtfy6RnLkr5bA76YxT8cJ6AUHzuVaZVW6xRcoj1jYJCVm6sdPwqdcEpnTRHQpLhRDbhn4E6jbh1tYH5ctyy`
- `3RdjLd1D3P3Xuz6Q5DjWUk5Z4hDp5WFWx1RnM3FHA3PgbGH8TvENfkR12zoVPnkWPnnhMHut69cXAXD1KJnt67XF`

Live re-check: one signature via RPC `getTransaction` -> slot **449954901**, `err=None`.

## Models

- **FCC**: `/v1/models` OK (~1071). Config model `anthropic/cloudflare/@cf/moonshotai/kimi-k2.7-code`. Chat completions **HTTP 404**; `/v1/messages` upstream NIM error -> **template_fallback** writer (labeled in outputs).
- **Jev**: `TYPESAFE_API_KEY` unset -> **dry_run_mock** (labeled). Would use `jev-latest` when keyed.

## Counts

- Events: 5 | Profiles: 8 | Routes: 8 | Timelines: 2
- Graph edges: 5 | co-entries: 0 (single active wallet in this sample) | token summaries: 2

## Gaps

1. Grok Build balance exhausted (402).
2. Most roster wallets: no successful pump.fun bonding-curve trades with wallet token deltas in last ~60 sigs on public RPC; replay sample is Doji (5 real trades).
3. FCC chat completions unavailable -> template writer.
4. No TypeSafe key -> mock Jev (did not hunt other agents' secrets).
5. X article login-walled (403); built from provided spec.
6. Public RPC rate limits â€” small batches only.

## Safety confirmation

- No order / buy / sell / swap / sign code (grep clean).
- No secrets committed (`.gitignore` has `.env`; keys runtime-only; never printed).
- No paid data spend; Grok not billed (already quota-blocked).
- Hermes gateway / keep_local **not** started.
- Observe-only CLI banner printed.

---

## Executor fix-ups after Freebuff session ended (2026-09-24 ~04:12 CDT)

Freebuff session ended (timebox / Freebucks). Small post-session fix-ups by the executor agent (not Freebuff):
1. Repointed both desktop shortcuts to `run_ui.bat` with IconLocation `trenchnet_radar.ico,0`:
   - `C:\Users\jpana\Desktop\TRENCHNET.lnk`
   - `C:\Users\jpana\OneDrive\Attachments\Desktop\TRENCHNET.lnk`
2. Ensured `run_ui.bat` opens `http://127.0.0.1:8791/` then starts `python -m trenchnet.cli ui`.
3. Re-verified UI HTTP 200 for `/`, `/assets/data.js`, `/paper`, `/health`, `/api/overview`; server stopped afterward.
4. pytest re-check: **41 passed**.
5. HyperFrames flythrough: **not rendered** (Freebuff skipped for timebox; clone exists at `HermesTools\hyperframes` but no mp4 produced â€” no spend).
6. PyInstaller `TRENCHNET Desk.exe` still pending (`run_ui.bat` is the live launcher).

Screenshot paths on disk (names Freebuff wrote):
- `out\dashboard_3440.png` (3440x1440)
- `out\dashboard_1920.png` (1920x1080)
- `out\dashboard_1280.png` (1280x800)


## Executor PASS 2 wrap (screenshots + verify) â€” 2026-09-24

Coded primarily by **Freebuff** (dashboard panels + history pipeline merge + tests). Executor: rotating fetch-history runner (Doji-first; Cented parked after tip err-spam), before_cursor resume patch, UI verify, screenshots.

- pytest: **54 passed**
- Screenshots re-shot: `out/dashboard_1280.png`, `out/dashboard_1920.png`, `out/dashboard_3440.png`
- UI routes checked 200 then server stopped
- HyperFrames / Desk.exe: **skipped** (optional; no spend)
- History fetch still running/rotating under `out/fetch_history_pass2.log` (resumable; not invented)


## Executor PASS 2 closeout (2026-09-24 ~04:37 CDT)

- Replayed after history progress: **events 46**, profiles 8, routes 8, timelines 10, `fcc_mode=fcc` (kimi-k2.7-code), Jev dry_run_mock.
- Lower-half panels present in `out/dashboard.html` (heatmap / token flows / co-entry matrix / paper ledger) with Solscan links; thin-data labels when empty.
- Screenshots refreshed: `out/dashboard_1280.png`, `out/dashboard_1920.png`, `out/dashboard_3440.png`.
- UI routes verified HTTP 200 then stopped.
- History rotator restarted (Doji-first); Cented tip is failed-tx spam â€” skipped toward end of rotation; per-wallet progress via `history-status` (never invented).
- HyperFrames / Desk.exe: skipped (optional).
- pytest: **54 passed**.

Who coded: **Freebuff** (panels + history merge + tests + RECEIPT PASS 2). **Executor** (fetch rotator, resume cursor patch, UI verify, screenshots, process hygiene).

## Port fix (PASS 2) - 2026-09-24 04:40 CDT

TRENCHNET desk UI default moved **8788 → 8791**. Reason: 8788 reserved for Muse local video gateway (Hermes profile). Also avoid 8765 / 8787 / 8790 (Connecture / aibus / mcp-gate). Updated: `trenchnet/cli.py` default, `trenchnet/webui.py` serve default, `run_ui.bat`, README Desk UI section, this RECEIPT. Tests use ephemeral ports (no hardcode). No processes on reserved ports were stopped.

## Port verify (PASS 2) - 2026-09-24 04:43 CDT

- Default UI port is **8791** (cli / webui / run_ui.bat / README / RECEIPT).
- Started desk on 127.0.0.1:8791; routes `/`, `/assets/data.js`, `/paper`, `/health`, `/api/overview` all HTTP 200; then stopped.
- Screenshots re-shot on 8791: `out\dashboard_1280.png`, `out\dashboard_1920.png`, `out\dashboard_3440.png`.
- Did **not** stop or touch listeners on 8765 / 8787 / 8788 / 8790.
- History rotator restarted (Doji-first, Cented last); resumable under `out\fetch_history_pass2.log`.


## PASS 3 + LIVE scaffold — 2026-09-24 05:00 CDT (executor)

### Pass 3 data
- Parallel multi-RPC history fetch (publicnode + mainnet-beta + mainnet), resume, skip zero-fill spam.
- Roster expanded to **40** wallets (8 seed + 32 from Kolscan GitHub monthly snapshot). pump.fun frontend API blocked (404/JWT) — listed for Jeremy free signup if desired.
- Token context: 9 Doji-related mints via Dexscreener + GeckoTerminal free APIs under `data/raw/token_context/`.
- UI :8791 left running for Jeremy (PID 41128 family). Screenshots/LIVE probe on **:8792**.
- X API / X MCP: not used.
- Who coded pass 3 core: executor (Freebuff still finishing dashboard wiring).

### LIVE (queued after / overlapping pass 3 close)
- Package `trenchnet/live/`: wallet (DPAPI), state/arm/kill/limits (default 0/disarmed), gates, Jupiter-lite routes, orders (simulate default; send needs CONFIRM LIVE ORDER).
- GUI: `out/live.html` at `/live` + scrubbed `/api/live/*` (no secrets in responses).
- Tests: **9 passed** (disarmed/caps/kill/hygiene/confirm/no-secret).
- Route: Jupiter lite free public; PumpPortal opt-in OFF; no agent signup for Helius/QuickNode.
- Docs: `docs/HOW_TO_GO_LIVE.md`.
- **No real tx sent. No private key read/printed/logged.** LIVE remains disarmed.


## Graph readability fix (Jeremy UI priority) — 2026-09-24 05:06 CDT
- Replaced perpetual force-sim with **precomputed bipartite layout then FREEZE** (no wobble; prefers-reduced-motion respected).
- Graph canvas **~70vh**, fullscreen toggle, wallets (blue circles) left / tokens (purple rounded squares) right.
- Edge thickness = SOL; green buys / magenta sells; arrows wallet→token; always-on labels; hover entry-order; click opens side panel.
- Group-by toggle + legend + **What people are buying** table under graph.
- Screenshot: `out\graph_3440.png` (3440×1440). Live on :8791/:8792 after hard reload. :8791 left running for Jeremy.

## Pass 3 scrub + LIVE (executor) — 2026-09-24 ~05:46 CDT

### A) Pass 3 data expansion
- **Before (baseline):** 8 seed wallets, ~46 events, 1 wallet with trades (Doji), ~6 flow tokens / 10 timelines, **0 co-entries**.
- **After:** roster **40** (8 seed + 32 expanded); history files **20**; wallets with trades **15**; events **145**; graph **edges 150**, **co-entries 13**, **token_summaries 14**; token_context files **13**.
- **History (8 seeds):** Doji 41 ev (20 pages, max_tx); tech 5; clukz 2 (complete); Joji 0 (complete); Jijo/decu 0 (max_pages/zero-fill); theo skipped zero-fill (99 pages); Cented short probe 3 pages / 0 pump events (errspam.bak parked).
- **Expand:** on-chain co-buyers of Doji mints via free RPC + Kolscan GitHub snapshot provenance; cobuy harvest also seeded real TradeEvents into history for top cobuyers (not invented).
- **Sources used:** Solana public RPCs (`api.mainnet-beta.solana.com`, `api.mainnet.solana.com`, `solana-rpc.publicnode.com`), Dexscreener + GeckoTerminal, Kolscan monthly snapshot (yksanjo/kol-tracker), on-chain mint cobuyers.
- **Sources blocked (Jeremy free-signup if wanted):** pump.fun frontend API (JWT/auth); Birdeye/GMGN API keys; X/Twitter API (~$0 / policy — not used). Optional free RPC upgrades: Helius/QuickNode free tiers (not signed up).
- **Rebuild:** `run_replay` with FCC stubbed off (local FCC :8082 unreachable; template fallback). `dashboard.regenerate` refreshed `out/dashboard.html` + `out/assets/data.js`.
- **Screenshots:** `out/dashboard_full_1280.png`, `out/dashboard_full_1920.png`, `out/dashboard_full_3440.png`, `out/graph_3440.png`.

### B) LIVE
- Package under `trenchnet/live/` + GUI `/live` on **8791**. Default **disarmed**, all caps **0**, DPAPI wallet path, ARM LIVE / ARM AUTO phrases, confirm modal, kill switch, simulate-only until confirm.
- **Route/fees:** Jupiter lite preferred (free public quote; normal Solana network fees only). PumpPortal opt-in **OFF** (may take per-trade fee if enabled).
- **Tests:** `tests/test_live.py` **9 passed**; full suite **72 passed**.
- **Screenshot:** `out/live_page.png`.
- **Confirm:** no real tx sent; private key never read/printed; LIVE remains disarmed.

### Who coded / running
- **Executor** coded Pass3 fetch/expand/rebuild/LIVE wiring/screenshots (Freebuff idle this stretch).
- **Still running:** UI `127.0.0.1:8791` PID **45628** (leave up for Jeremy). Optional stray :8792 UI may also exist.

### What Jeremy must do
1. Hard-reload `http://127.0.0.1:8791/` and open Graph / co-entry / heatmap panels.
2. Review `http://127.0.0.1:8791/live` (disarmed). Generate dedicated wallet yourself if/when ready; fund only risk capital.
3. Optional free signups (agent did not): pump.fun API, Helius/QuickNode free RPC.
4. Never paste main MetaMask/Coinbase key into LIVE.


## Pass 4 — Helius + Birdeye (executor) — 2026-09-24 ~07:30 CDT

### Before → After (vs Pass 3)
| Metric | Pass 3 | Pass 4 |
|--------|--------|--------|
| Roster wallets | 40 | **40** |
| Wallets with trades | 15 | **26** |
| Events (history / graph-unique) | ~145 / edges 150 | **2468** / graph **2322** |
| Co-entries | 13 | **19** |
| Token summaries | 14 | **50** |

### Thin wallets (Helius primary)
- **Cented:** 1 event (`source=helius`); pump filter empty → broad pass found 1.
- **theo:** 0 events; `zero_fill_skip` after Helius empty + prior 99-page RPC zerofill (no further RPC walk).
- **Jijo:** 0 events (Helius empty + RPC max_pages; no pump/swap activity in window).
- **decu:** 0 events (same).

### Sources
- **Helius** enhanced txs (`type=SWAP` + `source=PUMP_FUN`, then shallow/broad as needed) — PRIMARY history. Events tagged `source: helius`. RPC fallback via `HELIUS_RPC_URL` then public RPCs when needed; untagged legacy rows tagged `rpc`.
- **Birdeye** (free Standard): token price + OHLCV for 12 mints — all OK; wallet PnL summary for 5 seeds — all OK; top_traders — OK. **Blocked endpoints:** none this run (`data/raw/birdeye/_birdeye_blocked.json` empty).
- Keys loaded from `.env` via `trenchnet.secrets` only; never logged. `QUICKNODE_RPC_URL` / `PUMPFUN_JWT` ignored (empty).

### Helius limits
- **No credit/429 hard stop** this run (`limit_hit=False` in phase2c). Continue-window misses handled with early stop + optional broad/RPC.

### Tests / safety
- Full suite: **78 passed** (72 prior + 6 new mocked Helius/Birdeye tests).
- Leak check over `out/` + `data/`: **PASS** (391 text files scanned; key values not present).
- LIVE remains **disarmed**, caps 0; UI **8791** left running (PID 45628).

### Screenshots
- LightBringer: `out\pass4_dashboard_1280.png`, `_1920.png`, `_3440.png`, `out\pass4_graph_3440.png`
- Box: `/workspace/trenchnet-pass4/pass4_dashboard_1280.png` (and `_1920`, `_3440`, `pass4_graph_3440.png`)

### Code added
- `trenchnet/helius_client.py`, `trenchnet/birdeye_client.py`, `trenchnet/history_helius.py`
- `tools/pass4_fetch_seq.py`, `pass4_phase2.py`, `pass4_phase2c.py`, `pass4_leakcheck.py`, `pass4_shots.py`
- `tests/test_helius_birdeye.py`
- TradeEvent optional `source` field

