# TRENCHNET

**Watch-only Solana / pump.fun wallet tracker** for a configured roster. Paper-first desk UI. **LIVE trading is disarmed by default** (caps at 0; the app never arms, funds, or sends unless *you* explicitly arm and confirm in the GUI).

This repo is **observe / analysis / paper**. It does not ship wallet private keys. Put your own API keys in a local `.env` (never commit it):

```powershell
copy .env.example .env
# then edit .env with your Helius / Birdeye (etc.) keys
```

Generated dashboards and Pass 4 screenshots live under `out/`. Roster addresses and derived stats are public on-chain data.

**Pass 6 (paper):** pool-trade Helius price reconstruction for denser backtest marks, then Pass 5 backtest/scores/interactive desk.

**Pass 5 (paper):** copy-trade backtest, walk-forward, wallet scores, interactive desk (filters, drawer, sortable tables, backtest sliders). `python -m trenchnet.cli backtest`. LIVE remains disarmed.

---
## Desk UI

Watch/paper only. Default bind: `http://127.0.0.1:8791/` (port **8791**). Port 8788 is reserved for the Muse local video gateway; do not use 8765, 8787, or 8790 (Connecture / aibus / mcp-gate).

```powershell
.\run_ui.bat
# or
.\.venv\Scripts\python.exe -m trenchnet.cli ui
```

## Setup (Windows / LightBringer)

```powershell
cd path\to\trenchnet
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Secrets (read at runtime only; never committed):
- Copy `.env.example` → `.env` and fill keys listed there (Helius, Birdeye, optional FCC/Typesafe).
- `.env` is gitignored. Do not commit keys.

## Config

- `config/settings.yaml` — RPC, graph window, FCC model, Jev model, paths
- `config/roster.yaml` — seed wallets with **source URLs** (Kolscan leaderboard snapshot)

Roster sort after metrics: `realized_pnl_sol` desc, then `trade_count` desc, then address asc.

## Run

Replay from saved raw JSON (offline once `data/raw/` is populated):

```powershell
cd path\to\trenchnet
.\.venv\Scripts\python.exe -m trenchnet.cli replay
```

Poll public Solana RPC into `data/raw/`:

```powershell
.\.venv\Scripts\python.exe -m trenchnet.cli poll
```

Fetch then replay:

```powershell
.\.venv\Scripts\python.exe -m trenchnet.cli fetch-and-replay
```

Tests (PnL, graph/co-entry, routing):

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Outputs (`out/`)

| Path | Contents |
|------|----------|
| `out/profiles/` | Per-wallet metrics + narrative (JSON/MD) + roster order |
| `out/graph/summary.json` | Edges, co-entry Jaccard, token relationship summaries |
| `out/routes/` | Jev gate routes per wallet + `all_routes.json` |
| `out/reports/` | Versioned situation reports (facts vs interpretation) |
| `out/timelines/` | Per-token markdown + HTML timelines |

## Data sources (free)

1. **Solana public RPC** `https://api.mainnet-beta.solana.com` — `getSignaturesForAddress` + `getTransaction` (jsonParsed), small batches + sleep.
2. Parse pump.fun bonding-curve program `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P` from token balance deltas (PumpSwap AMM `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA` accepted as ecosystem).
3. Seed wallets from public Kolscan leaderboard snapshot: https://github.com/yksanjo/kol-tracker/blob/main/snapshots/2026-05-21_0320Z.json (upstream https://kolscan.io/leaderboard).

## Models

- **FCC** OpenAI-compatible at `http://127.0.0.1:8082/v1`. Prefer Windows Python so localhost reaches FCC. If chat completions fail, a **clearly labeled template writer** is used.
- **Jev** via TypeSafe System One (`jev-latest`). If `TYPESAFE_API_KEY` is unset, a **clearly labeled dry-run/mock judge** runs.

## Hard rules

- Observe-only; no orders.
- No invented wallets or signatures — cite real tx signatures.
- No spend on paid data APIs; stub + gap-list if needed.
- Hermes services are not started by this tool.

## Pass 4 data sources (keys in local .env only)
- **Helius** — primary wallet history via Enhanced Transactions API (SWAP / PUMP_FUN); RPC fallback. Numbers tagged helius.
- **Birdeye** — token price, OHLCV, wallet PnL / top traders where free tier allows. Numbers tagged irdeye.
- Never commit .env. Agent leak-checks out/ + data/ after runs.

### Pass 7 — Coin Desk tab + Top Pick
- **Coin Desk tab** is observe-only: reads http://127.0.0.1:3010/api/state or %LOCALAPPDATA%\\token-desk\\data\\decisions.jsonl. Start Coin Desk.exe yourself if you want a live Base/hood.fun board; TRENCHNET will not start or stop it.
- **Top Pick** is a paper verdict card with documented thresholds in config/picks.yaml. BUY candidate requires multiple confirmations + safety. Track record under data/picks/. Not financial advice; walk-forward may be insufficient_oos.

