# 09: 標註 relevant_contents

**What to build:** 研究者審完 08 的題目和 14 的遊記後，由 agent 逐題對照 `expect`，把回答需要的片段 id 寫進 `relevant_contents`，再交給研究者確認。做法照 mock README 的第 5 步：

- 只放回答這題真的要用到的片段。
- 負例的片段不放進任何一題。
- 順便檢查抽取結果有沒有怪東西；有的話用 `--force` 重抽那一篇，再重新對應。
- 每題附上簡短的標註理由（哪個片段對應 `expect` 的哪一點），方便研究者確認。

**Blocked by:** 08, 14

**Status:** ready-for-human

- [x] 30 題的 `relevant_contents` 都由 agent 標註，附上標註理由
- [x] 抽取結果中寫錯的地點名稱、混進的奇怪文字都已經處理
- [x] 重抽後 content id 有變的話，所有受影響題目的對應都已經更新
- [ ] 標註結果交給研究者確認，研究者的修改都已經套用

## Notes

- 審稿文件：`.scratch/st-rag-main-system/09-annotation-review.md`（逐題標註理由、沒標的片段、待決定事項）。
- `check_mock.py` 錯誤 0；提醒 16 條都是範圍內沒標的正例片段，理由寫在審稿文件。
- 這輪沒有重抽：沒找到寫錯的地點名稱。清水寺片段 176 原本是轉述，依研究者決定改成親眼所見：遊記和 `main.db` 片段文字直接改，沒有重抽，id 不變。
- 晴空塔、澀谷 SKY、伏見稻荷 9 題的舊 id 已換成 14 重抽後的 id。
