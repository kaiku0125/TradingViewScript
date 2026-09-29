# AGENTS.md

## Repo Purpose
This repository maintains TradingView Pine scripts for portfolio tracking and rebalancing.
The primary recurring workflow is syncing holdings data from Google Sheets into `PNLRebalance`.

## PNLRebalance Dashboard
`PNLRebalance` is a Pine v6 script whose display is the dashboard developed in the `pnlRebalanceRefactor` preview (2026-09-28) and merged back on 2026-09-29; the preview file no longer exists. It provides `資產總覽` and `精簡監控` display modes selected by INPUT_DASHBOARD_MODE. The legacy `cell*` / `renderCryptoAsset` table layout is not a selectable mode. All holdings, weekly and pnl sync workflows target this file directly; the auto-generated blocks, `var float` constants and the `rdArray` history block are unchanged from the previous layout, so no sync script needed changes.

The dashboard uses the PNG base palette and its own merged-cell renderer. Its background transparency setting defaults to 65 (0 opaque, 100 transparent) and applies to both modes; text, separators, and allocation colors remain opaque. The table backing is fully transparent to avoid stacking background opacity. Keep summary cards and the allocation strip independent of detail text widths. `DASHBOARD_COLUMNS` is the single ordered schema for detail keys, titles and widths; headers, merges, values and tooltips resolve through stable keys. Reorder schema entries rather than numeric cell coordinates. Keep all seven unique keys and widths totaling 48; the script validates these constraints. Detail columns are asset, current/target weight, deviation in percentage points, rebalance, value, holding PNL, and realized PNL; realized PNL must remain visible in its own column. Individual holdings appear beside the asset symbol on one line (e.g. BTC · 0.3762), using canonical MY_*_POSITION values, thousands separators and up to four decimals (extra precision for tiny holdings). The asset tooltip shows the raw quantity only when the inline display rounds it. Cash and category totals omit quantities. DASHBOARD_STACKED_HOLDINGS defaults to false; dashboardValueStacked and the three-row merged layout remain available when it is true. The default uses two grid rows (content, separator). PNL status emoji use the original ratioStateJudge rules; keep the PNG palette for text colors. The 加密資產 category row also shows a status emoji, judged on the aggregate holding return of the five main coins (sum of holding PNL divided by sum of holding cost, i.e. current value minus PNL); the 現金 and 台股 category rows do not. The allocation strip is two grid rows: the current-weight bar at 1.5% of pane height (1.5 times its initial height) and a thinner, 60%-transparent target-weight bar directly beneath it; the label row shows only the current weight for each category; target weights appear in the strip's tooltip. The cash detail labels are 台幣 and 美金. Numeric detail columns (weight, deviation, value, PNL, realized) are right-aligned with two trailing spaces; the asset column stays left and rebalance stays centered. Detail rows use the base font plus INPUT_DETAIL_FONT_OFFSET (default +1, min font 8); the column header row uses DASH_MUTED text two sizes smaller than detail text on the darker DASH_BG background. Category rows use the lighter DASH_GROUP background, child rows use DASH_PANEL. Deviation text is DASH_TEXT, turning DASH_AMBER only on individual-asset rows whose relative deviation meets the same threshold that colors the buy/sell label; category rows and rows without a target stay uncolored. Zero value / PNL / realized amounts render as `—`. The four summary card titles carry a leading emoji: 💰 總資產, a dynamic ratioStateJudge emoji on 績效損益 (moved from the value line, which shows only amount and percentage), 💵 可用現金, 💳 總負債. Category names carry no emoji; ₿ / ⟠ glyphs remain on BTC / ETH. The title row's right side shows the display currency and the USD/TWD rate (pUsd_Twd); the footer shows the live update timestamp and the month/day of the last rdArray record, and no currency. Hover hints live on the 再平衡, 損益 and 偏離 column headers. Individual-asset rebalance cells show only the original buy/sell quantity (shares or coins), centered on one line. Monetary adjustment amounts and category funding/withdrawal instructions are shown in tooltips; category cells show only 增加配置 / 減少配置 / 維持. Tooltips never repeat data already visible on the row: the PNL tooltip carries only the holding return rate, the value and realized cells have none, and the rebalance tooltip omits the raw amount / ratio / quantity text. The 績效損益 card has no tooltip since its percentage is on the value line. Use thousands separators for displayed amounts and quantities, retaining existing quantity precision. Category adjustment labels are white; individual buy/sell labels are gray below abs((current-target)/current) thresholds and gold at or above them. The thresholds are inputs: INPUT_STOCK_JUDGE_RATIO (default 30%) for 0050 and INPUT_CRYPTO_JUDGE_RATIO (default 15%) for every crypto asset; the rebalance tooltip shows the relative deviation but not the threshold. Zero/missing current weight cannot produce a valid relative deviation and stays gray. Do not route the dashboard back through the legacy `cell*` / `renderCryptoAsset` table layout.

INPUT_PRIVACY (default off) masks sensitive absolute numbers in both modes: amounts (cards, value, holding PNL, realized PNL) become six full-width asterisks and quantities (inline holdings, buy/sell quantities) become three, keeping sign-free fixed widths. Percentages, deviation, actions, the allocation strip, exchange rate and timestamps stay visible. Tooltips carrying amounts or raw quantities are dropped while masked. The background chart and its high/low labels switch to PNL ÷ allCost as a percentage so the price scale shows no amounts.

The background PNL chart plots `rdArray` records with linear interpolation between record dates (INPUT_CHART_INTERPOLATE, default on) before optional SMA smoothing (default period 5). It renders a 2px line in DASH_GREEN / DASH_RED with a gradient fill fading toward a dotted zero hline, plus optional labels at the historical highest and lowest recorded PNL (INPUT_CHART_LABELS, default on; value and date, placed on the record's own bar). There is no latest-value label; the current PNL is read from the 績效損益 card. The chart hides in 精簡監控 mode or when 資產走勢線圖 is off. Keep chart colors on the PNG palette rather than the Colour library.

## Workflow Documentation Rule
If any workflow, automation, sync path, trigger, payload shape, generated block, or scheduled behavior is added or changed, `AGENTS.md` must be updated in the same change.

The scheduled weekly sync and manual `/sync` must use the same workflow entrypoint and produce the same side effects.

## Main Workflow: Update Holdings(更新持倉)
When the user asks to update holdings, refresh positions, sync the Pine block, or regenerate the auto-generated section, follow this process:

Required inputs:
- token
- commit preference

If either value is missing, ask the user before running the sync.

1. Treat Google Sheets as the source of truth for holdings, exchange usd balances, and `cash_liability`.
2. Do not run `holdings/update_holdings_pine.py` until the user has provided a token.
3. If the user only says `Update Holdings`, ask exactly:
   - `1. token=?`
   - `2. create commit after sync: yes/no?`
4. Use `holdings/update_holdings_pine.py` to fetch holdings and usd balances from the Google Apps Script endpoint.
5. By default, update both:
   - `generated/holdings.pine`
   - `PNLRebalance`
6. Replace the crypto holdings block between:
   - `// === AUTO-GENERATED START ===`
   - `// === AUTO-GENERATED END ===`
7. Replace the exchange usd block between:
   - `// === AUTO-GENERATED USD START ===`
   - `// === AUTO-GENERATED USD END ===`
8. Replace the cash / liability block between:
   - `// === AUTO-GENERATED CASH LIABILITY START ===`
   - `// === AUTO-GENERATED CASH LIABILITY END ===`
9. Aggregate any `DEBT*` rows from `cash_liability` into a single generated `DEBT` value in `PNLRebalance`.
10. Do not manually rewrite holdings arrays, exchange usd values, or cash / liability values if they can be produced by the script.
11. Missing exchanges in the `usd` sheet should default to `0`.
12. Create a commit after sync only if the user explicitly says yes.
13. If the user wants a commit but does not specify a commit message, use:
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
python3 holdings/update_holdings_pine.py --token "$HOLDINGS_WEB_APP_TOKEN"
```

If the user wants to generate the Pine block without modifying `PNLRebalance`:

```bash
python3 holdings/update_holdings_pine.py --token "$HOLDINGS_WEB_APP_TOKEN" --skip-pnl-update
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
python3 holdings/update_holdings_pine.py --token "$HOLDINGS_WEB_APP_TOKEN"
```

- Generate only `generated/holdings.pine` without updating `PNLRebalance`:

```bash
python3 holdings/update_holdings_pine.py --token "$HOLDINGS_WEB_APP_TOKEN" --skip-pnl-update
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

- `/sync` and the scheduled weekly sync must run the same command and the same workflow behavior.

- Run:

```bash
python3 weekly_holdings_pnl_sync.py --token "0125" --commit
```

- This should:
  - fetch holdings from Google Sheets
  - fetch `cash_liability` from Google Sheets
  - update `generated/holdings.pine`
  - update `PNLRebalance`
  - calculate current `speculationPNL`
  - update pnl history
  - refresh live trade rows from Apps Script
  - update trade history artifacts from the fresh snapshot
  - create Notion weekly review on a best-effort basis
  - send Telegram summary on a best-effort basis
  - create a commit when holdings changed, usd balances changed, cash / liability values changed, today's pnl history has not been recorded yet, or `trade_history/TradeHistoryLabels.pine` changed
  - skip creating a duplicate Notion weekly review if that week's page already exists
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
6. `generated/trade_rows.json` must pass snapshot schema validation before conversion starts.
7. Hard fail the trade history sync when:
   - `fetched_at` is missing
   - `tabs` is missing
   - `tabs` is not an object
   - any tab rows are not a 2D row list
8. Keep `tabs` as the raw row snapshot keyed by tab name.
9. `spreadsheet_url` is optional metadata for snapshot validation and should not block conversion when omitted.
10. Only after the snapshot is refreshed, run:

```bash
python3 trade_history/update_trade_history.py
```

11. Do not rely on an old local snapshot when the Apps Script endpoint or Codex connector can be refreshed in the current turn.

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
- Exchange USDT balances (`EXCHANGE_USD`) are cash, not crypto exposure. Since 2026-09-23 they are added to `totalCash` (alongside `BITO_AVAL`), excluded from `totalCryptoAssets`, and subtracted from `allCost` the same way `BITO_AVAL` is. `weekly_holdings_pnl_sync.py` mirrors this in its `speculationPNL` calculation; keep both in sync.
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
  - `holdings/update_holdings_pine.py`
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

After any holdings sync, weekly sync, or trade history sync, explicitly tell the user which Pine scripts need to be copied back into TradingView for this run.

- At minimum, evaluate whether these Pine scripts changed:
  - `PNLRebalance`
  - `trade_history/TradeHistoryLabels.pine`
- If a file changed and should be updated in TradingView, list it under:
  - `This run, copy back to TradingView:`
- If a file did not change, list it under:
  - `This run, no TradingView update needed:`
