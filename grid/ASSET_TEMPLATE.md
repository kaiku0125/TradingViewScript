# Grid Asset Template

## Asset
- `asset_symbol`:
- `timeframe`:

## Inputs
- `previous_low`:
- `target_price`:
- `fee_rate_percent`:
- `atr_period`: `14`
- `atr_value`:

## Proposed Range
- `range_upper`:
- `range_lower`:
- `range_formula`: `lower = previous_low - 1 * ATR(14), upper = target_price`

## Grid Structure
- `mode`: `aggressive`
- `theoretical_grid_count`:
- `spacing_method`: `ATR-based`
- `spacing_value`:
- `spacing_percent_range`:
- `round_trip_fee_percent`:
- `net_spacing_percent_range`:
- `grid_count_formula`: `round((range_upper - range_lower) / (0.35 * ATR(14)))`

## Risk Rules
- `take_profit_rule`:
- `stop_condition`:
- `max_additional_drawdown`:

## Notes
- `notes`:
