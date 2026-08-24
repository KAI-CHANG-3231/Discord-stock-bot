# Discord Stock Bot 版本與分支命名規範

本專案自下一個正式版本起統一使用 Semantic Versioning（SemVer），避免再把專案名稱、分支名稱與版本號混在一起。

## 正式版本號

固定格式：`vMAJOR.MINOR.PATCH`

- `MAJOR`：不相容的架構、設定或資料格式變更，例如 `v5.0.0` → `v6.0.0`。
- `MINOR`：向下相容的新功能，例如 `v5.0.0` → `v5.1.0`。
- `PATCH`：向下相容的錯誤修正，例如 `v5.1.0` → `v5.1.1`。
- 測試版本：`v5.1.0-beta.1`、`v5.1.0-rc.1`。

版本號一律使用小寫 `v`、三段數字與句點。不要再使用 `V5`、`DC_data_stockV5`、`stockdataDCV5` 等格式。

## 分支命名

長期分支：

- `main`：唯一正式、可部署的版本，也是 GitHub 預設分支。
- `develop`：只有在同時開發多項大型功能時才建立；一般小型修改可直接由 `main` 建短期分支。

短期分支格式：`類型/小寫-kebab-case-說明`

- `feature/dealer-options-data`
- `feature/option-position-analysis`
- `fix/weekend-discord-schedule`
- `fix/neutral-color-display`
- `hotfix/discord-send-failure`
- `docs/versioning-policy`
- `chore/frontend-build`
- `release/v5.1.0`

規則：

- 只使用英文小寫、數字、連字號與一個用途前綴。
- 分支名稱不放專案名稱，也不把版本號當成功能分支名稱。
- 合併後刪除短期分支；正式版本由 Git tag 保存。
- 歷史快照若必須保留，使用 `archive/legacy-v1`、`archive/legacy-v2`。

## Git tag 與 GitHub Release

- Git tag：`v5.0.0`
- Release 標題：`Discord Stock Bot v5.0.0`
- Release 說明固定分成 `新增`、`修正`、`變更`、`升級注意事項`。
- 已發布的 tag 不移動、不覆寫；若內容有問題，發布下一個 patch 版本。

## Commit 訊息

採 Conventional Commits：

- `feat: add dealer options chip data`
- `fix: skip scheduled Discord delivery on weekends`
- `fix: unify neutral status color`
- `docs: add versioning policy`
- `chore: rebuild frontend assets`

一個 commit 只描述一組相關變更；標題使用英文小寫動詞，控制在約 72 個字元內。

## 現有版本遷移對照

| 現有名稱 | 定位 | 建議處理 |
| --- | --- | --- |
| `stockdataDCV4` | 目前預設與最新開發線 | 完成本次驗證後改名為 `main` |
| `Discord-datastockV2` | 舊版分支 | 改名為 `archive/legacy-v2` 或確認無需保留後刪除 |
| `Discord-datastock` | 最早舊版分支 | 改名為 `archive/legacy-v1` 或確認無需保留後刪除 |
| `DC_data_stockV2` | 舊版 tag | 保留，不重新命名，Release 標記為 Legacy v2 |
| `DC_data_stockV3` | 舊版 tag | 保留，不重新命名，Release 標記為 Legacy v3 |
| `V4` | 舊版 tag | 保留，不重新命名，Release 標記為 Legacy v4 |

本次包含週末排程、判讀規則、自營商選擇權資料等較完整功能更新，建議作為新命名規範的第一個正式版本：`v5.0.0`。

## 發布流程

1. 從 `main` 建立功能或修正分支。
2. 完成程式檢查、測試與敏感檔案確認。
3. 合併回 `main`，確認 Dashboard 與 Discord 輸出。
4. 建立不可移動的 tag，例如 `v5.0.0`。
5. 建立同名 GitHub Release 並列出變更。
6. 緊急修正使用 `hotfix/...`，完成後發布下一個 patch 版本。

## 不可進入版本庫的檔案

- `discord_config.json`
- `.env` 與任何 token、webhook 或私密頻道資料
- `.venv/`
- `logs/`
- `__pycache__/`、`*.pyc`

