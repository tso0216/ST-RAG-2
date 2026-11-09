# 03 移動經驗

Status: ready-for-agent
Blocked by: 02

照 spec〈題型 ticket 的流程〉出移動經驗 10 題：`ptt_v2/move.json`，id `move-01`…。

## 本題型要注意

放進找題材和出題子代理的指示裡：

- `space` 是移動發生的地點（車站、機場、場館出口）；題目文字裡另一端用泛稱（市區、車站、飯店）。
- 時間一定是條件，`when` 不能空；最多 2 題不是 `exact`。
- 資料偏少，湊不滿就少出，在 Answer 寫原因。

`plan` 時特別看 planner 有沒有為另一端多開子查詢；有的話照 generate.md 改題目文字。

## 完成條件

- `ptt_v2/move.json` 有 10 題，id 連續；不到 10 題在 Answer 寫原因。
- `check` 帶上 `ptt_v2/` 下所有題目檔，全部通過。
- `plan` 讀法不同的題目都改了文字，或在 Answer 說明是 planner 讀錯。
- 盲審的不一致都解決了；`review/move-diff-before.txt` 存著修正前的 `blind-diff`。
- 審 `expect` 提出的問題都處理了。
- `calibrate ptt_v2/move.json --negatives ptt_v2/calibration/move.json` 印出「正向全部涵蓋、反向全部擋住」。
- Answer 照 spec〈Answer〉寫完。
