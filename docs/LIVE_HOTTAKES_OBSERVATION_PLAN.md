> **DRAFT - on hold** (Jeremy: live test can wait; not required for Pass 9.)

# Live Hot Takes observation plan (PAPER only)

**Mode:** observe / paper tracking. **LIVE stays disarmed** (all caps 0). No orders, no keys printed.

## Goal
Confirm the Hot Takes side window is useful in real time: new flags appear, countdowns/outcomes update, and the 5-minute poll lag is honest.

## Pre-flight (1 minute)
1. Open desk via `funtokenss` / `run_ui.bat` → `http://127.0.0.1:8791/`
2. Confirm badges: **WATCH-ONLY · PAPER · LIVE OFF**
3. Hot Takes panel shows up front: *“Checks for new Hot Takes every 5 minutes…”*
4. Note **Last checked** and **Next check in m:ss**
5. `GET /api/live/state` → `armed: false`, all limits `0`

## 30–60 minute observation
| Step | Action | Pass if |
|------|--------|---------|
| A | Leave desk open; do not restart unless crashed | Tracker stays `running: true` |
| B | Watch for a new Hot Take card (may be zero — that is OK) | If one appears: token, reason, flags, entry price/source visible |
| C | On an open take past +15m / +1h | Horizon chips become WIN / LOSS / UNPRICED (never invent) |
| D | Click a triggering wallet | Existing drawer opens |
| E | After ~10–15 min | Two `last_poll_iso` values ≈ 5 minutes apart (+ Helius work) |
| F | Check `/api/hottakes/tracker` | `poll_interval_seconds: 300`; credits estimate rising slowly |

## What not to do
- Do not arm LIVE, raise caps, or import a wallet
- Do not start/stop Coin Desk or touch ports 8765 / 8787 / 8788 / 8790 / 3010
- Do not treat Hot Takes or Top Pick as financial advice

## Success criteria
- UI always states 5-minute lag up front
- Outcomes use real prices + cost model; UNPRICED when no trade in staleness window
- Paper-only badges remain visible; LIVE remains disarmed
