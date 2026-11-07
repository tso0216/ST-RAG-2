# 04: 多子查詢與分組

**What to build:** 檢索計畫支援一到多個子查詢，並支援 `group_by` 和 `compose` 兩個設定：

- `group_by` 可以從 `month`、`day_type`、`time_of_day`、`place` 中選一個或多個；每個片段分到它分布質量最大的那一組。
- `compose` 是 `merge` 或 `contrast`。

這樣「什麼時候去人比較少」可以依時段整理；「傍晚哪裡適合看夕陽」可以依地點整理；「十二月傍晚跟晚上哪個比較不擠」可以分兩個子查詢各自找證據，再對照作答。

規劃器維持 zero-shot，prompt 只說明格式，不放範例，也不提題型名稱，讓 LLM 自己組出計畫。

**Blocked by:** 01

**Status:** ready-for-agent

- [x] 規劃器的輸出格式支援多個子查詢、`group_by`、`compose`，格式說明寫進規劃器的 prompt
- [x] 檢索 seam 測試涵蓋以下行為：
  - `group_by` 照指定的維度分組
  - 多個維度可以同時分組
  - `compose=contrast` 時，各子查詢的結果分開交給生成器
- [x] 生成器依分組和對照結構作答
- [x] 用現有 eval 的比較題（例如澀谷 SKY 十二月傍晚和晚上的比較），規劃器能產生兩個子查詢的計畫，答案有對照兩邊

## Comments

實作摘要（issue 04）：

- `Plan` 新增 `group_by`（`month`、`day_type`、`time_of_day`、`place`，可多選、照列出的順序）和 `compose`（`merge`／`contrast`，預設 `merge`）。
- 新模組 `rag/group.py`：`Retriever.retrieve_grouped(plan, question)` 回傳交給生成器的段落（`Section`），每段再依 `group_by` 分組（`Group`）。`merge` 把所有子查詢的證據合成一段（同一片段只留分數最高的那筆）；`contrast` 每個子查詢一段。原本的 `Retriever.retrieve` 不變。
- 生成器的輸入改成依段落和分組組織；`python -m strag_v3.rag --json` 多了 `sections`，`results` 照舊。

需要研究者決定的地方：

- **分組的並列與邊界規則**是我先訂的：時間維度的邊際分布是均勻的（`不明`）時另成「不明」組；兩組質量並列時歸給順序在前的組（月份 1→12、平日→假日、早上→中午→下午→晚上→深夜），例如 `16-17` 歸下午、`冬`（沒平滑時）歸 1 月、`全天` 歸早上。
- **`time_of_day` 的分組表**（`group.TIME_OF_DAY_GROUPS`）：早上 5–10、中午 11–12、下午 13–16、晚上 17–23、深夜 0–4。依 `DEFAULT_PERIODS` 梯形值最高的時段切，交界歸後面的時段；「深夜」是五個時段詞以外新加的組名。這張表跟 `planner.md` 的說明是兩處各寫一次，改的時候要一起改。
- **組的順序**：時間維度照上面的固定順序；`place` 照該地點最高分的證據排。
- **q3 實測**（`十二月去澀谷 SKY，傍晚跟晚上哪個時段比較不擠？`）：規劃器產生兩個子查詢（12 月 `16-18`、12 月 `晚上`，aspect 都是「人潮擁擠程度」），`compose=contrast`、`group_by=[]`。答案有分開說明兩個時段再對照，也講明是兩位旅客不同天的經驗。但 eval `expect` 的「週末傍晚要預約」沒出現，因為那段在片段 24（`15` 點），規劃器把傍晚換成 `16-18`，沒平滑時 15 點的重疊度是 0。等 issue 02 的週期平滑合進來再看。答案的結論也比 `expect` 保守：它指出晚上人少的是「平日加下雨」的那一次，不能直接歸因於時段。
