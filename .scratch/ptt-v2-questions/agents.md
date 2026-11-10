# 子代理共用指示

專案根目錄 `/Users/yentso/Research-Project/ST-RAG-2`。指令從根目錄跑 `.venv/bin/python scripts/eval/qgen.py <指令>`（zsh，`--when` 的 JSON 用單引號包）。不要讀程式原始碼（`scripts/`、`src/` 下的 .py），不要 commit、切分支、stash、reset，只改指示裡交代的檔。`pool`、`frag` 不印文章 id，要查就用 sqlite3 唯讀查 `data/ptt.db` 的 content 表。回報不要貼片段原文。暫存檔一律放在 scratchpad 底下自己的子目錄（用你的任務命名，例如 `blind-time-1/`），不要寫在 scratchpad 根目錄，其他子代理會同時寫同名檔。

## 出題子代理

1. 先讀 `src/strag_v3/eval/questions/generate.md` 全文、`.scratch/ptt-v2-questions/issues/02-stay.md` 末尾的〈給下一個題型〉，和你那個題型的 ticket（`.scratch/ptt-v2-questions/issues/`）裡的〈本題型要注意〉。
2. 照 generate.md〈流程〉2–6 步出題：先寫好 `aspect_rule`，再用 `layers`、`pool --when` 判每一層要判的候選，定 `coverage`，寫題目文字、`expect`、`expect_sources`。選題表的「可能收的片段」只是初步判斷，每一筆候選都要自己照〈收不收片段〉重判。
3. 寫進指示給的草稿檔（格式跟 generate.md〈檔案〉的題目檔一樣），`check <草稿>` 要通過。
4. 自己跑 plan：先用 sqlite3 唯讀查 nominatim_cache，確認 planner 可能寫的日文名解析得到 `space` 的地點 id；再對草稿跑 `plan <草稿>`（每題 1 次 Opus 呼叫）。讀法不同就照 generate.md〈驗證〉的 plan 段改題目文字，最多改兩次，改完重跑 plan 和 check。
5. 題材做不成（違反 generate.md 哪一條，或 plan 改兩次還是不一致）：指示有給備用列的，就改用那一列從頭做，id 不變；沒有備用就停下來回報原因。
6. 回報每題一行：id、題目、coverage、收幾筆、`label_issues` 幾筆、plan 結果、遇到的問題（換了題材要寫原因）。
7. 之後協調者會把盲審、審 `expect`、校準發現的問題交回給你。修完一樣跑 `check`；改了題目文字或 `aspect_rule` 的話，也要重跑 plan。修完回報一行。

## 盲審子代理

只能看三樣東西：指示給的 `blind-input` 檔（照檔頭「說明」做）、`src/strag_v3/eval/questions/generate.md` 的〈收不收片段〉一節（用 `grep -n '^### 5' ` 找到起訖行，只讀那一節），以及檔裡每層的 `pool` 指令印出的片段。不准開 `src/strag_v3/eval/questions/ptt_v2/`、`.scratch/ptt-v2-questions/` 下的 `drafts/`、`slots/`，`review/` 下也只能開指示給的檔，不要查資料庫。只判指示給你的題目 id，照說明的格式寫進指示給的檔，引文從片段逐字複製。回報每題一行（id、收幾筆、各理由碼幾筆），加上難判的地方（每題最多一句）。

## 審 expect 子代理

材料：指示給的 JSON（每題的 question、when、coverage、aspect_rule、relevant_contents、expect、expect_sources；比較題另有 options）；generate.md 的〈收不收片段〉和〈`expect`〉兩節；收進來的片段全文，用 `frag <片段 id>...` 取。不要改任何檔。

每題逐條檢查：每個部分都有引文撐住嗎？程度和範圍跟原文一樣嗎（數字照抄、阿拉伯數字、不換算）？是不是只有一個狀態值？開頭的寫法對嗎？合併的條目，每個來源都撐得住嗎？收進來的片段裡，有沒有照 aspect_rule 算數、地點和時間也對的句子，卻沒被任何一條涵蓋？

回報格式：沒問題的題寫「<id>：OK」。有問題的每個問題一行，寫「<id> 第 N 條：問題｜建議改法」，漏涵蓋寫「<id> 漏涵蓋：片段 id 的哪句（15 字以內）｜建議」。

## 反向答案子代理

讀 generate.md〈驗證〉的校準段，和〈`expect`〉的開頭寫法。每題的正向答案用 `answer <題目檔> <id>` 取。題目的 coverage、expect 可以從題目檔讀，但不要改題目檔。

每題寫一個反向答案，照正向答案的寫法，把每一條的關鍵值都改錯，一條都不能漏，也不能留下跟正向一致的地方。同一題裡如果有兩條方向相反（一條人多、一條人少），子區域、鐘點、設施名這些限定都要保留，免得翻過來剛好撞上另一條。`time_backoff` 題把實際時間改成題目問的時間；`space_backoff` 題拿掉揭露條，把別處的經驗說成問的地點；`none` 題編一段經驗。

寫成指示給的 calibration 檔，格式 `{題目 id: 反向答案}`。回報每題一行：「id：改了哪幾個關鍵值」。
