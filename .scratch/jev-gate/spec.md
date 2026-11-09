# Spec：用 JEV 取代語意門檻

## 目標

檢索時，時間硬過濾後的每個候選片段改交給 JEV（TypeSafe AI 的判斷模型）判斷「是否和問題相關」，判成相關的全部通過，取代現在的「語意分數 ≥ 最高分 − δ」。語意門檻保留成消融選項。

動機：現有 eval（`src/strag_v3/eval/full/runs/20261108-150746_full.json`）recall 0.98、precision 0.82，問題在取太多，不在漏掉。

## 不做的事

- dense baseline（`rag/dense.py`）不改，不加 JEV 版本。
- 不寫 ADR、不改 GLOSSARY。
- 全部判成不相關時，不另外揭露「有資料但不相關」；照舊回傳 `Available`。
- `space` 為 null 時不另外加預先篩選。

## 檢索規則（`gate = "jev"`，預設）

每個子查詢：

1. 地點解析、時間硬過濾：和現在一樣。
2. 相關判斷：每個候選片段各送一個 JEV 請求（一組問題 × 一個片段，不把多個片段塞進同一個 `state`）。
   - `state`：`{"question": 原問題, "aspect": sq.aspect, "passage": 片段 content}`；沒有 aspect 時不放 `aspect` 這個 key。
   - 不送時間標籤（month／day_type／time），只送 content 文字。
   - 問題類型 `noul`；`instructions` 和 `criteria.true/false` 是固定的中文短句，寧可多取。草稿：
     - instructions：「片段是否和問題相關？不用判斷時間是否符合。」
     - true：「片段提到和問題相關的經驗，只回答一部分也算。」
     - false：「片段和問題無關。」
3. 通過：`noul ≥ 0.5` 的全部通過，沒有數量上限。0.5 寫死在 `Params`，不在 dev 上調。
4. 排序：`relevance = noul`；`score = relevance × unknown_discount`（片段有時間 `不明` 時），依 `(-score, content_id)` 排序。打折只影響排序，不影響過不過。
5. 退讓：一筆都沒通過，就算「沒有證據」，照原本順序做時間退讓、空間退讓；都沒有就回傳空結果附 `Available`（和現在一樣）。退讓時的新候選一樣經過 JEV。

`gate = "semantic"` 時完全照現有邏輯（`aspect or question` 的 embedding cosine，≥ 最高分 − δ），`relevance` 存 cosine。

## JEV 呼叫（`service/jev.py`）

- 套件：`typesafe-sdk`（PyPI 名稱；import 名稱 `typesafe_sdk`），加進 `requirements.txt`。
- 用 `AsyncTypeSafeClient`，`client.system_one(model=..., state=..., questions={...})`，機率在 `response.answers[<name>].noul`。
- 金鑰：環境變數 `TYPESAFE_API_KEY`；目前金鑰放在專案根目錄 `.env`，程式沒有載入 `.env` 的機制，實作時要處理（不印出金鑰）。
- 模型固定 `jev-1.14.0`（不要用 `jev-latest` 別名）。
- 重試：SDK 的 `RetryPolicy(max_retries=3)`，不自己再包一層。還是失敗就讓該題照現有 `Outcome.error` 記錄，不自動改用語意門檻。
- 並發數：`Params.jev_concurrency = 4`。

## 快取（DB 表 `jev_cache`）

- key：`(model, criteria_hash, question, aspect, content_id)`；`criteria_hash` 是 instructions＋criteria 的 hash，`aspect` 沒有時存空字串。
- 存：`noul`、回應裡的 `model`（實際回答的版本）、建立時間。
- 有快取就只讀快取，不重問。原因：JEV 結果不固定（官方測試同輸入平均 3.8% 判斷會變），且 `jev-1.14.0` 已公告 30 天後停用，論文重現靠快取。
- 建表方式比照現有 `embedding` 表（用到時才建），`scripts/db/create_main_db.py` 也一併建。

## 參數與命令列

- `Params` 新增：`gate: Literal["jev", "semantic"] = "jev"`、`jev_model = "jev-1.14.0"`、`jev_pass = 0.5`、`jev_concurrency = 4`。`delta` 保留給 semantic。
- `python -m strag_v3.rag` 和 `python -m strag_v3.eval.full run` 加 `--gate {jev,semantic}`，預設 `jev`。
- eval 結果檔的 `config` 記錄 `gate`（和 jev 時的模型版本）。

## 資料結構

- `Evidence.semantic` 改名為 `relevance`（jev 時是 `noul`，semantic 時是 cosine）。
- `eval.full compare` 要能讀舊的 runs JSON（欄位叫 `semantic`、`config` 沒有 `gate` 的視為 `semantic`）。

## 驗證

> **實作範圍只到第 1 步。** 實作這份 spec 時不得呼叫真實 JEV API（不跑第 2、3 步、不寫一次性腳本試打）；做完第 1 步就停下來回報。第 2、3 步要等使用者另外明確指示才做。

1. 單元測試：比照 `tests/fake_nominatim.py` 做 fake JEV，不打網路。至少涵蓋：
   - 判成相關的全部通過、沒通過的不出現；排序和 `time_unknown` 打折；
   - 全部不通過時觸發時間退讓、再空間退讓、最後回 `Available`；
   - 送出的 `state` 不含時間標籤、沒有 aspect 時不含 `aspect`；
   - 快取命中時不呼叫 JEV；
   - JEV 失敗時該題記成錯誤；
   - `--gate semantic` 結果和改動前一致。
2. dev 漏判檢查（切成預設前）：dev 題目、gold plan 時間過濾後的候選，對照 `relevant_contents`，列出被 JEV 判成不相關的相關片段（片段 id、內容、noul）。交給使用者看過，再決定判準要不要改。test 不碰。
3. 之後再跑 `eval.full run --split dev --judge` 兩次（`--gate jev`、`--gate semantic`）用 `compare` 比 precision／recall／expect_coverage。

## 參考

JEV 文件（背景 agent 抓下來的副本）：`/private/tmp/claude-501/-Users-yentso-Research-Project-ST-RAG-2/ae94b13b-7697-4d2c-ba2c-0764f522c267/scratchpad/ts/`；線上 https://docs.typesafe.ai （`/primitives/noul.md`、`/models.md`、`/sdk/python.md`、`/cookbooks/classifying_rag_passages.md`）。
