# 05: 評估框架與兩個 baseline

**What to build:** 研究者用一個命令跑完所有 eval 題目，拿到檢索指標的彙總結果：

- 指標：取回集合對 `relevant_contents` 的 recall、precision、F1，時間違規率（取回的片段中，時間跟題目 `when` 不相符、又沒有標成退讓或 `不明` 的比例），以及有回答率（有取回證據的題目比例）。
- 結果依題型（`type`）和 dev／test（`split`）分組報告。

可以切換的設定：

- 完整系統
- dense baseline：只用語意分數取 top-k
- 硬過濾 baseline：跟完整系統一樣的時間比對和景點階層，但時間退讓和空間退讓都關掉
- oracle 模式：用題目的 `when` 取代規劃器解析出來的時間

舊的題目檔沒有 `type`、`split` 欄位時，照樣要能跑。

**Blocked by:** 01, 12

**Status:** ready-for-agent

- [ ] 一個命令就能指定題目檔或資料夾、系統設定、題目子集（dev／test），輸出彙總結果，並存成可以比較的檔案
- [ ] 每題的計畫、取回集合、答案都留存下來，方便逐題檢查
- [ ] dense、硬過濾兩個 baseline 和 oracle 模式都能切換
- [ ] 評估 seam 測試用手寫的系統輸出（固定的取回集合），驗證以下數值算得正確：
  - 集合的 recall、precision、F1
  - 時間違規率
  - 有回答率
  - 依題型和 split 分組的彙總
- [ ] 能在現有 3 個景點、9 題上跑完，並產出結果
