"""政党インパクト指数 $C_p(t)$ (旧$I_p(t)$・$E_p(t)$を統合)を計算する。

$I_p(t)$(国会の議席占有率)と$E_p(t)$(知事・市区町村長)は当初、単位が
異なる(議席1つとポスト1つ)という理由で別建てにしていたが、2026-09に
ユーザー指示で1つの合成指数$C_p(t)$へ統合した。合成の重みは既存の
$E_p(t)$と同じ「人口の平方根」を土台にしつつ、国会だけは実際の議席数$n$も
掛けた$\\sqrt{nP_{国}}$を使う——1機関=1票として数えると知事・市区町村長1人分と
同格になってしまうため、議員1人ずつが有権者を代表するという解釈を採用した
(2026-09にユーザー指示で$\\sqrt{P_e}$のみの旧式から変更、design_document.tex
\\S2.2参照)。衆議院・参議院は任期・解散の有無が異なる別々の選挙であり、
$\\sqrt{\\cdot}$の非線形性のため衆参を合算してから1回だけ$\\sqrt{n_{国}P_{国}}$を
掛けるのと、衆参それぞれ自院の議席数$n_c$で$\\sqrt{n_cP_{国}}$を個別に掛けて
から合成するのとでは異なる値になる。後者(分離)を採用した
(2026-09にユーザー指摘、\\texttt{compute_combined_index}参照)。
知事・市区町村長は1ポスト=1人なので$n=1$、$\\sqrt{nP_j}=\\sqrt{P_j}$のまま
変わらない。

都道府県議会・市区町村議会は2026-09にユーザー判断で対象から除外済み——
地方議会には(a) 自民党系候補の多くが党名を出さず無所属で出馬する一方で
共産党はほぼ必ず党名を出すというラベリングの非対称性があり、無所属を
除いて政党だけで見ると政党間の実勢比較が歪む、(b) 首長と違って候補者個人の
推薦・支持政党を記録した情報源が存在せず①を補正する手段が無い、という
2つの理由がある。
"""
from __future__ import annotations

from .lineage import canonicalize


def national_parties_from_diet(diet_seats: dict[str, dict[str, int]]) -> set[str]:
    """衆参の会派名から「国政政党」の集合を導出する(恣意的な固定リストを避け、
    実際に国会に議席を持つ政党だけを客観的に定義する、[[seiryoku_shisu_design]]の
    「国政政党のみ個別追跡」方針を実データから機械的に判定する)。
    """
    parties: set[str] = set()
    for chamber_seats in diet_seats.values():
        for name in chamber_seats:
            party = canonicalize(name)
            if party != "無所属":
                parties.add(party)
    return parties


def national_parties_meeting_requirement(
    diet_seats: dict[str, dict[str, int]],
    shugiin_district_pct: dict[str, float] | None = None,
    sangiin_district_pct: dict[str, float] | None = None,
) -> set[str]:
    """政党助成法上の「政党要件」——(a) 国会議員5人以上、または(b) 1人以上かつ
    直近の国政選挙で得票率2\\%以上——を満たす政党の集合を返す(2026-09にユーザー
    指示で、\\texttt{national_parties_from_diet}の「1議席以上あれば追跡」という
    緩い基準から法定要件に強化)。

    得票率は衆院選小選挙区・参院選選挙区のみを見る(比例代表の総務省公表サマリは
    議席を得た政党しか載らないため使えない、\\texttt{fetch/vote_share.py}参照)。
    比例代表でのみ2\\%を満たし小選挙区・選挙区ではどこも満たさない政党は、5議席
    未満なら本関数では要件ありと判定できない既知の制約が残る。
    """
    seat_counts: dict[str, int] = {}
    for chamber_seats in diet_seats.values():
        for name, n in chamber_seats.items():
            party = canonicalize(name)
            if party != "無所属":
                seat_counts[party] = seat_counts.get(party, 0) + n

    shugiin_district_pct = shugiin_district_pct or {}
    sangiin_district_pct = sangiin_district_pct or {}

    result: set[str] = set()
    for party, seats in seat_counts.items():
        if seats >= 5:
            result.add(party)
            continue
        if seats >= 1:
            pct = max(shugiin_district_pct.get(party, 0.0), sangiin_district_pct.get(party, 0.0))
            if pct >= 2.0:
                result.add(party)
    return result


def _restrict_to_national(party: str, national_parties: set[str] | None) -> str:
    """国政政党の集合が与えられている場合、それ以外(地域政党等)は無所属・諸派に
    一括する([[seiryoku_shisu_design]]の「ローカル政党は諸派に一括」方針)。
    """
    if national_parties is None or party == "無所属" or party in national_parties:
        return party
    return "無所属"


def _effective_party_shares(
    formal_party: str,
    endorsing_parties: list[str],
    national_parties: set[str] | None = None,
) -> dict[str, float]:
    """届出政党が無所属の首長を、推薦・支持政党で仕分ける({政党: 按分比率}を返す)。

    届出政党名がある場合はそちらを優先し、推薦・支持情報は無所属の場合にのみ使う。
    複数政党の相乗り推薦は均等按分する(報道の扱い等に基づく恣意的な重み付けを
    避けるため、[[seiryoku_shisu_design]]の設計方針=恣意的な係数の排除と整合)。
    """
    party = _restrict_to_national(canonicalize(formal_party), national_parties)
    if party != "無所属" or not endorsing_parties:
        return {party: 1.0}
    share = 1.0 / len(endorsing_parties)
    shares: dict[str, float] = {}
    for p in endorsing_parties:
        canon = _restrict_to_national(canonicalize(p), national_parties)
        shares[canon] = shares.get(canon, 0.0) + share
    return shares


def _normalize_seats(raw_seats: dict[str, int], national_parties: set[str] | None = None) -> dict[str, int]:
    """会派名を正規化しつつ同じ政党の議席数を合算する。"""
    merged: dict[str, int] = {}
    for name, n in raw_seats.items():
        party = _restrict_to_national(canonicalize(name), national_parties)
        merged[party] = merged.get(party, 0) + n
    return merged


def _phi(raw_seats: dict[str, int], national_parties: set[str] | None = None) -> dict[str, float]:
    """体1つぶんの議席占有率 $\\phi_p^{(b)}(t)$ を計算する(無所属・諸派を含めて正規化)。"""
    seats = _normalize_seats(raw_seats, national_parties)
    total = sum(seats.values())
    if total == 0:
        return {}
    return {party: n / total for party, n in seats.items()}


def weighted_share_by_jurisdiction(entries: list[tuple[dict[str, float], float]]) -> dict[str, float]:
    """[(政党シェアdict, 重み)]を重みで加重平均する。

    個々の自治体をそれぞれ自身の重み(通常は人口)で直接加重するための共通ロジック
    (compute_executive_indexで使用)。
    """
    weighted: dict[str, float] = {}
    total_w = 0.0
    for shares, w in entries:
        for party, share in shares.items():
            weighted[party] = weighted.get(party, 0.0) + w * share
        total_w += w
    return {p: v / total_w for p, v in weighted.items()} if total_w else {}


def compute_assembly_index(diet_seats: dict[str, dict[str, int]]) -> dict[str, float]:
    """議会指数 $I_p(t)$: 国会(衆参合算)の議席占有率 $\\phi_p^{(国会)}(t)$。

    ここでの「衆参合算」は単なる議席数の比率(線形量)であり、衆参それぞれの
    占有率を自院の議席数で加重平均した値と数学的に完全に一致する
    ($\\sum_c n_c\\phi_p^{(c)} / \\sum_c n_c$は各院の生の議席数をそのまま足し合わせるのと同じ)。
    したがって衆参を分けて計算しても同じ結果になり、単純合算のままで問題ない。
    これは\\texttt{compute_combined_index}の$\\sqrt{n_eP_e}$のような非線形(平方根)の
    重みを衆参合算後の総議席数に対して掛ける場合とは事情が異なる——非線形な
    重みでは「先に合算してから重みを掛ける」と「院ごとに重みを掛けてから
    合算する」で異なる値になるため、\\texttt{compute_combined_index}では衆参を
    分離している(2026-09にユーザー指摘、design_document.tex \\S2.2参照)。

    国政政党の集合は衆参の会派構成そのものから導出し(\\texttt{national_parties_from_diet}参照)、
    それ以外の地域政党は無所属・諸派に一括する(実質的に発生しないが、関数の
    一貫性のため引数は残す)。
    """
    kokkai = {}
    for chamber_seats in diet_seats.values():
        for name, n in chamber_seats.items():
            kokkai[name] = kokkai.get(name, 0) + n

    national_parties = national_parties_from_diet(diet_seats)
    return _phi(kokkai, national_parties)


def _executive_jurisdiction_entries(
    national_parties: set[str] | None, weight_fn
) -> tuple[list[tuple[dict[str, float], float]], int, int]:
    """既知の知事・市区町村長を(政党シェア, 重み)のリストにする。

    知事はregistry(政治山で確認できた分は更新済み)、市区町村長はmunicipal_registry
    (go2senkyo由来、無ければWikidata)から、既知の自治体ぶんだけを積み上げる。
    総務省の年次集計(全国集計値)は個々の自治体を特定できないため使えない
    ([[seiryoku_shisu_design]]参照)。カバレッジが低いうちは既知の自治体が
    少なく偏りうるため、必ずcoverageと合わせて解釈する。

    推薦・支持による無所属首長の仕分けは、地方自治総合研究所「全国首長名簿」の
    直近1年ぶんの選挙結果(jichisoken)で確認できた自治体にのみ反映する。対象期間に
    選挙が無かった自治体は従来通り届出政党(多くは無所属のまま)を使う。
    """
    from . import municipal_registry, registry
    from .fetch import jichisoken, population

    gov_registry = registry.load_or_init_registry()
    pref_pop = population.prefecture_population_by_name()
    gov_endorsements = jichisoken.governor_endorsements()

    muni_state = municipal_registry.load_checkpoint()
    muni_pop = population.municipal_population_by_name()
    muni_endorsements = jichisoken.municipal_head_endorsements()

    entries: list[tuple[dict[str, float], float]] = []
    known_jurisdictions = 0

    for pref, entry in gov_registry.items():
        p = pref_pop.get(pref)
        if p is None:
            continue
        endorsement = gov_endorsements.get(pref)
        endorsing = endorsement.endorsing_parties if endorsement else []
        entries.append((_effective_party_shares(entry["party"], endorsing, national_parties), weight_fn(p)))
        known_jurisdictions += 1

    for jid_str, entry in muni_state["head"].items():
        name = municipal_registry.jurisdiction_name(int(jid_str))
        p = muni_pop.get(name)
        if p is None:
            continue
        endorsement = muni_endorsements.get(name)
        endorsing = endorsement.endorsing_parties if endorsement else []
        entries.append((_effective_party_shares(entry["party"], endorsing, national_parties), weight_fn(p)))
        known_jurisdictions += 1

    total_jurisdictions = municipal_registry.coverage_report(muni_state)["total_jichitai"]
    return entries, known_jurisdictions, total_jurisdictions


def compute_executive_index(national_parties: set[str] | None = None, weight_fn=None) -> dict:
    """首長指数 $E_p(t)$: 都道府県・市区町村を「体」でまとめず、既知の自治体を
    個々にその自治体自身の人口の平方根で重み付けして直接集計する。

    $$E_p(t) = \\frac{\\sum_{j\\in 既知の自治体} \\sqrt{P_j}\\cdot\\mathbb{1}[党(j,t)=p]}
                      {\\sum_{j\\in 既知の自治体} \\sqrt{P_j}}$$

    人口の平方根で重み付けるのは、二段階の投票システムで個々の有権者の実効
    投票力を自治体規模によらず均等にする「ペンローズの平方根則」に基づく
    (2026-09にユーザー指摘で予算の線形重みから変更、[[seiryoku_shisu_design]]参照)。

    national_partiesを渡すと、それ以外の政党(地域政党等)を無所属・諸派に一括する。
    省略した場合は衆参の会派構成から自前で導出する。
    """
    import math

    from .fetch import diet

    if weight_fn is None:
        weight_fn = math.sqrt
    if national_parties is None:
        national_parties = national_parties_from_diet(diet.fetch_diet_seats())

    entries, known_jurisdictions, total_jurisdictions = _executive_jurisdiction_entries(
        national_parties, weight_fn
    )
    return {
        "share": weighted_share_by_jurisdiction(entries),
        "known_jurisdictions": known_jurisdictions,
        "total_jurisdictions": total_jurisdictions,
    }


def compute_combined_index(weight_fn=None) -> dict:
    """政党インパクト指数 $C_p(t)$: 国会(衆参それぞれ別枠)+ 既知の知事・
    市区町村長を、人口と議席・ポスト数の積の平方根$\\sqrt{n_jP_j}$で加重した
    単一の合成指数。

    $$C_p(t) = \\frac{\\sum_{c\\in\\{衆,参\\}}\\sqrt{n_cP_{国}}\\cdot\\phi_p^{(c)}(t)
                       + \\sum_{j\\in 既知の自治体} \\sqrt{P_j}\\cdot\\mathbb{1}[党(j,t)=p]}
                      {\\sum_{c}\\sqrt{n_cP_{国}} + \\sum_{j} \\sqrt{P_j}}$$

    衆院・参院は現在の議席数$n_c$も掛けるが、$\\sqrt{\\cdot}$が非線形なため
    「衆参の議席をまず合算してから$\\sqrt{n_{国}P_{国}}$を1回だけ掛ける」のとは
    異なる値になる——$n_{衆}, n_{参}$を個別に立てたほうが、院をまたいで
    合算した場合より重みの合計が大きくなる($\\sqrt{a}+\\sqrt{b} \\geq \\sqrt{a+b}$、
    2026-09にユーザー指摘で衆参合算から分離、design_document.tex \\S2.2参照)。
    知事・市区町村長は$n_j=1$なので$\\sqrt{n_jP_j}=\\sqrt{P_j}$のまま
    (モジュールdocstring参照)。
    """
    import math

    from .fetch import diet, population

    if weight_fn is None:
        weight_fn = math.sqrt

    diet_seats = diet.fetch_diet_seats()
    national_parties = national_parties_meeting_requirement(
        diet_seats,
        shugiin_district_pct=_latest_shugiin_district_pct(),
        sangiin_district_pct=_latest_sangiin_district_pct(),
    )
    national_pop = population.national_population()

    entries, known_jurisdictions, total_jurisdictions = _executive_jurisdiction_entries(
        national_parties, weight_fn
    )
    for chamber_seats in diet_seats.values():
        n_c = sum(chamber_seats.values())
        if n_c == 0:
            continue
        entries.append((_phi(chamber_seats, national_parties), math.sqrt(n_c * national_pop)))

    return {
        "share": weighted_share_by_jurisdiction(entries),
        "known_jurisdictions": known_jurisdictions,
        "total_jurisdictions": total_jurisdictions,
    }


def _latest_shugiin_district_pct() -> dict[str, float]:
    """直近の衆院選(小選挙区)の党派別得票率。回次は会派別議員数の変遷ページの
    セッション表記(「第51回」等)からそのまま取り出す(固定値を決め打ちしない)。
    """
    import re

    from .fetch import diet_history, vote_share

    history = diet_history.fetch_shugiin_history()
    if not history:
        return {}
    m = re.search(r"\d+", history[-1].session)
    if not m:
        return {}
    return vote_share.shugiin_district_vote_pct(int(m.group()))


def _latest_sangiin_district_pct() -> dict[str, float]:
    """直近の参院選(選挙区)の党派別得票率。参院選は1947年から3年ごとの完全に
    規則的な周期のため、現在の年からその年までに実施済みの直近の回次を機械的に
    導出できる(vote_share.sangiin_ordinal_for_year参照)。
    """
    from datetime import date

    from .fetch import vote_share

    ordinal = vote_share.sangiin_ordinal_for_year(date.today().year)
    return vote_share.sangiin_district_vote_pct(ordinal)
