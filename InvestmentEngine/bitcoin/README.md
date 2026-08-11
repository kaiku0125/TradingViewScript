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

Stage 3 已於 2026-08-11 Review 並核准：在 Stage 2.1 核准的策略與容量設計之上，加入本機且 Git ignored 的 canonical JSONL Journal、不可變市場快照、可修訂決策、append-only 實際成交、每週目標快照及 Daily／Weekly／Monthly 報表模板。目前仍沒有資料擷取、策略 runtime、排程或通知。

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

尚未完成：

- 參數回測與營運驗證
- 真實 Journal 寫入與驗證程式
- API、通知、自動化與 Dashboard 整合規格
- 任何實際程式碼或排程

## 文件索引

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)：系統邊界、分層與擴充方向
- [`decision_log.md`](decision_log.md)：重大設計決策及原因
- [`SPEC.md`](SPEC.md)：Smart DCA 詳細規格與計算順序
- [`CONFIG.md`](CONFIG.md)：可調參數、預設值及驗證契約
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md)：Journal、決策、成交與報表資料契約
- [`templates/DAILY_JOURNAL.md`](templates/DAILY_JOURNAL.md)：每日決策與執行紀錄模板
- [`templates/WEEKLY_REPORT.md`](templates/WEEKLY_REPORT.md)：每週進度、品質與容量摘要模板
- [`templates/MONTHLY_REPORT.md`](templates/MONTHLY_REPORT.md)：月度投入、遵循度與投資組合摘要模板
- `ROADMAP.md`：版本與整合規劃（第 4 階段建立）

## 預定目錄

```text
InvestmentEngine/bitcoin/
├── README.md
├── SPEC.md
├── CONFIG.md
├── ROADMAP.md              # 第 4 階段
├── decision_log.md
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DATA_MODEL.md
│   ├── INTEGRATIONS.md     # 第 4 階段
│   └── OPERATIONS.md       # 第 4 階段
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

本模組目前僅包含設計文件、資料契約與報表模板，不提供投資建議、不抓取即時市場資料，也不會執行交易。真實成交資料預設不提交 Git。
