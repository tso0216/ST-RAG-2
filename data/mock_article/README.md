# mock_article

手寫的遊記和檢索題目，用來測時空 RAG：旅客問「某景點在某個時間是什麼狀況」，看系統能不能撈到對的片段、回答對的內容。

```
data/mock_article/
├── README.md
├── mock_<地點>_<時空摘要>.json      遊記（正例和負例都放這層）
└── eval/
    └── <地點>_questions.json         題目
```

`eval/` 必須是子資料夾：extract 讀資料夾時只讀第一層的 `*.json`，題目放第一層會被當成文章。

現有範例：晴空塔，正例 2 篇、負例 2 篇、題目 3 題（`eval/skytree_questions.json`）。

## 流程

一個地點走一次下面的流程。**一定先出題，再寫遊記**，遊記是為了讓題目有答案、有干擾才寫的。

### 1. 出題

在 `eval/<地點>_questions.json` 寫 1–3 題，每題先想清楚三件事：

- 旅客會怎麼問（`question`，口語原句）
- 問題限定了哪些時空條件（`when`）
- 答案應該包含哪些重點（`expect`）

題目之間要有差異，常見的組合：

- 一題剛好對到某一篇的某個時段（例如「一月平日早上」）
- 一題對到另一篇的另一個時段（例如「冬天週末傍晚」）
- 一題要跨兩篇比較（例如「冬天什麼時候去比較好」）

### 2. 寫正例遊記

依題目需要寫 2 篇左右，讓每題都找得到答案：

- 同一地點的不同時空狀況分給不同篇、不同作者（`author` 不同），差異要明顯：排隊時間、人潮、看得到／看不到的東西。
- 時間要具體：幾月、星期幾、幾點；也可以混用「傍晚」「一開門」這種說法。
- 可以順便帶到別的地點（例如先去淺草寺），或放一句轉述（「聽說」「看到很多人說」），讓提取不會太簡單。
- 文字要像真人寫的心得，不要條列；每篇約 300–600 字。
- 寫完把 `expect` 對一遍，確認每個重點在文中都寫得出來。

### 3. 寫負例遊記

同一地點，寫 2 篇**時空條件不符合任何一題**的遊記，用來測檢索會不會撈錯：

- 先把所有題目的 `when` 列出來，負例的時間要全部避開。注意範圍大的條件：只要有一題是 `"month": "冬"`，負例就不能落在 12–2 月。
- 寫成難負例：主題、時段盡量跟正例相似，只差在題目限定的條件。例如正例是一月平日早上看富士山，負例就寫五月平日早上、一樣開門就上去、但看不到富士山。
- 寫進題目檔的 `negative_articles`。

### 4. 提取

```bash
cd src
../.venv/bin/python -m strag_v3.extract ../data/mock_article/
```

- DB 已經有片段的文章會略過，只抽新的。
- 要重抽就加 `--force`：會刪掉該篇的舊片段再寫入，**content id 會變**，做完要重做第 5 步。
- 預設每次都呼叫 LLM；加 `--cache` 才會用快取。

### 5. 對應片段

列出這個地點的所有片段：

```bash
sqlite3 data/main.db "SELECT id, article_id, poi_name, day_type, time, month, content
  FROM content WHERE article_id LIKE 'mock_skytree%' ORDER BY id"
```

逐題對照 `expect`，把回答需要的片段 id 寫進 `relevant_contents`：

- 只放回答這題真的要用到的片段；同篇但時段不符的不要放（例如問傍晚，就不放天黑後下樓那段）。
- 負例的片段不放進任何一題。
- 順便檢查提取結果有沒有怪東西（地點名稱寫錯、混進奇怪的字），有的話用 `--force` 重抽那篇再重新對應。

## 遊記檔格式

```json
{
  "id": "mock_skytree_weekday_opening_fuji",
  "kind": "post",
  "source": "mock",
  "title": "一月底平日一開門就上晴空塔，富士山清楚到不像真的",
  "author": "mock_traveler_b",
  "created_at": "2026-01-28T21:30:00+09:00",
  "text": "出發前看到很多人說……"
}
```

| 欄位 | 說明 |
|---|---|
| `id` | 跟檔名相同，`mock_<地點>_<時空摘要>` |
| `kind` | 固定 `post` |
| `title`、`text` | 會送進提取的 prompt，`title` 會接在 `text` 前面 |
| `source`、`author`、`created_at` | 只是紀錄，不會送進 prompt；`author` 每篇不同 |

## 題目檔格式

```json
{
  "place_name": "東京晴空塔",
  "articles": ["mock_skytree_weekend_sunset_wind", "mock_skytree_weekday_opening_fuji"],
  "negative_articles": ["mock_skytree_may_weekday_morning_haze", "mock_skytree_august_sunday_evening"],
  "questions": [
    {
      "id": "q1",
      "question": "一月平日早上去晴空塔，看得到富士山嗎？要排多久？",
      "when": {"month": "1", "day_type": "平日", "time": "早上"},
      "relevant_contents": [9, 10, 11],
      "expect": ["開門前約二十分鐘到……", "富士山很清楚……"]
    }
  ]
}
```

| 欄位 | 說明 |
|---|---|
| `place_name` | 地點 |
| `articles` | 正例遊記的 id |
| `negative_articles` | 負例遊記的 id |
| `questions[].question` | 旅客會問的原句 |
| `questions[].when` | 時空條件，沒限制的欄位不寫 |
| `questions[].relevant_contents` | 回答需要檢索到的 `main.db` content id |
| `questions[].expect` | 答案應包含的重點 |

`when` 的格式跟 content 表一樣：

| 欄位 | 可用的值 |
|---|---|
| `month` | `1`–`12`、範圍 `M-M`（跨年寫 `12-2`）、`春` `夏` `秋` `冬` |
| `day_type` | `平日`、`假日` |
| `time` | `0`–`23`、範圍 `H-H`、`早上` `中午` `下午` `晚上` `全天` |
