# Generated Reports

此目錄存放由 canonical Journal 衍生的 Daily Journal、Weekly Report 與 Monthly Report。

Gate 4A-4 renderer 只讀取 `../data/` 的 canonical 資料，不重新抓取市場資料、重算或覆寫原始決策與成交事件。輸出位於 `generated/{daily,weekly,monthly}/` 且 Git ignored；相同 canonical watermark 與模板會產生相同內容。
