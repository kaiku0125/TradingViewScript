# Bitcoin Smart DCA Weekly Report

> Template version: `weekly_report.v1`

## 報表資訊

| 欄位 | 值 |
|---|---|
| 週期（Asia/Taipei） | `{{week_start}}` ～ `{{week_end}}` |
| 產生時間 | `{{generated_at}}` |
| Weekly target ID | `{{weekly_target_id}}` |
| Config versions | `{{config_versions}}` |
| Execution data watermark | `{{execution_watermark}}` |
| 資料完整性 | `{{data_completeness_status}}` |

## 本週目標與結果

| 項目 | USD／比例 |
|---|---:|
| Weekly target | `{{weekly_target_usd}}` |
| Weekly minimum | `{{weekly_min_usd}}` |
| Weekly soft max | `{{weekly_soft_max_usd}}` |
| Weekly hard max | `{{weekly_hard_max_usd}}` |
| 實際投入 | `{{actual_invested_week_usd}}` |
| 與 target 差異 | `{{target_variance_usd}}` |
| 最低目標完成率 | `{{weekly_min_completion_ratio}}` |
| 本週取得 BTC | `{{btc_acquired_week}}` |
| 本週有效成本均價 | `{{actual_average_price_week_usd}}` |

## 每日明細

| 日期 | 決策狀態 | 建議 USD | 實際 USD | 差異 | 執行狀態 | 主要原因 |
|---|---|---:|---:|---:|---|---|
| `{{plan_date}}` | `{{decision_status}}` | `{{suggested_usd}}` | `{{actual_usd}}` | `{{variance_usd}}` | `{{execution_status}}` | `{{reason_summary}}` |

## 資料品質與限制

| 項目 | 次數／狀態 |
|---|---:|
| Normal | `{{normal_days}}` |
| Degraded | `{{degraded_days}}` |
| Base only | `{{base_only_days}}` |
| Blocked | `{{blocked_days}}` |
| Pending | `{{pending_days}}` |
| Plan infeasible | `{{plan_infeasible_days}}` |
| Soft-cap overrides | `{{soft_cap_override_days}}` |

未解決問題：

- `{{open_issue}}`

## 期末投資組合與下週展望

| 項目 | 值 |
|---|---:|
| 累積實際投入 | `{{cumulative_actual_invested_usd}}` USD |
| 剩餘預算 | `{{remaining_budget_usd}}` USD |
| 累積 BTC | `{{cumulative_btc}}` |
| 有效平均成本 | `{{average_cost_usd}}` USD |
| 剩餘投資日 | `{{days_remaining}}` |
| 未來 hard capacity | `{{future_hard_capacity_usd}}` USD |
| 目前計畫可行 | `{{plan_feasible}}` |

摘要：`{{weekly_summary}}`
