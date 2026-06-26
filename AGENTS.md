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

## Main Workflow: Grid Parameters(網格參數)
When the user asks for grid parameters, grid setup, `/網格參數`, or asset-specific grid planning such as `/網格參數 BTC`, follow this process:

Required inputs:
- asset symbol
- setup context

If the user only says `/網格參數` without a symbol, ask exactly:
- `1. asset symbol=?`
- `2. setup context=? (止跌盤整 / 一般盤整 / 其他)`

If the user says `/網格參數 BTC` and no further context, ask exactly:
- `1. timeframe=?`
- `2. 前低=?`
- `3. 目標價=?`
- `4. 手續費率=?`

Workflow rules:
1. Use `grid/README.md` as the canonical workflow and questionnaire reference.
2. Use `grid/ASSET_TEMPLATE.md` as the canonical per-asset recording template.
3. Treat the user's described market structure as the first-class assumption for parameter discussion.
4. When the user has not provided enough information to estimate a range, ask follow-up questions instead of inventing precise upper and lower bounds.
5. When proposing a grid range, explicitly separate:
   - trigger context
   - upper bound
   - lower bound
   - grid count
   - spacing method
   - fee impact
   - stop condition
6. For the current default setup:
   - lower bound = `previous low - 1 * ATR(14)`
   - upper bound = `user target price`
   - mode = `aggressive`
   - spacing method = `ATR-based`
   - spacing value = `0.35 * ATR(14)`
   - theoretical grid count = `round((upper - lower) / (0.35 * ATR(14)))`
7. If `ATR(14)` is not provided by the user, fetch recent OHLC data and calculate the latest ATR(14) before proposing the range.
8. Always clarify the timeframe because ATR depends on timeframe.
9. Include the user-provided fee rate in the evaluation.
10. When evaluating spacing, calculate:
   - spacing percent range versus lower bound, reference price, and upper bound
   - round-trip fee percent = `2 * fee_rate_percent`
   - net spacing percent range = `spacing percent range - round-trip fee percent`
11. Prefer volatility-aware language such as `ATR`, recent swing high/low, consolidation range, and prior resistance/support when explaining the bounds.
12. Record reusable parameter systems and notes under `grid/`.
13. Do not treat a grid-parameter request as a holdings or pnl sync request unless the user explicitly asks for both.

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
  - send Telegram summary on a best-effort basis
  - create a commit when holdings changed, usd balances changed, or today's pnl history has not been recorded yet
  - skip commit when holdings and usd balances are unchanged and today's pnl history already exists

If the user types `/更新交易紀錄`, treat it as a request to update local trade history artifacts immediately.

- Run:

```bash
python3 trade_history/update_trade_history.py
```

- This should:
  - refresh `generated/trade_rows.json` from the live Google Sheet tabs before conversion
  - ensure the snapshot includes `fetched_at` metadata
  - generate `generated/trades.json`
  - generate `generated/trades.csv`
  - preserve raw values without calculations

## Trade History Workflow
When the user asks to update trade history, sync trade history, regenerate trade rows, or types `/更新交易紀錄`, follow this process:

1. Treat the Google Sheet as the source of truth.
2. Use the Codex Google Drive connector to read the live Google Sheet tabs before running the local converter.
3. Refresh `generated/trade_rows.json` from the live Google Sheet response before running the local converter.
4. The local Python scripts do not fetch Google Sheets by themselves. In Codex mode, the agent must refresh the snapshot first in the same turn.
3. Include snapshot metadata at top level:
   - `fetched_at`
   - `spreadsheet_url`
   - `tabs`
4. Keep `tabs` as the raw row snapshot keyed by tab name.
5. Only after the snapshot is refreshed, run:

```bash
python3 trade_history/update_trade_history.py
```

6. Do not rely on an old local snapshot when the Google Sheet can be refreshed in the current turn.

### Codex Route
For `/更新交易紀錄`, default to the Codex route:

1. Read the latest live rows from Google Sheets through the connector.
2. Overwrite `generated/trade_rows.json` with the fresh snapshot.
3. Run `python3 trade_history/update_trade_history.py`.
4. Summarize:
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

For grid-parameter discussions, summarize:
- asset symbol
- setup context
- whether enough inputs were provided
- which parameter fields are still missing
- where the parameter system is recorded under `grid/`
