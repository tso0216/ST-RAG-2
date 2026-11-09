# 05 找時間

Status: ready-for-agent
Blocked by: 04

照 spec〈題型 ticket 的流程〉出找時間 10 題：`ptt_v2/find_time.json`，id `time-01`…。

## 本題型要注意

放進找題材和出題子代理的指示裡：

- 要填 `asks`；`when` 只放其他限定，沒有就是 `null`。只出 `exact`。
- 問的維度，片段的標籤也要確定（〈收不收片段〉第 4 條）。
- `expect` 先寫片段在問的維度上的標籤值；時段標 `全天` 的寫「整天：」。

盲審子代理也要提醒〈收不收片段〉第 4 條的找時間規定：問的維度標成 `不明` 的片段也不能收。

## 完成條件

- `ptt_v2/find_time.json` 有 10 題，id 連續；不到 10 題在 Answer 寫原因。
- `check` 帶上 `ptt_v2/` 下所有題目檔，全部通過。
- `plan` 讀法不同的題目都改了文字，或在 Answer 說明是 planner 讀錯。
- 盲審的不一致都解決了；`review/find_time-diff-before.txt` 存著修正前的 `blind-diff`。
- 審 `expect` 提出的問題都處理了。
- `calibrate ptt_v2/find_time.json --negatives ptt_v2/calibration/find_time.json` 印出「正向全部涵蓋、反向全部擋住」。
- Answer 照 spec〈Answer〉寫完。
