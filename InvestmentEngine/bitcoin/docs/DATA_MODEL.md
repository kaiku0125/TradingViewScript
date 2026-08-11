# Bitcoin Smart DCA Engine Data Model

## 1. 文件狀態

- 資料模型版本：`1.0-draft.3`
- 階段：Stage 3 Accepted；Stage 4A candle timing 與 Gate 4A-1 operation contract implemented（2026-08-11）
- 時區：除來源原始時間外，業務日期與週期皆使用 `Asia/Taipei`
- 儲存格式：UTF-8 JSON Lines（JSONL），每行一個完整事件或紀錄

本文件定義 Journal、實際成交、投資組合衍生狀態與週／月報表所使用的 canonical contract。它不定義 API、排程、通知或自動交易。

## 2. 核心原則

1. 系統建議與實際成交永久分開保存。
2. 市場快照一旦被決策引用即不可原地修改；修正資料必須建立新快照。
3. 同日重算建立新的決策 revision，舊 revision 不刪除；目前有效版本由 revision chain 的唯一末端推導，不回頭修改舊紀錄。
4. 成交以 append-only event 保存；錯誤資料以 reversal 與 replacement 修正，不覆寫歷史。
5. 剩餘資金、累積 BTC、平均成本及進度只由有效的實際成交推導。
6. 報表是 Journal 的衍生視圖，不可自行重新抓市場資料或重算策略建議。
7. 所有金額與數量在儲存層使用十進位字串，避免二進位浮點誤差。
8. 所有 ID 在資料集中唯一；建議格式為 UUID，但實作可使用其他不重複、不可重用的字串。
9. Journal 與報表不得保存 API key、token、webhook secret 或交易所憑證。

## 3. Canonical 資料集

| 路徑 | 記錄類型 | 寫入方式 | 用途 |
|---|---|---|---|
| `data/market_snapshots.jsonl` | `MarketSnapshot` | append-only | 保存實際參與決策的市場輸入 |
| `data/decisions.jsonl` | `DecisionRecord` | append-only revisions | 保存限制前後建議及原因 |
| `data/executions.jsonl` | `ExecutionEvent` | append-only | 保存實際買入、reversal 與 replacement |
| `data/weekly_targets.jsonl` | `WeeklyTargetSnapshot` | append-only | 保存每週第一個投資日建立的不可變目標 |

`PortfolioState`、Daily Journal、Weekly Report 與 Monthly Report 都是由上述 canonical 資料集產生的衍生結果。Stage 3 不建立真實投資資料；實際資料檔留待後續實作或人工補登流程核准後產生。

## 4. 共用型別與格式

### 4.1 時間與日期

- `plan_date`：`YYYY-MM-DD`，依 `Asia/Taipei` 判定。
- timestamp：帶 offset 的 RFC 3339，例如 `2026-08-11T21:03:12+08:00`。
- `cutoff_at` 固定對應該日 `21:00:00+08:00`。
- 來源資料同時保存 `observed_at`、`available_at`、`fetched_at`，不得只留抓取時間。

### 4.2 Decimal

- USD：非負十進位字串，最多 2 位小數，例如 `"180.00"`。
- BTC：非負十進位字串，最多 8 位小數，例如 `"0.00154231"`。
- 價格：正十進位字串，例如 `"116710.25"`。
- 分數與倍率：十進位字串，儲存足以重現結果的精度，不先格式化成百分比。

成交的有效成本價不由使用者輸入或保存為 canonical 欄位，而是以 `usd_amount / btc_quantity` 動態計算。

### 4.3 資料品質

每個外部輸入使用：

```json
{
  "source": "coinbase_exchange",
  "symbol": "BTC-USD",
  "value": "116710.25",
  "interval": "5m",
  "observed_at": "2026-08-11T21:00:00+08:00",
  "available_at": "2026-08-11T21:00:00+08:00",
  "fetched_at": "2026-08-11T21:01:10+08:00",
  "timezone": "UTC",
  "cutoff_at": "2026-08-11T21:00:00+08:00",
  "stale_after": "PT10M",
  "quality_status": "valid",
  "fallback_used": false
}
```

`quality_status` 只允許 `valid`、`stale`、`missing`、`invalid`。缺失值使用 `null`，不得用 `0` 冒充。

對 OHLC candle，供應商 timestamp 與 normalized `bucket_start`、`bucket_end` 都必須保存；close value 的 `observed_at` 固定使用 `bucket_end`，表示該 close 成立的時間，不把 bucket start 誤當成資料完成時間。

## 5. MarketSnapshot

一筆 `MarketSnapshot` 是某次決策所看到的完整、不可變輸入集合。

必要欄位：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `schema_version` | string | 固定 `market_snapshot.v1` |
| `snapshot_id` | string | 唯一 ID |
| `operation_id` | string | 產生此紀錄的本機 command operation ID |
| `plan_date` | date | 決策業務日期 |
| `cutoff_at` | timestamp | 當日資料截止 |
| `created_at` | timestamp | 快照建立時間 |
| `btc_reference` | data point | Coinbase 5m reference close |
| `btc_previous_reference` | data point | 前一決策日 reference close |
| `btc_daily_candles` | object | 計算 90 日高點與 ATR 所需的已完成日線及其內容雜湊 |
| `fear_greed` | data point | Alternative.me 指標，可為 missing |
| `bviv` | data point | Volmex primary 或 fixing，可為 missing |
| `portfolio_input` | object | 決策前的衍生實際投資狀態 |
| `quality_summary` | object | 整體 valid／degraded／blocked 及原因碼 |

`portfolio_input` 至少保存 `as_of_execution_id`、`actual_invested_usd`、`remaining_funds_usd`、`actual_invested_this_week_usd` 與 `actual_invested_today_usd`，使決策可重現且不依賴日後改變的最新狀態。

## 6. DecisionRecord

每次正式計算建立一個 revision：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `schema_version` | string | 固定 `decision.v1` |
| `decision_id` | string | 同一日期各 revision 共用的穩定 ID |
| `revision_id` | string | 此 revision 唯一 ID |
| `operation_id` | string | 產生此 revision 的本機 command operation ID |
| `revision` | integer | 從 1 起遞增 |
| `supersedes_revision_id` | string/null | 被本次取代的 revision |
| `plan_date` | date | 決策業務日期 |
| `snapshot_id` | string | 使用的不可變市場快照 |
| `weekly_target_id` | string | 當週目標快照 |
| `config_version` | string | 使用的 Config 版本 |
| `calculated_at` | timestamp | 實際計算時間 |
| `decision_status` | enum | 見下方狀態 |
| `scores` | object | location、sentiment、ATR drop、absolute drop、shock、directional |
| `market_amounts` | object | base、adaptive、BVIV modifier、market amount |
| `pacing` | object | pace floor、weekly catchup、minimum required today |
| `capacity` | object | 日／週／全期容量與可行性 |
| `final_suggested_usd` | USD/null | Budget Guard 後金額；blocked 時為 null |
| `reason_codes` | string[] | 機器可讀原因 |
| `reason_summary` | string | 簡潔的人類可讀說明 |

`decision_status` 沿用 `SPEC.md`：`normal`、`degraded`、`base_only`、`blocked`、`plan_infeasible`、`completed`。

`reason_codes` 建議使用穩定代碼，例如 `LOCATION_DRAWDOWN`、`SENTIMENT_FEAR`、`SHOCK_DAILY_DROP`、`BVIV_NEUTRAL_MISSING`、`WEEKLY_CATCHUP`、`CAPACITY_MINIMUM`、`SOFT_CAP_OVERRIDDEN`、`HARD_CAP_APPLIED` 與 `PLAN_INFEASIBLE`。

若同日重算：

- 必須沿用相同的 `plan_date` 與 21:00 cutoff。
- 必須建立新 `snapshot_id` 與新 revision，除非輸入快照完全相同且只是重新輸出相同結果。
- 舊 revision 保留，並由新 revision 的 `supersedes_revision_id` 指向。
- 同一 `decision_id` 必須形成單一、無循環的 revision chain；未被其他 revision 取代的唯一末端就是 current revision。
- 已有成交不會改寫原建議；只會影響新 revision 的 `portfolio_input` 與 `remaining_to_execute_today`。

## 7. ExecutionEvent

一天可以有零到多筆實際成交。每筆買入獨立保存：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `schema_version` | string | 固定 `execution.v1` |
| `execution_id` | string | 唯一且不可重用 |
| `operation_id` | string | 同一 command 產生的事件共用 ID；correction 的 reversal／replacement 必須相同 |
| `event_type` | enum | `purchase`、`reversal`、`day_close` |
| `plan_date` | date | 歸屬的 DCA 日期 |
| `decision_revision_id` | string/null | 對應建議；歷史補登可為 null |
| `executed_at` | timestamp | 實際成交時間；手動回報預設等於 `recorded_at` |
| `recorded_at` | timestamp | 寫入 Journal 時間 |
| `usd_amount` | USD/null | purchase 的總現金投入成本，包含未拆分的手續費；day_close 為 null |
| `btc_quantity` | BTC/null | purchase 實際收到的淨 BTC；day_close 為 null |
| `venue` | string | 交易場所；手動回報未提供時預設 `unknown` |
| `external_reference` | string/null | 外部成交 ID，不放憑證 |
| `reverses_execution_id` | string/null | reversal 必填 |
| `source` | enum | `manual`、`imported`、`integration` |
| `close_reason` | enum/null | day_close 使用：`skipped`、`completed_for_day` |
| `note` | string/null | 人工備註 |

規則：

- `purchase` 的 USD 與 BTC 都必須大於 0。
- 使用者手動新增 purchase 時只需提供 `usd_amount` 與 `btc_quantity`。`executed_at` 預設使用回報的 `recorded_at`；`source` 預設 `manual`，`venue` 預設 `unknown`。
- v1 不另外追蹤手續費。`usd_amount` 表示實際支付的全部 USD，`btc_quantity` 表示扣除任何 BTC fee 後實際收到的淨 BTC。因此衍生有效成本價固定為 `usd_amount / btc_quantity`，已自然反映費用造成的成本影響。
- 修改錯誤成交時，先追加 `reversal` 指向原 event，再追加正確的 replacement `purchase`。
- `reversal` 不得被再次 reversal；同一 purchase 最多一筆有效 reversal。
- `day_close` 表示使用者明確結束當日等待：沒有成交時可標記 `skipped`，已有部分或完整成交時可標記 `completed_for_day`。它不包含金額，也不影響 PortfolioState。
- 同一 `plan_date` 若有多筆 day_close，以最後一筆有效事件作當日人工結束狀態；若其後追加 purchase，執行狀態仍由最新成交總額重新推導。
- 歷史補登使用實際成交日作 `plan_date`，並以 `source=imported` 標記，不得假裝是當時已存在的系統建議。

## 8. WeeklyTargetSnapshot

每週第一個有效投資日在決策前建立，建立後不可因後續成交修改：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `schema_version` | string | 固定 `weekly_target.v1` |
| `weekly_target_id` | string | 唯一 ID |
| `operation_id` | string | 產生此紀錄的本機 command operation ID |
| `weekly_target_key` | string | 同一計畫週各 revision 共用的穩定 key |
| `revision` | integer | 從 1 起遞增 |
| `supersedes_revision_id` | string/null | 被本次資料修正取代的 revision |
| `week_start` / `week_end` | date | Asia/Taipei 週界；計畫首尾週可截短 |
| `created_for_plan_date` | date | 建立目標的投資日 |
| `created_at` | timestamp | 建立時間 |
| `config_version` | string | 使用的 Config 版本 |
| `remaining_funds_at_week_start_usd` | USD | 週開始實際剩餘資金 |
| `active_days_in_week` | integer | 本週有效投資日數 |
| `total_days_remaining` | integer | 含建立日 |
| `weekly_target_usd` | USD | 週名目目標 |
| `weekly_min_ratio` | decimal | 當週固定比例 |
| `weekly_min_usd` | USD | 最低進度目標 |
| `weekly_soft_max_usd` | USD | soft cap |
| `weekly_hard_max_usd` | USD | hard cap |

若資料錯誤需要修正，使用同一週的穩定 key 建立帶 `revision` 與 `supersedes_revision_id` 的新紀錄並保留原紀錄；current target 同樣由無循環 revision chain 的唯一末端推導。不得因市場變化在週中重設目標。

## 9. PortfolioState（衍生）

`PortfolioState` 不作獨立 canonical source。它在指定 `as_of` 時間由未被 reversal 的 purchase 推導：

```text
actual_invested_usd = sum(purchase.usd_amount)
total_btc = sum(purchase.btc_quantity)
remaining_funds_usd = max(0, initial_budget - actual_invested_usd)
average_cost_usd = actual_invested_usd / total_btc
```

- Budget Guard 使用包含未拆分費用的 `actual_invested_usd`，因為它代表 10,000 USD 計畫預算的實際現金流出。
- `average_cost_usd` 使用總現金投入除以實際收到的淨 BTC，因此是包含費用效果的有效平均成本；v1 不提供獨立 fee 分析。
- 若有效投入超過初始預算，資料狀態為 `invalid`，不得把剩餘資金靜默截成正常完成狀態。
- `actual_invested_today` 與 `actual_invested_this_week` 依 `plan_date` 聚合。

## 10. Daily Journal 衍生狀態

每日執行狀態由目前有效決策與成交事件推導：

| 狀態 | 條件 |
|---|---|
| `no_decision` | 尚無當日決策 |
| `blocked` | 當日有效決策為 blocked |
| `pending` | 有可執行建議、實際投入為 0，且沒有 skipped day_close |
| `skipped` | 實際投入為 0，且使用者以 day_close 明確標記 skipped |
| `partially_executed` | `0 < actual < final_suggested` |
| `executed` | 實際投入等於建議，依 0.01 USD 比較 |
| `over_executed` | 實際投入高於建議 |
| `completed` | 計畫剩餘資金為 0 且資料有效 |

`skipped` 不是由金額自動推導的狀態；只有使用者追加 `day_close(close_reason=skipped)` 且實際投入仍為 0 時才成立。未回報不得自動視為 skipped。

## 11. 報表契約

### 11.1 Daily Journal

每日 Journal 必須顯示當前有效決策，同時列出 revision 數量、實際成交明細、執行偏差和期末 PortfolioState。模板見 `templates/DAILY_JOURNAL.md`。

### 11.2 Weekly Report

使用 Asia/Taipei 週期，至少包含週目標快照、每日建議與實際投入、狀態分布、累積偏差、期末剩餘預算及下週可行性。模板見 `templates/WEEKLY_REPORT.md`。

### 11.3 Monthly Report

以日曆月及計畫日期交集為範圍，至少包含實際投入、BTC 數量、成交均價、建議遵循度、資料品質、Config 使用情況及期末容量狀態。模板見 `templates/MONTHLY_REPORT.md`。

報表必須保存：

- `generated_at`
- 資料範圍
- 使用的最新 execution event ID 或資料水位
- 所含 Config versions
- 是否存在 pending、blocked、invalid 或 plan_infeasible 狀態

同一資料水位與同一模板版本應產生相同報表內容。

## 12. 驗證規則

Stage 3 後續實作至少驗證：

1. 所有必要欄位存在，schema version 可辨識。
2. ID 唯一且引用存在。
3. 同一 decision 的 revision chain 無循環且只有一個未被取代的末端。
4. 同一週的 weekly target revision chain 無循環且只有一個未被取代的末端。
5. Decimal 字串格式、非負限制與精度正確；purchase 的 USD 與 BTC 都大於 0。
6. `observed_at <= cutoff_at` 且 `available_at <= calculated_at`。
7. blocked 決策的 `final_suggested_usd` 必須為 null。
8. 非 blocked 決策的 final amount 不超過該 revision 保存的 remaining funds、daily hard capacity 或 weekly hard capacity。
9. reversal 只引用既有 purchase，且金額與數量相符；day_close 不可包含成交金額或數量。
10. PortfolioState 可完全由 execution events 重建。
11. 報表不得改寫 canonical 資料。

## 13. 保留與隱私

- Canonical Journal 應保留完整計畫期間及其後的稽核需求，不因產生報表而刪除。
- Repository 只提交模型、模板及無敏感資訊的範例；真實成交資料預設不提交 Git。
- 未來若同步 Google Sheets、交易所或 Dashboard，canonical ownership 與衝突處理必須在 Stage 4 另行核准。
- 備份、加密、存取控制與災難復原屬於 Stage 4 Operations，不在本階段實作。
