"""答案指標：評審對一題答案的判斷 → 每題的 `expect` 覆蓋率和時間誤植，以及彙總。

評審（`judge.py`）逐條給出：
- `expect`：題目的每個 `expect` 重點，答案有沒有涵蓋，和理由。
- `claims`：答案裡把某段經驗說成問到的時間（題目的 `when` 或檢索條件的時間）的說法，每條說法是不是誤植
  （那段經驗其實是別的時間，答案卻沒講明），和理由。題目和計畫都沒有限定時間時是 None，不算誤植。

每題：
- `expect` 覆蓋率：涵蓋的重點數除以重點數；題目沒有 `expect` 時不算。
- 誤植：誤植的說法數和講到時間的說法數。

彙總：
- `expect` 覆蓋率：各題的平均（macro），只算有 `expect` 的題目。
- 時間誤植率：所有題目的誤植說法數除以講到時間的說法數（pooled），沒有任何這類說法時不算。
沒有評審結果的題目（沒開答案評估、沒有答案）不算這兩項指標。
"""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ExpectCheck:
    point: str
    covered: bool
    reason: str


@dataclass(frozen=True)
class Claim:
    claim: str
    # 這條說法引用的片段 id
    content_ids: tuple[int, ...]
    misattributed: bool
    reason: str


@dataclass(frozen=True)
class Judgement:
    expect: tuple[ExpectCheck, ...]
    # 題目不限時間時是 None
    claims: tuple[Claim, ...] | None

    @property
    def expect_coverage(self) -> float | None:
        return sum(c.covered for c in self.expect) / len(self.expect) if self.expect else None

    @property
    def misattributed(self) -> int | None:
        return None if self.claims is None else sum(c.misattributed for c in self.claims)

    def to_dict(self) -> dict:
        return {
            "expect_coverage": self.expect_coverage,
            "misattributed": self.misattributed,
            "claims_n": None if self.claims is None else len(self.claims),
            "expect": [asdict(c) for c in self.expect],
            "claims": None if self.claims is None else [{**asdict(c), "content_ids": list(c.content_ids)}
                                                         for c in self.claims],
        }


def aggregate(judgements: list[Judgement]) -> dict:
    coverage = [c for j in judgements if (c := j.expect_coverage) is not None]
    timed = [c for j in judgements if j.claims is not None for c in j.claims]
    claims = len(timed)
    misattributed = sum(c.misattributed for c in timed)
    return {
        "n": len(judgements),
        "expect_coverage": sum(coverage) / len(coverage) if coverage else None,
        "misattribution_rate": misattributed / claims if claims else None,
        "claims_n": claims,
        "misattributed": misattributed,
    }
