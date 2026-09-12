"""政党名の名寄せ(git風の系譜管理の第一段階)。

会派名は「自由民主党・無所属の会」「自由民主党・こころ」のように、主要政党名の
後ろに「・」区切りで連立相手や無所属議員との相乗りを表す語句が付くことが多い
(公式の政党名自体に「・」が使われることはない)。そこで「・」より前の部分を
政党名とみなして名寄せする。

改称・合流・分裂そのものの履歴(LINEAGE_EVENTS)は記録のみ行い、
合流・分裂時の実測による議席の按分は今後の課題として未実装([[seiryoku_shisu_design]]参照)。
"""
from __future__ import annotations

from dataclasses import dataclass

# 無所属・諸派として扱う表記(完全一致)
INDEPENDENT_LABELS = {"無所属", "各派に属しない議員", "諸派", "無"}

# 表記ゆれのうち「・」区切りの除去だけでは吸収できないもの。
# 「れいわ新選組」->「いのちの党」のように、系譜イベント(LINEAGE_EVENTS)による
# 改称で新旧の名称が混在しているものもここで正規化する。データソースによって
# 改称の反映タイミングが異なるため(国会サイトは即時、総務省の年次集計は遅れる等)、
# 単純な最新名寄せではなく明示的な対応表として管理する。
_EXPLICIT_ALIASES = {
    "立憲民主": "立憲民主党",
    "れいわ新選組": "いのちの党",
}


def canonicalize(raw_name: str) -> str:
    """会派名・党派名の表記を現存政党の正式名称に正規化する。"""
    if raw_name in INDEPENDENT_LABELS or raw_name.startswith("無所属"):
        return "無所属"
    base = raw_name.split("・")[0]
    return _EXPLICIT_ALIASES.get(base, base)


@dataclass
class LineageEvent:
    date: str
    kind: str  # "改称" | "合流" | "分裂"
    before: list[str]
    after: list[str]
    note: str


# 現存政党が存在する範囲で確認できている系譜イベント。実測配分ロジックは未実装。
LINEAGE_EVENTS: list[LineageEvent] = [
    LineageEvent(
        date="2026-08-06",
        kind="改称",
        before=["れいわ新選組"],
        after=["いのちの党"],
        note="党名変更。組織としての連続性がある単純な改称。",
    ),
    LineageEvent(
        date="2026-02-08",
        kind="合流",
        before=["立憲民主党", "公明党"],
        after=["中道改革連合"],
        note="衆院選(第51回、2026-02-08投票)で両党が統一名簿で候補を擁立し合流。"
        "投票日以前の議席は立憲民主党・公明党それぞれの実際の名義のまま集計するため、"
        "月次フロー再構成では合流点で自然に系列が切り替わる(git風のmergeコミットに相当)。",
    ),
    LineageEvent(
        date="2026-08-31",
        kind="分裂",
        before=["中道改革連合"],
        after=["立憲民主党系", "公明党系"],
        note="3党合流断念にともなう分裂。議員の移籍先を実測して配分する必要がある(未実装)。"
        "2026-09時点ではDiet議席データ上もまだ「中道改革連合」名義のままであり"
        "(diet.fetch_diet_seats()で確認済み)、実際の名簿変更が起きるまでは"
        "現行のcanonicalize()がそのまま正しく機能する。",
    ),
]
