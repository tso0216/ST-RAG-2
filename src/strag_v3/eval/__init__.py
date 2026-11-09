"""評估：讀題目檔，用指定的系統設定跑每一題，算出檢索指標並依題型和 dev／test 分組。

- `questions.py`：讀題目檔或資料夾。
- `metrics.py`：題目加上系統輸出 → 每題的指標和分組彙總（評估 seam）。
- `full/`：主系統（full）的設定和逐題執行（`runner.py`）、答案評審與指標、命令列，`run` 跑評估並存檔到 `full/runs/`，`compare` 並排比較幾次的結果。
"""
