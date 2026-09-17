"""党勢指数$C_p(t)$を月次のフロー指標として再構成する。

2026-09にユーザー指示で、ストック指標(現時点で誰が何を保有しているかを
全自治体+国会について毎月積み上げる方式)からフロー指標(その月に実際に
選挙があった自治体・議会・国会だけを対象にする方式)へ設計を変更した。

理由: ストック方式では自治体の重み$\\sqrt{P_j}$が人口という定数だけで決まるため、
選挙結果が変わってもどの枠が動くかが変わるだけで、国会と地方全体の相対的な
重み自体はほぼ一切動かない(2026-09にユーザー指摘)。「インパクト」を見たい
という本プロジェクトの動機(\\S1)に照らすと、これは月ごとの変化を捉える指標
として適さない。そこで、その月に実際に選挙があった自治体・国会だけを
$\\sqrt{P_j}$で加重する方式にした——ある月にどれだけの人口を代表する選挙が
動いたか、その勝者の政党構成で$C_p(t)$を決める。

$$C_p(T) = \\frac{\\displaystyle\\sum_{e:\\, 投票日(e)\\in T} \\sqrt{n_eP_{e}}\\cdot\\mathbb{1}[党(e)=p]}
                  {\\displaystyle\\sum_{e:\\, 投票日(e)\\in T} \\sqrt{n_eP_{e}}}$$

ここで$e$はその月($T$)に投票日があった選挙イベント(知事選・市区町村長選・
都道府県議会選・市区町村議会選・衆院選・参院選)、$P_e$はその選挙が代表する
人口(自治体の場合はその自治体の人口、国会の場合は全国人口)、$n_e$はその
選挙で決まる議席・ポストの数(知事・市区町村長選は常に1、議会選挙・衆院選・
参院選は実際の議席数)。選挙が無かった月は$C_p(T)$自体が定義できない
(欠測とする)。

首長選挙は常に$n_e=1$なので$\\sqrt{n_eP_e}=\\sqrt{P_e}$のままだが、国会の
選挙だけは実際の議席数(衆院選なら465、参院選の半数改選なら実際の改選数)を
掛ける(2026-09にユーザー指示で$\\sqrt{P_e}$のみの旧式から変更、design_document.tex
\\S2.2参照)。これを「1機関=1票」と数えるか「議員1人ずつが有権者を代表する」と
数えるかで重みが大きく変わるため、後者の解釈を採用した。衆院選と参院選は
別々の選挙イベントであり、$e$としても月としても常に別々に扱う——衆参の
議席数を合算してから1回だけ$\\sqrt{n_{国}P_{国}}$を掛けるようなことはしない
(2026-09にユーザー指摘、index.pyの\\texttt{compute_combined_index}にあった
同種の合算を分離した際の議論と同じ)。

首長側は既存のexecutive_term_chains(turnover.build_term_chain_cache())の
チェーン全体を舐め、投票日がその月に一致するエントリだけを拾う。国会側は
衆参それぞれの選挙結果ファイルから同様に拾う(衆院選は解散総選挙、参院選は
3年ごとの半数改選)。

議会側(都道府県議会・市区町村議会)はmunicipal_registry.load_gikai_term_chain_cache()
のチェーンを同様に舐める。首長と異なり、無所属候補の推薦・支持政党を記録した
情報源(jichisoken)が個人単位では存在しないため、jichisoken補正は試みず、
届出政党そのままの議席占有率($\\phi_p(e)$、index._phi)を国会の選挙と同じ
やり方で計算する。以前はこの「補正手段が無い」ことを理由に議会全体を$C_p(T)$の
対象から外していたが、2026年9月に公開グラフを政党間の水準比較から「各政党
自身の推移」の表示に切り替えたことで、この制約は障害でなくなった——ラベリングの
非対称性(自民党系候補は無所属で出馬しがちで共産党はほぼ必ず党名を明示する)は
政党間の水準比較を歪めるが、政党間で比較しないなら歪みは実害にならない
(design_document.tex \\S2.1参照)。

参院側は当初diet_history.fetch_sangiin_history()(参議院の「会派別所属議員数の
変遷」、選挙直後の参議院\\textbf{全体}のスナップショット)を使い、常会・臨時会・
特別会など召集ごとの構成変化を選挙イベントと誤カウントしないよう、半数改選の
周期に合致する年の8月以降だけを拾うフィルタ(旧_real_sangiin_election_snapshots)
を実装していた(2026-09に発見・修正——2018〜2026年の期間だけで222件中25件が
誤って選挙イベント扱いされていた)。しかしこのフィルタを施しても、抽出される
スナップショットは「その選挙で改選された議席」ではなく「改選されなかった残り
半分も含む参議院全体」の構成であり、$n_e$・$\\phi_p(e)$の定義(その選挙イベントで
決まったこと)と食い違うことが後に判明した(2026-09に発見、design_document.tex
\\S2.2参照)。そこで総務省が参院選ごとに公表する「党派別男女別新前元別当選人数」
ファイルから、その回に実際に改選された議席の当選者数だけを取得する
diet_history.fetch_sangiin_election_history()に切り替えた。このファイルは
選挙のあった回にしか存在しないため、上記のフィルタ自体が不要になった。

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


# 重みシェアの内訳(図1中段)で使う選挙種別ラベル。build_month_snapshotsが
# 各エントリに付与し、_snapshots_from_windowsが窓内で合算する。
LEVEL_TYPES = ["衆院選", "参院選", "都道府県知事", "都道府県議会", "市区町村長", "市区町村議会"]


@dataclass
class MonthSnapshot:
    year: int
    month: int
    C_p: dict[str, float]
    n_events: int
    level_weight_share: dict[str, float]


def build_month_snapshots(
    min_year: int = MIN_YEAR, window_months: int = 12, local_only: bool = False
) -> list[MonthSnapshot]:
    """min_year以降、月ごとにその月を含めてwindow_monthsか月分遡って実際にあった
    選挙を集計してC_p(t)を再構成する(モジュールdocstring参照)。既定の12か月は、
    どの時点で切っても暦月の構成が同じになり、統一地方選のような季節的な偏りを
    機械的にキャンセルできるための選択(2026-09にユーザー指摘・指示)。

    window_months=1にすると単月集計(季節変動を含む生の値)に戻る。窓を長くする
    ほど標本は増えて振れは小さくなるが、直近の変化への追従は遅くなるトレードオフがある。

    local_only=Trueにすると衆参の国政選挙イベントを一切含めない「地方選挙限定」の
    系列を再構成する。「地方選は国政選挙の前哨戦か」を検証するために2026-09に
    追加(precursor.py参照)。以前はdiet_history.fetch_sangiin_election_history等を
    空リストに差し替えるモンキーパッチで代用していたが、そのやり方は呼び出し側の
    コードを書き換える必要がありテストしにくいため、正式なパラメータに昇格した。
    """
    import math

    from . import municipal_registry, turnover
    from .fetch import jichisoken

    if local_only:
        sangiin_entries: list[tuple[tuple[int, int] | None, dict[str, int]]] = []
        shugiin_entries: list[tuple[tuple[int, int] | None, dict[str, int]]] = []
    else:
        sangiin_entries = [(_ym(s.date), s.seats) for s in diet_history.fetch_sangiin_election_history()]
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
            name, size, by_year, level_type = (
                gov_id_to_name[jid], pref_pop.get(gov_id_to_name[jid]), gov_by_year, "都道府県知事",
            )
        else:
            name = municipal_registry.jurisdiction_name(jid)
            size, by_year = (muni_pop.get(name), muni_by_year) if name else (None, None)
            level_type = "市区町村長"
        if name and size is not None:
            local_entries.append((name, parsed, size, by_year, level_type))

    # 都道府県議会・市区町村議会(gikai)は、首長と違い候補者個人の推薦・支持政党を
    # 記録した情報源が無いため、jichisoken補正は試みず届出政党のみで$\\phi_p(e)$を
    # 計算する——国会の選挙と同じ扱い(2026年9月にユーザー指摘、design_document.tex
    # \\S2.1参照。以前はこの「補正手段が無い」ことを理由に議会全体を対象外にしていたが、
    # 政党間の水準比較をしない設計に転換したことで、この制約は障害でなくなった)。
    gikai_local_entries = []
    for jid_str, chain in municipal_registry.load_gikai_term_chain_cache()["chains"].items():
        jid = int(jid_str)
        parsed = _parsed_chain(chain)
        if jid in gov_id_to_name:
            size = pref_pop.get(gov_id_to_name[jid])
            level_type = "都道府県議会"
        else:
            name = municipal_registry.jurisdiction_name(jid)
            size = muni_pop.get(name) if name else None
            level_type = "市区町村議会"
        if size is not None:
            gikai_local_entries.append((parsed, size, level_type))

    today = date.today()
    months = _month_range((min_year, 1), (today.year, today.month))

    # 月ごとの生イベント(shares, weight)をまず作っておき、window_months分だけ
    # 遡って合算する(スライディングウィンドウ、2026-09にユーザー指示で追加)。
    # type_weight_by_monthは同じイベントを(選挙種別ラベル, weight)として並行して
    # 記録したもので、図1中段の「重みシェアの内訳」を出すために使う
    # (2026-09にユーザー指示、以前は別スクリプトで同じ集計をやり直していた)。
    entries_by_month: dict[tuple[int, int], list[tuple[dict[str, float], float]]] = {}
    type_weight_by_month: dict[tuple[int, int], list[tuple[str, float]]] = {}
    for ym in months:
        entries: list[tuple[dict[str, float], float]] = []
        type_weights: list[tuple[str, float]] = []

        for name, parsed, size, by_year, level_type in local_entries:
            for term in _terms_in_month(parsed, ym):
                endorsement = jichisoken.endorsement_for_vote_year(by_year, name, term["vote_date"])
                endorsing = endorsement.endorsing_parties if endorsement else []
                shares = _effective_party_shares(term["party"], endorsing, national_parties)
                w = math.sqrt(size)
                entries.append((shares, w))
                type_weights.append((level_type, w))

        for parsed, size, level_type in gikai_local_entries:
            for term in _terms_in_month(parsed, ym):
                seats = term["seats"]
                n_e = sum(seats.values())
                if n_e == 0:
                    continue
                w = math.sqrt(n_e * size)
                entries.append((_phi(seats, national_parties), w))
                type_weights.append((level_type, w))

        for date_key, seats in sangiin_entries:
            if date_key == ym:
                n_e = sum(seats.values())
                w = math.sqrt(n_e * national_pop)
                entries.append((_phi(seats, national_parties), w))
                type_weights.append(("参院選", w))
        for date_key, seats in shugiin_entries:
            if date_key == ym:
                n_e = sum(seats.values())
                w = math.sqrt(n_e * national_pop)
                entries.append((_phi(seats, national_parties), w))
                type_weights.append(("衆院選", w))

        entries_by_month[ym] = entries
        type_weight_by_month[ym] = type_weights

    return _snapshots_from_windows(entries_by_month, type_weight_by_month, months, window_months)


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


def _level_weight_share(type_weights: list[tuple[str, float]]) -> dict[str, float]:
    """[(選挙種別ラベル, weight)]から種別ごとの重みシェアを求める。全体の重みが
    0(local_only=Trueで国政選挙が窓内に無い等)の場合は空dictを返す。"""
    totals = {t: 0.0 for t in LEVEL_TYPES}
    for label, w in type_weights:
        totals[label] = totals.get(label, 0.0) + w
    grand_total = sum(totals.values())
    if not grand_total:
        return {}
    return {t: v / grand_total for t, v in totals.items()}


def _snapshots_from_windows(
    entries_by_month: dict[tuple[int, int], list[tuple[dict[str, float], float]]],
    type_weight_by_month: dict[tuple[int, int], list[tuple[str, float]]],
    months: list[tuple[int, int]],
    window_months: int,
) -> list[MonthSnapshot]:
    results: list[MonthSnapshot] = []
    for ym in months:
        if ym not in entries_by_month:
            continue
        window_entries: list[tuple[dict[str, float], float]] = []
        window_type_weights: list[tuple[str, float]] = []
        for w in _months_back(ym, window_months):
            window_entries.extend(entries_by_month.get(w, []))
            window_type_weights.extend(type_weight_by_month.get(w, []))
        if not window_entries:
            continue
        results.append(
            MonthSnapshot(
                year=ym[0],
                month=ym[1],
                C_p=weighted_share_by_jurisdiction(window_entries),
                n_events=len(window_entries),
                level_weight_share=_level_weight_share(window_type_weights),
            )
        )
    return results
