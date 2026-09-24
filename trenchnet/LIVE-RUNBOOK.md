# TRENCHNET LIVE Runbook (plain English)

**Default: DISARMED.** Nothing sends money until you arm it yourself. There is **no measured edge yet** (signals are simulated/paper). Prefer a **fresh burner wallet**.

## Where things live

| What | Path |
|------|------|
| Secrets | `C:\Users\jpana\Documents\HermesTools\trenchnet\.env` (gitignored) |
| LIVE state | `data\live\state.json` (gitignored folder) |
| Trades ledger | `data\live\trades.jsonl` + `trades.csv` |
| Open positions | `data\live\open_positions.json` |
| Position manager heartbeat | `data\live\position_manager_heartbeat.json` |
| KILL flag file | `TRENCHNET_KILL` in the repo root (gitignored) |
| Desk UI | http://127.0.0.1:8791/ and http://127.0.0.1:8791/live |
| This runbook | `trenchnet\LIVE-RUNBOOK.md` |


## Create the burner (recommended — MetaMask cannot export Solana keys)

1. In the trenchnet folder run:
   ```
   python -m trenchnet.cli new-wallet
   ```
   Or on **/live** click **Create burner wallet**.
2. It generates a fresh Solana keypair **locally**, writes the base58 secret to `.env` as `TRENCHNET_WALLET_KEY`, and saves a backup under `trenchnet\wallet-backup\` (gitignored).
3. It **refuses** if `TRENCHNET_WALLET_KEY` already has a value (never overwrites).
4. It prints/shows **only the public address** (full — you need it to fund) and a simple QR on `/live`. The secret is never printed or returned by the API.
5. Send SOL to that public address from MetaMask (or any exchange) on **Solana**.
6. Optional: import the backup key file into **Phantom** for a second copy you control. Never share the key.
7. Restart the desk so it reloads `.env`, then confirm **/live** shows the masked address + on-chain balance.

## Paste the private key (alternative)

1. Create a **burner** Solana wallet (Phantom / Solana CLI). Fund only what you can lose.
2. Open `.env` in the trenchnet folder (copy from `.env.example` if needed).
3. Add **one** of these (never commit `.env`):

```
TRENCHNET_WALLET_KEY=YOUR_BASE58_SECRET
```

or Solana CLI JSON byte array:

```
TRENCHNET_WALLET_KEY=[1,2,3,...]
```

4. Also set your public address for read-only dry-run / My Wallet card:

```
MY_WALLET_ADDRESS=YourPublicAddress
```

5. Restart the desk (`run_ui.bat` / funtokenss) so the process reloads `.env`.
6. On **/live**, click **Refresh**. When you arm, the UI shows the derived address **masked** (e.g. `E8xo…xa77`) — confirm it matches the wallet you funded.

Malformed keys fail with a clear error that **does not** print the secret.

## Caps (enforced before every order)

- Max **0.25 SOL** per trade  
- Max **4** open positions  
- Daily loss stop **2 SOL** realized → no new buys until next **CT** calendar day  
- Total loss kill **4 SOL** → auto-disarm; manual re-arm required  
- Always keep **≥ 0.05 SOL** for fees  
- Max **1** buy per token (default)  
- Min liquidity / min token age filters  
- Honeypot checks: mint + freeze authority revoked; can-sell simulation  
- Refuse to arm if on-chain balance **&lt; 0.30 SOL** (0.25 + 0.05) — balance is read live, never assumed  

On **/live** click **Apply spec caps** then **Save limits**.

## Arm

1. Caps &gt; 0, key pasted, wallet funded ≥ 0.30 SOL.  
2. Type exactly: `ARM TRENCHNET LIVE`  
3. Confirm masked pubkey.  
4. State stays disarmed across restarts until you arm again (and kill file is absent).

## Disarm

- Button **Disarm** on `/live`, or restart after KILL, or total-loss kill.

## KILL (stops new buys; disarms)

1. Big red **KILL LIVE** on `/live`, **or**  
2. Create empty/any file `TRENCHNET_KILL` in the repo root.  

Either one disarms and blocks new buys. Clear the file / turn kill off before arming again.

## SELL ALL (panic exit)

Three ways (all end in disarm):

1. **/live** → **SELL ALL NOW** → confirm  
2. CLI: `python -m trenchnet.cli sell-all` (add `--send` only when you really mean it; default is simulate)  
3. Desktop **SELL-ALL.vbs** (double-click; runs hidden; message box with result)  

Sell-all market-sells open ledger positions with escalating slippage/retries. Logs unsellable/rugged/no-route failures. **KILL ≠ sell-all**: KILL blocks buys; sell-all exits.

## Position manager (exits only)

- Hidden scheduled task: **TRENCHNET Position Manager**  
- Runs `pythonw` / no-window loop; CPU-light idle when disarmed + flat  
- Reloads opens from ledger; manages SL / TP / time stop / daily+total stops  
- **Cannot place buys**  
- Heartbeat: `data\live\position_manager_heartbeat.json` — shown on `/live` as `position manager: alive/…`

### Register / verify / remove task

```bat
schtasks /Create /TN "TRENCHNET Position Manager" /SC ONLOGON /RL LIMITED /RU "%USERNAME%" /TR "..." /F
schtasks /Query /TN "TRENCHNET Position Manager" /V /FO LIST
schtasks /Delete /TN "TRENCHNET Position Manager" /F
```

Installer script: `tools\install_position_manager_task.ps1`.

## Dry-run

On `/live` → **Run dry-run**. Uses `MY_WALLET_ADDRESS`, Jupiter quote, unsigned tx, `simulateTransaction` (no sign, no send). Empty-wallet simulation failures are OK and reported honestly.

## Check balance

- `/live` SOL readout, or My Wallet card on the paper desk, or Solscan for the public address.

## Troubleshooting

| Symptom | What to try |
|---------|-------------|
| Arm says balance too low | Fund burner; refresh; we never assume balance |
| Arm says caps 0 | Apply spec caps / save limits |
| Key malformed | Use base58 or JSON byte array; error won't show the value |
| Dry-run quote fails | Pump token may need PumpPortal route; try another mint |
| Position manager stale | Re-run installer; check Task Scheduler; heartbeat file |
| Want to stop everything | KILL + SELL ALL + Disarm + delete scheduled task |

## Safety promises

- Disarmed by default  
- Key never logged, never sent to UI, never in git  
- Agents must not arm or send  
- No measured edge yet — paper/sim only until you decide otherwise  
