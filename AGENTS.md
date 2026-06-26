# AGENTS.md

## Repo Purpose
This repository maintains TradingView Pine scripts for portfolio tracking and rebalancing.
The primary recurring workflow is syncing holdings data from Google Sheets into `PNLRebalance`.

## Main Workflow: Update Holdings(更新持倉)
When the user asks to update holdings, refresh positions, sync the Pine block, or regenerate the auto-generated section, follow this process:

Required inputs:
- token
- commit preference

If either value is missing, ask the user before running the sync.

1. Treat Google Sheets as the source of truth for both holdings and exchange usd balances.
2. Do not run `update_holdings_pine.py` until the user has provided a token.
3. If the user only says `Update Holdings`, ask exactly:
   - `1. token=?`
   - `2. create commit after sync: yes/no?`
4. Use `update_holdings_pine.py` to fetch holdings and usd balances from the Google Apps Script endpoint.
5. By default, update both:
   - `generated/holdings.pine`
   - `PNLRebalance`
6. Replace the crypto holdings block between:
   - `// === AUTO-GENERATED START ===`
   - `// === AUTO-GENERATED END ===`
7. Replace the exchange usd block between:
   - `// === AUTO-GENERATED USD START ===`
   - `// === AUTO-GENERATED USD END ===`
8. Do not manually rewrite holdings arrays or exchange usd values if they can be produced by the script.
9. Missing exchanges in the `usd` sheet should default to `0`.
10. Create a commit after sync only if the user explicitly says yes.
11. If the user wants a commit but does not specify a commit message, use:
    - `[update] Update assets`

## Main Workflow: Update Pnl(更新損益)
When the user asks to update pnl, refresh daily pnl, or append the current pnl history, follow this process:

Required inputs:
- current pnl
- commit preference

If either value is missing, ask the user before running the update.

1. Use the current Asia/Taipei date by default.
2. If the user only says `更新損益`, ask exactly:
   - `1. current pnl=?`
   - `2. create commit after sync: yes/no?`
3. Use `update_pnl_history.py` to update the `rdArray` history block in `PNLRebalance`.
4. If the current date already exists in the history block, overwrite that day's pnl value.
5. If the current date does not exist, append a new `array.push(rdArray, newData(...))` line.
6. Do not change `PNLRebalance` structure outside the historical `rdArray` initialization block unless the user explicitly asks.
7. Create a commit after sync only if the user explicitly says yes.
8. If the user wants a commit but does not specify a commit message, use:
   - `[update] Update pnl`

## Commands
Preferred command for holdings sync:

```bash
python3 update_holdings_pine.py --token "$HOLDINGS_WEB_APP_TOKEN"
```

If the user wants to generate the Pine block without modifying `PNLRebalance`:

```bash
python3 update_holdings_pine.py --token "$HOLDINGS_WEB_APP_TOKEN" --skip-pnl-update
```

Preferred command for pnl sync:

```bash
python3 update_pnl_history.py --pnl-value "<CURRENT_PNL>"
```

Preferred command for the full weekly sync workflow:

```bash
python3 weekly_holdings_pnl_sync.py --token "0125" --commit
```

Preferred command for trade history sync:

```bash
python3 refresh_trade_rows.py --token "$HOLDINGS_WEB_APP_TOKEN"
python3 trade_history/update_trade_history.py
```

Preferred command for live trade rows refresh only:

```bash
python3 refresh_trade_rows.py --token "$HOLDINGS_WEB_APP_TOKEN"
```

Preferred command for trade history conversion only after snapshot refresh:

```bash
python3 trade_history/update_trade_history.py
```

## Manual Update Shortcuts
Use these shortcuts when the user wants a manual update from Codex:

### `/更新持倉`
- Codex route:
  1. Ask for `token` and `create commit after sync: yes/no?` if missing.
  2. Run:

```bash
python3 update_holdings_pine.py --token "$HOLDINGS_WEB_APP_TOKEN"
```

- Generate only `generated/holdings.pine` without updating `PNLRebalance`:

```bash
python3 update_holdings_pine.py --token "$HOLDINGS_WEB_APP_TOKEN" --skip-pnl-update
```

### `/更新損益`
- Ask for `current pnl` and `create commit after sync: yes/no?` if missing.
- Run:

```bash
python3 update_pnl_history.py --pnl-value "<CURRENT_PNL>"
```

### `/更新交易紀錄`
- Preferred Codex route:
  1. Refresh `generated/trade_rows.json` from the Apps Script endpoint.
  2. If Apps Script is unavailable in the current context, use the Codex connector fallback.
  3. Run:

```bash
python3 refresh_trade_rows.py --token "$HOLDINGS_WEB_APP_TOKEN"
python3 trade_history/update_trade_history.py
```

- Local shell route:
  - refresh snapshot first, then run conversion

```bash
python3 refresh_trade_rows.py --token "$HOLDINGS_WEB_APP_TOKEN"
python3 trade_history/update_trade_history.py
```

## Manual Trigger Alias
If the user types `/sync`, treat it as a request to run the full weekly sync workflow immediately.

- Run:

```bash
python3 weekly_holdings_pnl_sync.py --token "0125" --commit
```

- This should:
  - fetch holdings from Google Sheets
  - update `generated/holdings.pine`
  - update `PNLRebalance`
  - calculate current `speculationPNL`
  - update pnl history
  - refresh live trade rows from Apps Script
  - update trade history artifacts from the fresh snapshot
  - send Telegram summary on a best-effort basis
  - create a commit when holdings changed, usd balances changed, today's pnl history has not been recorded yet, or `trade_history/TradeHistoryLabels.pine` changed
  - report a trade history refresh failure in summary without blocking holdings / pnl sync

If the user types `/更新交易紀錄`, treat it as a request to update local trade history artifacts immediately.

- Run:

```bash
python3 refresh_trade_rows.py --token "$HOLDINGS_WEB_APP_TOKEN"
python3 trade_history/update_trade_history.py
```

- This should:
  - refresh `generated/trade_rows.json` from the Apps Script endpoint before conversion
  - ensure the snapshot includes `fetched_at` metadata
  - generate `generated/trades.json`
  - generate `generated/trades.csv`
  - preserve raw values without calculations

## Trade History Workflow
When the user asks to update trade history, sync trade history, regenerate trade rows, or types `/更新交易紀錄`, follow this process:

1. Treat the Google Sheet as the source of truth.
2. Prefer the Apps Script endpoint for live refresh before running the local converter.
3. Refresh `generated/trade_rows.json` from the live response before running the local converter.
4. The local converter does not fetch Google Sheets by itself. The snapshot must be refreshed first in the same turn.
5. Include snapshot metadata at top level:
   - `fetched_at`
   - `spreadsheet_url`
   - `tabs`
6. Keep `tabs` as the raw row snapshot keyed by tab name.
7. Only after the snapshot is refreshed, run:

```bash
python3 trade_history/update_trade_history.py
```

8. Do not rely on an old local snapshot when the Apps Script endpoint or Codex connector can be refreshed in the current turn.

### Codex Route
For `/更新交易紀錄`, default to the Codex route:

1. Run `python3 refresh_trade_rows.py --token "$HOLDINGS_WEB_APP_TOKEN"` when the Apps Script endpoint is available.
2. If the Apps Script endpoint is unavailable in the current context, read the latest live rows from Google Sheets through the connector.
3. Overwrite `generated/trade_rows.json` with the fresh snapshot.
4. Run `python3 trade_history/update_trade_history.py`.
5. Summarize:
   - whether live rows were fetched successfully
   - which tabs were refreshed
   - whether `generated/trades.json` was updated
   - whether `generated/trades.csv` was updated

Do not ask the user to manually refresh the snapshot first when the connector is available.

## PNLRebalance Rules
- `PNLRebalance` reads holdings from the auto-generated arrays.
- For crypto assets, use the generated arrays as the canonical source.
- Do not reintroduce `input.float(defval=runtime_value)` for generated holdings values, because Pine requires `const` defaults.
- If manual overrides are needed, implement them as a separate switchable path instead of using runtime values as input defaults.

## Safety Rules
- Never overwrite content outside the auto-generated block when updating holdings.
- If the auto-generated block markers are missing, stop and report the issue.
- If the fetched payload is empty or malformed, stop and report the issue.
- If there are unexpected local changes in `PNLRebalance`, read the file carefully before editing and avoid reverting unrelated user changes.

## Verification
After updating holdings, verify:

1. `generated/holdings.pine` was regenerated.
2. `PNLRebalance` crypto holdings auto-generated block was updated.
3. `PNLRebalance` exchange usd auto-generated block was updated.
4. The generated arrays match the expected symbols and values from the payload.
5. The generated exchange usd values match the `usd` sheet, and missing exchanges default to `0`.
6. No `input.float(defval=runtime_value)` pattern was introduced for generated positions or costs.

After updating pnl, verify:

1. `PNLRebalance` history block was updated.
2. Same-day updates overwrite the existing entry instead of adding a duplicate.
3. New-day updates append one new `array.push(rdArray, newData(...))` line.
4. No code outside the `rdArray` history block was changed.

## Commit Workflow
After a successful holdings sync, the agent should create a commit only if the user explicitly asked for one.

- Do not include `generated/` artifacts in commits.
- Commit only the files that belong to the holdings sync workflow, such as:
  - `PNLRebalance`
  - `update_holdings_pine.py`
  - `AGENTS.md`
  - `.gitignore`
- Before committing, check for unrelated local changes and avoid bundling them into the same commit.
- Use a message that describes the workflow or automation change, not the agent itself.
- Prefer messages such as:
  - `[feat] Add automated holdings sync for PNLRebalance`
  - `[update] Refresh holdings in PNLRebalance`
- For pnl history updates, prefer:
  - `[update] Update pnl`
- If the change is only a holdings data refresh, use an `update` style message.
- If the change adds or modifies tooling, automation, or workflow behavior, use a `feat` style message.

## Response Style
When completing this workflow, summarize:
- whether holdings were fetched successfully
- whether `generated/holdings.pine` was updated
- whether `PNLRebalance` was updated
- whether a commit was created
- any blockers such as missing token, malformed payload, or missing markers
