# 04 找地點

Status: resolved
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

## Comments

- 2026-11-10 使用者核准加速，跟 generate.md〈流程〉、spec 不同的地方有三點：
  1. 03–06 四個題型同時做，不等 `Blocked by:`。違反 generate.md「一次做一個題型」。地點分配規則：移動經驗不用停留經驗用過的 10 個地點；跨題型的上限最後由五檔一起跑的 `check` 把關。
  2. 找題材時先查 nominatim_cache。出題子代理寫完自己先跑 `plan`，讀法不同就自己修，做不成就換備用題材。
  3. `plan` 通過後，盲審、審 `expect`、寫反向答案同時開。哪一題要修，就只重做那一題後面的驗證。
- 2026-11-10 使用者核准省額度做法（A–D 都用）：A. 審 expect 的小修正由協調者直接改草稿、自己跑 check，只有改題目文字或 aspect_rule 才重跑 plan；B. 可改可不改的小問題不處理；C. find_place 盲審從 4 個減成 2 個；D. 盲審和反向答案子代理改用 Sonnet。
- 2026-11-10 find_place 10 題 plan 全部「快取解析不到」（區域的 nominatim_cache 鍵 city 是空字串或縣名）。出題子代理換了 8 種寫法都失敗。使用者同意開 1 個 Sonnet 子代理唯讀查 src/ 和 qgen.py 找原因（破例讀原始碼）。
- 2026-11-10 原因（Sonnet 子代理查）：planner 照 prompt（rag/prompts/planner.md:10）為區域填 city（渋谷区→東京、京都市→京都），但快取裡區域的鍵是查外圍行政區時建的（city 空字串或縣名），place.py:186 精確鍵查不到；qgen 只讀快取所以失敗。實際系統會線上查 Nominatim，但「只讀快取」重跑時區域題會 place_unresolved。使用者同意破例補 data/ptt.db 的快取鍵：用 `scripts/db/pin_place.py --db data/ptt.db` 釘了 9 個區域的 24 個鍵（東京各區的 東京／東京都、京都市的 京都／京都市、大阪市的 大阪／大阪市、熱海市的 熱海／熱海市／静岡／静岡県、山梨県的 山梨／山梨県／甲府／甲府市、埼玉県的 埼玉／埼玉県／さいたま／さいたま市），osm 都跟原本的鍵相同。補完 plan 10 題一致。備份在 scratchpad 的 ptt.db.bak。根本修法（place.py 對區域加 fallback）留給之後的 ticket。

## Answer

### 出了哪些題（10 題）

| id | 區域 | when | aspect | coverage | 收 | expect |
|---|---|---|---|---|---|---|
| place-01 | 141 渋谷区 | 10 月 | 人潮多寡 | exact | 3 | 4 |
| place-02 | 76 文京区 | 12 月 | 花況（紅葉、銀杏） | exact | 4 | 7 |
| place-03 | 128 山梨県 | 1 月 | 景觀能見度 | exact | 2 | 5 |
| place-04 | 162 京都市 | 12 月 | 花況（紅葉、銀杏） | exact | 3 | 4 |
| place-05 | 162 京都市 | 5 月平日下午 | 開放狀況 | exact | 3 | 4 |
| place-06 | 167 埼玉県 | 5 月假日 | 人潮多寡 | exact | 4 | 5 |
| place-07 | 225 中央区 | 早上 | 開放狀況（店家開門） | exact | 4 | 5 |
| place-08 | 72 千代田区 | 3 月 | 排隊／等待時間 | exact | 2 | 2 |
| place-09 | 695 熱海市 | 2 月 | 花況（櫻花） | exact | 2 | 2 |
| place-10 | 102 大阪市 | 9 月 | 人潮多寡 | exact | 2 | 4 |

每題收的片段都涵蓋 2 個以上地點。選題表 `slots/find_place.md` 的 10 列都做成了，5 列備用沒用到。新宿區 4 月人潮跟比較題 cmp-08、cmp-09 同片段，選題時就避開了。

### 盲審一致率（修正前，`review/find_place-diff-before.txt`）

```
標註＼盲審 | 收 | 不計分 | 其他不收
收 | 29 | 0 | 0
不計分 | 0 | 0 | 0
其他不收 | 0 | 0 | 25
一致率：54/54（100.0%）
```

沒有不一致。依省額度做法，盲審開 2 個 Sonnet 子代理，各判 5 題。

### plan 讀法不同

- 第一次 10 題全部「快取解析不到」，不是讀法不同，原因與處理見 Comments：planner 為區域填的 city 跟 nominatim_cache 的鍵對不上，破例用 `pin_place.py` 補了 24 個鍵，補完 10 題一致。
- place-10：審 expect 後題目從「哪些地方人潮比較少？」改成「哪裡人多、哪裡人少？」，重跑 plan 一致。

### 審 expect 和校準

- place-03 第 5 條：補回鐘點「早上七點多」（中文數字照抄）。
- place-10 第 2 條：「人多了很多」改回原文程度「人和噪音多了大概十倍」。
- place-10 第 4 條：拿掉 aspect_rule 不算的「仍有位子」，補回「提早在 9 點前開」，source 截短。
- place-10 題目：4 條裡 3 條講人多，題目卻問人少，改成「哪裡人多、哪裡人少？」。
- 反向答案子代理第一次回報寫好了，但檔案不存在（指令卡在 cat 等輸入），叫它重寫一次，順便更新 place-03、place-10。
- 校準第一輪就印出「正向全部涵蓋、反向全部擋住」，沒換題。

### label_issues、地點錯配

- label_issues 0 筆。
- 新發現的地點錯配（找題材時）：宮下公園被放在横浜市中区；宇治在埼玉県秩父郡；奧日光、高松站在石川県；花川戶鮒忠在大阪府；皇居乾通在荒川区；上野仲町通在三鷹市。549 大石公園、585 日川時計店、389 富士見湖公園沒出現在所在縣的區域候選裡。
- 系統問題：區域的快取鍵（見 Comments）。根本修法是 `src/strag_v3/place.py` 的 `_resolve` 對區域加 fallback（精確鍵沒中時改試 city 空字串，或同名且只有一個 osm 的鍵），要另開 ticket。

### 給下一個題型

1. 區域題先確認 planner 填的 city 在快取裡有鍵；`qgen plan` 只讀快取，「快取解析不到」可能是解析層的問題，不一定是題目寫法。
2. 題目問的方向（人多還是人少）要跟 expect 的整體方向一致；兩種都有就問「哪裡人多、哪裡人少」。
3. 子代理寫檔後要 ls 確認檔案存在，不要只看它的回報。

