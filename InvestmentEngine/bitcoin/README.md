# Bitcoin Smart DCA Engine

Bitcoin Smart DCA Engine 是一套可長期維護的比特幣 Adaptive DCA 投資系統。本模組屬於目前的 TradingView Pine Script Repository，但它本身不是 Pine Script 策略，也不負責自動下單。

## 專案目標

- 投資標的：Bitcoin（BTC）
- 起始資金：10,000 USD
- 投資期間：2026-08-12 至 2026-10-15（含首尾共 65 天）
- Base DCA：每日 80 USD
- 核心原則：越便宜買越多，越昂貴買越少
- 期限要求：在結束日前完成全部資金投入
- 每日輸出：於 Asia/Taipei 21:00 產生簡潔、可追溯的 DCA 建議

Base DCA 在完整期間預計投入 5,200 USD，其餘 4,800 USD 保留給智慧調整與期限調速。Stage 2.1 已核准分配與 Budget Guard 的設計基準；完整 65 天計畫於 2026-08-11 Review 時平移至 8 月 12 日開始，數值參數仍需回測或營運驗證。

## 系統定位

本專案是一個投資決策與紀錄系統，預計逐步整合市場資料、客觀評分、資金保護、通知與報表。它應能回答：

1. 今天建議投入多少？
2. 建議是由哪些資料與規則產生？
3. 資金限制是否改變了原始建議？
4. 實際投入與建議投入是否一致？
5. 截至目前的投入進度與平均成本為何？

## 設計原則

- 文件與程式分離。
- 所有可調參數集中管理，不將策略數值散落在程式中。
- 市場資料、決策、資金限制、通知與儲存彼此解耦。
- 建議投入與實際投入分開紀錄。
- 所有輸出必須可由原始資料、設定版本及決策原因重現。
- 每次重大策略或架構變更都必須寫入 `decision_log.md`。
- 外部服務故障時，不得靜默產生看似正常的建議。

## 目前階段

Stage 3 與 Stage 4A 本機手動 MVP（Gate 4A-1～4A-4）均已於 2026-08-11 核准並實作。使用者另行授權 Stage 4B 的 21:00 本機排程與 Telegram 通知子集；`recommend`／`run-daily` 會保存 canonical recommendation 後傳送同一結果。仍沒有自動下單、備份、Dashboard 或交易所匯入。

已完成：

- 專案用途與邊界
- 高階架構
- 決策紀錄機制
- Repository 工作規則
- Smart DCA 計算順序與資金保護規格草案
- 集中式 Config 參數契約草案
- 週目標、全期容量檢查、`minimum_required_today` 與不可行狀態
- 方向因子分組及 BVIV 非方向性調節規則
- Canonical 資料來源、21:00 cutoff 與資料新鮮度契約
- Journal canonical storage 與資料驗證契約
- 建議與實際成交分離、一天多筆成交及 reversal 修正規則
- Daily Journal、Weekly Report 與 Monthly Report 模板
- 本機手動 MVP 的 Provider、CLI、錯誤處理與實作 Gate 設計
- Versioned machine config 與 Python 3.11+ CLI skeleton
- JSONL lock、append、fsync、schema／reference validation
- `record-purchase`、`correct-purchase`、`close-day`、`status`、`validate`
- Execution ledger、reversal／replacement 與 PortfolioState rebuild
- Pure indicators、方向分數與 BVIV modifier
- Weekly target、65 天 capacity buckets、pacing 與 Budget Guard
- Machine strategy-config validation 與 DecisionRecord hard-cap invariants
- Coinbase／Alternative.me／Volmex read-only Provider adapters
- Cutoff、freshness、retry、BVIVF fallback 與 secret redaction
- `recommend`、WeeklyTargetSnapshot、MarketSnapshot 與 DecisionRecord revisions
- Deterministic Daily／Weekly／Monthly Markdown renderer 與 canonical data watermark
- 不連外、不寫正式 Journal 的 2026-08-12 第一日 fixture rehearsal
- 共用 `DailyWorkflowService` 的手動／排程 recommendation 與 Telegram 通知
- 2026-08-12～2026-10-15 每日 21:00 Asia/Taipei local automation

尚未完成：

- 參數回測與營運驗證
- 2026-08-12 當日的 live provider 操作驗收
- Retry／missed-run alarm、報表自動化與 Dashboard
- 自動交易與自動備份

## 文件索引

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)：系統邊界、分層與擴充方向
- [`decision_log.md`](decision_log.md)：重大設計決策及原因
- [`SPEC.md`](SPEC.md)：Smart DCA 詳細規格與計算順序
- [`CONFIG.md`](CONFIG.md)：可調參數、預設值及驗證契約
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md)：Journal、決策、成交與報表資料契約
- [`templates/DAILY_JOURNAL.md`](templates/DAILY_JOURNAL.md)：每日決策與執行紀錄模板
- [`templates/WEEKLY_REPORT.md`](templates/WEEKLY_REPORT.md)：每週進度、品質與容量摘要模板
- [`templates/MONTHLY_REPORT.md`](templates/MONTHLY_REPORT.md)：月度投入、遵循度與投資組合摘要模板
- [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md)：本機 MVP 市場資料來源與降級規則
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md)：CLI、每日操作、錯誤與恢復契約
- [`ROADMAP.md`](ROADMAP.md)：設計、實作及驗收 Gate

## 預定目錄

```text
InvestmentEngine/bitcoin/
├── dca.py
├── README.md
├── SPEC.md
├── CONFIG.md
├── ROADMAP.md
├── decision_log.md
├── config/
│   └── config.1.0-draft.2.json
├── src/
│   └── bitcoin_dca/          # Gate 4A-1～4A-4 runtime
├── tests/
│   ├── test_journal_core.py
│   ├── test_decision_core.py
│   └── test_provider_recommendation.py
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DATA_MODEL.md
│   ├── INTEGRATIONS.md
│   └── OPERATIONS.md
├── templates/
│   ├── DAILY_JOURNAL.md
│   ├── WEEKLY_REPORT.md
│   └── MONTHLY_REPORT.md
├── data/
│   └── README.md
└── reports/
    └── README.md
```

目錄採漸進式建立：只有進入對應階段後才加入檔案，避免空目錄或未核准的介面被誤認為可用功能。

## 開發狀態

本模組目前包含已核准設計與 Gate 4A-1～4A-4 runtime。`recommend` 只會讀取公開市場資料並寫入本機 Journal，不讀交易所帳戶、不送單；`report` 只讀 canonical Journal。真實 canonical JSONL 與 generated reports 預設不提交 Git。

目前可用：

```bash
InvestmentEngine/bitcoin/.venv/bin/python --version  # 必須為 3.11+
InvestmentEngine/bitcoin/.venv/bin/python InvestmentEngine/bitcoin/dca.py validate
InvestmentEngine/bitcoin/.venv/bin/python InvestmentEngine/bitcoin/dca.py status
InvestmentEngine/bitcoin/.venv/bin/python InvestmentEngine/bitcoin/dca.py recommend
InvestmentEngine/bitcoin/.venv/bin/python InvestmentEngine/bitcoin/dca.py run-daily
InvestmentEngine/bitcoin/.venv/bin/python InvestmentEngine/bitcoin/dca.py test-telegram
InvestmentEngine/bitcoin/.venv/bin/python InvestmentEngine/bitcoin/dca.py record-purchase --usd "<USD>" --btc "<BTC>"
InvestmentEngine/bitcoin/.venv/bin/python InvestmentEngine/bitcoin/dca.py record-purchase --usd "<USD>" --btc "<BTC>" --plan-date 2026-08-12 --executed-at 2026-08-13T03:26:00+08:00
InvestmentEngine/bitcoin/.venv/bin/python InvestmentEngine/bitcoin/dca.py correct-purchase --execution-id "<ID>" --usd "<USD>" --btc "<BTC>"
InvestmentEngine/bitcoin/.venv/bin/python InvestmentEngine/bitcoin/dca.py close-day --reason skipped
InvestmentEngine/bitcoin/.venv/bin/python InvestmentEngine/bitcoin/dca.py report daily
InvestmentEngine/bitcoin/.venv/bin/python InvestmentEngine/bitcoin/dca.py report weekly --date 2026-08-12
InvestmentEngine/bitcoin/.venv/bin/python InvestmentEngine/bitcoin/dca.py report monthly --date 2026-08-12
InvestmentEngine/bitcoin/.venv/bin/python InvestmentEngine/bitcoin/dca.py rehearse-first-day
```

`recommend` 只允許在正式計畫期間的 Asia/Taipei 當日 21:00 cutoff 後執行，建議約 21:05 手動觸發。晚於 21:10 仍沿用當日 21:00 cutoff，不加入 cutoff 後資料。它會先 fsync canonical records，再顯示結果；輸出使用尚未回測證實的 draft parameters，且不代表交易已成交。
