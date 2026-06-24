# DCapp Stock

每日籌碼總覽 Dashboard 與 Discord Bot。專案會抓取 TWSE / TAIFEX 官方資料，整理成網頁 Dashboard、快取 JSON、Discord 文字摘要與圖片。

## 快速啟動

在 Windows 直接執行：

```text
DCapp_stock_open.bat
```

啟動後開啟：

```text
http://127.0.0.1:8080
```

保持命令視窗開啟即可使用；要停止服務請按 `Ctrl+C`。

## 主要功能

- 頁首顯示日期、大盤指數、漲跌點數、漲跌百分比、資料更新時間。
- 現貨區顯示上市成交金額、外資 / 投信 / 自營買賣超，單位為億元。
- 期貨區顯示臺股期貨法人未平倉多單、空單、淨額。
- 大額交易人區顯示臺股期貨組合 `TX+MTX/4+TMF/20` 所有契約前五大、前十大淨值。
- 選擇權區顯示 PCR、小台指散戶多空比、外資選擇權金額、台指選擇權法人多空未平倉。
- 外資選擇權金額與外資選擇權淨額提供近 30 日長條圖。
- 外資操作判讀整合外資現貨、前五 / 前十大淨值、PCR、外資選擇權金額，標示外資偏多、偏空、偏對沖或中性。
- 網頁下方保留近 30 個交易日明細。
- Discord 文字只顯示外資操作判讀，圖片顯示近 15 日明細表。

## 資料來源

- TWSE MI_INDEX：大盤指數、漲跌點數、漲跌百分比、上市成交金額。
- TWSE BFI82U：外資、投信、自營商上市買賣超金額。
- TAIFEX 期貨三大法人：臺股期貨與小台指法人多空未平倉。
- TAIFEX 期貨每日交易行情：小台全體未平倉量。
- TAIFEX 大額交易人：臺股期貨組合前五大、前十大交易人留倉。
- TAIFEX Put/Call Ratio：選擇權 PCR。
- TAIFEX 選擇權買賣權分計：外資選擇權金額、台指選擇權法人多空未平倉。

## 重要公式

大額交易人淨值：

```text
買方合計所有契約 - 賣方合計所有契約
```

小台指散戶多空比：

```text
小台指散戶留倉量 / 小台指全體未平倉量
= -1 * 小台指三大法人未平倉淨額 / 小台全體未平倉量
```

外資選擇權金額：

```text
外資選擇權多方金額 - 外資選擇權空方金額
```

## 顏色規則

- 正值、買超、多方：黑色。
- 負值、賣超、空方：紅色。
- 零值或缺資料：灰色。

## Discord 設定

本機私密設定放在：

```text
discord_config.json
```

請不要把 `discord_config.json` 上傳 GitHub。範例檔請參考：

```text
discord_config.example.json
```

格式如下：

```json
{
  "DISCORD_BOT_TOKEN": "your bot token",
  "DISCORD_CHANNEL_IDS": ["123456789012345678"],
  "DISCORD_SEND_AFTER_REFRESH": "1",
  "DISCORD_BOT_ENABLED": "1"
}
```

支援多個頻道 ID；網頁「傳送 Discord」按鈕會把相同文字與相同圖片送到所有頻道。

## Discord 指令

- `/stock_today`：傳送外資操作判讀文字與近 15 日明細圖片。
- `/stock_chart`：傳送外資操作判讀文字與近 15 日明細圖片。
- `/stock_refresh`：更新資料後傳送外資操作判讀文字與近 15 日明細圖片。

## 專案檔案說明

```text
app.py
```

主程式。負責資料抓取、資料解析、資料快取、HTTP API、靜態圖片產生、Discord Bot 與 Discord REST 傳送。

```text
templates/index.html
```

網頁 Dashboard。負責頁面排版、卡片、sparkline、長條圖、近 30 日明細表、更新資料與傳送 Discord 按鈕。

```text
data/latest.json
```

最新資料快取。網頁和 Discord 都讀這份資料。`schemaVersion` 目前是 `2`。

```text
static/overview-chart.png
static/latest-chart.png
```

每日籌碼快照圖，程式可重新產生。

```text
static/discord-history-detail.png
```

Discord 使用的近 15 日明細圖片，程式可重新產生。

```text
DCapp_stock_open.bat
```

Windows 啟動檔。會啟動本機 web server 並開啟瀏覽器。

```text
requirements.txt
```

Python 套件需求。

```text
discord_config.json
```

本機 Discord token 與頻道設定。此檔包含私密資訊，不可上傳。

```text
discord_config.example.json
```

可上傳的 Discord 設定範例，不含真實 token。

```text
github_upload/
```

整理後可上傳 GitHub 的版本。已排除 `.venv`、`.git`、logs、`__pycache__`、真實 Discord 設定。

## 資料模型重點

`data/latest.json` 主要包含：

- `marketIndex`：大盤指數、漲跌點數、漲跌百分比。
- `cashMarket`：上市成交金額。
- `spotInstitutional`：外資、投信、自營商買賣超金額。
- `futuresInstitutional`：期貨法人多單、空單、淨額。
- `retailMiniFutures`：小台指散戶留倉量、小台全體未平倉量、小台散戶多空比。
- `largeTraderFutures`：臺股期貨組合前五大、前十大交易人淨值。
- `optionPcr`：成交量 PCR、未平倉 PCR。
- `foreignOptionAmount`：外資選擇權多方金額、空方金額、淨額。
- `txoInstitutionalOpenInterest`：台指選擇權法人多空未平倉。
- `foreignPositionView`：外資操作判讀、分數、理由與各子項訊號。

## 常用開發指令

語法檢查：

```text
.venv\Scripts\python.exe -m py_compile app.py
```

檢查資料筆數與最新日期：

```text
.venv\Scripts\python.exe -c "import app; p=app.store.load(); print(len(p['rows']), p['latest']['dateLabel'])"
```

重新產生靜態圖片：

```text
.venv\Scripts\python.exe -c "import app; p=app.store.load(); app.generate_static_files(p)"
```

產生 Discord 訊息預覽：

```text
.venv\Scripts\python.exe -c "import app; p=app.store.load(); m=app.build_discord_message(p); print(m['content']); print(m['chartPath'])"
```

## 修改指南

- 要改資料來源或解析規則：修改 `app.py` 的 client / parser 類別。
- 要改外資操作判讀：修改 `build_foreign_position_view()` 與相關分類函式。
- 要改 Discord 文字：修改 `discord_summary()`。
- 要改 Discord 圖片：修改 `draw_history_detail_chart()`。
- 要改網頁卡片或表格：修改 `templates/index.html`。
- 改完後請同步需要上傳的檔案到 `github_upload/`。
