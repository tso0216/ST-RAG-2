# 01 qgen.py 補六個指令

Status: resolved
Blocked by: —

## 為什麼

題型 ticket 的主 session 只當協調者，要靠指令拿到短的輸出：各層有幾筆候選、草稿合併、盲審的輸入和對照。盲審一致率也要每個題型用同一套算法。

## 要做

在 `scripts/eval/qgen.py` 加六個子指令。候選和分層一律沿用現有的 `DB.layers`、`DB.must_judge`、`DB.pool`、`unknown_dims`、`places_of`，不要另寫一套規則。

- `layers <地點 id> [--when '<json>']`：檢索會依序試的每一層，一層一行：層名、撈的地點（id、名稱）、時間條件（時間退讓層印擴大後的條件）、候選數、其中限定維度不明的筆數。不印片段內容。
- `frag <片段 id>...`：印指定的片段，格式跟 `pool` 一樣。
- `usage [資料夾]`：資料夾（預設 `src/strag_v3/eval/questions/ptt_v2`）裡所有題目檔用掉的地點：每個地點在各題型和合計的題數，標出到上限的（沿用 `MAX_PER_PLACE_TYPE`、`MAX_PER_PLACE`）；再列出已出過的（地點、面向、時間條件）組合。沒有題目檔就印「還沒有題目」。
- `merge <題目檔> <草稿>...`：把草稿裡的題目依 id 排序，合併成題目檔（`annotation_note` 照 generate.md〈檔案〉）。id 重複就報錯，不寫檔。
- `blind-input <題目檔> [題目 id...]`：給盲審子代理的 JSON。開頭一段說明（要判什麼、結果寫成什麼格式），接著每題只放 `id`、`type`、`question`、`when`、`asks`、`aspect`、`aspect_rule`，和要判的層：跟 `must_judge` 一樣從第一層到 `coverage` 那層（`none` 是每一層；比較題是每個選項的原條件）。每層寫撈的地點範圍、時間條件、可以直接跑的 `qgen.py pool` 指令，和這層要判的片段 id（同一筆只放在第一次出現的那層；比較題同一筆出現在多個選項時，標出它屬於哪些選項）。不能帶出 `coverage`、`relevant_contents`、`relevant_articles`、`excluded`、`expect`、`expect_sources`、`label_issues`、`options[].relevant_contents`。
- `blind-diff <題目檔> <盲審檔>...`：盲審檔格式 `{題目 id: {"relevant": {片段 id: 算數那句原文}, "excluded": {片段 id: 理由碼}}}`，可以給多個檔，合併後對照。片段分三類：收、不計分（`時間不明`）、其他不收（`無關`、`別處`、`時間矛盾`）。印出標註 × 盲審的 3×3 對照表和一致率，再逐筆列出不一致的（題目 id、片段 id、標註、盲審、盲審引文）。另外列出：盲審漏判的候選、判了候選以外的片段、盲審引文不是片段原文的。

同步更新：

- `qgen.py` 開頭 docstring 的指令清單。
- generate.md〈工具〉的表格加這六個指令。〈驗證〉的盲審段改成用 `blind-input` 產生子代理的輸入、用 `blind-diff` 對照；給子代理的資訊跟原本一樣，不多不少。審 `expect` 那段補一句：收進來的片段全文用 `frag` 取。generate.md 其他段落不要動。

只改 `scripts/eval/qgen.py` 和 generate.md。

## 完成條件

用 generate.md〈範例〉裡完整的 stay-01 建一個草稿，放在 `.scratch/ptt-v2-questions/tmp/`（`check` 要通過）來試：

- `layers 50 --when '{"month": ["3"], "time": ["晚上"]}'` 每層的候選數，跟對應的 `pool` 指令印出的行數一樣。
- `merge` 兩個草稿（第二個把 id 改成 stay-02）得到兩題、依 id 排序；兩個草稿 id 相同時報錯、不寫檔。
- `blind-input` 的輸出沒有上面列的禁止欄位，要判的片段 id 合起來等於 `must_judge`。
- 盲審檔跟標註完全一樣時，`blind-diff` 一致率 100%；改掉一筆的判斷，那筆出現在對的格子和不一致清單裡。
- `frag 6 611`、`usage .scratch/ptt-v2-questions/tmp` 的輸出正確。
- 原有指令的行為不變。

Answer 寫：六個指令各一行用法範例。

## Answer

- `.venv/bin/python scripts/eval/qgen.py layers 50 --when '{"month": ["3"], "time": ["晚上"]}'`
- `.venv/bin/python scripts/eval/qgen.py frag 6 611`
- `.venv/bin/python scripts/eval/qgen.py usage`（預設 `ptt_v2/`；或 `usage .scratch/ptt-v2-questions/drafts`）
- `.venv/bin/python scripts/eval/qgen.py merge src/strag_v3/eval/questions/ptt_v2/stay.json .scratch/ptt-v2-questions/drafts/stay-*.json`
- `.venv/bin/python scripts/eval/qgen.py blind-input src/strag_v3/eval/questions/ptt_v2/stay.json [stay-03 stay-07] > .scratch/ptt-v2-questions/review/stay-input.json`
- `.venv/bin/python scripts/eval/qgen.py blind-diff src/strag_v3/eval/questions/ptt_v2/stay.json .scratch/ptt-v2-questions/review/stay-blind-1.json .scratch/ptt-v2-questions/review/stay-blind-2.json`

驗證：`tests/eval/test_qgen_commands.py` 16 個測試通過；用 `.scratch/ptt-v2-questions/tmp/` 的 stay-01／stay-02 草稿實跑完成條件每一項都對（layers 20／41／22 筆跟 pool 行數一致；merge 排序、重複 id 不寫檔；blind-input 沒有禁止欄位、要判的 id＝must_judge；blind-diff 一樣時 40/40、改一筆後落在「不計分→其他不收」並列出）。原有指令跟 HEAD 版逐字比對（places、areas、pool、outer、check、answer 和各子指令 -h），只有總 `-h` 多列了新指令；plan、calibrate 要呼叫 Opus 沒實跑，程式碼沒動。
