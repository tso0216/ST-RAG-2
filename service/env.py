"""從專案根目錄的 `.env` 載入環境變數（例如 `TYPESAFE_API_KEY`）。

只補沒設定的變數，已經在環境裡的照舊；不印出任何值。格式：一行一個 `KEY=VALUE`，`#` 開頭是註解，值可以加引號。
"""
import os
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def load_env(path: Path = ENV_PATH) -> None:
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key and value:
            os.environ.setdefault(key, value)
