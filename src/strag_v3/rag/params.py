"""檢索的可調參數，集中在這裡。

預設值依常理定，不在 test 題目上調；門檻和 δ 之後在 dev 題目上決定。
"""
from dataclasses import dataclass, field

# 時段詞的梯形分布：(a, b, c, d) 的單位是鐘點，a 之前和 d 之後為 0，b 到 c 為 1，中間線性。
# 每個小時格取格子中點（h + 0.5）的值，再正規化成分布；超過 24 的部分繞回 0 點。
# 邊界參考 Shwartz 2022（morning／noon／afternoon／evening 的分布），再依中文用法調整。
DEFAULT_PERIODS: dict[str, tuple[float, float, float, float]] = {
    "早上": (5, 6, 11, 12),    # 5 點 0.5，6–10 點 1，11 點 0.5
    "中午": (11, 12, 13, 14),  # 11 點 0.5，12 點 1，13 點 0.5
    "下午": (12, 13, 17, 18),  # 12 點 0.5，13–16 點 1，17 點 0.5
    "晚上": (17, 18, 23, 24),  # 17 點 0.5，18–22 點 1，23 點 0.5
    "全天": (5, 7, 21, 23),    # 白天整段：5 點 0.25，6 點 0.75，7–20 點 1，21 點 0.75，22 點 0.25
}


@dataclass(frozen=True)
class Params:
    # 分數 = 語意分數 × (epsilon + 時空重疊度)
    epsilon: float = 0.1
    # 時空重疊度的絕對門檻，刻意寬鬆，不要變成硬過濾
    overlap_min: float = 0.05
    # 語意分數的相對門檻：不低於該子查詢的最高分減 delta。
    # text-embedding-3-large 在晴空塔 eval 上，相關片段的分數散在 0.23–0.65，0.15 會漏掉排隊那段
    delta: float = 0.3
    # 時段詞的梯形邊界
    periods: dict[str, tuple[float, float, float, float]] = field(default_factory=lambda: dict(DEFAULT_PERIODS))


DEFAULT = Params()
