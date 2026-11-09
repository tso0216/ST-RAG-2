# 02 停留經驗

Status: ready-for-agent
Blocked by: 01

照 spec〈題型 ticket 的流程〉出停留經驗 10 題：`ptt_v2/stay.json`，id `stay-01`…。

## 本題型要注意

放進找題材和出題子代理的指示裡：

- 時間一定是條件，`when` 不能空。
- 最多 2 題不是 `exact`。
- 題目文字只出現一個地名。
- 淺草寺、東京晴空塔、東京迪士尼樂園／海洋的片段多，找時間和比較最需要它們；這幾個地點在這個題型盡量各只用 1 題。

## 完成條件

- `ptt_v2/stay.json` 有 10 題，id 連續；不到 10 題在 Answer 寫原因。
- `check` 帶上 `ptt_v2/` 下所有題目檔，全部通過。
- `plan` 讀法不同的題目都改了文字，或在 Answer 說明是 planner 讀錯。
- 盲審的不一致都解決了；`review/stay-diff-before.txt` 存著修正前的 `blind-diff`。
- 審 `expect` 提出的問題都處理了。
- `calibrate ptt_v2/stay.json --negatives ptt_v2/calibration/stay.json` 印出「正向全部涵蓋、反向全部擋住」。
- Answer 照 spec〈Answer〉寫完。
