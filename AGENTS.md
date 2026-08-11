# AGENTS.md

## Repo Purpose
This repository maintains TradingView Pine scripts for portfolio tracking and rebalancing.
The primary recurring workflow is syncing holdings data from Google Sheets into `PNLRebalance`.

## Workflow Documentation Rule
If any workflow, automation, sync path, trigger, payload shape, generated block, or scheduled behavior is added or changed, `AGENTS.md` must be updated in the same change.

The scheduled weekly sync and manual `/sync` must use the same workflow entrypoint and produce the same side effects.

## Bitcoin Smart DCA Engine Workflow

`InvestmentEngine/bitcoin` is a long-term Bitcoin Adaptive DCA decision and record-keeping module. It is not a Pine Script strategy and must remain independent from the existing holdings, PNL, and trade-history generated blocks unless a future reviewed integration explicitly connects them.

When working on this module:

1. Treat `InvestmentEngine/bitcoin/README.md` as the project entrypoint and `InvestmentEngine/bitcoin/docs/ARCHITECTURE.md` as the current system-boundary reference.
2. Do not implement strategy code, external integrations, scheduling, notifications, or automatic trading until the corresponding design phase has been reviewed and approved.
3. Keep documentation, configuration, runtime code, generated data, and reports separated.
4. Keep strategy parameters centralized; do not hard-code adjustable values across implementation files.
5. Record every major strategy, architecture, data-model, integration, or workflow decision in `InvestmentEngine/bitcoin/decision_log.md` in the same change.
6. Keep system recommendations separate from actual executed purchases in all future data models.
7. Ensure future decision outputs are reproducible from a market snapshot, configuration version, and recorded decision reasons.
8. Route every final suggested amount through the future budget and deadline guard. Notifications, dashboards, automations, and AI suggestions must not bypass it.
9. Never store API keys, bot tokens, or other secrets in project documents, configuration committed to Git, journals, or reports.
10. Work in reviewed stages. Stop after the requested stage and do not create later-stage files or implementation early.

Current documentation stages:

- Stage 1: project skeleton, `README.md`, `docs/ARCHITECTURE.md`, and `decision_log.md`
- Stage 2: `SPEC.md` and `CONFIG.md`
- Stage 2.1: weekly capacity, correlated-factor correction, BVIV direction guard, and canonical data-time contract
- Stage 3: data model, Journal, Weekly Report, and Monthly Report templates
- Stage 4: integrations, operations, and Roadmap

Current approved Stage 4A design constraints:

- Stage 4A local manual MVP design was reviewed and approved on 2026-08-11. Gate 4A-1 Journal core was separately authorized and implemented; Gate 4A-2 pure Decision Engine／Budget Guard and Gate 4A-3 Provider／recommend workflow were separately authorized, implemented, reviewed, and approved on 2026-08-11.
- Treat `InvestmentEngine/bitcoin/docs/INTEGRATIONS.md`, `InvestmentEngine/bitcoin/docs/OPERATIONS.md`, and `InvestmentEngine/bitcoin/ROADMAP.md` as the approved Stage 4A contract.
- The approved runtime design is a Python 3.11+ local CLI with standard-library-first dependencies, Decimal arithmetic, and no background service.
- The manual entrypoint is `python3 InvestmentEngine/bitcoin/dca.py <command>`. It implements `recommend`, `record-purchase`, `correct-purchase`, `close-day`, `status`, and `validate`; `report` does not exist yet.
- Approved implementation order is Journal core, pure Decision Engine and Budget Guard, Provider adapters, then deterministic reports and local rehearsal.
- The MVP reads only Coinbase Exchange `BTC-USD`, Alternative.me Fear & Greed, Volmex BVIV/BVIVF, and the local canonical Journal. It must not access exchange accounts or place orders.
- `VOLMEX_API_KEY` is the only approved optional secret for the MVP. Read it from the environment and redact it from URLs, logs, snapshots, journals, errors, and reports.
- Recommendation is a same-day manual command in the 21:00-21:10 Asia/Taipei window, targeting about 21:05. Do not create backdated recommendations or use cutoff-after data.
- Normalize candle close `observed_at` to the candle bucket end while preserving the provider's original bucket-start timestamp and both bucket boundaries.
- Save the MarketSnapshot and DecisionRecord before presenting the recommendation to the operator.
- Manual purchase recording requires an interactive confirmation and appends only total USD paid and net BTC received; never mutate an existing execution event.
- All JSONL writes use an exclusive local lock, complete-line append, flush, and fsync. Never truncate or rewrite canonical Journal files.
- Provider failure follows the approved quality rules: invalid BTC blocks, missing Fear & Greed degrades directional groups, and missing BVIV uses modifier 1.0 with an explicit degraded reason.
- Stage 4A excludes scheduling, notifications, Google Sheets, Dashboard, exchange imports, automatic backups, and automatic trading.
- The versioned machine config is `InvestmentEngine/bitcoin/config/config.1.0-draft.2.json`; Decimal parameters remain JSON strings and secrets must never enter it.
- Gate 4A runtime modules live under `InvestmentEngine/bitcoin/src/bitcoin_dca/`. Keep `dca.py` as a thin entrypoint and do not move decision logic into it.
- Gate 4A-2 exposes only pure, deterministic indicators, weekly-target／capacity calculations, and Budget Guard functions. It performs no network or Journal writes and does not add the `recommend` command.
- The Decision Engine must preserve the approved rules: reweight exactly two valid directional groups, use `base_only` below two groups, combine ATR and absolute drop with `max`, keep BVIV at or below 1.0, compute capacity across the shifted 65-day calendar, and never exceed remaining funds or daily／weekly hard caps.
- Gate 4A-3 modules are `providers.py` and `recommendation.py`. Provider adapters return normalized records and never invoke the Decision Engine directly; recommendation orchestration must append weekly target when needed, then snapshot, then decision, with fsync before terminal output.
- `recommend` is allowed only for the current Asia/Taipei plan date from 21:00:00 through 21:10:00. It has no backdated date option and uses the same 21:00 cutoff for same-day revisions.
- Coinbase requires exact 5m current／previous cutoff buckets and 91 continuous completed UTC daily candles. Missing, duplicate, unordered-after-normalization gaps, or invalid BTC data blocks the decision; it must never switch exchanges or substitute a ticker.
- Fear & Greed selects the latest valid Alternative.me value observed by cutoff and degrades when stale／missing. Volmex selects completed BVIV 60m, then completed BVIVF at the 16:00 America/New_York fixing time, then neutral 1.0; fallback or missing BVIV degrades explicitly.
- HTTP retries only timeout／connection／429／5xx using versioned runtime settings. `VOLMEX_API_KEY` may enter only the outgoing query and must be absent from descriptors, errors, snapshots, decisions, stdout, and tests' canonical artifacts.
- Gate 4A-3 writes `data/market_snapshots.jsonl`, `data/decisions.jsonl`, and `data/weekly_targets.jsonl`; Gate 4A-1 writes `data/executions.jsonl`. All real JSONL and lock files remain Git ignored.
- `record-purchase` writes only after interactive `yes` confirmation unless the operator explicitly passes `--yes`. It records the current Asia/Taipei date and rejects dates outside the approved plan.
- `correct-purchase` must append a same-operation reversal and replacement. Never modify or delete the original JSONL line, and never reverse the same purchase twice.
- `close-day --reason skipped` is invalid after an effective purchase that day; `completed_for_day` requires at least one effective purchase.
- `validate` must hard fail malformed UTF-8/JSONL, incomplete lines, schema/reference/revision/reversal errors, DecisionRecord numeric hard-cap violations, and an invalid over-budget PortfolioState.
- Run Gate 4A-1／4A-2／4A-3 tests with `PYTHONPYCACHEPREFIX=/tmp/bitcoin-dca-pycache python3 -m unittest discover -s InvestmentEngine/bitcoin/tests -v`.
- Do not implement Gate 4A-4 reports, scheduling, notifications, automatic backups, or automatic trading without separate explicit authorization.

Current approved Stage 3 constraints:

- Stage 3 was reviewed and approved on 2026-08-11.
- The current plan runs from 2026-08-12 through 2026-10-15 inclusive, preserving the original 65-day duration. Treat it as a full-plan delay, not a compressed schedule.
- Treat `InvestmentEngine/bitcoin/docs/DATA_MODEL.md` as the canonical Stage 3 storage contract.
- Keep market snapshots immutable once referenced by a decision.
- Store same-day recalculations as an append-only, acyclic decision revision chain. Preserve superseded revisions and derive the current revision as the chain's unique unsuperseded leaf.
- Store actual purchases as append-only execution events. Correct mistakes with reversal and replacement events instead of overwriting history; use a non-financial `day_close` event when the user explicitly skips or closes the day.
- Allow multiple purchases per plan date. Derive remaining budget, accumulated BTC, average cost, daily totals, and weekly totals only from effective actual execution events.
- Manual purchase input requires only total USD paid and net BTC received. Default execution time to the report time; derive effective cost price as USD divided by BTC.
- Do not track fees separately in v1. Treat total USD paid as budget cost and net BTC received as the acquired quantity, so the derived effective cost naturally includes fee impact.
- Keep `MarketSnapshot`, `DecisionRecord`, `ExecutionEvent`, and `WeeklyTargetSnapshot` as separate canonical record types.
- Treat PortfolioState and Daily／Weekly／Monthly reports as derived views, never as independent sources of truth.
- Use decimal strings in canonical JSONL records for USD, BTC, prices, scores, and multipliers.
- Store canonical JSONL locally under `InvestmentEngine/bitcoin/data/`; keep all real `*.jsonl` files Git ignored. Stage 3 does not require encryption or automated backups.
- Stage 3 approval does not authorize API integrations, strategy runtime code, scheduling, notifications, dashboards, or automatic trading.

Current approved Stage 2.1 design constraints:

- Use Coinbase Exchange `BTC-USD` as the canonical BTC market-data basis. Do not silently mix or switch exchange sources.
- Use a daily decision cutoff of 21:00 Asia/Taipei. Inputs observed after the cutoff must not affect that day's decision.
- Treat ATR drop and absolute daily drop as one shock group, not independent additive weights.
- Treat BVIV as a non-directional volatility modifier. In the v1.0 draft it may suppress but must not amplify the Adaptive amount.
- Evaluate both daily and weekly future capacity. Mark an infeasible remaining plan explicitly instead of silently increasing hard limits.
- Calculate `minimum_required_today` from the remaining current-week and future-week hard capacity, round that minimum upward to the currency unit, and include it in the final guard candidate.
- A capacity-required minimum may override a weekly soft cap but must never override daily or weekly hard caps.
- Compute `effective_weekly_soft_remaining` before calculating the final amount. Never apply the original weekly soft remainder first when `minimum_required_today` requires the reviewed soft-cap override.
- Do not override daily or weekly hard caps automatically on the final day.
- Stage 2.1 design was approved on 2026-08-02. Numeric weights, thresholds, multipliers, pacing ratios, and hard-cap amounts remain draft defaults pending backtesting or operational validation; do not describe them as proven effective.
- Approval covers Stage 2.1 design documentation only. Stage 3 documentation was separately requested on 2026-08-11; do not start runtime implementation, API integration, scheduling, notifications, dashboards, or automatic trading without separate explicit approval.

Any future workflow, automation, schedule, trigger, payload, storage contract, or external integration added to this module must also update this `AGENTS.md` section in the same change.

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
