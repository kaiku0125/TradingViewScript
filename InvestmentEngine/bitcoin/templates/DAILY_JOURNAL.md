# Bitcoin Smart DCA Daily Journal

> Template version: `daily_journal.v1`
> 此文件是由 canonical Journal 產生的人類可讀視圖，不是實際成交的來源。

## 基本資料

| 欄位 | 值 |
|---|---|
| 日期（Asia/Taipei） | `{{plan_date}}` |
| Cutoff | `{{cutoff_at}}` |
| 計算時間 | `{{calculated_at}}` |
| 報表產生時間（canonical watermark） | `{{generated_at}}` |
| 決策狀態 | `{{decision_status}}` |
| 執行狀態 | `{{execution_status}}` |
| Config | `{{config_version}}` |
| Decision revision | `{{revision}} / {{revision_count}}` |
| Snapshot ID | `{{snapshot_id}}` |

## 今日建議

| 項目 | USD |
|---|---:|
| Base DCA | `{{base_usd}}` |
| Adaptive | `{{adaptive_usd}}` |
| Market amount | `{{market_amount_usd}}` |
| Pace floor | `{{pace_floor_usd}}` |
| Weekly catchup | `{{weekly_catchup_usd}}` |
| Minimum required today | `{{minimum_required_today_usd}}` |
| 最終建議 | `{{final_suggested_usd}}` |
| 今日尚待執行 | `{{remaining_to_execute_today_usd}}` |

原因：`{{reason_summary}}`

原因代碼：`{{reason_codes}}`

## 市場快照

| 指標 | 數值 | 觀察時間 | 品質／Fallback |
|---|---:|---|---|
| BTC reference price | `{{btc_reference_price}}` | `{{btc_reference_observed_at}}` | `{{btc_reference_quality}}` |
| 90 日高點 | `{{recent_high}}` | `{{daily_data_observed_at}}` | `{{daily_data_quality}}` |
| ATR(14) | `{{atr_14}}` | `{{daily_data_observed_at}}` | `{{atr_quality}}` |
| Fear & Greed | `{{fear_greed}}` | `{{fear_greed_observed_at}}` | `{{fear_greed_quality}}` |
| BVIV | `{{bviv}}` | `{{bviv_observed_at}}` | `{{bviv_quality}} / {{bviv_fallback_used}}` |

| 分數／調節 | 值 |
|---|---:|
| Location | `{{location_score}}` |
| Sentiment | `{{sentiment_score}}` |
| ATR drop | `{{atr_drop_score}}` |
| Absolute drop | `{{absolute_drop_score}}` |
| Shock | `{{shock_score}}` |
| Directional | `{{directional_score}}` |
| BVIV modifier | `{{bviv_modifier}}` |

## Budget Guard

| 項目 | 值 |
|---|---:|
| 決策前剩餘預算 | `{{remaining_funds_before_usd}}` USD |
| 今日 hard capacity | `{{today_hard_capacity_usd}}` USD |
| 本週 hard remaining | `{{weekly_hard_remaining_usd}}` USD |
| 本週 soft remaining | `{{weekly_soft_remaining_usd}}` USD |
| Soft cap feasibility override | `{{soft_cap_overridden_for_feasibility}}` |
| 全期剩餘容量 | `{{total_capacity_including_today_usd}}` USD |
| Plan feasible | `{{plan_feasible}}` |

## 實際成交

| 回報／成交時間 | Venue | 總投入 USD | 實收 BTC | 衍生有效成本價 | Execution ID |
|---|---|---:|---:|---:|---|
| `{{executed_at}}` | `{{venue}}` | `{{usd_amount}}` | `{{btc_quantity}}` | `{{derived_effective_price_usd}}` | `{{execution_id}}` |

若沒有成交，保留空表並顯示 `pending`；不得填入建議金額冒充實際成交。

## 今日執行結果

| 項目 | 值 |
|---|---:|
| 實際投入 | `{{actual_invested_today_usd}}` USD |
| 建議差異（actual - suggested） | `{{execution_variance_usd}}` USD |
| 實際取得 BTC | `{{actual_btc_today}}` |
| 有效成本均價 | `{{actual_average_price_today_usd}}` USD |
| 使用者註記 | `{{execution_note}}` |
| 當日人工結束狀態 | `{{day_close_reason}}` |

## 投資組合期末狀態

| 項目 | 值 |
|---|---:|
| 累積實際投入 | `{{cumulative_actual_invested_usd}}` USD |
| 剩餘預算 | `{{remaining_budget_usd}}` USD |
| 累積 BTC | `{{cumulative_btc}}` |
| 有效平均成本 | `{{average_cost_usd}}` USD |
| 本週實際投入 | `{{actual_invested_this_week_usd}}` USD |
| Execution data watermark | `{{execution_watermark}}` |
