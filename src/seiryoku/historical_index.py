"""過去時点の議会指数$I_p(t)$・首長指数$E_p(t)$を年次粒度で再構成する。

現行のindex.pyは「現在」だけを計算する設計だが、本モジュールは過去に遡って
年ごとのスナップショットを組み立てる。

$I_p(t)$は現行と同じく国会(衆参合算)の議席占有率のみ(2026-09に都道府県議会・
市区町村議会をI_pの対象から除外、index.py参照)。国会側は衆議院に単一の
通史ページが無いため総選挙ごとの結果ファイルを使っており、機械可読な形式が
第45回(2009年)以降にしか無い(diet_history.py参照)。

$E_p(t)$は当初、総務省の年次集計(体ごとの単純な首長人数集計)で$I_p(t)$と
同じ式を使う案を試したが、この集計は届出政党ベースであり、日本の首長選挙の
実態として知事・市区町村長のほぼ全員(2025年時点で知事45/47)が無所属で
届出するため、無所属が99%を占めるだけの使い物にならない結果になった
(2026-09-05にユーザー指摘、[[seiryoku_shisu_design]]参照)。現行の$E_p(t)$が
jichisoken(全国首長名簿)の推薦・支持データで無所属を仕分けている理由と
同じ問題である。

次に「現在の議席台帳のうち実際に選挙で確認できたエントリだけを対象年で
フィルタする」案を試したが、これは各自治体の「現在の任期」1つしか知らない
ため、対象年が現在から離れるほど「現在の任期がまだ始まっていない」自治体が
除外され、2018〜2021年は対象0件になった。そこでユーザー指示により、
turnover.build_term_chain_cache()で前任者・前々任者…と2018年まで遡った
在任履歴の全チェーン(data/executive_term_chains.json、1785自治体ぶん
エラー0件で取得済み)を使い、各自治体についてその年の12月31日時点で
在任していた任期を選ぶ方式にした(`_pick_term`)。前任者側の推薦・支持は
turnover.pyと同じ「当選時点の年版」データ(`jichisoken.endorsement_for_vote_year`)
で仕分ける。2018年より前が対象にできないのは、jichisokenが遡れる最古の
年版が2018年版であるため。個々の自治体の予算は年ごとに取得し直すと
47都道府県×年数ぶんの追加ダウンロードが必要になるため、現在の値をそのまま
流用する(年ごとの予算の変動は小さいとみなす近似、[[seiryoku_shisu_design]]の
予算と人口の相関検証と同じ発想)。

この設計変更に伴い、I_p(t)も同じ2018年以降にレンジを揃えている
(2026-09-05のユーザー指示)。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .analysis import _ERA_START
from .fetch import diet_history
from .index import _effective_party_shares, _phi, national_parties_from_diet, weighted_share_by_jurisdiction

MIN_YEAR = 2018

_SANGIIN_DATE_RE = re.compile(r"([RHS])(\d+|元)\.(\d+)\.(\d+)")
_YEAR_RE = re.compile(r"(\d{4})")


def _sangiin_date_key(date_label: str) -> tuple[int, int, int] | None:
    m = _SANGIIN_DATE_RE.match(date_label)
    if not m:
        return None
    era, year_s, month, day = m.groups()
    year_in_era = 1 if year_s == "元" else int(year_s)
    year = _ERA_START[era][0] + year_in_era - 1
    return (year, int(month), int(day))


def _year_of(date_str: str | None) -> int | None:
    if not date_str:
        return None
    m = _YEAR_RE.match(date_str)
    return int(m.group(1)) if m else None


def _seats_as_of(snapshots: list, year: int, date_key) -> dict[str, int] | None:
    """dateがyear年12月31日以前の中で最新のスナップショットのseatsを返す。"""
    candidates = [(date_key(s.date), s) for s in snapshots]
    candidates = [(k, s) for k, s in candidates if k is not None and k[0] <= year]
    if not candidates:
        return None
    return max(candidates, key=lambda ks: ks[0])[1].seats


@dataclass
class YearSnapshot:
    year: int
    I_p: dict[str, float]
    E_p: dict[str, float]
    E_p_known_jurisdictions: int
    national_parties: set[str]


def _build_i_p_series(min_year: int) -> dict[int, tuple[dict[str, float], set[str]]]:
    """{年: (I_p, national_parties)}を返す。I_p(t)は国会(衆参合算)の議席占有率のみ
    (2026-09に都道府県議会・市区町村議会を対象から除外、index.py参照)。
    """
    sangiin_snaps = diet_history.fetch_sangiin_history()
    shugiin_snaps = diet_history.fetch_shugiin_history()

    def _shugiin_date_key(date_iso: str) -> tuple[int, int, int] | None:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", date_iso)
        return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None

    from datetime import date as _date

    years = range(min_year, _date.today().year + 1)
    result: dict[int, tuple[dict[str, float], set[str]]] = {}
    for year in years:
        sangiin_seats = _seats_as_of(sangiin_snaps, year, _sangiin_date_key)
        shugiin_seats = _seats_as_of(shugiin_snaps, year, _shugiin_date_key)
        if sangiin_seats is None or shugiin_seats is None:
            continue

        kokkai_seats: dict[str, int] = {}
        for name, n in list(shugiin_seats.items()) + list(sangiin_seats.items()):
            kokkai_seats[name] = kokkai_seats.get(name, 0) + n

        national_parties = national_parties_from_diet({"衆議院": shugiin_seats, "参議院": sangiin_seats})
        I_p = _phi(kokkai_seats, national_parties)
        result[year] = (I_p, national_parties)
    return result


def _pick_term(chain: list[dict], year: int) -> dict | None:
    """chain(新しい順)の中から、year年12月31日時点で有効だった任期
    (=投票年がyear以下の中で最新のもの)を返す。無ければNone。"""
    candidates = [t for t in chain if (_year_of(t["vote_date"]) or 10**9) <= year]
    if not candidates:
        return None
    return max(candidates, key=lambda t: t["vote_date"])


def _build_e_p_series(
    national_parties_by_year: dict[int, set[str]],
    weight_fn=math.sqrt,
) -> dict[int, tuple[dict[str, float], int]]:
    """{年: (E_p, 対象にできた自治体数)}を返す。

    turnover.build_term_chain_cache()が事前構築した「前任者・前々任者…と
    2018年まで遡った任期チェーン」(data/executive_term_chains.json)を使い、
    各自治体についてその年の12月31日時点で在任していた任期を選んで積み上げる。
    jichisokenの「当選時点の年版」推薦・支持データで無所属を仕分けるのは
    turnover.pyの前任者判定と同じロジック。national_parties(国政政党の集合)は
    現在の衆参構成ではなく、_build_i_p_seriesが算出したその年の衆参構成由来の
    ものを年ごとに使う——現在の構成だけで判定すると、民主党のように既に解党した
    政党が「今は国政政党でない」として無所属側に誤って一括されてしまうため。

    重みは人口の平方根(ペンローズの平方根則、2026-09に予算の線形重みから変更)。
    """
    from . import municipal_registry, turnover
    from .fetch import jichisoken, population

    turnover._ensure_governor_ids_loaded()
    gov_id_to_name = {jid: name for name, jid in turnover._GOVERNOR_JICHITAI_IDS.items()}
    chains = turnover.load_term_chain_cache()["chains"]

    pref_pop = population.prefecture_population_by_name()
    muni_pop = population.municipal_population_by_name()
    gov_by_year = jichisoken.governor_endorsements_by_year()
    muni_by_year = jichisoken.municipal_head_endorsements_by_year()

    entries = []
    for jid_str, chain in chains.items():
        jid = int(jid_str)
        if jid in gov_id_to_name:
            name, p, by_year = gov_id_to_name[jid], pref_pop.get(gov_id_to_name[jid]), gov_by_year
        else:
            name = municipal_registry.jurisdiction_name(jid)
            p, by_year = (muni_pop.get(name), muni_by_year) if name else (None, None)
        if name and p is not None:
            entries.append((name, chain, p, by_year))

    result: dict[int, tuple[dict[str, float], int]] = {}
    for year, national_parties in national_parties_by_year.items():
        jurisdiction_entries = []
        known = 0
        for name, chain, p, by_year in entries:
            term = _pick_term(chain, year)
            if term is None:
                continue
            endorsement = jichisoken.endorsement_for_vote_year(by_year, name, term["vote_date"])
            endorsing = endorsement.endorsing_parties if endorsement else []
            shares = _effective_party_shares(term["party"], endorsing, national_parties)
            jurisdiction_entries.append((shares, weight_fn(p)))
            known += 1
        result[year] = (weighted_share_by_jurisdiction(jurisdiction_entries), known)
    return result


def build_year_snapshots(min_year: int = MIN_YEAR) -> list[YearSnapshot]:
    """min_year以降、年ごとにI_p(t)・E_p(t)を再構成する(モジュールdocstring参照)。"""
    i_p_series = _build_i_p_series(min_year)
    national_parties_by_year = {year: national_parties for year, (_, national_parties) in i_p_series.items()}
    e_p_series = _build_e_p_series(national_parties_by_year)

    results: list[YearSnapshot] = []
    for year in sorted(i_p_series):
        I_p, national_parties = i_p_series[year]
        E_p, known = e_p_series.get(year, ({}, 0))
        results.append(
            YearSnapshot(year=year, I_p=I_p, E_p=E_p, E_p_known_jurisdictions=known, national_parties=national_parties)
        )
    return results
