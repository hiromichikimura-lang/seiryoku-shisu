"""政党インパクト指数$C_p(t)$を月次のフロー指標として再構成する。

2026-09にユーザー指示で、ストック指標(現時点で誰が何を保有しているかを
全自治体+国会について毎月積み上げる方式)からフロー指標(その月に実際に
選挙があった自治体・国会だけを対象にする方式)へ設計を変更した。

理由: ストック方式では自治体の重み$\\sqrt{P_j}$が人口という定数だけで決まるため、
選挙結果が変わってもどの枠が動くかが変わるだけで、国会と地方全体の相対的な
重み自体はほぼ一切動かない(2026-09にユーザー指摘)。「インパクト」を見たい
という本プロジェクトの動機(\\S1)に照らすと、これは月ごとの変化を捉える指標
として適さない。そこで、その月に実際に選挙があった自治体・国会だけを
$\\sqrt{P_j}$で加重する方式にした——ある月にどれだけの人口を代表する選挙が
動いたか、その勝者の政党構成で$C_p(t)$を決める。

$$C_p(T) = \\frac{\\displaystyle\\sum_{e:\\, 投票日(e)\\in T} \\sqrt{P_{e}}\\cdot\\mathbb{1}[党(e)=p]}
                  {\\displaystyle\\sum_{e:\\, 投票日(e)\\in T} \\sqrt{P_{e}}}$$

ここで$e$はその月($T$)に投票日があった選挙イベント(知事選・市区町村長選・
衆院選・参院選)、$P_e$はその選挙が代表する人口(自治体の場合はその自治体の
人口、国会の場合は全国人口)。選挙が無かった月は$C_p(T)$自体が定義できない
(欠測とする)。

首長側は既存のexecutive_term_chains(turnover.build_term_chain_cache())の
チェーン全体を舐め、投票日がその月に一致するエントリだけを拾う。国会側は
衆参それぞれの選挙日単位のスナップショットから同様に拾う(衆院選は解散総選挙、
参院選は3年ごとの半数改選)。参院側はdiet_history.fetch_sangiin_history()が
常会・臨時会・特別会など召集のたびのスナップショットを返す(選挙の無い会期も
含む)ため、そのまま使うと欠員補充等による微小な構成変化まで選挙イベントとして
誤カウントする。半数改選は3年周期で固定なので、周期に合致する年の最初の
8月以降のスナップショットだけを拾う(_real_sangiin_election_snapshots、
2026-09に発見・修正——2018〜2026年の期間だけで222件中25件が誤って
選挙イベント扱いされていた)。

個別に追跡する政党の集合は、政党助成法上の「政党要件」(5議席以上、または
1議席以上かつ直近国政選挙で得票率2%以上、index.national_parties_meeting_requirement
参照)を満たす政党とする。月ごとに「その時点で要件を満たしていたか」を遡って
判定し直すのはせず、直近の国政選挙時点の判定を全期間に固定で適用する
(2026-09にユーザー指示、Wikipedia「日本の政党一覧」で現在の要件充足政党を
確認したのがきっかけ、_current_national_parties参照)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .fetch import diet_history, population
from .historical_index import _sangiin_date_key
from .index import (
    _effective_party_shares,
    _latest_sangiin_district_pct,
    _latest_shugiin_district_pct,
    _phi,
    national_parties_meeting_requirement,
    weighted_share_by_jurisdiction,
)

MIN_YEAR = 2018

_YM_RE = re.compile(r"(\d{4})-(\d{2})")


def _ym(date_str: str | None) -> tuple[int, int] | None:
    if not date_str:
        return None
    m = _YM_RE.match(date_str)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _sangiin_ym(date_label: str) -> tuple[int, int] | None:
    key = _sangiin_date_key(date_label)
    return (key[0], key[1]) if key else None


_SANGIIN_CYCLE_BASE_YEAR = 1947  # vote_share.sangiin_ordinal_for_yearと同じ3年周期の起点


def _is_sangiin_election_year(year: int) -> bool:
    return (year - _SANGIIN_CYCLE_BASE_YEAR) % 3 == 0


def _real_sangiin_election_snapshots(
    snapshots: list,
) -> list[tuple[tuple[int, int], dict[str, int]]]:
    """参議院の本来の選挙(半数改選)直後のスナップショットだけを抽出する。

    diet_history.fetch_sangiin_history()は常会・臨時会・特別会など国会の
    召集ごとの構成スナップショットを全て返す(年に2〜3回)。これはI_p(t)の
    ような「ある時点の構成」を求めるストック用途には正しいデータだが、
    フロー方式で「その月に選挙があったか」を判定する用途にそのまま使うと、
    選挙が無かった会期(欠員補充・会派異動による微小な構成変化)まで
    国会全体(sqrt(全国人口)という非常に大きな重み)を持つ「選挙イベント」
    として誤カウントしてしまう(2026-09に発見)。参議院の半数改選は解散が
    無く3年周期で固定、かつ必ず7月に投票されるため、周期に合致する年の
    最初の8月以降のスナップショット(投票直後に召集される会期)だけを
    選挙イベントとして拾う。
    """
    parsed = [(_sangiin_ym(s.date), s.seats) for s in snapshots]
    parsed = [(k, v) for k, v in parsed if k is not None]
    by_year: dict[int, tuple[tuple[int, int], dict[str, int]]] = {}
    for ym, seats in parsed:
        year, month = ym
        if not _is_sangiin_election_year(year) or month < 8:
            continue
        if year not in by_year or ym < by_year[year][0]:
            by_year[year] = (ym, seats)
    return list(by_year.values())


def _month_range(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    months = []
    y, m = start
    while (y, m) <= end:
        months.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return months


def _parsed_chain(chain: list[dict]) -> list[tuple[tuple[int, int], dict]]:
    parsed = [(_ym(c["vote_date"]), c) for c in chain]
    return [(k, v) for k, v in parsed if k is not None]


def _terms_in_month(parsed_chain: list[tuple[tuple[int, int], dict]], ym: tuple[int, int]) -> list[dict]:
    """投票日がちょうどymの月に一致する任期(通常0件か1件)を返す。"""
    return [term for k, term in parsed_chain if k == ym]


def _current_national_parties() -> set[str]:
    """政党要件(5議席以上、または1議席以上かつ直近国政選挙で得票率2%以上)を
    満たす政党の集合を、直近の衆参構成・得票率から1回だけ求める。

    月ごとに「その時点で要件を満たしていたか」を遡って判定し直すのはせず、
    全期間にこの1つの集合を適用する(2026-09にユーザー指示、「直近の国政選挙で
    要件を満たす政党のみでいい」という簡略化)。民主党のように既に解党した政党の
    過去の議席は、この集合に無い名前として無所属・諸派側に一括される。
    """
    from .fetch import diet

    diet_seats = diet.fetch_diet_seats()
    return national_parties_meeting_requirement(
        diet_seats,
        shugiin_district_pct=_latest_shugiin_district_pct(),
        sangiin_district_pct=_latest_sangiin_district_pct(),
    )


@dataclass
class MonthSnapshot:
    year: int
    month: int
    C_p: dict[str, float]
    n_events: int


def build_month_snapshots(min_year: int = MIN_YEAR, window_months: int = 12) -> list[MonthSnapshot]:
    """min_year以降、月ごとにその月を含めてwindow_monthsか月分遡って実際にあった
    選挙を集計してC_p(t)を再構成する(モジュールdocstring参照)。既定の12か月は、
    どの時点で切っても暦月の構成が同じになり、統一地方選のような季節的な偏りを
    機械的にキャンセルできるための選択(2026-09にユーザー指摘・指示)。

    window_months=1にすると単月集計(季節変動を含む生の値)に戻る。窓を長くする
    ほど標本は増えて振れは小さくなるが、直近の変化への追従は遅くなるトレードオフがある。
    """
    import math

    from . import municipal_registry, turnover
    from .fetch import jichisoken

    sangiin_entries = _real_sangiin_election_snapshots(diet_history.fetch_sangiin_history())
    shugiin_entries = [(_ym(s.date), s.seats) for s in diet_history.fetch_shugiin_history()]
    national_pop = population.national_population()
    national_parties = _current_national_parties()

    turnover._ensure_governor_ids_loaded()
    gov_id_to_name = {jid: name for name, jid in turnover._GOVERNOR_JICHITAI_IDS.items()}
    chains = turnover.load_term_chain_cache()["chains"]

    pref_pop = population.prefecture_population_by_name()
    muni_pop = population.municipal_population_by_name()
    gov_by_year = jichisoken.governor_endorsements_by_year()
    muni_by_year = jichisoken.municipal_head_endorsements_by_year()

    local_entries = []
    for jid_str, chain in chains.items():
        jid = int(jid_str)
        parsed = _parsed_chain(chain)
        if jid in gov_id_to_name:
            name, size, by_year = gov_id_to_name[jid], pref_pop.get(gov_id_to_name[jid]), gov_by_year
        else:
            name = municipal_registry.jurisdiction_name(jid)
            size, by_year = (muni_pop.get(name), muni_by_year) if name else (None, None)
        if name and size is not None:
            local_entries.append((name, parsed, size, by_year))

    today = date.today()
    months = _month_range((min_year, 1), (today.year, today.month))

    # 月ごとの生イベント(shares, weight)をまず作っておき、window_months分だけ
    # 遡って合算する(スライディングウィンドウ、2026-09にユーザー指示で追加)。
    entries_by_month: dict[tuple[int, int], list[tuple[dict[str, float], float]]] = {}
    for ym in months:
        entries: list[tuple[dict[str, float], float]] = []

        for name, parsed, size, by_year in local_entries:
            for term in _terms_in_month(parsed, ym):
                endorsement = jichisoken.endorsement_for_vote_year(by_year, name, term["vote_date"])
                endorsing = endorsement.endorsing_parties if endorsement else []
                shares = _effective_party_shares(term["party"], endorsing, national_parties)
                entries.append((shares, math.sqrt(size)))

        for date_key, seats in sangiin_entries:
            if date_key == ym:
                entries.append((_phi(seats, national_parties), math.sqrt(national_pop)))
        for date_key, seats in shugiin_entries:
            if date_key == ym:
                entries.append((_phi(seats, national_parties), math.sqrt(national_pop)))

        entries_by_month[ym] = entries

    return _snapshots_from_windows(entries_by_month, months, window_months)


def _months_back(ym: tuple[int, int], n: int) -> list[tuple[int, int]]:
    """ym自身を含め、ymからn-1か月遡った月までのリストを新しい順で返す。"""
    result = []
    y, m = ym
    for _ in range(n):
        result.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return result


def _snapshots_from_windows(
    entries_by_month: dict[tuple[int, int], list[tuple[dict[str, float], float]]],
    months: list[tuple[int, int]],
    window_months: int,
) -> list[MonthSnapshot]:
    results: list[MonthSnapshot] = []
    for ym in months:
        if ym not in entries_by_month:
            continue
        window_entries: list[tuple[dict[str, float], float]] = []
        for w in _months_back(ym, window_months):
            window_entries.extend(entries_by_month.get(w, []))
        if not window_entries:
            continue
        results.append(
            MonthSnapshot(
                year=ym[0],
                month=ym[1],
                C_p=weighted_share_by_jurisdiction(window_entries),
                n_events=len(window_entries),
            )
        )
    return results
