"""国政選挙(衆院選・参院選)があった年月の一覧をdata/に持つ。

TimesFM-3の採用ルール(design_document.tex \\S7.2)は「国政選挙が絡む月」だけを
対象にする。「絡む月」は(a)実際に投票日があった月そのもの、(b)$C_p(T)$の12か月
後方ウィンドウからその選挙がちょうど抜ける、選挙のn+12か月後、の2種類がある
(2026-09のバックテストで確立、note記事「予測とサプライズについて」参照)。
"""
from __future__ import annotations

import json
from pathlib import Path

from .fetch import diet_history

MONTHS_PATH = Path(__file__).resolve().parents[2] / "data" / "national_election_months.json"


def _ym(date_str: str) -> tuple[int, int]:
    y, m, _ = date_str.split("-")
    return (int(y), int(m))


def compute_election_months() -> list[tuple[int, int]]:
    """実際に取得できる衆参の選挙結果から、投票日があった(年, 月)の集合を返す
    (重複除去・昇順)。"""
    return sorted({ym for ym, _label in compute_election_events()})


def compute_election_events() -> list[tuple[tuple[int, int], str]]:
    """実際に取得できる衆参の選挙結果から、((年, 月), "衆院選"|"参院選")の一覧を
    返す(charts.pyの図中ラベル用、2026-09に追加)。同じ月に両方あった場合は
    両方を別要素として残す(実際には起きていないが、起きても表示上問題ない)。"""
    events = [(_ym(s.date), "参院選") for s in diet_history.fetch_sangiin_election_history()]
    events += [(_ym(s.date), "衆院選") for s in diet_history.fetch_shugiin_history()]
    return sorted(events)


def save_election_months(months: list[tuple[int, int]]) -> list[list[int]]:
    saved = [[y, m] for y, m in months]
    MONTHS_PATH.parent.mkdir(exist_ok=True)
    MONTHS_PATH.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    return saved


def load_election_months() -> list[tuple[int, int]]:
    if not MONTHS_PATH.exists():
        return []
    return [tuple(ym) for ym in json.loads(MONTHS_PATH.read_text(encoding="utf-8"))]


def _add_months(ym: tuple[int, int], n: int) -> tuple[int, int]:
    y, m = ym
    m += n
    while m > 12:
        m -= 12
        y += 1
    return (y, m)


def is_election_linked_month(
    year: int, month: int, election_months: list[tuple[int, int]], window_months: int = 12
) -> bool:
    """(year, month)が「国政選挙が絡む月」かどうか。実際の選挙月そのもの、または
    ちょうどwindow_monthsか月前が選挙月(=$C_p(T)$の後方ウィンドウからその選挙が
    抜ける月)ならTrue。"""
    ym = (year, month)
    for e in election_months:
        if e == ym or _add_months(e, window_months) == ym:
            return True
    return False
