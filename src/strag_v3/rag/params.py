"""檢索的可調參數，集中在這裡。

預設值依常理定，不在 test 題目上調；δ 之後在 dev 題目上決定。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Params:
    # 語意分數的相對門檻：不低於該子查詢的最高分減 delta。
    # text-embedding-3-large 在晴空塔 eval 上，相關片段的分數散在 0.23–0.65，0.15 會漏掉排隊那段
    delta: float = 0.3
    # 片段有任何一個時間維度是 `不明` 時，分數乘上這個折扣（小於 1；設成 1 就不折扣）
    unknown_discount: float = 0.8
    # 沒有證據時，時段和月份各往外擴一格再查（消融時關掉）
    time_backoff: bool = True
    # 時間退讓後還是沒有，退到外圍的地點再查（消融時關掉）
    space_backoff: bool = True


DEFAULT = Params()
