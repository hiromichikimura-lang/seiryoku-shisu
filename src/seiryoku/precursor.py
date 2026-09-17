"""「地方選は国政選挙の前哨戦か」の検証表を保守する(design_document.tex
\\S7.3、note記事「おまけ」参照)。

同じ院(衆院/参院)の連続する2回の国政選挙のペアについて、選挙直前の地方限定
$C_p(t)$(国会の選挙を含めずに再構成した系列、monthly_index.build_month_snapshots
のlocal_only=True)の増減方向と、実際の議席シェアの増減方向が一致するかを見る。

2026-09の検証では、衆参それぞれ連続する回のペア(計4組)で立憲民主党・
国民民主党・日本共産党が4組全て一致、日本維新の会が4組全て逆、という結果に
なった。これは水準(レベル)ではなく差分(モメンタム)で見た場合の結果であり、
水準ベースの比較は自民党の規模による見せかけの相関だと判明して採用していない
(design_document.tex \\S7.3、2026-09にユーザー指摘)。

注意: 上記の確定した数値(note記事・design_document.texに掲載済み)は、
セッション限りのスクリプトで一度だけ計算したものであり、そのスクリプト自体は
残っていない。本モジュールは同じ考え方(選挙直前月の地方限定C_pの増減方向 vs
実際の議席シェアの増減方向)を独立に実装し直したもので、実際に4組で検算した
ところ立憲・共産・公明・自民は一致したが、国民民主党・日本維新の会は2026年
2月の衆院選(中道改革連合の結成と同時)を含むペアで符号が異なった(2026-09に
確認)。既に公開した過去の数値は正としてそのまま残し、本モジュールは今後の
選挙で1行ずつ追加していく運用とする。
"""
from __future__ import annotations

import json
from pathlib import Path

from .fetch import diet_history
from .forecast import ADOPTED_PARTIES

TABLE_PATH = Path(__file__).resolve().parents[2] / "data" / "precursor_verification.json"


def _ym(date_str: str) -> tuple[int, int]:
    y, m, _ = date_str.split("-")
    return (int(y), int(m))


def _share(seats: dict[str, int], party: str) -> float:
    total = sum(seats.values())
    return seats.get(party, 0) / total if total else 0.0


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def _local_cp_before(local_history: list[dict], year: int, month: int, party: str) -> float | None:
    """(year, month)の選挙の直前の月の地方限定C_pを返す(その月が無ければNone)。"""
    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    for h in local_history:
        if h["year"] == prev_y and h["month"] == prev_m:
            return h["C_p"].get(party, 0.0)
    return None


def consecutive_election_pairs(chamber_history: list) -> list[tuple]:
    """同じ院の選挙結果を投票日順に並べ、連続する2回ずつのペアを返す。"""
    ordered = sorted(chamber_history, key=lambda s: s.date)
    return list(zip(ordered, ordered[1:]))


def compute_verification_rows(local_history: list[dict]) -> list[dict]:
    """衆参それぞれの連続選挙ペアについて、政党ごとの方向一致を1行ずつ作る。"""
    rows: list[dict] = []
    for chamber, fetcher in (
        ("参院選", diet_history.fetch_sangiin_election_history),
        ("衆院選", diet_history.fetch_shugiin_history),
    ):
        for election_a, election_b in consecutive_election_pairs(fetcher()):
            ya, ma = _ym(election_a.date)
            yb, mb = _ym(election_b.date)
            for party in ADOPTED_PARTIES:
                local_a = _local_cp_before(local_history, ya, ma, party)
                local_b = _local_cp_before(local_history, yb, mb, party)
                if local_a is None or local_b is None:
                    continue
                local_direction = _sign(local_b - local_a)
                actual_direction = _sign(_share(election_b.seats, party) - _share(election_a.seats, party))
                if local_direction == 0 or actual_direction == 0:
                    continue
                rows.append(
                    {
                        "chamber": chamber,
                        "election_a": election_a.date,
                        "election_b": election_b.date,
                        "party": party,
                        "local_direction": local_direction,
                        "actual_direction": actual_direction,
                        "match": local_direction == actual_direction,
                    }
                )
    return rows


def update_precursor_table(local_history: list[dict]) -> list[dict]:
    rows = compute_verification_rows(local_history)
    TABLE_PATH.parent.mkdir(exist_ok=True)
    TABLE_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows


def load_precursor_table() -> list[dict]:
    if not TABLE_PATH.exists():
        return []
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))


def summarize_by_party(rows: list[dict]) -> dict[str, dict[str, int]]:
    """政党ごとに{一致数, 総数}を集計する(note記事の「4組中n組一致」の元データ)。"""
    summary: dict[str, dict[str, int]] = {p: {"match": 0, "total": 0} for p in ADOPTED_PARTIES}
    for row in rows:
        s = summary.setdefault(row["party"], {"match": 0, "total": 0})
        s["total"] += 1
        if row["match"]:
            s["match"] += 1
    return summary
