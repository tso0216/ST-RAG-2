"""結果檔和評審檔的格式與存放。

結果檔 `runs/<時間>_<系統>[_k<k>].json`：
    {"config": {系統、k、取回的粒度、生成模型、題目、開始時間…},
     "questions": [每題的 Outcome]}
評審檔：跟結果檔同名、副檔名換成 `.judge.json`；已經有了就另存 `<結果檔>.<時間>.judge.json`。
    {"config": {評審模型、n、門檻、問法…}, "run": 結果檔檔名, "run_config": 結果檔的 config,
     "questions": [每題的 Verdict], "disagreements": [...], "agreement": {"coverage": …, "unsupported": …}}
兩種檔都不覆寫。
"""
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

RUNS = Path(__file__).resolve().parent / "runs"

# 取回的粒度：none 沒有取回（llm）、article 只有文章（dense_raw）、fragment 有片段（其餘三個）


@dataclass
class Cost:
    # 交給生成器的輸入 token 數
    input_tokens: int = 0
    # LLM 呼叫數（規劃器、過濾條件、生成器）
    llm_calls: int = 0
    # 系統自己的 JEV 呼叫數（相關判斷的片段數，含讀快取的），不含評審
    jev_calls: int = 0


@dataclass
class Outcome:
    """一個系統對一題的輸出。出錯時 answer 是 None、error 有訊息。"""
    id: str
    answer: str | None = None
    # 取回的片段 id（依排序）；沒有片段的系統是空的
    contents: list[int] = field(default_factory=list)
    # 取回的文章 id
    articles: list[str] = field(default_factory=list)
    # strag 標了退讓（時間或空間）的片段 id
    backoff: list[int] = field(default_factory=list)
    cost: Cost = field(default_factory=Cost)
    error: str | None = None
    # 問的地點解析不到（strag）或對不到任何片段的地點名稱（dense_filter）
    place_unresolved: bool = False
    # 系統各自的附帶資訊，例如 dense_filter 的過濾條件、dense_raw 取回的原文段
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "Outcome":
        return cls(**{**d, "cost": Cost(**d.get("cost", {}))})


def now() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _write_new(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x") as f:  # 已經存在就丟 FileExistsError，不覆寫
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def save_run(config: dict, outcomes: list[Outcome], folder: Path = RUNS) -> Path:
    k = f"_k{config['k']}" if config.get("k") is not None else ""
    return _write_new(folder / f"{now()}_{config['system']}{k}.json",
                      {"config": config, "questions": [asdict(o) for o in outcomes]})


def load_run(path: Path) -> tuple[dict, list[Outcome]]:
    data = json.loads(Path(path).read_text())
    return data["config"], [Outcome.from_dict(q) for q in data["questions"]]


def judge_path(run: Path) -> Path:
    first = run.with_name(run.stem + ".judge.json")
    return first if not first.exists() else run.with_name(f"{run.stem}.{now()}.judge.json")


def save_judge(run: Path, data: dict) -> Path:
    return _write_new(judge_path(run), {**data, "run": run.name})


def load_judge(path: Path) -> tuple[dict, Path]:
    """回傳評審檔的內容，和它評的結果檔（跟評審檔在同一個資料夾）。"""
    path = Path(path)
    data = json.loads(path.read_text())
    return data, path.with_name(data["run"])
