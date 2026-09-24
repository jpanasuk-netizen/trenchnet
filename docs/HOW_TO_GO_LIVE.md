# How to go LIVE (Jeremy only)

LIVE is **disarmed by default**. The agent never arms, never funds, never sends, never prints your key.

## Route
- Preferred: **Jupiter lite** (`lite-api.jup.ag`) — free public quote/swap, **no TRENCHNET fee**, normal Solana network fees only.
- Pump.fun bonding-curve local ix path is scaffolded for pre-graduation tokens.
- **PumpPortal** local-tx API is **opt-in** in the LIVE GUI (may take a per-trade fee) — leave OFF unless you accept that fee.

## RPC
- Default public mainnet RPC.
- Optional free-signup RPCs you can paste into the LIVE page (agent did **not** sign up): Helius free tier, QuickNode free tier.

## Steps
1. Open `http://127.0.0.1:8791/live` (restart desk to pick up LIVE) or `http://127.0.0.1:8792/live`.
2. Generate a fresh wallet (or import a dedicated one). Fund only what you can lose.
3. Set all limits > 0 → Save.
4. Type exactly `ARM LIVE` → Arm. (Auto needs `ARM AUTO`.)
5. Preview (simulate) → confirm modal → type `CONFIRM LIVE ORDER` yourself to sign+send.
6. Big red KILL anytime. App restart auto-disarms.

## Safety
- Secret at `%LOCALAPPDATA%\trenchnet\live_wallet.bin` (DPAPI), never in repo/logs/API.
- Paper hygiene gates apply before any live order.
- Ledger: `data/live/ledger.jsonl` (no secrets).
