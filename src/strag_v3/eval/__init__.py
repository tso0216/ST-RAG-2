"""評估：讀題目檔，用指定的系統設定跑每一題，算出檢索指標並依題型和 dev／test 分組。

- `questions.py`：讀題目檔或資料夾。
- `metrics.py`：題目加上系統輸出 → 每題的指標和分組彙總（評估 seam）。
- `runner.py`：系統設定（完整系統、dense、硬過濾、oracle）和逐題執行。
- `__main__.py`：命令列，`run` 跑評估並存檔，`compare` 並排比較幾次的結果。
"""
