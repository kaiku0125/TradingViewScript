# Bitcoin Smart DCA Local Operations

## 1. 文件狀態

- 階段：Stage 4A Accepted；Stage 4B scheduler／Telegram subset authorized（2026-08-11）
- 日期：2026-08-11
- 執行模式：手動 CLI＋每日 21:00 Asia/Taipei Codex local automation
- 正式計畫：2026-08-12 至 2026-10-15，Asia/Taipei

本文件定義本機 runtime 的已核准操作與命令契約。Gate 4A-1～4A-4 與 Stage 4B 的 scheduler／Telegram 子集均已於 2026-08-11 授權實作。

## 2. MVP 成功條件

本機 MVP 必須能完成：

1. 21:00 cutoff 後手動抓取合格市場資料。
2. 建立不可變 MarketSnapshot。
3. 依固定 Config 計算訊號與 Budget Guard。
4. 保存 DecisionRecord 後輸出今日建議。
5. 只用 USD 與實收 BTC 登記一至多筆實際成交。
6. 從 execution events 重建剩餘預算、BTC 數量及有效平均成本。
7. 產生 Daily／Weekly／Monthly Markdown report。
8. 驗證全部 JSONL 與引用關係。
9. 由同一 workflow 在 21:00 保存 recommendation 後傳送 Telegram。

它不需要自建背景 daemon、GUI 或自動下單；排程由 Codex local automation 管理。

## 3. 建議 runtime 形態

Stage 4A runtime 基準：

- Python 3.11+。
- 核心金額使用 `decimal.Decimal`。
- 時區使用標準函式庫 `zoneinfo`。
- CLI 使用 `argparse`。
- JSONL、UUID、hash、檔案鎖及 HTTP 優先使用標準函式庫。
- 初版不引入資料庫、Web framework、Pandas 或排程框架。

單一入口為：

```bash
python3 --version  # 必須為 3.11+
python3 InvestmentEngine/bitcoin/dca.py <command>
```

Entry point 會拒絕 Python 3.10 以下版本，避免在未核准 runtime 上執行正式 Journal workflow。

本機安裝與隔離環境：

```bash
/opt/homebrew/bin/brew install python@3.11
/opt/homebrew/opt/python@3.11/bin/python3.11 -m venv InvestmentEngine/bitcoin/.venv
InvestmentEngine/bitcoin/.venv/bin/python --version
```

正式操作建議直接使用 `InvestmentEngine/bitcoin/.venv/bin/python`，不依賴 shell 的 `python3` 或 PATH。`.venv/` 為本機產物並已 Git ignored；Stage 4A 使用 standard library，不需要額外 `pip install`。

`dca.py` 只作薄 CLI；目前已接入 Config、Validator、Journal、Ledger、read-only Providers、pure Decision Engine、Budget Guard、`recommend` orchestration、Reporter、isolated rehearsal 與 `DailyWorkflowService`／Telegram notifier。

## 4. 預定本機檔案

```text
InvestmentEngine/bitcoin/
├── dca.py                         # 已實作 CLI entrypoint
├── config/                        # 已建立 versioned machine config
├── src/bitcoin_dca/               # Gate 4A-1～4A-4 runtime modules
├── data/
│   ├── market_snapshots.jsonl     # Git ignored
│   ├── decisions.jsonl            # Git ignored
│   ├── executions.jsonl           # Git ignored
│   ├── weekly_targets.jsonl        # Git ignored
│   └── .bitcoin_dca.lock           # Git ignored
└── reports/
    └── generated/                  # Git ignored
        ├── daily/
        ├── weekly/
        └── monthly/
```

Gate 4A-1 已建立 Journal core；Gate 4A-2 已建立 pure Indicators、Decision Engine、weekly capacity 與 Budget Guard；Gate 4A-3 已建立 Providers 與 `recommend` orchestration；Gate 4A-4 已建立 canonical-only Reporter 與 isolated rehearsal。

## 5. 每日手動流程

### 5.1 產生建議

狀態：Gate 4A-3 已核准並實作；Gate 4A-4 fixture rehearsal 已通過，live provider 首日操作留待 2026-08-12。

手動與排程共用：

```bash
InvestmentEngine/bitcoin/.venv/bin/python InvestmentEngine/bitcoin/dca.py recommend
InvestmentEngine/bitcoin/.venv/bin/python InvestmentEngine/bitcoin/dca.py run-daily
```

兩個命令均執行相同 `DailyWorkflowService`：先檢查 Telegram credentials，再建立 canonical recommendation，最後傳送相同結果。`run-daily` 是排程使用的明確 alias。手動操作仍建議約 21:05；若晚於 21:10 執行，仍使用同一個 21:00 cutoff，不加入 cutoff 後資料。

執行順序固定：

1. 取得 exclusive local lock；已有另一個寫入命令時立即停止。
2. 驗證 machine config 與四個 canonical JSONL。
3. 依 effective execution events 重建決策前 PortfolioState。
4. 如為當週第一個計畫日且尚無目標，建立 WeeklyTargetSnapshot。
5. 以當日 21:00 cutoff 讀取 Coinbase、Alternative.me 與 Volmex。
6. 建立並 fsync MarketSnapshot。
7. 計算 indicators、market amount、pacing、capacity 及 Budget Guard。
8. 建立並 fsync DecisionRecord。
9. 釋放 lock。
10. 將已保存 decision 的相同摘要傳送 Telegram。
11. 在 terminal 顯示摘要；報表由明確的 `report` 命令產生。

「先保存、後顯示」是固定順序，避免 terminal 顯示一個未寫入 Journal 的建議。

### 5.2 Telegram 設定測試

```bash
InvestmentEngine/bitcoin/.venv/bin/python InvestmentEngine/bitcoin/dca.py test-telegram
```

此命令只傳送一則非投資建議的設定測試，不呼叫 Provider、不寫 Journal。Secrets 位於 repository-root `.env.local`：

```text
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
VOLMEX_API_KEY=...  # optional
```

### 5.3 每日 21:00 排程

Codex local automation `smart-dca-21-00-telegram` 已啟用；它每日 21:00 Asia/Taipei 喚起，並只在 2026-08-12～2026-10-15 執行：

```bash
InvestmentEngine/bitcoin/.venv/bin/python InvestmentEngine/bitcoin/dca.py run-daily
```

Mac 必須保持開機、醒著、上網，且 repository／`.venv`／`.env.local` 保持可用。`.env.local` 本機權限應為 `0600`。Stage 4B 目前沒有 retry window 或 missed-run alarm；失敗時由 automation run 狀態供使用者檢查。

### 5.4 手動買入與登記

狀態：Gate 4A-1 已實作。

使用者自行在交易所完成買入；MVP 永遠不操作交易所。買入後輸入：

```bash
python3 InvestmentEngine/bitcoin/dca.py record-purchase \
  --usd 150.00 \
  --btc 0.00128500
```

使用者只輸入：

- 實際支付的總 USD。
- 實際收到的淨 BTC。

系統自動填入：

- `plan_date`：目前 Asia/Taipei 日期。
- `recorded_at`：命令執行時間。
- `executed_at`：預設等於 `recorded_at`。
- `source=manual`。
- `venue=unknown`。
- 目前有效 `decision_revision_id`。

命令必須先顯示即將追加的 USD、BTC、衍生有效成本價與 plan date，要求互動式 `yes` 確認。未來可提供 `--yes` 給明確的非互動呼叫，但不能作預設。

成功寫入後顯示累積投入、剩餘預算、累積 BTC 與有效平均成本。需要 Daily Journal 時再明確執行 `report daily`。

### 5.5 結束當日

狀態：Gate 4A-1 已實作。

沒有買入：

```bash
python3 InvestmentEngine/bitcoin/dca.py close-day --reason skipped
```

已有部分或完整買入並決定不再追加：

```bash
python3 InvestmentEngine/bitcoin/dca.py close-day --reason completed_for_day
```

未執行 `close-day` 不代表 skipped；狀態維持由成交與建議推導的 `pending` 或 `partially_executed`。

## 6. 其他命令契約

### 6.1 查看狀態

狀態：已實作 PortfolioState 與最新 canonical decision 摘要；完整 period view 由 `report` 提供。

```bash
python3 InvestmentEngine/bitcoin/dca.py status
```

唯讀輸出：目前計畫日、最新決策、今日實際投入、剩餘預算、累積 BTC、有效平均成本、本週目標與全期可行性。不得修改或補寫 Journal。

### 6.2 修正成交

狀態：Gate 4A-1 已實作。

```bash
python3 InvestmentEngine/bitcoin/dca.py correct-purchase \
  --execution-id <id> \
  --usd 180.00 \
  --btc 0.00154000
```

此命令在一次 lock 期間依序追加：

1. 指向原 purchase 的 reversal。
2. replacement purchase。

不得原地修改或刪除舊 JSONL 行。執行前顯示原值、新值及投資組合差異並要求確認。

### 6.3 驗證 Journal

狀態：Gate 4A-1 已實作 structural、revision、reference、execution、reversal 與 PortfolioState validation；Gate 4A-2 已加入 DecisionRecord numeric fields、BVIV 不放大與 final hard-cap invariants。

```bash
python3 InvestmentEngine/bitcoin/dca.py validate
```

唯讀執行 `DATA_MODEL.md` 的全部 schema、引用、revision、reversal、Decimal、cutoff、hard-cap 與 portfolio rebuild 驗證。任何 invalid 都以非零 exit code 結束。

### 6.4 產生報表

狀態：Gate 4A-4 已核准並實作。

```bash
python3 InvestmentEngine/bitcoin/dca.py report daily
python3 InvestmentEngine/bitcoin/dca.py report weekly
python3 InvestmentEngine/bitcoin/dca.py report monthly
python3 InvestmentEngine/bitcoin/dca.py report weekly --date 2026-08-12
python3 InvestmentEngine/bitcoin/dca.py report daily --stdout --date 2026-08-12
```

- Daily 預設目前 plan date。
- Weekly 預設包含目前日期的 Asia/Taipei 週。
- Monthly 預設目前日曆月與計畫期間交集。
- `--date YYYY-MM-DD` 可產生歷史衍生報表，但不建立或補造 recommendation。
- 預設寫入 `reports/generated/{daily,weekly,monthly}/`；`--stdout` 只輸出內容。
- 報表只能讀取 canonical JSONL，不呼叫 Provider。
- data watermark 保留 canonical append order 並排序 JSON object keys 後計算 SHA-256；`generated_at` 取最大 canonical event timestamp。
- 同一 data watermark 與 template version 產生 byte-identical 內容。

## 7. 日期與重算限制

### 7.1 今日 recommendation

- `recommend` 只允許目前 Asia/Taipei 日期。
- 21:00 前執行必須停止，不寫 snapshot 或 decision。
- Recommendation 可在當日 21:00 cutoff 後執行；晚於 21:10 仍建立當日 decision，但不得加入 cutoff 後資料。
- 同日重算仍沿用相同 21:00 cutoff。
- 同日重算沿用同一 cutoff，建立新的 snapshot 與 decision revision。

### 7.2 不補造歷史建議

MVP 不提供 backdated `recommend --date`。錯過某日就保留 `no_decision`，不能在隔天使用事後已知資料補造看似當時產生的建議。

若需要補登真實成交，只能在未來另行核准的 import workflow 中以 `source=imported` 保存；不得偽造 `decision_revision_id`。

## 8. Idempotency、鎖與故障恢復

### 8.1 Exclusive lock

- 所有 JSONL 寫入命令共用 `data/.bitcoin_dca.lock`。
- 取得不到 lock 時立即失敗，不等待另一程序。
- `status` 與 `validate` 可唯讀，但讀取時必須避免看到半行資料。

### 8.2 JSONL append

- 寫入前先在記憶體完成完整 record、schema validation 與 JSON serialization。
- 每個 record 以單一完整 UTF-8 line append，完成後 flush 與 fsync。
- 禁止 truncate 或 rewrite canonical JSONL。
- 每筆 command 產生 `operation_id`，寫入相關 record，供 crash recovery 及重跑識別。

### 8.3 recommend crash recovery

跨檔案無法形成單一 filesystem transaction，因此採可恢復的 dependency order：

```text
weekly target（若需要） → market snapshot → decision
```

若 crash 留下尚未被 DecisionRecord 引用的 snapshot，下一次 `recommend` 先比較 operation、cutoff、config 與 normalized payload：

- 完全相同：完成缺少的 DecisionRecord，不重複 snapshot。
- 任一不同：建立新 snapshot 與 revision；舊 orphan 保留並由 validate 報告 warning。

不得自動刪除 orphan record。

## 9. 錯誤與 exit code

| Exit code | 類型 | 是否寫入 |
|---:|---|---|
| `0` | 成功；包含 normal、degraded、base_only、completed | 依命令 |
| `2` | 決策 blocked 或 plan_infeasible 警示 | 保存 snapshot／decision 後輸出警示 |
| `3` | Config／Journal／schema invalid | 不新增策略或成交資料 |
| `4` | 操作輸入錯誤或使用者取消 | 不寫入 |
| `5` | lock／filesystem／fsync 錯誤 | 不宣稱成功；需 validate |
| `6` | 未分類 runtime error | 不宣稱成功；需 validate |

BTC 資料失敗會保存 blocked decision；Fear & Greed 或 BVIV 的允許降級則以 exit 0 完成，但 terminal 必須醒目列出 degraded 原因。

Telegram credentials 缺失會在 recommendation 前失敗且不新增 decision。若 decision 已 fsync 後 Telegram delivery 才失敗，canonical decision 保留，command 以非零結束；不得因重送通知而修改舊 record。

## 10. 第一日操作

2026-08-12 是計畫首日。首日 `recommend` 必須額外確認：

1. Config version 為預期版本且 65 天初始 hard capacity 可行。
2. 四個 canonical JSONL 不存在或為空；若已有資料必須先 validate。
3. PortfolioState 為投入 0、剩餘 10,000 USD、BTC 0。
4. 建立第一個 partial-week WeeklyTargetSnapshot。
5. 從 Coinbase 取得 8/11 21:00 的 previous reference。
6. 取得足夠已完成 UTC 日線計算 recent high 與 ATR。

任一必要條件不成立就停止或產生 blocked decision，不猜測首日基準。

正式首日前可執行隔離演練：

```bash
python3 InvestmentEngine/bitcoin/dca.py rehearse-first-day
```

此命令使用固定 provider fixtures、temporary Journal 與 temporary reports，完成 recommend → confirmed purchase → close-day → status／validate → Daily／Weekly／Monthly reports。它不連外、不讀寫正式 canonical datasets，結束前會比較正式 Journal 雜湊；temporary artifacts 隨命令結束移除。這不取代 2026-08-12 的 live provider 驗收。

## 11. 每日操作清單

```text
[ ] 系統時間與 Asia/Taipei 日期正確
[ ] 目前已達當日 21:00 cutoff，建議約 21:05 執行
[ ] 執行 recommend
[ ] 確認 Telegram 收到與 terminal 相同的 decision status／amount
[ ] 閱讀資料品質、原因、hard caps 與最終建議
[ ] 在交易所手動決定是否買入
[ ] 每筆成交執行 record-purchase（USD + BTC）
[ ] 完成後執行 close-day；沒回報就保留 pending
[ ] 執行 status 確認剩餘預算與平均成本
[ ] 執行 report daily；週末／月末再產生 weekly／monthly
```

## 12. MVP 操作邊界

- CLI 輸出是系統規則的計算結果，不代表交易已成交。
- 使用者仍自行決定是否買入及實際買入金額。
- MVP 不保存交易所帳密，不讀取交易所帳戶，也不送單。
- 任何手動編輯 JSONL 都屬於 unsupported operation；應使用 correction command。
- numeric strategy defaults 尚未經回測證實，輸出必須標示 `draft parameters`。
- 沒有備份是 Stage 3 已接受的取捨；本機檔案遺失時系統無法重建實際投資狀態。
