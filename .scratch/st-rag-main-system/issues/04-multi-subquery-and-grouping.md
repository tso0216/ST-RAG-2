# 04: 多子查詢與分組

**What to build:** 檢索計畫支援一到多個子查詢，並支援 `group_by` 和 `compose` 兩個設定：

- `group_by` 可以從 `month`、`day_type`、`time_of_day`、`place` 中選一個或多個；每個片段分到它分布質量最大的那一組。
- `compose` 是 `merge` 或 `contrast`。

這樣「什麼時候去人比較少」可以依時段整理；「傍晚哪裡適合看夕陽」可以依地點整理；「十二月傍晚跟晚上哪個比較不擠」可以分兩個子查詢各自找證據，再對照作答。

規劃器維持 zero-shot，prompt 只說明格式，不放範例，也不提題型名稱，讓 LLM 自己組出計畫。

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] 規劃器的輸出格式支援多個子查詢、`group_by`、`compose`，格式說明寫進規劃器的 prompt
- [ ] 檢索 seam 測試涵蓋以下行為：
  - `group_by` 照指定的維度分組
  - 多個維度可以同時分組
  - `compose=contrast` 時，各子查詢的結果分開交給生成器
- [ ] 生成器依分組和對照結構作答
- [ ] 用現有 eval 的比較題（例如澀谷 SKY 十二月傍晚和晚上的比較），規劃器能產生兩個子查詢的計畫，答案有對照兩邊
