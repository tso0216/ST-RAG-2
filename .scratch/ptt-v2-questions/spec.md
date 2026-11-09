# Spec：照 generate.md 出 ptt_v2 題庫

## 目標

照 `src/strag_v3/eval/questions/generate.md` 出 ptt_v2 題庫：停留經驗、移動經驗、找地點、找時間、比較各 10 題（湊不滿就少出），寫到 `src/strag_v3/eval/questions/ptt_v2/`，最後寫 `ptt_v2/report.md`。

出題和標註的規則只看 generate.md。這份 spec 只管怎麼分工、怎麼控制 context，不改規則；兩邊對不上時照 generate.md，並在 ticket 的 `## Comments` 記一筆。

## 為什麼這樣分工

第一次讓一個 session 自己做完全部，18 次工具呼叫就用掉約 19 萬 tokens，一題都還沒寫：讀 `qgen.py` 原始碼花了約 2.2 萬字，把 648 筆片段全部印出來找題材又花了約 5 萬字。新 session 光系統提示就佔約 7 萬 tokens。

所以一個題型一張 ticket，但主 session 只當協調者：讀片段、判片段、寫題目都交給子代理（Agent 工具），主 session 只看摘要和短的檢查輸出。

## 怎麼跑

- 一張 ticket 開一個新 session。照編號做，`Blocked by:` 列的都 `resolved` 了才開工。
- 開工把 `Status:` 改成 `claimed`；收工在檔尾加 `## Answer`（見〈Answer〉），再改成 `resolved`。
- 開工先讀這份 spec、自己的 ticket、generate.md 全文，和之前每張 ticket Answer 裡的〈給下一個題型〉。
- 指令從專案根目錄跑：`.venv/bin/python scripts/eval/qgen.py <指令>`。shell 是 zsh，`--when` 的 JSON 用單引號包。
- 不要 commit，不要切分支、stash、reset；工作目錄裡有使用者還沒 commit 的修改，不要碰。不要改 `questions/ptt/`、`data/ptt.db`，也不要改 `src/` 底下的程式碼（ticket 01 另有規定）。
- 做不完：停在 `check` 通過的狀態，在 Answer 寫還沒做的部分，在 `issues/` 開一張新 ticket 接手，並把它加進下一張 ticket 的 `Blocked by:`。

## 位置

`ptt_v2/` 指 `src/strag_v3/eval/questions/ptt_v2/`；`slots/`、`drafts/`、`review/` 指 `.scratch/ptt-v2-questions/` 下的資料夾。

| 題型 | stem | id |
|---|---|---|
| 停留經驗 | `stay` | `stay-01`… |
| 移動經驗 | `move` | `move-01`… |
| 找地點 | `find_place` | `place-01`… |
| 找時間 | `find_time` | `time-01`… |
| 比較 | `compare` | `cmp-01`… |

- 題目檔：`ptt_v2/<stem>.json`，用 `qgen.py merge` 從草稿合併，不直接改。
- 草稿：`drafts/<stem>-<n>.json`，第 n 個出題子代理寫的題目，格式跟題目檔一樣。
- 選題表：`slots/<stem>.md`。
- 盲審：`review/<stem>-input.json`（`blind-input` 的輸出）、`review/<stem>-blind-<n>.json`（第 n 個盲審子代理的判斷）、`review/<stem>-diff-before.txt`（修正前的 `blind-diff`）。
- 校準的反向答案：`ptt_v2/calibration/<stem>.json`（generate.md 規定的位置）。

## 主 session 的守則

1. 不讀 `scripts/eval/qgen.py` 和 `src/` 的原始碼；工具用法看 generate.md〈工具〉和 `qgen.py -h`（ticket 01 例外）。
2. 不在主對話印片段（`pool`、`frag`、整個 DB）。要看片段才能做的事，交給子代理。
3. 子代理只回摘要（每題一兩行），不貼片段原文。
4. 修正交回原本負責那題的出題子代理（`SendMessage`），讓它改自己的草稿、跑過 `check` 再回報，然後重新 `merge`。那個子代理已經結束，就開新的，給它題目 id 和要修的地方。

## 題型 ticket 的流程

1. **找題材**：跑 `usage` 看已經用掉的地點和組合。開一個子代理照〈找題材〉範本找 13 個候選，挑 10 題、留 3 題備用，寫成選題表（見〈選題表〉）。
2. **出題**：開 5 個出題子代理同時做，每個負責 2 題（見〈出題子代理〉）。都回報後 `merge`，再跑 `check`，帶上 `ptt_v2/` 下所有題目檔（跨題型的上限才查得到）。做不成的題，把備用交給同一個子代理；備用用完就再找題材，補不到就少出。
3. **驗證**，照 generate.md〈驗證〉的順序：
   1. `plan`：讀法不同的交回出題子代理，照 generate.md 處理。
   2. 盲審：`blind-input` 存成檔，開 2 個新子代理各審 5 題。只給它們這個檔、generate.md〈收不收片段〉和負責的題目 id，不准開 `ptt_v2/`、`drafts/` 下的檔；判斷照檔頭說明的格式寫進 `review/<stem>-blind-<n>.json`。跑 `blind-diff`，輸出先存成 diff-before，再把不一致連同盲審引文交回出題子代理，照 generate.md 判誰對、修正。
   3. 審 `expect`：開新子代理，給它 generate.md〈驗證〉列的東西（片段全文讓它自己用 `frag` 取）；有問題交回出題子代理。
   4. 校準：開新子代理寫反向答案（給它 generate.md〈驗證〉的校準段，正向答案讓它自己用 `answer` 取），寫進 `ptt_v2/calibration/<stem>.json`；主 session 跑 `calibrate`。正向沒涵蓋，交回出題子代理改 `expect`；反向沒擋住，先請校準子代理確認反向答案真的改了那條的關鍵值。

   每輪修正後重新 `merge`、跑 `check`。改了題目文字、`aspect_rule` 或收不收的題，`plan` 和盲審要對那幾題重跑（`blind-input` 可以只帶這些題目 id）；只改了 `expect` 的，重跑 `check` 和 `calibrate` 就好。

## 出題子代理（指示範本）

〈〉換成實際內容：

> 你負責 ptt_v2〈題型〉的〈題目 id〉，題材是選題表 `.scratch/ptt-v2-questions/slots/<stem>.md` 的第〈序〉列。先讀 `src/strag_v3/eval/questions/generate.md` 全文，照〈流程〉2–6 步出題：先寫好 `aspect_rule`，再用 `layers`、`pool --when` 判每一層要判的候選，定 `coverage`，寫題目文字、`expect`、`expect_sources`。〈本題型要注意的事〉
>
> 寫進 `.scratch/ptt-v2-questions/drafts/<stem>-<n>.json`（格式跟 generate.md〈檔案〉的題目檔一樣），用 `.venv/bin/python scripts/eval/qgen.py check` 檢查這個檔要通過。不要讀程式原始碼，不要改別的檔。題材做不成（違反 generate.md 哪一條）就停下來回報原因。
>
> 回報每題一行：id、題目、coverage、收幾筆、`label_issues` 幾筆、遇到的問題。不要貼片段原文。之後我會把 plan、盲審、審 `expect`、校準發現的問題交回給你修，修完一樣跑 `check` 再回報。

## 找題材（子代理指示範本）

> 替 ptt_v2 題庫找〈題型〉的候選題。先讀 `src/strag_v3/eval/questions/generate.md` 的〈系統怎麼找片段〉〈工具〉〈規則〉1–4、6、7。從專案根目錄用 `.venv/bin/python scripts/eval/qgen.py` 的 `places`、`areas`、`layers`、`pool`、`outer` 讀資料，不要讀程式原始碼。
>
> 找〈N〉個組合：某個面向在某個時間條件下有 1–8 筆明確描述（比較題是每個選項都有）。題型判定和各項限制照 generate.md。不要用 generate.md 列的錯配地點、另一個景點的局部，也不要用〈已用掉的地點和組合〉。偏好候選 30 筆以內的組合，太多就加時間條件或換小一點的範圍。〈本題型要注意的事〉
>
> 只回一張表，不要貼片段原文：地點 id｜名稱｜when（JSON）｜aspect｜其他（asks 或選項）｜預期 coverage｜各層候選數｜可能收的片段 id｜一句話說為什麼可行。

## 選題表

| 序 | 狀態 | 地點 id | 名稱 | when | aspect | 其他 | 預期 coverage | 各層候選數 | 可能收的片段 | 子代理 |
|---|---|---|---|---|---|---|---|---|---|---|

- 狀態：`待做`、`備用`、`完成 stay-03`、`放棄：<原因>`。
- 其他：找時間題寫 `asks`，比較題寫每個選項（標籤、地點、when）。
- 子代理：負責的出題子代理編號 n（對應草稿檔名）和它的 agent id，交回修正時用。

## Answer

- 出了哪些題（id、地點、coverage、收幾筆），放棄的候選和原因
- 修正前的一致率（貼 `blind-diff` 的對照表）、不一致的地方和怎麼解決
- `plan` 讀法不同的題目和處理方式
- 審 `expect` 和校準改了哪些條、換掉哪些題
- `label_issues` 筆數、新發現的地點錯配
- 〈給下一個題型〉：這個題型踩到、下一個題型要先避開的 3–5 件事

## Ticket

| # | ticket | Blocked by |
|---|---|---|
| 01 | qgen.py 補六個指令 | — |
| 02 | 停留經驗 | 01 |
| 03 | 移動經驗 | 02 |
| 04 | 找地點 | 03 |
| 05 | 找時間 | 04 |
| 06 | 比較，加全部檢查和報告 | 05 |
