# Bitcoin Smart DCA Local MVP Integrations

## 1. 文件狀態

- 階段：Stage 4A Accepted（2026-08-11）
- 日期：2026-08-11
- 範圍：本機手動 MVP 的唯讀市場資料 Adapter
- 非範圍：排程、通知、Dashboard、Google Sheets、交易所帳戶及自動下單
- Runtime 狀態：Gate 4A-3 Accepted／Implemented（2026-08-11）

本文件把 Stage 2.1 已核准的 canonical data sources 對應到本機 MVP 的外部讀取契約。所有策略公式、品質狀態與新鮮度仍以 `SPEC.md`、`CONFIG.md` 及 `docs/DATA_MODEL.md` 為準。

## 2. MVP 整合總覽

| 資料 | Provider | 存取 | MVP 角色 | 失敗行為 |
|---|---|---|---|---|
| BTC 5m／1d OHLCV | Coinbase Exchange | 公開 REST GET | canonical reference、recent high、ATR、daily drop | `blocked` |
| Fear & Greed | Alternative.me | 公開 REST GET | sentiment group | `degraded`；依有效方向群組重新正規化 |
| BVIV 60m | Volmex | REST GET；可能需要 API key | v1 非方向性 modifier primary | 嘗試 fixing fallback |
| BVIVF daily fixing | Volmex | REST GET；公開能力依供應方案 | BVIV fallback | modifier 1.0 並 `degraded` |
| Portfolio | Local JSONL Journal | 本機唯讀重建 | remaining funds 與進度 | `blocked` |

MVP 只能讀取公開市場資料，不能呼叫任何下單、帳戶、資產轉移或交易所私有端點。

## 3. 共用 Adapter 契約

每個 Provider Adapter 必須回傳標準化結果，不能把供應商原始 response 直接傳入 Decision Engine：

```text
ProviderResult
├── provider
├── request_descriptor
├── fetched_at
├── observations[]
├── quality_status
├── fallback_used
└── error_codes[]
```

規則：

1. `request_descriptor` 保存 endpoint 名稱、非敏感 query、HTTP status 與 response hash；不得保存 API key、完整含密鑰 URL 或 Authorization header。
2. 數值先以字串解析成 Decimal，不使用 binary float 參與策略計算。
3. 外部 timestamp 必須轉為帶 timezone 的時間，原始 timestamp 同時保留。
4. response 為空、格式錯誤、時間不符、重複 bucket 衝突或超出合理範圍時標記 `invalid`，不得補零。
5. Adapter 只負責取得與正規化資料；不能計算 DCA 金額或繞過 Budget Guard。
6. 相同 Provider response 和 cutoff 必須產生相同標準化結果。

## 4. Coinbase Exchange Adapter

### 4.1 官方能力

MVP 使用 Coinbase Exchange 公開 market data REST endpoint：

```text
GET https://api.exchange.coinbase.com/products/BTC-USD/candles
```

官方 candles 支援 `300` 秒（5 分鐘）及 `86400` 秒（日線）granularity，單次最多回傳 300 根；回應順序不可假設，且無成交的 interval 可能沒有資料。官方文件：

- https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles
- https://docs.cdp.coinbase.com/exchange/introduction/welcome

### 4.2 21:00 reference price

台北 21:00 等於 UTC 13:00。當日 reference candle 必須是：

```text
bucket start = 12:55:00 UTC
bucket end   = 13:00:00 UTC
reference    = candle.close
```

Request 必須傳入明確 `start`、`end` 與 `granularity=300`。Adapter 必須按 bucket timestamp 尋找完全匹配的 candle，不得取 response 陣列第一筆、最後一筆或 cutoff 後的 candle。

Coinbase response timestamp 代表 bucket start；normalized record 必須同時保存 `bucket_start=12:55`、`bucket_end=13:00`，並以 bucket end 作 close 的 `observed_at`。

Previous reference 使用前一個計畫日相同 cutoff 的 5m close。第一個計畫日或本機 Journal 尚無前日快照時，由 Coinbase 歷史 candles 讀取；不得使用另一交易所補值。

Reference validation：

- product 固定 `BTC-USD`。
- close 必須大於 0。
- candle end 必須等於 cutoff。
- cutoff 與 fetched time 的新鮮度依 `CONFIG.md` 驗證。
- 缺少精確 bucket 時為 `missing`，一般決策 `blocked`。

### 4.3 UTC 日線

日線使用 `granularity=86400` 且固定 UTC 00:00 邊界。只接受 `bucket_end <= cutoff_at` 的完整 candle；當日尚未完成的 UTC 日線必須排除。

MVP 一次請求足以容納計算 90 日近期高點及 ATR(14) 所需資料，但仍必須：

- 取得至少 91 根連續、已完成的日線，讓 ATR true range 有前一日 close。
- 按 timestamp 升冪排序並檢查重複。
- 對缺口明確報錯，不用前值填補 OHLC。
- 將實際參與 recent-high 與 ATR 計算的 normalized candles 保存進 MarketSnapshot。

Coinbase 官方提醒歷史 candle 可能不完整，因此「HTTP 200」不等於資料有效。

## 5. Alternative.me Fear & Greed Adapter

### 5.1 Endpoint

```text
GET https://api.alternative.me/fng/?limit=2&format=json
```

官方文件說明 `value` 為 0～100，`timestamp` 預設為 Unix time，且資料為每日更新。MVP 取兩筆是為了在最新值時間晚於 cutoff 或格式異常時仍能檢查前一筆。官方文件：

- https://alternative.me/crypto/fear-and-greed-index/

### 5.2 選值與歸因

- 將每筆 timestamp 轉為 UTC，再選 `observed_at <= cutoff_at` 的最新值。
- value 必須是 0～100 的整數。
- 最大年齡為 `CONFIG.md` 的 36 小時。
- API 不提供可靠的實際 publish timestamp 時，MVP 保守地把 `available_at` 記為本次 `fetched_at`，並保留原始 observed timestamp。
- Daily／Weekly／Monthly 對外顯示 Fear & Greed 時必須標示來源為 Alternative.me。
- 缺失或 stale 不得用 0 代替；方向群組依 `SPEC.md` 降級。

## 6. Volmex BVIV Adapter

### 6.1 Endpoint 與憑證

MVP 使用：

```text
GET https://rest-v1.volmex.finance/v2/history
```

官方 history contract 使用 `symbol`、`resolution`、`from`、`to`，並可帶 `apikey`。官方方案頁顯示 public/free access 支援 daily 與 60-minute，但實際權限及 rate limit 仍以執行時 response 為準：

- https://rest-v1.volmex.finance/api
- https://volmex.finance/data
- https://volmex.finance/pricing

API key 只允許由環境變數 `VOLMEX_API_KEY` 讀取。它不可寫入 Config、命令列參數、log、MarketSnapshot、Journal 或 Git。因 API key 可能位於 query string，HTTP log 必須遮蔽 `apikey`。

### 6.2 Primary：BVIV 60m

```text
symbol=BVIV
resolution=60
```

- 選擇截止前最後一個完整 60 分鐘 bucket。
- bucket end 必須 `<= cutoff_at`。
- 最大年齡為 2 小時。
- value 必須大於 0。
- 合格時 `fallback_used=false`。

### 6.3 Fallback：BVIVF fixing

Primary missing、stale、invalid 或未授權時，MVP 查詢：

```text
symbol=BVIVF
resolution=D
```

`BVIVF` 是約紐約時間 16:00 的每日 fixing；對台北 21:00 cutoff，應選截止前最近一筆已完成 fixing。最大年齡為 36 小時，並標記 `fallback_used=true`。官方 fixing 方法：

- https://volmex.finance/papers/BVIV-Fixing-Indices-Paper.pdf

MVP 固定使用 `BVIVF`，不在同一版本中混用 `BVIVFL`。若未來要改 fixing variant，必須更新 Config 版本與 ADR。

### 6.4 全部不可用

Primary 與 fallback 都不可用時：

- `bviv.value=null`
- `quality_status=missing` 或實際錯誤品質
- `bviv_modifier=1.0`
- 決策狀態至少為 `degraded`
- reason code 包含 `BVIV_NEUTRAL_MISSING`

BVIV 缺失不能阻擋 BTC 核心決策，也不能被解讀為低波動。

## 7. HTTP 與重試政策

本機手動 MVP 的每個 Provider request：

- connect/read timeout：10 秒。
- 最多 3 次 attempts。
- retry delays：1 秒、3 秒。
- 只重試 timeout、connection error、HTTP 429 與 HTTP 5xx。
- HTTP 4xx 除 429 外不重試。
- 429 若有合理的 `Retry-After`，可等待但單次不超過 30 秒。
- 每次 attempt 記錄 provider、時間、結果與已遮蔽的 error；不保存 response 中的秘密。

上述是 Stage 4A 營運草案值，不是策略參數；實作時仍須集中放入 versioned runtime config，不得散落於 Adapter。

## 8. 禁止的 fallback

MVP 不允許：

- Coinbase 自動切換 Kraken、CoinGecko、TradingView 或其他交易所。
- 用目前 ticker 取代缺失的 cutoff 5m close。
- 用 cutoff 後資料補當日缺口。
- 人工輸入 BTC price、Fear & Greed 或 BVIV 後冒充官方 Provider response。
- 將缺失指標寫為 0。
- 因 API 失敗而沿用未通過新鮮度檢查的昨日值。

測試 fixture 可以使用人工資料，但必須明確標記 `source=test_fixture`，且不能寫入正式 Journal。

## 9. 實作前驗證事項

Provider runtime 另行授權後，實作至少建立：

1. 正常 response fixture。
2. 空 response、缺 bucket、重複 bucket及亂序 response fixture。
3. cutoff 邊界與 cutoff 後資料排除測試。
4. stale、timeout、429、4xx 與 5xx 測試。
5. Volmex 無 key、無權限、primary 成功、BVIVF fallback 及全部缺失測試。
6. 確認任何 error、snapshot 與 command output 都不洩漏 `VOLMEX_API_KEY`。
