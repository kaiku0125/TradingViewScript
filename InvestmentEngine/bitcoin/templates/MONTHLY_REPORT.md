# Bitcoin Smart DCA Monthly Report

> Template version: `monthly_report.v1`

## 報表資訊

| 欄位 | 值 |
|---|---|
| 月份／計畫交集 | `{{period_start}}` ～ `{{period_end}}` |
| 產生時間 | `{{generated_at}}` |
| Config versions | `{{config_versions}}` |
| Execution data watermark | `{{execution_watermark}}` |
| 資料完整性 | `{{data_completeness_status}}` |

## 本月投入摘要

| 項目 | 值 |
|---|---:|
| 系統建議總額 | `{{total_suggested_usd}}` USD |
| 實際投入總額 | `{{total_actual_usd}}` USD |
| 建議差異 | `{{total_variance_usd}}` USD |
| 取得 BTC | `{{btc_acquired}}` |
| 成交筆數 | `{{execution_count}}` |
| 有效成本均價 | `{{actual_average_price_usd}}` USD |

## 執行與策略行為

| 指標 | 值 |
|---|---:|
| 有建議日數 | `{{decision_days}}` |
| 完全執行日 | `{{executed_days}}` |
| 部分執行日 | `{{partially_executed_days}}` |
| 超額執行日 | `{{over_executed_days}}` |
| Pending 日 | `{{pending_days}}` |
| Blocked 日 | `{{blocked_days}}` |
| 建議遵循率 | `{{adherence_ratio}}` |
| 平均 Directional score | `{{average_directional_score}}` |
| 平均 BVIV modifier | `{{average_bviv_modifier}}` |
| Capacity-required minimum 觸發日 | `{{minimum_required_days}}` |

建議遵循率的 v1 定義：

```text
min(total_actual_usd, total_suggested_usd) / total_suggested_usd
```

當建議總額為 0 時顯示 `N/A`，不得除以零；同時另列 over-executed 日數，避免遵循率掩蓋超額投入。

## 每週摘要

| 週期 | Weekly target | 建議 USD | 實際 USD | 最低目標完成率 | 期末可行性 |
|---|---:|---:|---:|---:|---|
| `{{week_range}}` | `{{weekly_target_usd}}` | `{{weekly_suggested_usd}}` | `{{weekly_actual_usd}}` | `{{weekly_min_completion_ratio}}` | `{{plan_feasible}}` |

## 資料品質與版本

- Degraded dates：`{{degraded_dates}}`
- Blocked dates：`{{blocked_dates}}`
- Pending dates：`{{pending_dates}}`
- Plan infeasible dates：`{{plan_infeasible_dates}}`
- Config transitions：`{{config_transitions}}`
- Reversed／corrected executions：`{{corrected_execution_count}}`

## 月末投資組合

| 項目 | 值 |
|---|---:|
| 累積實際投入 | `{{cumulative_actual_invested_usd}}` USD |
| 剩餘預算 | `{{remaining_budget_usd}}` USD |
| 累積 BTC | `{{cumulative_btc}}` |
| 有效平均成本 | `{{average_cost_usd}}` USD |
| 已投入比例 | `{{budget_deployed_ratio}}` |
| 剩餘投資日 | `{{days_remaining}}` |
| 未來 hard capacity | `{{future_hard_capacity_usd}}` USD |
| 目前計畫可行 | `{{plan_feasible}}` |

月度摘要：`{{monthly_summary}}`
