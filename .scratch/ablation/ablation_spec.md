# Spec：消融實驗

Status: needs-triage

## 問題

比較實驗（`eval/baseline/`）只證明主系統整體比對照組好，沒有說明是哪個元件的功勞。論文要一張消融表：每次拿掉一個元件，看指標掉多少；另外要一個上限，交代剩下的差距是生成器還是檢索造成的。

## 解法

在 `src/strag_v3/eval/ablation/` 放消融實驗。題目（ptt_v2 50 題）、生成模型、評審、指標、結果檔格式都沿用 `eval/baseline/`，只多出「變體」的定義和一張跟 `full` 比的表。

```bash
PYTHONPATH=.:src python -m strag_v3.eval.ablation run --system full
PYTHONPATH=.:src python -m strag_v3.eval.ablation run --system no_time_filter --base src/strag_v3/eval/ablation/runs/<full 結果檔>
PYTHONPATH=.:src python -m strag_v3.eval.ablation judge <結果檔> [--base <full 評審檔>] [--n 3]
PYTHONPATH=.:src python -m strag_v3.eval.ablation report src/strag_v3/eval/ablation/runs/*.judge.json
PYTHONPATH=.:src python -m strag_v3.eval.ablation region-check        # 離線，不呼叫模型
```

## 放進去的變體

| `--system` | 做法 | 要證明什麼 | 預估（用現有 strag 結果檔和 `data/ptt.db` 離線算的） |
|---|---|---|---|
| `full` | 主系統預設參數 | 基準 | 片段 P 0.757、R 1.000、時間違規 0 |
| `no_time_filter` | 不做時間硬過濾，地點範圍內的片段全部送相關判斷 | 時間硬過濾 | 候選片段 451 → 1048 筆；JEV 的判準明寫「不用判斷時間是否符合」，所以時間不符的片段會通過，時間違規率和無支持比例應該上升 |
| `region_llm` | 區域展開不用 OSM 階層，改由 LLM 從「有片段的地點清單」挑出在區域內的地點 | OSM 空間階層比 LLM 常識好（或至少一樣好、更便宜） | 結果不是預先注定的，是空間階層這一塊的主要對照；只影響找地點 10 題 |
| `no_region` | 區域不展開，只取掛在區域本身的片段 | 空間階層的下限 | 找地點 10 題的 29 個標準片段全部掛在區域底下的地點，片段 R 1.000 → 0；其他 40 題不變。這是必然的結果，論文裡只當下限，不當主要證據 |
| `no_gate` | 不做相關判斷，時間過濾後的候選全部通過 | 相關判斷 | 取回 312 → 451 筆，標準片段只有 157 筆，P 大幅下降 |
| `gate_semantic` | 相關判斷改回語意門檻（`gate=semantic`，δ=0.3） | JEV 比語意門檻好 | 舊題庫上 semantic 是 P 0.82、R 0.98，要在 ptt_v2 重量 |
| `oracle_evidence` | 不規劃、不檢索，直接把標準片段交給生成器 | 生成器的上限 | `full` 的無支持比例 0.58 有多少是檢索帶進來的、多少是生成器和評審本身的底噪 |

### 空間階層的論證怎麼寫

`no_region` 掉到 0 是題目設計決定的，單獨放沒有說服力。空間階層靠三樣東西一起撐：

1. baseline 表已有的對比：找地點題的片段 R，`dense_frag`（沒有階層，靠語意）0.517、`dense_filter`（字串比對）0.025、`strag` 1.000。
2. `region_llm`：回答「LLM 自己就知道區域裡有什麼，為什麼要 OSM」。
3. 階層涵蓋率（`region-check`，見下）：回答「標準片段是從系統自己的展開範圍挑的，階層漏掉的地點不會出現在標準答案裡」這個循環性。

## 不放的變體和理由

| 變體 | 理由 | 什麼時候可以放 |
|---|---|---|
| 關時間退讓 | 50 題只有 stay-10 一題走時間退讓，其他 49 題結果一模一樣 | 補了退讓題組之後 |
| 關空間退讓 | 50 題沒有任何一題走空間退讓，結果跟 `full` 完全相同 | 同上 |
| 排除時間不明的片段 | 標準片段裡只有 1／157 筆在問到的維度是不明；指標又規定「時間不明」的排除片段不計分。所以這個變體的 P、R 幾乎不變，量不出設計的好處，只會顯示取回量少了三成（312 筆裡 98 筆）。放進表裡反而讓人質疑為什麼要收時間不明的片段 | 要有「只有時間不明片段可答」的題目，或有衡量答案資訊量的指標 |
| 用題目標註的地點和時間直接檢索（跳過規劃） | 規劃器在這 50 題已經等於標註：46 題的候選片段集合跟標註條件完全一樣，另外 4 題是退讓題和比較題重複計數，`full` 的片段 R 已經是 1.000。跑出來會跟 `full` 一樣。而且題目出題時就用規劃器驗過，這個一致是出題流程保證的，不能當成規劃器的證據 | 有不經過系統出的獨立題目之後 |

「排除時間不明」的離線數字要留意：`full` 取回的非標準片段 155 筆裡，97 筆是問到的維度不明。這是 `full` 片段 P 只有 0.757、找時間題無支持比例 0.90 的可能來源，`oracle_evidence` 的結果會幫忙確認。

## 實作決定

### 主系統要加的開關（`rag/params.py`、`rag/retrieve.py`）

預設值不變，主系統行為不變。

- `Params.time_filter: bool = True`：關掉時 `_run` 不做 `time.matches`，候選是整個 pool；時間退讓那一輪不跑（沒有東西可擴）。片段的 `time_unknown` 標記照舊。
- `Params.region_scope: bool = True`：關掉時區域只取 `{place.id}` 的片段，不呼叫 `Places.scope`；空間退讓退到外圍行政區時也一樣只取外圍本身。
- `Params.gate` 多一個值 `"none"`：候選全部通過，`relevance = 1.0`，不建 `JEVGate`、不算 embedding。`GATES` 和 `--gate` 的選項跟著加。

規劃器和生成器的提示詞都不動：`no_time_filter` 的規劃器照樣輸出時間條件，生成器照樣看得到片段的時間標籤和問的時間。這樣差距只來自檢索有沒有過濾。

### 變體表（`ablation/variants.py`）

一個 dict：名稱 → `Params` 的覆寫。之後補退讓題組時，加一行 `"no_time_backoff": {"time_backoff": False}` 就好。

```python
VARIANTS = {
    "full": {},
    "no_time_filter": {"time_filter": False},
    "no_region": {"region_scope": False},
    "no_gate": {"gate": "none"},
    "gate_semantic": {"gate": "semantic"},
}
```

`baseline` 的 `Strag` 寫死 `DEFAULT`，改成收一個 `params` 參數（預設 `DEFAULT`），ablation 直接用它，不另寫一份。

### `oracle_evidence`

- 從題目標註組出檢索計畫，不呼叫規劃器：
  - 比較題：每個 `options` 一個子查詢（該選項的 `space`、`when`、題目的 `aspect`），`compose=contrast`，每個子查詢的證據是該選項的 `relevant_contents`。
  - 其他題：一個子查詢（題目的 `space`、`when`、`aspect`），`compose=merge`，證據是 `relevant_contents`。
  - `group_by` 一律空。
- 證據的 `relevance = 1.0`，`time_unknown` 照片段的標籤；`coverage` 不是 `exact` 的題（目前只有 stay-10）標 `time_backoff=True`，生成器才會照規則講明退讓。
- 用主系統的生成器提示詞和 `build_sections`、`build_answer_prompt`。
- `Space` 需要的 `name_ja` 從 `place` 表用 `place_id` 讀，`city` 留空（不會拿去解析）。
- `baseline/questions.py` 的 `Question` 沒有 `space` 和 `aspect`，要補這兩欄（比較題的 `Option` 補 `space`）。
- 成本：LLM 呼叫 1、JEV 呼叫 0。

### `region_llm`

- 只換「區域 → 範圍內的地點」這一步，其他（地點解析、時間硬過濾、JEV 相關判斷、兩種退讓、生成器）都跟 `full` 一樣。景點的子查詢不受影響。
- `Retriever` 的建構子多收一個選用的 `region_expander`（輸入區域的 `Place`，回傳地點 id 集合）。有給的時候，區域的範圍用它，不呼叫 `Places.scope`；空間退讓退到外圍行政區時也用它。主系統不傳，行為不變。
- ablation 的 expander：把區域名稱（中、日文）和 DB 裡所有有片段的地點（311 個，給 id、中文名、日文名，不給座標、不給 `outer_id`）交給 `claude-opus-5-5`，structured output 回傳在區域內的地點 id。提示詞放 `ablation/prompts/region.md`。
- 給清單而不是讓 LLM 自由列名稱：自由列名稱會把「名稱寫法對不上」算成 LLM 的錯，對照組變弱。給清單是這個做法最強的版本。
- 同一個區域在一次 `run` 裡只問一次。LLM 回的 id 集合存在 `extra.region_places`，之後算指標不用重跑。
- 成本：有區域子查詢的題 LLM 呼叫數加 1，輸入 token 另外記（清單約 311 列，會隨資料庫變大而變貴，這點要寫進論文）。
- 除了共用指標，報表另外列這 10 題「LLM 挑的地點」對「OSM 階層範圍內的地點」的 precision、recall（只算有片段的地點）。

### 階層涵蓋率（`region-check`）

離線檢查，不呼叫任何模型：

```bash
PYTHONPATH=.:src python -m strag_v3.eval.ablation region-check
```

- 對象：題目用到的 9 個區域（另外印全部有 `boundary` 的區域的合計；785 個區域裡 555 個有邊界）。
- 每個區域比兩個集合，只算有片段的地點：
  - 階層：`outer_id` 往下遞迴展開到的地點（`Places.scope`）。
  - 幾何：座標（`lat`、`lon`）落在區域 `boundary` 多邊形裡的地點。
- 輸出每個區域的：兩邊都有、只有幾何有（階層漏掉）、只有階層有（座標在邊界外）的地點數和片段數，附地點名稱。
- 找地點 10 題另外列：「只有幾何有」的地點裡，符合該題時間條件的片段有幾筆。這些是出題時看不到、可能該算標準片段的候選，數字是 0 才能說 R 1.000 不是循環造成的；不是 0 就要回頭補標註或修 `outer_id`。
- 點在多邊形內的判斷自己寫（射線法，支援 Polygon 和 MultiPolygon、含洞），不加新套件。

### 沿用 `full` 的答案（`--base`）

生成和評審都不快取，同一題重跑會有雜訊（JEV 官方數字是同輸入 3.8% 會變）。`no_region` 有 40 題跟 `full` 拿到一模一樣的證據，重新生成只會把雜訊算成差距。

- `run` 把每題交給生成器的 user prompt 的 sha256 存在 `extra.prompt_hash`。
- `run --base <full 結果檔>`：某題的 `prompt_hash` 跟 base 相同時，直接抄 base 的答案，`extra.same_as_base = true`，不呼叫生成器。成本欄照抄 base 的。
- `judge --base <full 評審檔>`：`same_as_base` 的題抄 base 的判斷，不重問。
- `oracle_evidence` 不用 `--base`。

### 檔案

| 檔案 | 做什麼 |
|---|---|
| `ablation/__main__.py` | 命令列：`run`、`judge`、`report` |
| `ablation/variants.py` | 變體表、`oracle_evidence` 系統、`region_llm` 的 expander |
| `ablation/prompts/region.md` | `region_llm` 的提示詞 |
| `ablation/region_check.py` | 階層涵蓋率 |
| `ablation/report.py` | 消融表 |
| `ablation/runs/` | 結果檔和評審檔，命名和格式同 baseline，不覆寫 |

`judge`、`metrics`、`results`、`questions`、`fragments`、`run_all` 直接從 `eval.baseline` import；`results` 的存檔資料夾已經是參數。

### 報表

主表一列一個變體，`full` 在第一列，其他列每個數字後面附跟 `full` 的差：

| 欄 | 說明 |
|---|---|
| expect 覆蓋率、無支持比例 | 附 95% 信賴區間；差距另外做配對 bootstrap（同一組重抽的題目），信賴區間不含 0 才標 `*` |
| 片段 P、R、F1、時間違規率 | `oracle_evidence` 這幾欄留空 |
| 取回片段數／題、輸入 token／題、JEV 呼叫／題 | 交代拿掉元件省了多少、多花多少 |
| 跟 `full` 證據不同的題數 | 讓讀者知道差距是幾題造成的 |

另一張依題型分的表，格式同 baseline。`no_region` 的效果只在找地點題，要靠這張表才看得出來。

### 資料與成本

- DB 用 `data/ptt.db`。`no_time_filter` 會多問約 600 個（問題 × 片段）的 JEV 相關判斷，照主系統原本的行為寫進 `jev_cache`；其他變體用到的判斷都已經在快取裡。
- `jev-1.14.0` 已公告停用，`no_time_filter` 要趁還能呼叫時先跑。
- embedding 快取沿用 baseline 的 `chunks.db`。
- 每個變體約 50 次規劃器加 50 次生成器（有 `--base` 的會更少），評審每題約 5 次 JEV。

## 測試

用 `tests/fake_typesafe.py` 和 `tests/fake_nominatim.py`，不打網路。

- `time_filter=False`：時間不符的片段會進候選；時間退讓那一輪不跑。
- `region_scope=False`：區域只拿到掛在自己身上的片段；景點不受影響。
- `gate="none"`：候選全部通過，沒有 JEV 呼叫。
- 三個開關都是預設值時，`tests/rag/` 現有測試全過。
- `region_expander`：有給時區域的範圍照它回的 id，景點不受影響；沒給時跟現在一樣。同一個區域只問一次。
- `region-check`：用假的邊界和座標，驗兩邊都有、只有幾何有、只有階層有三種分類；MultiPolygon 和有洞的多邊形判對。
- `oracle_evidence`：一般題是一段、比較題每個選項一段，證據剛好是標準片段；stay-10 的證據帶退讓標記。
- `--base`：`prompt_hash` 相同的題抄答案、不呼叫生成器；不同的題照常生成。
- 報表：差距欄和「跟 `full` 證據不同的題數」算對。

## 不做的事

- 不改 baseline 的五個系統和它們的結果檔。
- 不調任何參數（δ、`jev_pass` 照預設）。
- 不做兩個元件同時拿掉的組合。
- 不把相關判斷換成一般 LLM（那是評審可信度那一塊的實驗，另開 spec）。
