# 09: 人工標註 relevant_contents

**What to build:** 研究者審完 08 起草的遊記和題目後，逐題對照 `expect`，把回答需要的片段 id 寫進 `relevant_contents`。做法照 mock README 的第 5 步：

- 只放回答這題真的要用到的片段。
- 負例的片段不放進任何一題。
- 順便檢查抽取結果有沒有怪東西；有的話用 `--force` 重抽那一篇，再重新對應。

這是論文「人工標註」的依據，必須由研究者本人完成。

**Blocked by:** 08

**Status:** ready-for-human

- [ ] 30 題的 `relevant_contents` 都由研究者確認
- [ ] 抽取結果中寫錯的地點名稱、混進的奇怪文字都已經處理
- [ ] 重抽後 content id 有變的話，所有受影響題目的對應都已經更新
