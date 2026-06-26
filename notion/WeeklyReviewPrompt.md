# Weekly Review for Notion AI

這個 repo 已經能先算出大部分每週回顧需要的客觀數據。

相關腳本輸出：
- `weekly_holdings_pnl_sync.py` 會計算：
  - `speculationPNL`
  - `speculationPNLRatio`
  - 各資產 `unrealized_pnl_twd`
  - `exchange_usd`
  - holdings 與 USD balance 的變化摘要
- `update_pnl_history.py` 會更新 `PNLRebalance` 內的每日 pnl 歷史

Notion 應該是回顧層，不是計算引擎。

## 給 Notion AI 的中文 Prompt

```text
幫我建立一個可重複使用的 Weekly Review 頁面模板，給我的投資組合追蹤流程使用。

背景：
- 我已經用 TradingView 和 Pine scripts 處理即時行情、圖表、持倉同步和 pnl 追蹤。
- 我的本地腳本已經會先算出大部分客觀的投資組合數據。
- Notion 不需要取代 TradingView，也不是計算引擎。
- 我希望 Notion 只是輕量的每週回顧層。
- 這個流程主要是給 portfolio tracking 和 rebalancing 使用，不是 day trading。
- 我希望這個模板未來可以讓 script 產出的數據直接貼上或自動同步。

請只建立一個乾淨、簡單的 Weekly Review 頁面，而且只包含以下 4 個部分：

1. 本週總資產變化
2. 本週最大獲利來源
3. 本週最大失誤
4. 下週調整計畫

要求：
- 保持極簡，容易維護
- 整份內容最好 5 分鐘內可以填完
- 不要建立大型 trading journal
- 不要加入額外 dashboard
- 不要加入不必要的 database
- 第 1 和第 2 部分標示為系統填入資料
- 第 3 和第 4 部分標示為手動回顧
- 每個部分下面加上 2 到 3 個簡短的引導問題
- 請輸出成單一頁面模板，不要擴展成完整 workspace

請依照以下資料對應方式設計：
- 本週總資產變化：由 script 輸出數據填入
- 本週最大獲利來源：由 unrealized pnl 最高的資產填入
- 本週最大失誤：手動填寫
- 下週調整計畫：手動填寫
```

## 建議欄位

如果你之後要把它改成 Notion database，欄位先維持最小化：

- `週別`
- `本週總資產變化`
- `本週最大獲利來源`
- `本週最大失誤`
- `下週調整計畫`

## 這個 repo 對應的自動填寫來源

- `本週總資產變化`
  - 來自 weekly sync summary 或之後的 portfolio snapshot 輸出
- `本週最大獲利來源`
  - 來自 `unrealized_pnl_twd` 中數值最高的資產
- `本週最大失誤`
  - 手動
- `下週調整計畫`
  - 手動

## 哪些先不要自動化

先不要急著自動化這兩項：
- `本週最大失誤`
- `下週調整計畫`

這兩欄的價值來自你的判斷，不是原始數字。
