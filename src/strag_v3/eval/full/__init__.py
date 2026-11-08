"""跑主系統（full）的各項指標：`python -m strag_v3.eval.full`。

- `runner.py`：設定和逐題執行。
- `planner.py`：規劃器正確率，拿規劃器的計畫跟題目的 `gold_plan` 比對。
- `__main__.py`：命令列。

baseline（dense、hard）和 oracle 不在這裡跑；結果檔存在 `runs/`。
"""
