# Bitcoin Smart DCA Engine Specification

## 1. 文件狀態

- 規格版本：`1.0-draft.1`
- 狀態：Stage 2.1 設計已核准；數值參數仍為待回測的草案預設值
- 適用期間：2026-08-01 至 2026-10-03
- 決策時區：Asia/Taipei

本文件定義可人工重算、可測試的 Smart DCA 行為。所有可調數值集中於 [`CONFIG.md`](CONFIG.md)。本階段仍是設計文件，不是投資建議或程式實作。

## 2. 設計目標

- 每日維持基礎市場曝險，但不得繞過資金硬限制。
- 市場較便宜、恐慌或出現向下衝擊時增加投入。
- 避免同一場下跌被多個高度相關因子重複計權。
- BVIV 只描述波動大小，不單獨提供買入方向。
- 以週目標、每日進度與全期容量檢查，避免把資金堆到最終日。
- 每次建議都可由市場快照、Config 版本與原因重現。
- 系統只產生建議；實際成交失敗時不得宣稱計畫完成。

## 3. 投資期間與資金

| 項目 | 值 |
|---|---:|
| 計畫資金 | 10,000 USD |
| 投資期間 | 2026-08-01 至 2026-10-03 |
| 投資日數 | 64 個日曆日 |
| Base DCA | 80 USD/day |
| Base Budget | 5,120 USD |
| Adaptive Reserve | 4,880 USD |
| 名目每日 Adaptive 配額 | 76.25 USD |

剩餘資金、週額度、進度與平均成本一律以「實際投入」計算，不以未執行的建議計算。

## 4. 決策時間與禁止偷看未來

- 每日資料截止時間：`21:00:00 Asia/Taipei`，即 `13:00:00 UTC`。
- 系統可在截止後短暫等待完整資料，目標於 21:05 前產生通知；正式排程與重試留待第 4 階段。
- 只有 `observed_at <= cutoff_at` 且 `available_at <= calculation_at` 的資料可以進入決策。
- 同日重算仍使用相同 cutoff，不得加入 21:00 之後的市場資訊。
- 每份輸入必須保存 `source`、`symbol`、`value`、`interval`、`observed_at`、`available_at`、`fetched_at`、`timezone`、`stale_after`、`quality_status` 與 `fallback_used`。

## 5. Canonical 資料來源

### 5.1 BTC 行情

- Primary provider：Coinbase Exchange public market data。
- Product：`BTC-USD`。
- Reference price：截止於 21:00 的最後一根完整 5 分鐘 candle close。
- Previous reference price：前一個決策日相同截止時間的 reference price。
- 日線 OHLC：Coinbase `BTC-USD`、UTC 00:00 邊界、只使用截止時間前已完成的日線。
- 近期高點與 ATR 必須使用同一套日線，不得混入其他交易所。
- 價格快照最大允許年齡：10 分鐘。
- v1.0 不自動切換交易所；Primary 不可用時標記 `blocked`。加入 Kraken、CoinGecko 或 TradingView 備援前，必須另立 Config 版本與決策紀錄。

### 5.2 Fear & Greed

- Provider：Alternative.me Crypto Fear & Greed API。
- 使用截止時間前最新已發布值。
- 最大允許年齡：36 小時。
- 顯示或對外輸出時保留來源標示。

### 5.3 BVIV

- Provider：Volmex BVIV（Bitcoin 30-day implied volatility）。
- Primary：截止時間前最後一個完整 60 分鐘值，最大允許年齡 2 小時。
- Fallback：最近一個已完成的官方 BVIV fixing，最大允許年齡 36 小時，並標記 `fallback_used=true`。
- 若兩者皆不可用，BVIV modifier 固定為 1.0，狀態標記 `degraded`；不得把缺失值當成低波動。

### 5.4 投資組合

- Canonical source：本專案的實際成交 Journal；格式在第 3 階段定義。
- Google Sheets 未經未來整合 Review 前，只能作檢視或同步副本，不能覆寫 canonical actual investment。
- 剩餘資金狀態無效時標記 `blocked`。

## 6. 共用函數

```text
clamp(x, lower, upper) = min(max(x, lower), upper)
linear_score(x, low, high) = clamp((x - low) / (high - low), 0, 1)
floor_to_cent(x) = floor(x × 100) / 100
ceil_to_cent(x) = ceil(x × 100) / 100
```

內部計算保留完整精度。一般最終輸出向下截斷至 0.01 USD，避免超支；最低必要投入向上取至 0.01 USD，避免因精度損失使計畫失去可行性。

## 7. 方向性因子

三個方向群組各產生 `0～1` 分數，越高越支持加碼。

### 7.1 價格位置：45%

近期高點使用過去 90 個已完成 UTC 日線的最高價。

```text
drawdown_pct = max(0, (recent_high - reference_price) / recent_high × 100)
location_score = linear_score(drawdown_pct, 5, 30)
```

- 回檔不超過 5%：0 分。
- 回檔介於 5%～30%：線性增加。
- 回檔達 30%：1 分。

### 7.2 市場情緒：25%

```text
sentiment_score = clamp((60 - fear_greed_value) / (60 - 10), 0, 1)
```

- Fear & Greed 達 60 以上：0 分。
- 介於 10～60：越恐慌分數越高。
- 達 10 以下：1 分。

### 7.3 下跌衝擊：30%

ATR 使用 Coinbase `BTC-USD` 最近 14 根已完成 UTC 日線，以 Wilder RMA 計算。

```text
daily_drop_pct = max(0, (previous_reference_price - reference_price)
                        / previous_reference_price × 100)
atr_pct = ATR(14) / previous_reference_price × 100
down_atr_multiple = daily_drop_pct / atr_pct

atr_drop_score = linear_score(down_atr_multiple, 0.5, 2.0)
absolute_drop_score = linear_score(daily_drop_pct, 2, 10)
shock_score = max(atr_drop_score, absolute_drop_score)
```

ATR 與單日跌幅描述同一場向下衝擊，因此只取較強者，不相加。價格沒有下跌時兩者皆為 0。ATR 不存在或不大於 0 時，只使用有效的絕對跌幅分數並標記降級。

### 7.4 方向性綜合分數

```text
directional_score =
    0.45 × location_score
  + 0.25 × sentiment_score
  + 0.30 × shock_score
```

若部分方向因子缺失：

- BTC reference price 或資金狀態無效：`blocked`，不產生一般建議。
- 3 個方向群組皆有效：`normal`。
- 2 個有效：按有效權重重新正規化，狀態 `degraded`。
- 少於 2 個有效：不計算 Adaptive，狀態 `base_only`。
- 缺失因子不得以 0 分代替。

## 8. BVIV 只作波動調節

BVIV 不加入方向性分數。先正規化波動：

```text
bviv_level = linear_score(bviv_value, 50, 100)
downside_gate =
    daily_drop_pct > 0
    OR drawdown_pct >= 5
    OR fear_greed_value <= 40
```

v1.0 採保守調節：

```text
if BVIV invalid:
    bviv_modifier = 1.0
else if downside_gate:
    bviv_modifier = 1.0
else:
    bviv_modifier = 1.0 - 0.10 × bviv_level
```

因此：

- 高 BVIV 本身不會增加投入。
- 已有回檔、恐慌或下跌訊號時，BVIV 不放大也不削弱方向訊號。
- 高 BVIV 但沒有便宜／下跌訊號時，Adaptive 金額最多降低 10%。
- 未來若要允許 BVIV 放大加碼，必須以回測結果另立決策，不直接修改 v1.0。

## 9. 市場建議金額

```text
adaptive_multiplier = 2 × directional_score
market_adaptive_amount = 76.25 × adaptive_multiplier × bviv_modifier
market_amount = base_dca + market_adaptive_amount
```

在 BVIV modifier 為 1 時：

- 分數 0：80.00 USD。
- 分數 0.5：156.25 USD。
- 分數 1：232.50 USD。

## 10. 資金進度與每週目標

### 10.1 週期

- 週期為 Asia/Taipei 星期一 00:00 至星期日 23:59:59。
- 計畫第一週與最後一週即使不滿七天，仍按實際投資日數建立週目標。
- 週投入以實際成交計算。

### 10.2 週目標快照

每週第一個投資日，在當日決策前建立不可變的週目標：

```text
weekly_target =
    remaining_funds_at_week_start
    × active_days_in_this_week
    / total_days_remaining_at_week_start
```

期限緊迫度：

```text
urgency = clamp((21 - days_remaining) / (21 - 7), 0, 1)
weekly_min_ratio = 0.80 + 0.20 × urgency
weekly_soft_max_ratio = 1.30

weekly_min = weekly_target × weekly_min_ratio
weekly_soft_max = min(weekly_target × 1.30, weekly_hard_max)
```

- 剩餘 21 天以上：至少完成週目標 80%。
- 剩餘 20～8 天：週最低比例逐步由 80% 增至 100%。
- 剩餘 7 天內：週最低目標為 100%。
- 市場訊號可提前投入至週 soft max，但不可突破週 hard max。

### 10.3 每日進度底線

```text
required_daily_pace = remaining_funds / days_remaining
pace_floor = required_daily_pace × weekly_min_ratio

weekly_gap = max(0, weekly_min - actual_invested_this_week)
weekly_catchup = weekly_gap / active_days_remaining_in_week

progress_candidate = max(market_amount, pace_floor, weekly_catchup)
```

如此市場昂貴時仍可接近最低進度，便宜時則由市場訊號提高投入。

## 11. 全期容量檢查

### 11.1 變數

每天在產生建議前，依日曆把今天到結束日分成週 bucket：

```text
R = 今日決策前的 remaining_funds
D = daily_hard_max
W = weekly_hard_max - actual_invested_this_week
n = 今天之後、本週剩餘投資日數
F = 下週起至結束日的總 hard capacity
```

每個未來週 bucket 的最大容量為：

```text
week_capacity = min(
    active_days_in_bucket × daily_hard_max,
    weekly_hard_remaining_for_bucket
)
```

`F` 是下週起所有未來週 bucket 容量的總和。當前週的 `W` 必須扣除本週已實際投入；未來完整週使用完整 `weekly_hard_max`。

### 11.2 包含今天的可行性檢查

```text
current_week_capacity_including_today = min((n + 1) × D, W)
total_capacity_including_today = current_week_capacity_including_today + F
```

```text
if R > total_capacity_including_today:
    status = plan_infeasible
```

`plan_infeasible` 表示即使今天開始使用所有 hard capacity，也無法在期限內完成。系統仍可建議當日允許的最大合理金額並發出人工警告，但不得自動提高 hard caps。Config、計畫日期或 hard caps 改變時，必須重新執行容量檢查。

### 11.3 今日最低必要投入

若計畫仍可行，今天之後的本週容量為：

```text
current_week_future_capacity = min(n × D, W)
```

今日最低必要投入為：

```text
minimum_required_today = ceil_to_cent(max(
    0,
    R - current_week_future_capacity - F
))
```

此數值回答：「若今天投入少於多少，未來即使完全使用每日與每週 hard capacity，也無法完成計畫？」它是硬性可行性底線，不是市場評分，也不取代正常的 pace floor 或 weekly catchup。

若 `minimum_required_today` 超過今日可用 hard capacity：

```text
today_hard_capacity = min(R, D, W)
```

則狀態必須是 `plan_infeasible`。最低必要投入採向上取至 0.01 USD，避免向下截斷造成容量缺口。

## 12. Budget Guard

### 12.1 一般日

```text
weekly_hard_remaining = max(0, weekly_hard_max - actual_invested_this_week)
weekly_soft_remaining = max(0, weekly_soft_max - actual_invested_this_week)

if minimum_required_today > weekly_soft_remaining:
    effective_weekly_soft_remaining = min(
        minimum_required_today,
        weekly_hard_remaining
    )
    soft_cap_overridden_for_feasibility = true
else:
    effective_weekly_soft_remaining = weekly_soft_remaining
    soft_cap_overridden_for_feasibility = false

guard_candidate = max(
    market_amount,
    pace_floor,
    weekly_catchup,
    minimum_required_today
)

final_amount = floor_to_cent(min(
    guard_candidate,
    remaining_funds,
    daily_hard_max,
    weekly_hard_remaining,
    effective_weekly_soft_remaining
))
```

必須先計算 `effective_weekly_soft_remaining`，再計算 `final_amount`；不得先使用原始 weekly soft cap 截斷結果。若 `minimum_required_today` 大於 `weekly_hard_remaining`，前一節的容量檢查必須已將狀態標記為 `plan_infeasible`。任何情況都不得自動突破 daily hard max、weekly hard max 或 remaining funds。

### 12.2 最終日

```text
final_amount = floor_to_cent(min(
    remaining_funds,
    daily_hard_max,
    weekly_hard_remaining
))
```

最終日不再自動覆寫每日或每週硬上限。

- 若剩餘資金在容量內，建議投入剩餘資金。
- 若剩餘資金超出容量，狀態為 `plan_infeasible`，通知使用者人工決定是否調整計畫。
- 系統不得為了滿足日期目標而靜默破壞風險限制。

### 12.3 已用完資金

剩餘資金小於或等於 0 時，建議為 0，狀態 `completed`。

## 13. 同日重算與實際投入

- 每個日期只有一份目前有效建議，但修訂歷史不得刪除。
- 同日重算沿用 21:00 cutoff，不加入截止後資料。
- 已部分成交時：`remaining_to_execute_today = max(0, final_amount - actual_invested_today)`。
- 實際投入超過建議時，保留原建議並記錄執行偏差。
- 建議不等於成交；所有進度只由 actual investment 更新。

## 14. 決策狀態

| 狀態 | 意義 | 金額建議 |
|---|---|---|
| `normal` | 三個方向群組有效 | 是 |
| `degraded` | 兩個方向群組有效或 BVIV 採 fallback／缺失 | 是 |
| `base_only` | 少於兩個方向群組有效 | Base 與進度規則 |
| `blocked` | BTC reference price 或資金狀態無效 | 否 |
| `plan_infeasible` | 剩餘資金超過未來硬容量 | 允許容量內建議並警告 |
| `completed` | 剩餘資金為 0 | 0 USD |

## 15. 每日解釋要求

每日輸出至少包含：

- 決策 cutoff 與計算時間
- 各資料來源、觀察時間、新鮮度及 fallback 狀態
- BTC reference price、Fear & Greed、BVIV、ATR
- location、sentiment、ATR drop、absolute drop、shock 與 directional 分數
- BVIV modifier 與 downside gate
- Base、Adaptive、market amount
- pace floor、weekly target、weekly catchup
- minimum required today、包含今日的總容量與可行性狀態
- 每日／每週 hard capacity 及是否覆寫 soft cap
- 最終建議、累積實際投入、剩餘資金與 Config 版本

## 16. 驗收情境

### 16.1 重複下跌訊號

若 `atr_drop_score=0.8`、`absolute_drop_score=0.6`：

```text
shock_score = max(0.8, 0.6) = 0.8
```

不得把兩者相加成 1.4，也不得當成兩個獨立權重。

### 16.2 高 BVIV、價格接近高點

若 `bviv_level=1` 且 downside gate 為 false：

```text
bviv_modifier = 0.90
```

高波動不會成為額外買入方向。

### 16.3 週進度落後

若週最低目標尚差 600 USD、剩餘 3 個投資日：

```text
weekly_catchup = 600 / 3 = 200 USD/day
```

候選金額至少為 200 USD，再通過 hard caps。

### 16.4 容量不足

若剩餘資金為 2,500 USD，但包含今天的未來總硬容量只有 2,000 USD：

```text
status = plan_infeasible
```

系統不得自動提高硬上限 500 USD。

### 16.5 今日最低必要投入

若：

```text
R = 2,300
D = 500
W = 1,500
n = 2
F = 1,000
```

則：

```text
current_week_future_capacity = min(2 × 500, 1,500) = 1,000
minimum_required_today = 2,300 - 1,000 - 1,000 = 300 USD
```

今日若投入少於 300 USD，未來 hard capacity 將不足。

### 16.6 最終日

若剩餘資金 450 USD，日／週剩餘容量皆足夠，建議 450 USD。若剩餘 900 USD 但每日硬上限為 500 USD，建議最多 500 USD 並標記 `plan_infeasible`。

## 17. Stage 2.1 核准範圍與待回測參數

以下架構與規則已核准：方向因子分組、BVIV 非方向性限制、canonical 資料契約、週／全期容量檢查、`minimum_required_today`，以及最終日不得自動突破 hard caps。

以下數值是實作起始用的草案預設值，不代表已由歷史回測或實盤證實有效：

- 方向群組權重 45%／25%／30%
- ATR 與絕對跌幅取 `max`
- BVIV 只抑制、不放大，modifier 範圍 0.90～1.00
- 週最低比例由 80% 漸增至 100%，soft max 為 130%
- 每日 hard max 500 USD、每週 hard max 2,000 USD

Fear & Greed 與其他壓力因子的剩餘相關性，以及上述數值的敏感度，留待後續回測確認；這不改變 Stage 2.1 的核准狀態。
