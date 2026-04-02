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

1. Treat Google Sheets as the source of truth for holdings.
2. Do not run `update_holdings_pine.py` until the user has provided a token.
3. If the user only says `Update Holdings`, ask exactly:
   - `1. token=?`
   - `2. create commit after sync: yes/no?`
4. Use `update_holdings_pine.py` to fetch holdings from the Google Apps Script endpoint.
5. By default, update both:
   - `generated/holdings.pine`
   - `PNLRebalance`
6. Replace only the block between:
   - `// === AUTO-GENERATED START ===`
   - `// === AUTO-GENERATED END ===`
7. Do not manually rewrite holdings arrays if they can be produced by the script.
8. Do not modify non-auto-generated portfolio logic unless the user explicitly asks.
9. Create a commit after sync only if the user explicitly says yes.
10. If the user wants a commit but does not specify a commit message, use:
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
2. `PNLRebalance` auto-generated block was updated.
3. The generated arrays match the expected symbols and values from the payload.
4. No `input.float(defval=runtime_value)` pattern was introduced for generated positions or costs.

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
