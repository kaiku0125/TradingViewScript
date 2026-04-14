# Market State Agent

## Purpose
Use this workflow when the user provides a fixed `行情狀態` block and wants a short trading analysis based on the `TDHighLow` system.

## Supported State Codes
- `L` = `Long` = 多頭延續
- `S` = `Short` = 空頭延續
- `ML` = `Mixed from Long weakening` = 混合(由多頭轉弱)
- `MS` = `Mixed from Short strengthening` = 混合(由空頭轉強)
- `M` = `Mixed` = 混合

Hard rules:
- Never interpret `L` as `Low`
- Never interpret `S` as sell-only sentiment
- `L / S` are structure-direction codes, not price-level abbreviations

## Required Input Format
Only treat the request as a market-state workflow when the user provides this structure:

```text
行情狀態
4H = M
1H = L
15m = ML
5m = S
```

Rules:
- The first line must be exactly `行情狀態`
- Each following line must use `週期 = 代號`
- Accept 2 to 4 timeframes
- The timeframes must be ordered from large period to small period

If the format is incomplete, missing the `行情狀態` header, or the order is unclear, ask the user to resend it in the fixed format.

## Interpretation Rules
- The first timeframe is `大(P)` and defines the main bias
- The second timeframe is `中(P)` and is used to judge retracement, structure quality, or whether price is in a tradable zone
- The last timeframe is `小(P)` and is used to judge re-acceleration, invalidation, or timing
- If 4 timeframes are provided:
  - The 1st is `大(P)`
  - The 2nd is `中大(P)`
  - The 3rd is `中小(P)`
  - The 4th is `小(P)`

The analysis must always produce one explicit conclusion first:
- `偏多`
- `偏空`
- `等待`

Bias rules:
- If `大(P)` is `L`, prefer `偏多`
- If `大(P)` is `S`, prefer `偏空`
- If `大(P)` is `M`, `ML`, or `MS`, default to `等待` unless lower timeframes align clearly as a retracement-then-restart structure
- `ML` means a bullish structure has started to weaken and is usually interpreted as a retracement or early breakdown phase
- `MS` means a bearish structure has started to strengthen upward and is usually interpreted as a rebound or early reversal phase
- Pure `M` means consolidation or unclear structure and should not be treated as an immediate directional trigger
- If multi-timeframe conflict is large, prefer `等待`

## Fixed Output Template
For every valid `行情狀態` input, use this short fixed template:

```text
結論：偏多 / 偏空 / 等待

大(P)：
一句話定義主背景

中(P)：
一句話說明現在是推進、回撤、反彈或整理

小(P)：
一句話說明是否可進、是否仍要等

操作：
直接寫等什麼才進，或現在可做什麼

失效：
直接寫哪個週期若繼續惡化，就放棄原方向
```

Output rules:
- Keep it short, usually 6 to 10 lines
- Do not write long-form education or general market essays
- State the conclusion first, then explain
- Use trading language and focus on what to do now

## Expected Example
Input:

```text
行情狀態
4H = M
1H = L
15m = ML
5m = S
```

Expected direction:
- `結論：等待`

Reasoning:
- `4H` is mixed, so the higher-level background is not clean
- `1H` is bullish, so the directional bias is not directly short
- `15m` is weakening from bullish structure and `1m` is still bearish, which means the pullback is likely still ongoing
- The preferred action is to wait for lower timeframe stabilization and re-acceleration rather than chase either side immediately

## Test Examples
- `4H = L / 1H = L / 15m = MS`
  - Should lean `偏多`, but wait for lower timeframe restart
- `4H = S / 1H = S / 15m = ML`
  - Should lean `偏空`, but wait for rebound exhaustion
- `4H = M / 1H = L / 15m = ML / 1m = S`
  - Should be `等待`
- `1D = L / 4H = M / 1H = MS`
  - Should be cautious bullish observation, not immediate entry
- Invalid or malformed format
  - Must ask the user to resend in the fixed `行情狀態` format
