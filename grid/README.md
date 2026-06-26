# Grid Parameter System

This folder stores the reusable workflow and notes for grid-trading parameter design.

## Primary Goal
Standardize how grid parameters are discussed, questioned, and recorded for each asset.

## Trigger Phrases
- `/網格參數`
- `/網格參數 BTC`
- `grid setup`
- `grid parameters`

## Default Intake
If the user only gives an asset such as `/網格參數 BTC`, ask:

1. `timeframe=?`
2. `前低=?`
3. `目標價=?`
4. `手續費率=?`

If the user provides `前低` and `目標價` but not `timeframe`, ask for timeframe before calculating.

## Parameter Fields
Each grid setup should define these fields:

- `asset_symbol`
- `timeframe`
- `previous_low`
- `target_price`
- `fee_rate_percent`
- `atr_period`
- `atr_value`
- `range_upper`
- `range_lower`
- `range_formula`
- `spacing_percent`
- `round_trip_fee_percent`
- `net_spacing_percent`
- `take_profit_rule`
- `stop_condition`
- `notes`

## Range Logic
For the current default setup, use this sequence:

1. Read the user-provided `previous low`.
2. Read the user-provided `target price`.
3. Fetch recent OHLC data for the chosen symbol and timeframe.
4. Calculate the latest `ATR(14)`.
5. Set `lower bound = previous low - 1 * ATR(14)`.
6. Set `upper bound = target price`.

## Default Mode
The default mode is `aggressive`.

- `spacing method = ATR-based`
- `spacing value = 0.35 * ATR(14)`
- `theoretical grid count = round((upper - lower) / (0.35 * ATR(14)))`
- do not clamp the final result

## Suggested Framing
When proposing a setup, keep the answer in this structure:

1. Trigger context
2. Upper bound
3. Lower bound
4. ATR source and value
5. Theoretical grid count
6. Spacing method
7. Fee impact
8. Stop condition

## Recording
Use `ASSET_TEMPLATE.md` to create or update asset-specific notes when needed.

## Local Command
Use this command to calculate the current default range:

```bash
python3 grid/calc_grid_bounds.py --symbol BTC-USD --timeframe 1d --previous-low 100000 --target-price 112000
```
