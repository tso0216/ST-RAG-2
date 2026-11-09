# strag_v3：時空 RAG

用旅客遊記裡的親身經驗，回答「某個地點在某個時間是什麼狀況」。
術語（片段、地點、別名、景點、區域、時段、時間退讓、空間退讓）以根目錄 `GLOSSARY.md` 為準，設計決策在 `docs/adr/`。

這份 README 給接手的 agent 看：讀完應該不用再翻原始碼，就知道系統做什麼、資料長什麼樣子、怎麼跑。細節以各模組開頭的 docstring 為準。

## 整體流程

```
遊記（Reddit 連結／PTT 文章 JSON）
  └─ extract：LLM 把文章拆成片段（地點 × 月份 × 平日/假日 × 時段 + content）
       └─ place.py：地點名稱 → Nominatim → OSM 物件（place 表，含外圍行政區）
            └─ 寫進 SQLite：content、place
問題
  └─ rag/llm.plan：規劃器（Opus）把問題轉成檢索計畫
       └─ rag/retrieve：地點解析 → 時間硬過濾 → 相關判斷（JEV）→ 退讓
            └─ rag/group：依 compose / group_by 整理成段和分組
                 └─ rag/llm.answer：生成器（Opus）照證據回答、標出處、講明退讓
```

## 目錄

| 路徑 | 做什麼 |
|---|---|
| `place.py` | 地點解析（抽取和檢索共用）。先查 `nominatim_cache`，沒有才打 Nominatim；景點用 `layer=poi`，區域用 `layer=address` 且只收行政區。結果寫進 `place` 表，記錄外圍行政區 `outer_id`。支援別名（`place_alias`）。`Places.resolve / scope / outer` 是檢索用的三個方法 |
| `time_slots.md` | 時段鐘點表（早上 5–10、中午 11–13、下午 14–17、晚上 18–4），抽取和規劃器 prompt 共用，prompt 裡的 `{{時段表}}` 會被換成它 |
| `extract/` | 抽取。`__main__.py` 命令列、`pipeline.py` 主流程、`fetch.py` 抓 Reddit（Arctic Shift）或讀文章 JSON、`llm.py` 呼叫 LLM（有快取 `.cache/extract/`）、`store.py` 寫 DB、`prompts/system.md` 抽取規則 |
| `rag/plan.py` | 檢索計畫的資料結構：`Plan(sub_queries, group_by, compose)`、`SubQuery(space, time, aspect)`、`Space(name, name_ja, city, kind)` |
| `rag/timematch.py` | 時間標籤：`TimeSpec`（片段）、`TimeQuery`（問題）、`matches`（硬過濾）、`widened`（時間退讓） |
| `rag/retrieve.py` | `await Retriever.retrieve(plan, question)`：核心檢索與退讓 |
| `rag/relevance.py` | gate=jev 的相關判斷：每個候選片段問 JEV 一次（判準、`state` 格式），結果快取在 DB 的 `jev_cache` 表；JEV 呼叫在根目錄 `service/jev.py` |
| `rag/group.py` | merge / contrast 與 group_by 分組 |
| `rag/evidence.py` | 輸出結構：`Evidence`、`SubQueryResult`、`Available`、`Group`、`Section` |
| `rag/params.py` | 可調參數：`gate`（`jev` 預設／`semantic`）、`jev_model=jev-1.14.0`、`jev_pass=0.5`、`jev_concurrency=4`、`delta=0.3`（semantic 用）、`unknown_discount=0.8`、`time_backoff`、`space_backoff` |
| `rag/embedding.py` | `text-embedding-3-large`，結果快取在 DB 的 `embedding` 表 |
| `rag/dense.py` | Dense baseline：不看計畫，只用原問題取 top-k（對照組） |
| `rag/llm.py` + `rag/prompts/` | 規劃器（`planner.md`）和生成器（`generator.md`），模型 `claude-opus-5-5`，structured output；實際呼叫在根目錄 `service/llm.py` |
| `eval/` | 評估。`questions.py` 讀題目檔、`metrics.py` 檢索指標、`full/` 跑完整系統（規劃器正確率、LLM 評審答案）、`question/question_type.md` 題型定義 |

## 資料（SQLite）

預設 DB 是 `data/main.db`（`extract/paths.py`），用 `scripts/db/create_main_db.py` 建。PTT 資料在 `data/ptt.db`，跑時加 `--db data/ptt.db`。

| 表 | 內容 |
|---|---|
| `content` | 片段：`article_id`、`poi_id`→place、`poi_name`、`month`（`1`–`12`、`M-M`、`春夏秋冬`、`不明`）、`day_type`（平日/假日/不明）、`time`（早上/中午/下午/晚上/全天/不明）、`content`（只記「換個時間就可能不同」的狀態，不記地點屬性） |
| `place` | 一列一個 OSM 物件：`kind`（景點/區域）、`name_ja`、`name_zh`、座標、`boundary`（區域的 geojson）、`outer_id`（外圍行政區） |
| `place_stats` | view：每個地點的片段數 |
| `place_alias` | 人工別名 → 查詢鍵（`scripts/db/alias_place.py` 加） |
| `nominatim_cache` | Nominatim 原始回應快照；論文重跑時只讀快取 |
| `embedding` | embedding 快取（用到時才建） |
| `jev_cache` | JEV 判斷快取：鍵（模型, 判準 hash, 原問題, aspect, 片段 id），存 noul、實際回答的模型版本、建立時間；有快取就不重問，論文重跑靠它 |

`data/ptt.db` 現況（2026-11）：150 篇、312 個片段、663 個地點（有片段的約 140 個）。片段集中在東京：淺草寺 61、東京晴空塔 31，其餘多半 1–9 筆。時段不明 120 筆、平日/假日不明 155 筆。

## 檢索規則（`rag/retrieve.py`）

每個子查詢：

1. **地點**：`name_ja + city + kind` 解析成 OSM 物件。解析不到 → 空結果、標 `place_unresolved`，不退讓。景點只取自己的片段；區域取自己加上範圍內所有地點（遞迴 `outer_id`）的片段。`space` 為 null 不限地點。
2. **時間硬過濾**：月份（換成月份集合，有交集即符合；季節 春3–5 夏6–8 秋9–11 冬12–2）、平日/假日（字面）、時段（片段是 `全天` 時符合任何時段）三個維度都要符合。片段某維度是 `不明` 時算符合，但標 `time_unknown`，分數乘 0.8。
3. **相關判斷**（`gate`）：
   - `jev`（預設）：每個候選片段各問 JEV（`jev-1.14.0`）一次，`state` 是原問題、aspect、片段內容（不送時間標籤）；noul ≥ 0.5 的全部通過，沒有數量上限。`relevance` 存 noul。JEV 重試後還是失敗，該題記成錯誤，不改用語意門檻。
   - `semantic`（消融）：`aspect`（沒有就用原問題）跟 content 的 cosine；取「≥ 該子查詢最高分 − δ」的全部片段，不是固定 top-k。`relevance` 存 cosine。
   - 排序：`score = relevance`，時間不明再乘 0.8；只影響排序，不影響過不過。
4. **退讓**（各只一次，有證據就停）：
   - 時間退讓：時段、月份各環狀往外擴一格（早上↔中午↔下午↔晚上↔早上、12↔1），平日/假日不擴。
   - 空間退讓：退到外圍行政區，照區域規則取片段，時間用原條件。
   - 一筆都沒通過才算沒有證據；退讓的新候選一樣經過相關判斷。
   - 都沒有 → 回傳空結果，附 `Available`：該地點有資料的時段、月份各幾筆。

之後依計畫整理：`merge` 合成一段（同片段只留最高分，退讓標記要每份都退讓才留）；`contrast` 每個子查詢一段。`group_by` 可選 `month`、`day_type`、`time_of_day`、`place`，可多選。

生成器規則（`rag/prompts/generator.md`）：只根據證據、每個說法標 `[片段 id]`、不同文章要講明是不同旅客、退讓或時間不明要講明跟問題的差距、沒證據時報有資料的時段/月份筆數、地點解析不到要請使用者換寫法。

## 怎麼跑

從專案根目錄跑，`PYTHONPATH=.:src`（pytest 已在 `pytest.ini` 設好）。需要 Anthropic、OpenAI 和 TypeSafe（JEV，`TYPESAFE_API_KEY`）的 API key（見 `service/llm.py`、`rag/embedding.py`、`service/jev.py`）；`rag` 和 `eval.full` 會先讀專案根目錄的 `.env`（`service/env.py`，只補沒設定的變數）。

```bash
# 建 DB
python scripts/db/create_main_db.py --db data/main.db
# 抽取（PTT 文章 JSON 資料夾，推文一起抽）
PYTHONPATH=.:src python -m strag_v3.extract data/ptt_article --ptt --db data/ptt.db --jobs 4
# 問問題（--json 輸出完整結構；--no-time-backoff / --no-space-backoff / --gate semantic 做消融）
PYTHONPATH=.:src python -m strag_v3.rag "平日早上淺草寺人多嗎？" --db data/ptt.db
# 評估完整系統
PYTHONPATH=.:src python -m strag_v3.eval.full run data/mock_article/eval --split dev --judge [--gate semantic]
PYTHONPATH=.:src python -m strag_v3.eval.full compare src/strag_v3/eval/full/runs/*.json
# 測試（Nominatim 用 tests/fake_nominatim.py、JEV 用 tests/fake_typesafe.py，不打網路）
pytest
```

## 跟一般 LLM / native RAG 的差別（論文賣點）

- **時間硬過濾**：問「早上」不會撈到下午的片段；native RAG 只靠語意，常把不同時段的經驗混在一起。
- **空間階層**：問區域（例如押上）會取到範圍內景點（十間橋、晴空塔）的片段，即使內文沒寫到區名。
- **退讓加揭露**：沒有完全符合的資料時，往相鄰時段/月份或外圍區域找，並在答案裡講明「這是十一月的經驗」；都沒有時明說沒資料、列出有資料的時段月份。一般 LLM 只會用常識補答。
- **多旅客、可追溯**：每句附片段 id，區分不同旅客不同天的經驗；可以 contrast（平日 vs 假日、早上 vs 下午）或依月份、時段分組。

用 `data/ptt.db` 好示範的問題：

- 找時間：「淺草寺幾點去人最少？」（早上 7–8 點空、9:40 已多人、晚上 8–9 點後幾乎沒人：片段 184、124、67、134、46、141、6、140）
- 比較：「淺草寺平日早上跟假日早上差多少？」（平日 134、184、67；假日 135、62）
- 找地點：「冬天晚上在押上哪裡拍晴空塔倒影？」（區域 → 十間橋 45、98、100）
- 依月份分組：「晴空塔晚上看夜景，各月份的能見度如何？」（2 月 33、93；4 月 61）
- 季節＋區域：「春天晚上在台東區哪裡可以賞夜櫻？」（淺草寺 140、上野恩賜公園 161）
- 沒資料時：問淺草寺附近沒有片段的地點，看空間退讓和揭露（未實測，地點要先能被 Nominatim 解析）

## 已知限制

- 時段比鐘點粗（7 點和 10 點都算早上），鐘點只留在 content 給生成器引用。
- 片段大多集中在少數景點，冷門地點常常只能靠退讓或回「沒資料」。
- 時間 `不明` 的片段很多，硬過濾時都會被放進來（打折並標記）。
- 地點解析依賴 Nominatim 第一筆，寫法對到錯的 OSM 物件時要加別名。
