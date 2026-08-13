# Bitcoin Smart DCA Engine Roadmap

## 1. 文件狀態

- 版本：`0.1`
- 階段：Stage 4A Accepted（2026-08-11）
- 日期：2026-08-11

Roadmap 只描述交付順序與 Review gate，不授權自動下單或提前建立後續功能。

## 2. 已完成

### Stage 1：系統邊界

- 專案入口、高階架構與決策紀錄
- 狀態：Accepted

### Stage 2／2.1：策略與資金保護設計

- Smart DCA 公式、集中參數、canonical source、cutoff、因子去重
- Weekly target、全期容量、minimum-required-today、hard-cap 原則
- 狀態：Accepted design；numeric defaults 待回測／營運驗證

### Stage 3：Journal 與報表資料契約

- 四個 canonical JSONL record types
- 建議與成交分離、revision、reversal、day-close
- Daily／Weekly／Monthly templates
- 狀態：Accepted（2026-08-11）

## 3. Stage 4A：本機手動 MVP

### Gate 4A-D：設計 Review

交付：

- `docs/INTEGRATIONS.md`
- `docs/OPERATIONS.md`
- `ROADMAP.md`
- 對應 ADR 與治理更新

通過條件：

- 使用者接受每日 CLI 互動。
- 確認 21:00 cutoff 後 recommendation 可執行，目標約 21:05 手動執行。
- 確認 Volmex key 為可選環境變數。
- 確認不補造歷史 decision。
- 確認本機無備份風險。
- 確認 MVP 沒有排程、通知與自動交易。

目前狀態：Accepted（2026-08-11；2026-08-12 調整）。以下七項均已核准：Python 3.11+ 本機 CLI、21:00 cutoff 後同日 recommendation 可執行、Volmex optional key 與 BVIVF／中性降級、不補造歷史 recommendation、purchase 寫入前確認，以及暫無排程、通知、自動下單與備份。

核准時使用的 Review checklist：

```text
1. Python 3.11+ 本機 CLI：接受／修改
2. 21:00 cutoff 後同日 recommendation window：接受／修改
3. Volmex key 可選，失敗用 BVIVF／中性降級：接受／修改
4. 不補造歷史 recommendation：接受／修改
5. record-purchase 互動確認：接受／修改
6. 無排程、通知、自動下單與備份：接受／修改
7. Stage 4A design：核准／修改後再審
```

### Gate 4A-1：Journal core

狀態：Implemented（2026-08-11）。

已完成：

- Python package skeleton 與 machine config
- Decimal／time／ID utilities
- JSONL schemas、exclusive lock、append、validate
- Execution ledger、reversal、day-close、PortfolioState
- `record-purchase`、`correct-purchase`、`close-day`、`status`

驗收結果：14 個 unit tests 通過；固定 fixtures 可重建相同 PortfolioState，CLI 可載入 versioned config，錯誤／不完整 JSONL hard fail，取消確認不寫入，第二個 writer 無法取得 lock。

### Gate 4A-2：Pure decision core

狀態：Accepted／Implemented（2026-08-11）。

- Indicators 與 score normalization
- BVIV modifier
- Weekly targets、pacing、capacity buckets
- Budget Guard
- 65 天日曆及邊界測試

驗收結果：15 個 decision-core unit tests 通過；相同 normalized input＋Config 產生 byte-equivalent canonical numeric fields，首尾 partial week 與全部 65 天使用同一 calendar bucket 邏輯，並以全 65 天、多組 remaining／weekly-spend 組合驗證 final amount 不突破 remaining funds、daily hard max 或 weekly hard remaining。

### Gate 4A-3：Provider adapters

狀態：Accepted／Implemented（2026-08-11）。

- Coinbase Exchange 5m／1d
- Alternative.me Fear & Greed
- Volmex BVIV／BVIVF
- freshness、cutoff、retry、redaction
- `recommend`

驗收結果：14 個 Gate 4A-3 tests 通過，涵蓋正常、stale、missing、亂序、重複 bucket、日線 gap、cutoff、429、4xx、5xx、timeout、BVIVF fixing availability、fallback、neutral degradation、blocked persistence、same-day revision、orphan recovery 與 secret redaction。

### Gate 4A-4：Reports 與試運轉

狀態：Accepted／Implemented（2026-08-11）。

- Daily／Weekly／Monthly renderer
- data watermark 與 deterministic report tests
- 第一日 dry run
- 至少一次不寫正式 Journal 的 fixture-based rehearsal

驗收：使用者能完成 recommend → 手動買入 → record → status → report，且 validate 無錯誤。

實作結果：`report daily|weekly|monthly` 只讀 canonical JSONL，以 period-scoped SHA-256 data watermark 與 canonical 最大事件時間產生 deterministic Markdown；`rehearse-first-day` 使用固定 provider fixtures 與 temporary Journal 完成完整首日鏈，並驗證正式 Journal 前後不變。2026-08-12 的 live provider 操作仍需當日執行。

Review 結果：使用者接受三種報表內容、canonical-only／deterministic watermark、revision／reversal／多筆成交呈現、隔離式第一日 rehearsal，以及正式 Journal 不變保證，並核准 Gate 4A-4。Stage 4A local manual MVP 因此標記為 Accepted。

## 4. Stage 4B：本機自動化

### 已授權子集（2026-08-11）

- 21:00 Asia/Taipei Codex local scheduler
- Telegram recommendation／blocked／failure 通知
- 手動與排程共用 `DailyWorkflowService` 與 `run-daily` entrypoint
- `.env.local` secret loading 與 token redaction

狀態：Implemented。Telegram test delivery 已成功；Codex automation `smart-dca-21-00-telegram` 已建立並啟用。第一個正式 operational run 為 2026-08-12 21:00 Asia/Taipei。

### 尚未授權

- retry window 與 missed-run alarm
- LINE 通知
- 自動產生週／月報表
- 本機備份

排程、手動 `recommend` 與手動 `run-daily` 共用同一 `DailyWorkflowService` side effects，避免兩套決策流程。

## 5. 後續候選

不屬於目前承諾範圍：

- Dashboard
- Google Sheets read-only mirror
- 交易所成交匯入
- 參數 backtest 與敏感度分析
- Config promotion from draft to validated
- AI explanation／review assistant

自動交易沒有預定階段；若未來提出，必須另立安全、授權與風險 Review，且仍不得繞過 Budget Guard。

## 6. 建議近期順序

```text
Stage 4A design approval
  → Journal core（completed）
  → Pure decision core（completed）
  → Provider adapters（completed）
  → Reports（accepted）
  → Local fixture rehearsal（completed）
  → Manual MVP acceptance
```

不要先做排程或通知。若 Journal、Decision Engine 或 Budget Guard 尚未通過測試，外部輸出只會放大錯誤。
