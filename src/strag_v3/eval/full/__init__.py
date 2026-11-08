"""跑主系統（full）的各項指標：`python -m strag_v3.eval.full`。

- `runner.py`：設定和逐題執行。
- `planner.py`：規劃器正確率，拿規劃器的計畫跟題目的 `gold_plan` 比對。
- `answer.py`：答案指標，從評審的逐條判斷算 `expect` 覆蓋率和時間誤植率。
- `judge.py`：答案評審（Opus，prompt 在 `judge.md`），結果快取在 DB。
- `__main__.py`：命令列。

baseline（dense、hard）和 oracle 不在這裡跑；結果檔存在 `runs/`。
"""
