# 04 找地點

Status: ready-for-agent
Blocked by: 03

照 spec〈題型 ticket 的流程〉出找地點 10 題：`ptt_v2/find_place.json`，id `place-01`…。

## 本題型要注意

放進找題材和出題子代理的指示裡：

- `space` 是 `areas` 裡的行政區，題目文字要看得出問的是區域（「台東區」「淺草一帶」）。
- 收的片段至少涵蓋 2 個地點；條件下的候選超過 50 筆，就換小一點的區域或加時間條件（先看 `layers`）。
- `expect` 每條先寫地點名。
- 時間一定是條件，`when` 不能空；最多 2 題不是 `exact`。

區域的候選多，盲審改開 4 個子代理，每個最多 3 題。

## 完成條件

- `ptt_v2/find_place.json` 有 10 題，id 連續；不到 10 題在 Answer 寫原因。
- `check` 帶上 `ptt_v2/` 下所有題目檔，全部通過。
- `plan` 讀法不同的題目都改了文字，或在 Answer 說明是 planner 讀錯。
- 盲審的不一致都解決了；`review/find_place-diff-before.txt` 存著修正前的 `blind-diff`。
- 審 `expect` 提出的問題都處理了。
- `calibrate ptt_v2/find_place.json --negatives ptt_v2/calibration/find_place.json` 印出「正向全部涵蓋、反向全部擋住」。
- Answer 照 spec〈Answer〉寫完。
