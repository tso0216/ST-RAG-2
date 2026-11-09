from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
ARTICLE_DIR = DATA / "article"
CACHE_DIR = ROOT / ".cache" / "extract"
DB_PATH = DATA / "ptt.db"
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
# 時段的鐘點邊界表：抽取和規劃器的 prompt 共用這一份，prompt 裡寫 `{{時段表}}` 的地方換成它
TIME_SLOTS_PATH = Path(__file__).resolve().parents[1] / "time_slots.md"
TIME_SLOTS_MARK = "{{時段表}}"
