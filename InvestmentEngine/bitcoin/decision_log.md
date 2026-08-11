# Bitcoin Smart DCA Engine Decision Log

本文件記錄會影響策略行為、系統邊界、資料格式、外部整合或維護方式的重大決策。一般文字修正不需新增紀錄。

## 紀錄格式

每筆決策應包含：

- 編號與標題
- 日期
- 狀態：Proposed、Accepted、Superseded 或 Rejected
- 背景
- 決策
- 原因
- 影響與取捨
- 後續事項

若決策被取代，保留原紀錄並連結到新決策，不回頭刪除歷史。

---

## DCA-ADR-001：採用分層、可替換的投資決策架構

- 日期：2026-07-31
- 狀態：Accepted

### 背景

專案未來需要整合多個市場資料來源、通知管道、自動化平台、Dashboard 與 AI Agent。若將資料擷取、評分、資金限制和通知寫在同一流程，策略難以測試，也容易因外部服務改版而影響核心決策。

### 決策

系統劃分為資料來源、擷取與驗證、標準化、訊號評分、決策、Budget Guard、Journal、報表及通知等責任邊界。外部服務透過 Adapter／Provider 接入，核心決策不依賴特定供應商格式。

### 原因

- 可以獨立替換資料來源或通知管道。
- 可以針對決策與資金限制進行確定性測試。
- 能逐步擴充，無須一次建好所有整合。

### 影響與取捨

初期文件與介面設計較多，但可降低後續耦合與重寫成本。

### 後續事項

在實作階段確認實際模組名稱、依賴方向與測試邊界。

---

## DCA-ADR-002：分開記錄建議投入與實際投入

- 日期：2026-07-31
- 狀態：Accepted

### 背景

使用者的實際成交金額、時間或價格可能與系統建議不同。若只保存單一投入數字，將無法區分策略表現和執行偏差。

### 決策

每日紀錄分開保存限制前建議、限制後最終建議及實際成交結果。投資組合與平均成本以實際成交為準，策略分析則同時保留建議值。

### 原因

- 保留完整稽核軌跡。
- 可以分析是否遵循建議及偏差原因。
- 避免未成交的建議污染真實持倉。

### 影響與取捨

Journal 欄位會增加，並需要支援決策後補登成交資料。

### 後續事項

第 3 階段在 `DATA_MODEL.md` 定義欄位、狀態與更新規則。

---

## DCA-ADR-003：Budget Guard 是不可繞過的最終控制層

- 日期：2026-07-31
- 狀態：Accepted

### 背景

Smart DCA 訊號可能在市場劇烈波動時產生較大投入建議，但專案同時要求避免過早耗盡資金，並在期限前完成投入。

### 決策

市場訊號先產生限制前建議，再由獨立 Budget Guard 套用每日上限、每週上限、剩餘資金與期限調速規則。通知、Dashboard、n8n 或未來 AI Agent 都不得繞過此層。

### 原因

- 將「何時值得加碼」與「實際允許投入多少」分離。
- 確保所有輸出遵守一致的資金保護規則。
- 便於測試最後一日與剩餘資金等邊界。

### 影響與取捨

系統必須同時保存限制前後金額及限制原因；最終公式仍需第 2 階段 Review。

### 後續事項

在 `SPEC.md` 與 `CONFIG.md` 定義規則順序、參數與邊界。

---

## DCA-ADR-004：採用漸進式目錄與文件交付

- 日期：2026-07-31
- 狀態：Accepted

### 背景

使用者要求分階段 Review，且本次不得開始撰寫實際程式碼。一次建立所有空白文件或程式目錄，容易讓未核准設計被誤認為已定案。

### 決策

第 1 階段只建立專案入口、高階架構和決策紀錄。策略、Config、資料模型、範本、整合與 Roadmap 在各自階段 Review 後建立；程式目錄留到實作階段。

### 原因

- 每個階段都有清楚的 Review 邊界。
- 避免空殼檔案掩蓋未完成的設計。
- 保持文件與實作狀態一致。

### 影響與取捨

完整目錄不會一次出現，但 README 會列出預定結構與完成狀態。

### 後續事項

每次階段核准後更新 README 狀態，重大變更同步新增 ADR。

---

## DCA-ADR-005：投資計畫改於 2026-08-01 開始

- 日期：2026-07-31
- 狀態：Superseded by DCA-ADR-014

### 背景

原始計畫的投資期間為 2026-07-31 至 2026-10-03。使用者在第 1 階段 Review 時決定將開始日期順延一天，結束日期與每日 Base DCA 維持不變。

### 決策

投資期間改為 2026-08-01 至 2026-10-03，含首尾共 64 天。每日 Base DCA 維持 80 USD。

### 原因

配合最新的實際投資啟動計畫。

### 影響與取捨

- Base DCA 預算由 5,200 USD 改為 5,120 USD。
- 智慧調整與期限調速的預留資金由 4,800 USD 改為 4,880 USD。
- 起始資金 10,000 USD 與結束日期 2026-10-03 不變。
- 第 2 階段的期限調速與資金限制規格必須以 64 天期間為準。

### 後續事項

建立 `SPEC.md` 與 `CONFIG.md` 時，使用新的開始日期、期間天數與預算分配。

---

## DCA-ADR-006：五因子採 0～1 正規化加權模型

- 日期：2026-07-31
- 狀態：Superseded by DCA-ADR-010

### 背景

近期高點距離、Fear & Greed、BVIV、ATR 與單日跌幅的單位及範圍不同。若直接混合原始值，權重難以理解，也不利於增加新因子。

### 決策

每個因子先依版本化門檻轉為 0～1 分數，再依 30%、25%、15%、15%、15% 的草案權重組合。Adaptive 金額使用每日名目配額乘以 0～2 倍的線性倍數。

### 原因

- 各因子的貢獻可比較、可解釋。
- 門檻、權重與金額映射可以分開測試。
- 未來新增 Macro 或 AI 因子時可沿用同一介面。

### 影響與取捨

線性模型易理解但未必完整反映極端市場的非線性行為；初始門檻需要經 Review 與未來回測調整。

### 後續事項

使用者 Review `SPEC.md` 與 `CONFIG.md` 後，將本決策改為 Accepted 或以新決策取代。

---

## DCA-ADR-007：期限調速與最終日投入規則

- 日期：2026-07-31
- 狀態：Superseded by DCA-ADR-009

### 背景

純市場評分無法保證 2026-10-03 前投入全部資金，但過早採用平均剩餘資金投入又會削弱 Adaptive DCA 的資金保留能力。

### 決策

草案採用分段期限調速：剩餘 21 天時開始逐步補足所需平均投入速度，剩餘 7 天時完全生效，並以未來每日容量可行性底線避免過晚累積。最終日建議投入全部剩餘資金，覆寫每日及每週上限。

### 原因

- 前段保留較多 Adaptive Reserve 等待較佳市場條件。
- 後段逐步降低無法完成投入的風險。
- 最終日規則提供明確的期限保證。

### 影響與取捨

最終日可能出現明顯高於一般上限的建議；若實際交易失敗，系統只能記錄未完成，不能保證真實成交。

### 後續事項

Review 21／7 天門檻、每日 500 USD、每週 2,000 USD 與最終日覆寫規則。

---

## DCA-ADR-008：缺失因子採降級計算，不以零值代替

- 日期：2026-07-31
- 狀態：Superseded by DCA-ADR-010 and DCA-ADR-011

### 背景

Fear & Greed 或 BVIV 等外部來源可能暫時不可用。把缺失資料當成 0 分會使系統產生看似正常、實際偏低的建議。

### 決策

BTC 價格或資金狀態缺失時阻擋一般決策；至少 3 個因子有效時重新正規化有效權重；少於 3 個時只採 Base DCA 與必要期限規則。所有降級必須明確標示。

### 原因

- 不偽造資料。
- 保留每日持續曝險的 Base DCA 理念。
- 在資料完整性與系統可用性之間取得可見、可追蹤的平衡。

### 影響與取捨

降級時的結果與完整資料模型不同，必須在通知、Journal 與報表中標記，避免直接比較。

### 後續事項

第 4 階段再定義資料新鮮度、來源優先順序、重試與告警政策。

---

## DCA-ADR-009：以週目標與全期容量取代最終日無條件投入

- 日期：2026-08-01
- 狀態：Accepted（2026-08-02）

### 背景

原草案只檢查未來每日容量，且允許最終日覆寫每日與每週上限，可能把大量資金延遲到最後一天，破壞資金保護原則。

### 決策

每週第一個投資日建立週目標，週最低比例由 80% 隨期限提高到 100%，市場訊號可使用至 130% soft max。每天依日曆同時計算每日與每週 hard capacity；容量不足時標記 `plan_infeasible`。最終日不得自動覆寫 daily 500 USD 或 weekly 2,000 USD hard caps。

### 原因

- 讓進度落後在前期被看見並逐步補足。
- 週限制成為真正的容量條件，不再被最終日例外架空。
- 區分可調的進度 soft cap 與不可自動突破的風險 hard cap。

### 影響與取捨

系統不能保證使用者實際完成投入，只能確保建議在可行時維持計畫進度。若實際執行持續落後，需提早人工調整期限或 hard caps。

### 後續事項

Review 80%～100% 週最低比例、130% soft max 與 hard caps。

---

## DCA-ADR-010：將相關因子分組並限制 BVIV 的方向性

- 日期：2026-08-01
- 狀態：Accepted（2026-08-02）

### 背景

回檔、ATR 下跌與單日跌幅會對同一場價格下跌重複計權；BVIV 衡量波動大小而不是價格方向，不能因數值高就直接增加買入。

### 決策

方向模型改為價格位置 45%、市場情緒 25%、下跌衝擊 30%。ATR 與絕對跌幅合併為同一 shock group 並取較高分。BVIV 移出方向分數，v1.0 只作 0.90～1.00 的保守調節：沒有回檔、恐慌或下跌 gate 時可抑制 Adaptive，任何情況都不放大投入。

### 原因

- 降低相關因子的重複曝險。
- 保留 ATR 與絕對跌幅兩種尺度，但只計一次 shock 權重。
- 避免把高隱含波動誤當成看多或便宜訊號。

### 影響與取捨

模型更保守，極端恐慌時不會因 BVIV 額外放大；未來需有回測證據才能放寬 modifier 上限。

### 後續事項

Review 45%／25%／30% 權重、shock `max` 方法與 BVIV modifier。Fear & Greed 與價格回檔／波動壓力可能仍有相關性，但不阻擋 Stage 2.1；後續回測必須檢查因子相關矩陣、邊際貢獻與移除單一因子後的敏感度，再決定是否調整情緒權重。

---

## DCA-ADR-011：鎖定 Canonical 資料來源與 21:00 cutoff

- 日期：2026-08-01
- 狀態：Accepted（2026-08-02）

### 背景

相同的 BTC 價格、日線、Fear & Greed 或 BVIV 若使用不同供應商、時間邊界或發布時間，會產生不同建議，也可能在回測中使用當時尚不可取得的資料。

### 決策

BTC 使用 Coinbase Exchange `BTC-USD`，reference price 為台北 21:00 截止前最後完整 5 分鐘 candle close；近期高點與 ATR 使用同來源已完成 UTC 日線。Fear & Greed 使用 Alternative.me 截止前最新值。BVIV 使用 Volmex 截止前完整 60 分鐘值，必要時退回最近已完成 fixing。每份輸入保存觀察、可取得、抓取與截止時間。v1.0 不靜默切換 BTC 交易所。

### 原因

- 相同輸入與 Config 可以重現相同結果。
- 防止 cutoff 後資料進入當日決策。
- 避免跨交易所價格與 OHLC 基準混用。

### 影響與取捨

Coinbase 不可用時一般決策會 blocked；BVIV fallback 可能較舊且必須標記。正式排程、授權、重試與告警仍待第 4 階段。

### 後續事項

第 3 階段把資料時間與品質欄位納入資料模型；第 4 階段定義抓取、授權、重試與通知流程。

---

## DCA-ADR-012：加入今日最低必要投入容量底線

- 日期：2026-08-02
- 狀態：Accepted（2026-08-02）

### 背景

全期容量檢查可以識別整體計畫是否可行，但若沒有每日最低容量底線，系統仍可能在某一天投入過少，使原本可行的計畫在之後變成不可行。

### 決策

每天以剩餘資金、今天之後的當週容量及下週起總容量計算：

```text
minimum_required_today = ceil_to_cent(max(
    0,
    remaining_funds
    - current_week_future_capacity
    - future_weeks_capacity
))
```

最終 guard candidate 必須取市場建議、pace floor、weekly catchup 與 `minimum_required_today` 的最大值。容量底線可以覆寫 weekly soft cap，但不可覆寫 daily 或 weekly hard caps。

### 原因

- 防止今天投入過少而消耗未來完成計畫的可能性。
- 同時尊重每日與每週共享容量。
- 將正常進度管理與最後可行性底線分開。

### 影響與取捨

最低必要投入必須向上取至美分，與一般最終金額向下截斷的規則不同。若最低值超出今日 hard capacity，系統必須標記 `plan_infeasible`，不能自動提高上限。

### 後續事項

實作時針對部分週、最後一週、週額度已部分使用及美分邊界建立測試案例。

---

## DCA-ADR-013：採用事件式 Journal 並分離建議與實際成交

- 日期：2026-08-11
- 狀態：Accepted（2026-08-11）

### 背景

Stage 2.1 已要求每次建議可由市場快照、Config 版本與原因重現，且資金進度必須以實際成交而非系統建議計算。Stage 3 需要定義可以支援同日重算、一天多筆成交、歷史補登、成交修正與週／月報表的 canonical storage contract。

若每日只保存一份可覆寫的彙總資料，同日重算會失去舊決策，成交修正也會破壞稽核軌跡；若直接保存可修改的剩餘資金，則無法證明它是否與實際成交一致。

### 決策

Stage 3 採用 UTF-8 JSON Lines，分成四個 canonical 資料集：

1. 不可變的 `MarketSnapshot`。
2. 以無循環 revision chain 保存、由唯一未被取代末端推導 current 的 `DecisionRecord`。
3. 支援一天多筆成交、以 reversal 和 replacement 修正，並以 `day_close` 明確記錄跳過或結束等待的 append-only `ExecutionEvent`。
4. 每週第一個投資日建立、建立後不可因市場或成交變化重設的 `WeeklyTargetSnapshot`。

`PortfolioState` 不作獨立 source of truth，而是由未被 reversal 的實際 purchase events 推導。Daily Journal、Weekly Report 與 Monthly Report 也只作衍生視圖，不重新抓取市場資料或改寫 canonical records。所有金額、數量、價格、分數與倍率在 canonical JSONL 中使用十進位字串。

手動成交只要求輸入總 USD 投入與實際收到的淨 BTC，成交時間預設為回報時間。v1 不拆分手續費；總 USD 視為預算成本，並以 `USD / BTC` 推導包含費用效果的有效成本價。真實 JSONL 存在 repository 的 `data/` 目錄，但必須 Git ignored；本階段不要求加密或自動備份。

### 原因

- 完整保留建議、重算與成交修正的稽核軌跡。
- 系統建議不會污染真實持倉及剩餘預算。
- 可以從相同資料水位重建相同投資組合與報表。
- 一天多筆成交及事後補登不需要修改原決策。
- JSONL 容易人工檢查，也適合未來逐筆寫入與轉入資料庫。

### 影響與取捨

- 後續實作必須驗證 ID 引用、current revision 唯一性、decimal 格式與 reversal 規則。
- 查詢最新狀態需要聚合事件，不能直接信任可修改的餘額欄位。
- 真實 Journal 可能包含敏感投資資料，預設不得提交 Git。
- 本決策只建立資料與報表契約，不授權 API、排程、通知、Dashboard 或交易實作。

### 後續事項

- 實作 Journal 寫入、schema 驗證與投資組合重建時，遵守本契約。
- Stage 4 定義外部整合 ownership、衝突處理、重試、通知與 Operations。

---

## DCA-ADR-014：將完整 65 天投資計畫推遲至 2026-08-12

- 日期：2026-08-11
- 狀態：Accepted

### 背景

原始計畫為 2026-07-31 至 2026-10-03，共 65 天；其後曾把起始日改為 2026-08-01 並保留舊截止日，因此縮短為 64 天。在 Stage 3 Review 完成前尚未建立 canonical Journal 或正式執行流程，使用者決定將計畫推遲至 2026-08-12，並明確要求維持最初的 65 天期間，而不是壓縮在舊截止日前完成。

### 決策

投資期間改為 2026-08-12 至 2026-10-15，含首尾共 65 個日曆日。總預算維持 10,000 USD，Base DCA 維持每日 80 USD。

衍生值改為：

```text
base_budget = 65 × 80 = 5,200 USD
adaptive_reserve = 10,000 - 5,200 = 4,800 USD
nominal_adaptive_daily = 4,800 / 65 ≈ 73.846153846 USD
```

`SPEC.md` 與 `CONFIG.md` 版本同步提升至 `1.0-draft.2`。內部計算保留 `4,800 / 65` 的完整精度，最終建議仍按既有 Budget Guard 規則處理到美分。

### 原因

- 讓正式計畫起點與 canonical Journal 啟用時間一致。
- 保留原始 65 天資金配置與節奏，不因啟動延遲而壓縮投資期間。
- 避免把沒有標準化決策與成交紀錄的先前日期誤認為計畫執行期。

### 影響與取捨

- DCA-ADR-005 的 2026-08-01 起始日被本決策取代。
- 結束日由 2026-10-03 順延至 2026-10-15，維持 65 個投資日。
- Base Budget 回到原始 65 天計畫的 5,200 USD，Adaptive Reserve 為 4,800 USD。
- 每日 500 USD 與每週 2,000 USD hard caps 仍為待驗證草案值，且不得自動突破。
- 日期平移後，實作前必須用 65 天新日曆重新驗證每週 bucket 與全期 hard capacity。

### 後續事項

- 核心引擎實作時加入 2026-08-12 首日、2026-10-15 最終日與部分週容量測試。
- 回測或營運驗證新的每日名目 Adaptive 配額及既有 hard caps。

---

## DCA-ADR-015：本機手動 MVP 採分層 CLI 與唯讀 Provider

- 日期：2026-08-11
- 狀態：Accepted（2026-08-11）

### 背景

Stage 3 已定義 canonical Journal，但目前沒有方法建立市場快照、執行 Budget Guard、保存每日建議或讓使用者登記成交。直接先做排程、通知或 Dashboard 會在核心決策與 Journal 尚未驗證時放大錯誤，也會增加除錯範圍。

### 決策

Stage 4A 提議先建立完全由使用者手動觸發的 Python 3.11+ 本機 CLI。MVP 依序實作 Journal core、pure Decision Engine／Budget Guard、Provider Adapters、deterministic reports 與本機 rehearsal。

市場資料只以唯讀 REST 取得：Coinbase Exchange `BTC-USD` 5m／1d、Alternative.me Fear & Greed、Volmex `BVIV` 60m 及 `BVIVF` daily fixing。Volmex key 為可選環境變數 `VOLMEX_API_KEY`，不得進入命令列、log 或 Journal。MVP 不讀交易所帳戶、不送單、不排程、不通知，也不補造歷史 decision。

未來 CLI 以單一入口提供 `recommend`、`record-purchase`、`close-day`、`correct-purchase`、`status`、`validate` 與 `report`。所有寫入使用 exclusive lock、append-only JSONL、flush 與 fsync。Recommendation 必須在台北 21:00～21:10 window 內手動觸發，先保存 MarketSnapshot 與 DecisionRecord，再顯示給使用者。Candle close 的 normalized `observed_at` 使用 bucket end，同時保留供應商原始 bucket-start timestamp；因此 `DATA_MODEL.md` review version 提升至 `1.0-draft.2`。

### 原因

- 用最小操作面驗證完整決策與紀錄閉環。
- Pure core 可用固定 snapshot 測試，不依賴外部 API。
- 唯讀 Provider 不需要交易所帳戶權限，降低安全風險。
- 手動觸發便於觀察 cutoff、degraded、blocked 與 hard-cap 邊界。
- 單一 CLI entrypoint 可供未來排程重用，避免手動與自動流程分叉。

### 影響與取捨

- 使用者每天必須手動執行 recommend 及登記成交。
- 錯過當日不補造 recommendation，報表會留下 `no_decision`。
- Volmex 60m 權限不足時可能使用 BVIVF fallback 或中性 modifier。
- 本機無備份是已知資料遺失風險。
- Python runtime、HTTP/retry 數值與 CLI 設計已核准，但仍不能視為已實作。

### 後續事項

- 另行授權 Gate 4A-1 Journal core 實作。
- 第一日 rehearsal 必須驗證 2026-08-12 partial week、previous reference 與 65 天容量。
