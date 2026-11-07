# 05: 評估框架與兩個 baseline

**What to build:** 研究者用一個命令跑完所有 eval 題目，拿到檢索指標的彙總結果：

- 指標：取回集合對 `relevant_contents` 的 recall、precision、F1，時間違規率（取回的片段中，時間跟題目 `when` 不相符、又沒有標成退讓或 `不明` 的比例），以及有回答率（有取回證據的題目比例）。
- 結果依題型（`type`）和 dev／test（`split`）分組報告。

可以切換的設定：

- 完整系統
- dense baseline：只用語意分數取 top-k
- 硬過濾 baseline：跟完整系統一樣的時間比對和地點解析，但時間退讓和空間退讓都關掉
- oracle 模式：用題目的 `when` 取代規劃器解析出來的時間

舊的題目檔沒有 `type`、`split` 欄位時，照樣要能跑。

**Blocked by:** 01, 12

**Status:** resolved

- [x] 一個命令就能指定題目檔或資料夾、系統設定、題目子集（dev／test），輸出彙總結果，並存成可以比較的檔案
- [x] 每題的計畫、取回集合、答案都留存下來，方便逐題檢查
- [x] dense、硬過濾兩個 baseline 和 oracle 模式都能切換
- [x] 評估 seam 測試用手寫的系統輸出（固定的取回集合），驗證以下數值算得正確：
  - 集合的 recall、precision、F1
  - 時間違規率
  - 有回答率
  - 依題型和 split 分組的彙總
- [x] 能在現有 3 個景點、9 題上跑完，並產出結果

## Comments

實作在 `src/strag_v3/eval/`（`questions.py` 讀題目檔、`metrics.py` 算指標、`runner.py` 系統設定、`__main__.py` 命令列），dense baseline 在 `src/strag_v3/rag/dense.py`。用法寫在 `data/mock_article/README.md` 的「跑評估」。

實作時定下的規則（寫在 `metrics.py` 開頭）：

- recall、precision、F1 是各題平均（macro）；取回是空的時三個都是 0，但題目本來就沒有相關片段時三個都是 1。沒有 `relevant_contents` 的題目不算這三項。
- 時間違規：片段時間跟 `when` 不相符（照檢索的比對規則，`不明` 的維度算相符），又沒有標成時間退讓或空間退讓。違規率是所有題目的違規片段數除以取回片段數（pooled）。
- oracle 模式把每個子查詢的時間都換成 `when`。比較題的計畫有多個子查詢、各自時間不同時，oracle 會把它們換成同一個條件。
- dense 用原問題對全部片段取 top-k，預設 k=5（`--k`）。
- 規劃器產生看不懂的計畫時，那題記錄錯誤、當作沒取回；LLM 本身的錯誤讓整批停下。

在現有 3 個景點、9 題上的結果（`data/eval_runs/20261107-*.json`）：

| 設定 | R | P | F1 | 時間違規率 | 有回答率 |
|---|---|---|---|---|---|
| full | 0.981 | 0.981 | 0.980 | 0.000 | 1.000 |
| dense（k=5） | 0.581 | 0.311 | 0.380 | 0.689 | 1.000 |
| hard | 0.981 | 0.981 | 0.980 | 0.000 | 1.000 |
| full+oracle | 0.981 | 0.981 | 0.980 | 0.000 | 1.000 |

現有 9 題都直接有相符的片段，不會觸發退讓，所以 full 和 hard 一樣；要等 08 擴充題目後才看得出差距。
