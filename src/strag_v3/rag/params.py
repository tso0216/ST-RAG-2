"""檢索的可調參數，集中在這裡。

預設值依常理定，不在 test 題目上調；δ 之後在 dev 題目上決定。jev_pass 寫死 0.5，不在 dev 上調。
"""
from dataclasses import dataclass
from typing import Literal

# 相關判斷的選項（命令列 --gate 共用）
GATES = ("jev", "semantic")
GATE_HELP = "相關判斷：jev 問 JEV 每個片段是否相關（預設）；semantic 用語意分數的相對門檻（消融）"


@dataclass(frozen=True)
class Params:
    # 相關判斷：jev 是每個候選片段問 JEV 是否相關（預設）；semantic 是 embedding cosine 的相對門檻（消融）
    gate: Literal["jev", "semantic"] = "jev"
    # JEV 的模型版本；固定版本，不用 jev-latest 別名
    jev_model: str = "jev-1.14.0"
    # JEV 的 noul 不低於這個值就通過，沒有數量上限
    jev_pass: float = 0.5
    # 最多同時幾個 JEV 請求
    jev_concurrency: int = 4
    # gate=semantic 時語意分數的相對門檻：不低於該子查詢的最高分減 delta。
    # text-embedding-3-large 在晴空塔 eval 上，相關片段的分數散在 0.23–0.65，0.15 會漏掉排隊那段
    delta: float = 0.3
    # 片段有任何一個時間維度是 `不明` 時，分數乘上這個折扣（小於 1；設成 1 就不折扣）；只影響排序
    unknown_discount: float = 0.8
    # 沒有證據時，時段和月份各往外擴一格再查（消融時關掉）
    time_backoff: bool = True
    # 時間退讓後還是沒有，退到外圍的地點再查（消融時關掉）
    space_backoff: bool = True


DEFAULT = Params()
