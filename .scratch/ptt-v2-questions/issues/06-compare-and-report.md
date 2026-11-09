# 06 比較，加全部檢查和報告

Status: ready-for-agent
Blocked by: 05

照 spec〈題型 ticket 的流程〉出比較 10 題：`ptt_v2/compare.json`，id `cmp-01`…。做完再對五個題型做最後檢查、寫報告。

## 本題型要注意

放進找題材和出題子代理的指示裡：

- 選項之間只差一個維度；題目層的 `when` 只放選項共同的條件，每個選項寫完整的 `space` 和 `when`。
- 只出 `exact`；每個選項至少收 1 筆，收的片段要在該選項自己的候選裡。
- `expect` 每條先寫選項名稱；不寫片段自己沒做的比較（兩位旅客各自的經驗，不能寫成「假日比平日多」）。

## 比較做完之後

1. 五個題目檔一起跑 `check`（有跨題型的上限），要全部通過。沒過就照 spec 的流程修；換了題目的話，那題要重做驗證。
2. 先寫好這張 ticket 的 Answer，再開子代理寫 `ptt_v2/report.md`。給它 generate.md〈報告〉、01–06 每張 ticket 的 Answer（含途中新開的 ticket）、五個題目檔的路徑；`label_issues`、coverage 分布、地點用量讓它自己從題目檔和 `usage` 整理。

## 完成條件

- `ptt_v2/compare.json` 有 10 題，id 連續；不到 10 題在 Answer 寫原因。
- `plan` 讀法不同的題目都改了文字，或在 Answer 說明是 planner 讀錯。
- 盲審的不一致都解決了；`review/compare-diff-before.txt` 存著修正前的 `blind-diff`。
- 審 `expect` 提出的問題都處理了。
- `calibrate ptt_v2/compare.json --negatives ptt_v2/calibration/compare.json` 印出「正向全部涵蓋、反向全部擋住」。
- 五個題目檔一起跑 `check` 全部通過。
- `report.md` 涵蓋 generate.md〈報告〉的每一項；沒出滿 10 題的題型寫了原因。
- Answer 照 spec〈Answer〉寫完。
