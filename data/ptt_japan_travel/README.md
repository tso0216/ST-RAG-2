# ptt_japan_travel

PTT Japan_Travel 板的 `[問題]` 文，用來調查旅客實際會問哪些時空問題。分析見 `.scratch/travel-question-survey/survey.md`，爬取和分類腳本也在那個資料夾。

- 範圍：最近 80 頁索引裡的所有 `[問題]` 文，共 410 篇，發文期間 2026/5/19 到 11/7（2026/11/8 爬取）。

## 檔案

| 檔案 | 內容 |
|---|---|
| `questions_raw.json` | 410 篇：`url`、`title`、`time`、`body`（內文，最多 3000 字，不含推文）。有 5 篇只有標題、沒有內文。 |
| `questions_classified.json` | 有內文的 405 篇。除了上面的欄位，另有 `pushes`（推文，即回答）和 `questions`（LLM 拆出的提問，只留 `quote` 問題原文和 `category` 分類）。 |

注意：

- `pushes` 是物件陣列，每個元素是 PTT 的一行推文：`tag`（推／噓／→）、`user`（推文者）、`content`（內容）、`time`（月/日 時:分，沒有 IP；有 4 行缺時間）。一則長推文會斷成好幾行，同一人連續的幾行要自己合併。由 `.scratch/travel-question-survey/crawl_pushes.py` 在 2026/11/8 重抓，包含只有網址或文章代碼的推文，也包含分類之後才新增的推文。
- `body` 開頭混有 PTT 的作者、標題、時間 metadata。
