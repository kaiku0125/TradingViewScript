# Canonical Journal Data

此目錄預留給 Bitcoin Smart DCA 的 canonical JSONL 資料：

- `market_snapshots.jsonl`
- `decisions.jsonl`
- `executions.jsonl`
- `weekly_targets.jsonl`

真實 JSONL 使用 repository 內的此目錄作本機 canonical storage，但所有 `*.jsonl` 都必須由 `.gitignore` 排除，不得提交 Git。Gate 4A-1 已實作 exclusive `.bitcoin_dca.lock`、完整行 append、flush、fsync 與 `validate`；目前尚未寫入任何真實 execution。Stage 3 不要求加密或自動備份。欄位、修訂、驗證與隱私規則見 [`../docs/DATA_MODEL.md`](../docs/DATA_MODEL.md)。外部同步仍須另行核准。
