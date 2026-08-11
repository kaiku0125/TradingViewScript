# Bitcoin Smart DCA Engine Configuration Contract

## 1. 文件狀態

- Config 版本：`1.0-draft.2`
- 狀態：Stage 2.1 設計已核准；表列數值仍為待回測的草案預設值
- 原則：策略參數集中管理；API Key、Bot Token、Webhook Secret 不得進入 Git

## 2. 計畫參數

| 參數 | 草案預設值 | 型別／單位 | 驗證 |
|---|---:|---|---|
| `plan.currency` | `USD` | enum | 目前只允許 `USD` |
| `plan.asset` | `BTC` | enum | 目前只允許 `BTC` |
| `plan.initial_budget` | `10000.00` | decimal USD | `> 0` |
| `plan.start_date` | `2026-08-12` | ISO date | `<= end_date` |
| `plan.end_date` | `2026-10-15` | ISO date | `>= start_date` |
| `plan.timezone` | `Asia/Taipei` | IANA timezone | 必須有效 |
| `plan.data_cutoff_time` | `21:00` | local time | `HH:mm` |
| `plan.notification_target_time` | `21:05` | local time | 不早於 cutoff |
| `plan.base_dca` | `80.00` | USD/day | `>= 0` |

衍生值由系統計算，不手動維護：

```text
total_days = 65
base_budget = 5,200.00
adaptive_reserve = 4,800.00
nominal_adaptive_daily = 4,800 / 65 ≈ 73.846153846
```

## 3. Canonical 資料來源

### 3.1 BTC 行情

| 參數 | 草案預設值 | 說明 |
|---|---|---|
| `data.btc.provider` | `coinbase_exchange` | v1.0 不靜默切換供應商 |
| `data.btc.product` | `BTC-USD` | BTC 與 USD 現貨 |
| `data.btc.reference_interval` | `5m` | 截止時間前最後完整 candle |
| `data.btc.reference_field` | `close` | 決策 reference price |
| `data.btc.reference_max_age_minutes` | `10` | 超過即 stale |
| `data.btc.daily_interval` | `1d` | 近期高點與 ATR |
| `data.btc.daily_boundary` | `00:00_UTC` | 只使用已完成 candle |
| `data.btc.automatic_fallback` | `none` | 缺資料時 blocked |

### 3.2 Fear & Greed

| 參數 | 草案預設值 | 說明 |
|---|---|---|
| `data.fear_greed.provider` | `alternative_me` | Crypto Fear & Greed API |
| `data.fear_greed.use_latest_before_cutoff` | `true` | 禁止 cutoff 後資料 |
| `data.fear_greed.max_age_hours` | `36` | 超過即 stale |

### 3.3 BVIV

| 參數 | 草案預設值 | 說明 |
|---|---|---|
| `data.bviv.provider` | `volmex` | Bitcoin 30-day implied volatility |
| `data.bviv.primary_interval` | `60m` | 最後完整小時值 |
| `data.bviv.primary_max_age_hours` | `2` | Primary 新鮮度 |
| `data.bviv.fallback` | `latest_completed_fixing` | 只取已完成 fixing |
| `data.bviv.fallback_max_age_hours` | `36` | Fallback 新鮮度 |
| `data.bviv.missing_modifier` | `1.0` | 缺失時中性，不當成低波動 |

### 3.4 Portfolio

| 參數 | 草案預設值 | 說明 |
|---|---|---|
| `data.portfolio.canonical_source` | `local_journal` | 第 3 階段定義格式 |
| `data.portfolio.use_actual_investment` | `true` | 固定為 true |
| `data.portfolio.allow_external_overwrite` | `false` | 未 Review 前禁止外部覆寫 |

### 3.5 資料時間欄位

每份輸入必須包含：

| 欄位 | 意義 |
|---|---|
| `source` | 供應商 |
| `symbol` | 商品或指標代號 |
| `value` | 原始值 |
| `interval` | 資料週期 |
| `observed_at` | 數值代表時間 |
| `available_at` | 最早可取得時間 |
| `fetched_at` | 實際取得時間 |
| `timezone` | 原始時間語意 |
| `cutoff_at` | 本次決策截止時間 |
| `stale_after` | 新鮮度上限 |
| `quality_status` | valid／stale／missing／invalid |
| `fallback_used` | 是否採備援 |

## 4. 方向性因子

### 4.1 權重

| 參數 | 草案值 | 驗證 |
|---|---:|---|
| `factors.location.weight` | `0.45` | `0～1` |
| `factors.sentiment.weight` | `0.25` | `0～1` |
| `factors.shock.weight` | `0.30` | `0～1` |
| `decision.minimum_valid_directional_groups` | `2` | `1～3` |

權重總和必須為 1。只有 2 個有效群組時按有效權重正規化；少於 2 個時採 `base_only`。

### 4.2 價格位置

| 參數 | 草案值 | 單位／驗證 |
|---|---:|---|
| `factors.location.lookback_days` | `90` | integer days，`>= 2` |
| `factors.location.score_min_pct` | `5.0` | percent，`>= 0` |
| `factors.location.score_max_pct` | `30.0` | percent，`> min` |

### 4.3 市場情緒

| 參數 | 草案值 | 驗證 |
|---|---:|---|
| `factors.sentiment.score_zero_at` | `60` | `0～100` |
| `factors.sentiment.score_one_at` | `10` | `< score_zero_at` |

### 4.4 下跌衝擊

| 參數 | 草案值 | 單位／驗證 |
|---|---:|---|
| `factors.shock.atr_period` | `14` | integer days，`>= 2` |
| `factors.shock.atr_smoothing` | `wilder_rma` | enum |
| `factors.shock.atr_score_min_multiple` | `0.5` | `>= 0` |
| `factors.shock.atr_score_max_multiple` | `2.0` | `> min` |
| `factors.shock.drop_score_min_pct` | `2.0` | percent，`>= 0` |
| `factors.shock.drop_score_max_pct` | `10.0` | percent，`> min` |
| `factors.shock.combine_method` | `max` | v1.0 固定為 `max` |

## 5. BVIV 調節器

| 參數 | 草案值 | 說明 |
|---|---:|---|
| `bviv.score_min` | `50.0` | 波動分數起點 |
| `bviv.score_max` | `100.0` | 波動滿分 |
| `bviv.modifier_min` | `0.90` | 無 downside gate 時最大抑制 |
| `bviv.modifier_max_v1` | `1.00` | v1.0 禁止放大 |
| `bviv.gate.drawdown_pct` | `5.0` | 回檔 gate |
| `bviv.gate.fear_greed_max` | `40` | 恐慌 gate |
| `bviv.gate.any_negative_return` | `true` | 當日下跌 gate |

## 6. Adaptive 金額

| 參數 | 草案值 | 驗證 |
|---|---:|---|
| `decision.adaptive_multiplier_min` | `0.0` | `>= 0` |
| `decision.adaptive_multiplier_max` | `2.0` | `>= min` |
| `decision.rounding_unit` | `0.01` | USD，`> 0` |
| `decision.rounding_mode` | `floor` | 固定為 floor |

```text
adaptive_multiplier = min + directional_score × (max - min)
market_adaptive = nominal_adaptive_daily × adaptive_multiplier × bviv_modifier
```

## 7. 進度與週容量

| 參數 | 草案值 | 說明／驗證 |
|---|---:|---|
| `pacing.acceleration_start_days` | `21` | `> full_pace_days` |
| `pacing.full_pace_days` | `7` | `>= 1` |
| `pacing.weekly_min_ratio_early` | `0.80` | `0～1` |
| `pacing.weekly_min_ratio_late` | `1.00` | `>= early` |
| `pacing.weekly_soft_max_ratio` | `1.30` | `>= 1` |
| `pacing.snapshot_weekly_target` | `true` | 每週第一個投資日固定 |
| `pacing.enable_capacity_check` | `true` | 固定為 true |
| `pacing.enable_minimum_required_today` | `true` | 固定為 true |
| `pacing.minimum_required_rounding` | `ceil` | 向上取至金額單位 |
| `pacing.infeasible_policy` | `alert_no_hard_cap_override` | 不自動突破限制 |

## 8. Budget Guard

| 參數 | 草案值 | 說明／驗證 |
|---|---:|---|
| `budget.daily_hard_max` | `500.00` | USD，`>= base_dca` |
| `budget.weekly_hard_max` | `2000.00` | USD，`> 0` |
| `budget.week_start` | `monday` | Asia/Taipei |
| `budget.final_day_override_daily_max` | `false` | 固定為 false |
| `budget.final_day_override_weekly_max` | `false` | 固定為 false |
| `budget.allow_soft_cap_feasibility_override` | `true` | 只可提高到 hard max |
| `budget.allow_negative_remaining` | `false` | 固定為 false |

## 9. Config 驗證

Config 載入時必須驗證：

1. 日期、時區、截止時間、幣別與資產有效。
2. Base Budget 不超過起始資金。
3. Canonical provider、product、interval 與日線邊界完整。
4. 所有資料新鮮度限制大於 0。
5. 三個方向群組權重總和為 1。
6. 每個 score max 嚴格大於 score min。
7. BVIV modifier 不得高於 1.0，除非未來新版本明確核准。
8. 期限開始日大於完全生效日。
9. Daily hard max 至少等於 Base DCA，Weekly hard max 大於 0。
10. 最終日 hard-cap override 必須為 false。
11. `minimum_required_today` 必須啟用並採 `ceil`，不得向下截斷可行性底線。
12. 依日期、日／週 hard max 執行初始容量檢查；若 10,000 USD 在數學上不可行，Config 無效。

任何錯誤都不得靜默改值。

## 10. 版本治理

- 已用於正式決策的 Config 不可原地修改，必須建立新版本。
- 每日決策保存 Config 版本與完整資料時間欄位。
- 因子、金額、容量、資料來源或 cutoff 變更必須同步更新 `SPEC.md` 與 `decision_log.md`。
- Secrets 使用環境變數或秘密管理服務。

## 11. Stage 2.1 核准表

設計規則已核准，但權重、門檻、倍率、期限比例與 hard-cap 金額仍是草案預設值，不能描述為已證實有效。

| 分類 | 草案選擇 | 核准狀態 |
|---|---|---|
| BTC 行情 | Coinbase `BTC-USD`，無自動跨所 fallback | 設計已核准 |
| 時間 | 21:00 cutoff，21:05 前通知 | cutoff 已核准；通知時間待營運驗證 |
| 方向權重 | 45%／25%／30% | 架構已核准；數值待回測 |
| Shock | ATR 與絕對跌幅取 max | v1.0 設計已核准；敏感度待回測 |
| BVIV | modifier 0.90～1.00，不放大 | 非方向性限制已核准；數值待回測 |
| 週目標 | minimum 80% 漸增至 100%，soft max 130% | 規則已核准；數值待回測 |
| Hard caps | 每日 500、每週 2,000 USD | 不可自動突破已核准；金額待驗證 |
| 最終日 | 不覆寫 hard caps | 已核准 |
| 容量不足 | `plan_infeasible`，人工處理 | 已核准 |
| 今日容量底線 | `minimum_required_today`，向上取至美分 | 已核准 |
