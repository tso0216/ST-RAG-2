from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
ARTICLE_DIR = DATA / "article"
CACHE_DIR = ROOT / ".cache" / "extract"
DB_PATH = DATA / "main.db"
PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
