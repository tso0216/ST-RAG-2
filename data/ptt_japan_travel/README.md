# ptt_japan_travel

PTT Japan_Travel 板的 `[問題]` 文，用來調查旅客實際會問哪些時空問題。分析見 `.scratch/travel-question-survey/survey.md`，爬取和分類腳本也在那個資料夾。

- 範圍：最近 80 頁索引裡的所有 `[問題]` 文，共 410 篇，發文期間 2026/5/19 到 11/7（2026/11/8 爬取）。

## 檔案

| 檔案 | 內容 |
|---|---|
| `questions_raw.json` | 410 篇：`url`、`title`、`time`、`body`（內文，最多 3000 字，不含推文）。有 5 篇只有標題、沒有內文。 |
| `questions_classified.json` | 有內文的 405 篇。除了上面的欄位，另有 `pushes`（推文）和 `questions`（LLM 拆出的提問與分類，欄位定義見 `classify.py`）。 |

注意：

- `pushes` 是字串陣列：每個元素是 PTT 的一行推文，一則長推文會斷成好幾行，也沒有推文者和時間。
- `body` 開頭混有 PTT 的作者、標題、時間 metadata。
