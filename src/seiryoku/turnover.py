"""$C_p(T)$を補う「党派転換指数」$W_p^{\\text{turnover}}(T)$(design_document.texの
「党派転換指数(補助指標)」節を参照)。$C_p(T)$が「その期間の選挙結果そのものの
シェア」を見るのに対し、こちらは「前任者から政党が実際に入れ替わった選挙だけ」を
見る、勢いの方向に特化した指標。首長(知事・市区町村長)ぶんのみ実装している——
議会側は「選挙前後の議席数の差分」を求めるのに前回選挙時点の当選者データを
新たに取得する必要があり(現状のmunicipal_registryは直近の選挙結果しか保持
していない)、今後の課題として未着手。

$$\\Delta s_p(e) = s_p(e\\text{後}) - s_p(e\\text{前}), \\qquad
W_p^{\\text{turnover}}(T) = \\sum_{e:\\ 投票日(e)\\in T} \\sqrt{P_{\\text{自治体}(e)}} \\cdot \\max(\\Delta s_p(e), 0)$$

重みに人口の平方根を使うのは$C_p(T)$と同じ理由(index.pyのペンローズの平方根則、
2026-09に対数重みのattention_index.pyから統一)。以前は自治体の予算の対数を
使っていたが、$C_p(T)$のために対数重みを検討して却下した経緯(自治体の「個数」に
埋もれてほぼ均等重みになってしまう)がそのままこの指標にも当てはまるため、
一貫性のために置き換えた。

当選者・前任者どちらも[[seiryoku_shisu_design]]の$C_p(T)$と同じロジック
(index._effective_party_shares)で推薦・支持を反映した{政党: 按分比率}を持つ
(winner_shares/predecessor_shares、どちらも合計1.0)。首長選挙は1議席なので、
どちらも無所属で推薦も無い場合は{"無所属": 1.0}同士の比較になり$\\Delta=0$、
異なる政党への実質的な移動があった場合だけ正の$\\Delta$が生じる。

前任者側の推薦・支持政党は、jichisokenの「最新の既知の状態」(複数年版を
新しい順に上書きしたもの)ではなく、前任者が実際に当選した年の年版データ
(`jichisoken.endorsement_for_vote_year`)を使って判定する。両者が同じ「最新の
既知の状態」を参照すると、前任者も実は同じ政党の推薦を受けた無所属だった
ケースまで見せかけの奪取としてカウントしてしまうバグがあった(2026-09-05、
公明党の異常な高スコアから発覚——加点イベントの100%が前任者=無所属だった)。
該当する年版が見つからない場合は推薦なし(=形式上の届出政党のみ)にフォール
バックする。

前回選挙のデータ(前任者の政党)は新規のネットワーク取得が必要なため、
data/turnover_predecessors.jsonにチェックポイント保存する(municipal_registryと
同じ中断・再開可能な設計、[[seiryoku_shisu_design]]参照)。直近30日だけを見る
通常運用では対象件数が少なく毎回のライブ取得で十分だが、期間を大きく取ると
(例: 全首長ぶんまで遡る)対象が最大1785件になり数時間かかりうるため、
build_predecessor_cache()でバックグラウンド事前構築できるようにしている。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from . import municipal_registry, registry
from .fetch import go2senkyo, jichisoken, population
from .index import _effective_party_shares
from .lineage import canonicalize

PREDECESSOR_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "turnover_predecessors.json"


@dataclass
class TurnoverEvent:
    name: str
    vote_date: str
    winner_shares: dict[str, float]
    predecessor_shares: dict[str, float]
    population: int


def _two_most_recent_completed(jichitai_id: int) -> list:
    history = go2senkyo.jurisdiction_history(jichitai_id, "head")
    completed = [
        row
        for row in history
        if row.vote_date != "未定" and row.turnout not in ("-%", "") and row.detail_url
    ]
    return completed[:2]


def _winner_party(detail_url: str) -> str | None:
    candidates = go2senkyo.parse_candidates(detail_url)
    winner = next((c for c in candidates if c.elected), None)
    if winner is None:
        return None
    return canonicalize(winner.party) if winner.party else "無所属"


def load_predecessor_cache() -> dict:
    if PREDECESSOR_CACHE_PATH.exists():
        return json.loads(PREDECESSOR_CACHE_PATH.read_text(encoding="utf-8"))
    return {"entries": {}, "done_ids": [], "errors": {}}


def save_predecessor_cache(state: dict) -> None:
    PREDECESSOR_CACHE_PATH.parent.mkdir(exist_ok=True)
    PREDECESSOR_CACHE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _fetch_predecessor_data(jichitai_id: int) -> dict | None:
    """直近選挙・前回選挙の投票日と当選政党を返す。前回選挙が確認できなければNone。"""
    rows = _two_most_recent_completed(jichitai_id)
    if len(rows) < 2:
        return None
    latest, previous = rows
    latest_party = _winner_party(latest.detail_url)
    predecessor_party = _winner_party(previous.detail_url)
    if latest_party is None or predecessor_party is None:
        return None
    return {
        "latest_vote_date": latest.vote_date.replace("/", "-"),
        "latest_party": latest_party,
        "predecessor_vote_date": previous.vote_date.replace("/", "-"),
        "predecessor_party": canonicalize(predecessor_party),
    }


def _all_head_jichitai_ids() -> list[int]:
    """首長データがある(municipal_registryのhead + 47都道府県知事)jichitai_id一覧。"""
    muni_state = municipal_registry.load_checkpoint()
    ids = [int(jid_str) for jid_str in muni_state["head"]]
    ids.extend(_GOVERNOR_JICHITAI_IDS_LIST())
    return ids


def build_predecessor_cache(jichitai_ids: list[int] | None = None, checkpoint_every: int = 20) -> dict:
    """前回選挙のデータをまとめて事前取得し、data/turnover_predecessors.jsonへ
    チェックポイント保存する(中断・再開可能)。長時間かかりうるので、通常は
    バックグラウンドで実行する運用を想定。
    """
    ids = jichitai_ids if jichitai_ids is not None else _all_head_jichitai_ids()
    state = load_predecessor_cache()
    done = set(state["done_ids"])

    for i, jid in enumerate(ids):
        if jid in done:
            continue
        try:
            data = _fetch_predecessor_data(jid)
            if data is not None:
                state["entries"][str(jid)] = data
        except Exception as e:
            state["errors"][str(jid)] = str(e)
        state["done_ids"].append(jid)
        done.add(jid)
        if (i + 1) % checkpoint_every == 0:
            save_predecessor_cache(state)
            print(f"checkpoint: {i + 1}/{len(ids)} processed", flush=True)

    save_predecessor_cache(state)
    return state


TERM_CHAIN_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "executive_term_chains.json"


def _all_completed(jichitai_id: int, force: bool = False) -> list:
    """未定・投票率不明を除いた完了済み選挙を新しい順に全件返す
    (_two_most_recent_completedの「直近2件」制限を外した版)。"""
    history = go2senkyo.jurisdiction_history(jichitai_id, "head", force=force)
    return [
        row
        for row in history
        if row.vote_date != "未定" and row.turnout not in ("-%", "") and row.detail_url
    ]


def load_term_chain_cache() -> dict:
    if TERM_CHAIN_CACHE_PATH.exists():
        return json.loads(TERM_CHAIN_CACHE_PATH.read_text(encoding="utf-8"))
    return {"chains": {}, "done_ids": [], "errors": {}}


def save_term_chain_cache(state: dict) -> None:
    TERM_CHAIN_CACHE_PATH.parent.mkdir(exist_ok=True)
    TERM_CHAIN_CACHE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_term_chain(jichitai_id: int, min_year: int) -> list[dict]:
    """1自治体ぶんの首長選挙履歴を新しい順に遡り、{vote_date, party}のリストを返す。
    投票年がmin_year以下になった回、または履歴を遡り切ったところで止める
    (ユーザー指示: 前任者だけでなく前々任者・さらにその前も全部たどる。
    ただし無制限に遡っても、jichisoken(全国首長名簿、遡れるのは2018年分まで)で
    無所属を仕分けられない年は結局「形式上の無所属」しか分からず、
    C_p(T)再構成の実益が薄いため、min_year=2018を実質的な下限とする)。
    """
    chain: list[dict] = []
    for row in _all_completed(jichitai_id):
        try:
            candidates = go2senkyo.parse_candidates(row.detail_url)
        except Exception:
            break
        winner = next((c for c in candidates if c.elected), None)
        if winner is None:
            continue
        party = canonicalize(winner.party) if winner.party else "無所属"
        vote_date = row.vote_date.replace("/", "-")
        chain.append({"vote_date": vote_date, "party": party})
        year = vote_date[:4]
        if year.isdigit() and int(year) <= min_year:
            break
    return chain


def build_term_chain_cache(
    jichitai_ids: list[int] | None = None, min_year: int = 2018, checkpoint_every: int = 20
) -> dict:
    """前任者・前々任者…とmin_year以前の選挙に到達するまで遡って
    data/executive_term_chains.jsonへチェックポイント保存する(中断・再開可能)。
    既にキャッシュ済みの直近2件(turnover_predecessors.json由来のリクエストで
    util.fetchのキャッシュに乗っている分)は新規アクセス無しで済むが、3件目以降は
    自治体ごとに新規リクエストが発生するため、build_predecessor_cache以上に
    長時間かかる見込み(実行前に対象件数を確認しておくこと)。
    """
    ids = jichitai_ids if jichitai_ids is not None else _all_head_jichitai_ids()
    state = load_term_chain_cache()
    done = set(state["done_ids"])

    for i, jid in enumerate(ids):
        if jid in done:
            continue
        try:
            chain = _build_term_chain(jid, min_year)
            if chain:
                state["chains"][str(jid)] = chain
        except Exception as e:
            state["errors"][str(jid)] = str(e)
        state["done_ids"].append(jid)
        done.add(jid)
        if (i + 1) % checkpoint_every == 0:
            save_term_chain_cache(state)
            print(f"checkpoint: {i + 1}/{len(ids)} processed", flush=True)

    save_term_chain_cache(state)
    return state


def refresh_stale_term_chains(jichitai_ids: list[int] | None = None) -> dict:
    """done_ids入りした自治体は、build_term_chain_cache()が二度と再取得しない
    (中断・再開可能にするための恒久スキップ)。そのため新しい首長選挙が実施されても
    永久に反映されない不具合がある(2026-09、沖縄県知事選で発覚)。

    この関数は既にdone_idsに入っている自治体について、go2senkyoの最新ページを
    強制的に(util.fetchのキャッシュを無視して)再取得し、キャッシュ済みチェーンの
    先頭より新しい完了済み選挙が無いか確認する。見つかればdone_idsから外し、
    次にbuild_term_chain_cache()を呼んだときにそのIDだけが再構築されるようにする。

    1788自治体を約4秒間隔(go2senkyo.comのレート制限)で確認するため数時間かかる
    見込み。記事生成本体とは別の月次ジョブとして実行する想定(refresh_cli.py参照)。
    """
    state = load_term_chain_cache()
    ids = jichitai_ids if jichitai_ids is not None else list(state["done_ids"])

    stale: list[int] = []
    for jid in ids:
        try:
            completed = _all_completed(jid, force=True)
        except Exception:
            continue
        if not completed:
            continue
        newest_date = completed[0].vote_date.replace("/", "-")
        cached_chain = state["chains"].get(str(jid), [])
        cached_top = cached_chain[0]["vote_date"] if cached_chain else None
        if newest_date != cached_top:
            stale.append(jid)

    if stale:
        stale_set = set(stale)
        state["done_ids"] = [jid for jid in state["done_ids"] if jid not in stale_set]
        save_term_chain_cache(state)

    return {"checked": len(ids), "stale": stale}


def refresh_and_rebuild_term_chains(jichitai_ids: list[int] | None = None) -> dict:
    """refresh_stale_term_chains()で見つかった更新対象だけを、その場でbuild_term_chain_cache()
    により再構築する。build_term_chain_cache()をjichitai_ids無しで呼ぶと
    「まだ一度もdoneになっていない全自治体」まで対象になってしまうため、
    見つかったstaleなIDだけを明示的に渡す。"""
    stats = refresh_stale_term_chains(jichitai_ids)
    if stats["stale"]:
        build_term_chain_cache(jichitai_ids=stats["stale"])
    return stats


def _predecessor_endorsing_parties(
    endorsements_by_year: dict | None, name: str, predecessor_vote_date: str | None
) -> list[str]:
    """前任者が実際に当選した年の年版データから推薦・支持政党を引く。見つからなければ
    空リスト(=推薦なし、形式上の届出政党のみで判定)を返す。"""
    if not endorsements_by_year:
        return []
    entry = jichisoken.endorsement_for_vote_year(endorsements_by_year, name, predecessor_vote_date)
    return entry.endorsing_parties if entry is not None else []


def _turnover_event(
    jichitai_id: int,
    name: str,
    population_count: int | None,
    endorsing_parties: list[str],
    predecessor_cache: dict | None = None,
    national_parties: set[str] | None = None,
    predecessor_endorsements_by_year: dict | None = None,
) -> TurnoverEvent | None:
    """jichitai_idの首長選挙について、直近選挙(当選者)と前回選挙(前任者)を
    突き合わせる。前回選挙が確認できない(初めての選挙、データ欠落等)場合はNone。
    predecessor_cacheが渡されればそちらを優先し(ネットワーク取得を省略)、
    無ければその場でライブ取得する。national_partiesを渡すと、それ以外の政党
    (地域政党等)を無所属・諸派に一括する($C_p(T)$と同じ方針、[[seiryoku_shisu_design]]参照)。
    predecessor_endorsements_by_yearを渡すと、前任者側も当選時点の年版データで
    推薦・支持政党を仕分ける(モジュールdocstring参照)。
    """
    if population_count is None:
        return None
    cached = (predecessor_cache or {}).get(str(jichitai_id))
    if cached is not None:
        data = cached
    else:
        data = _fetch_predecessor_data(jichitai_id)
    if data is None:
        return None
    winner_shares = _effective_party_shares(data["latest_party"], endorsing_parties, national_parties)
    predecessor_endorsing = _predecessor_endorsing_parties(
        predecessor_endorsements_by_year, name, data["predecessor_vote_date"]
    )
    predecessor_shares = _effective_party_shares(data["predecessor_party"], predecessor_endorsing, national_parties)
    return TurnoverEvent(
        name=name,
        vote_date=data["latest_vote_date"],
        winner_shares=winner_shares,
        predecessor_shares=predecessor_shares,
        population=population_count,
    )


def _event_weight(event: TurnoverEvent) -> float:
    """イベント1件の重み$\\sqrt{P_e}$。人口が0以下(未確認)なら0。"""
    return math.sqrt(event.population) if event.population > 0 else 0.0


def _delta_scores(event: TurnoverEvent, gain: bool) -> dict[str, float]:
    """1件のTurnoverEventを{政党: 加点}に変換する。gain=Trueなら奪取した側
    ($W_p^{\\text{turnover}}$)、gain=Falseなら奪われた側($L_p^{\\text{turnover}}$)。
    winner_shares・predecessor_sharesは共に合計1.0なので、両者は同じイベントの
    表と裏の関係になる(全政党で合計すると常に一致する)。
    """
    scores: dict[str, float] = {}
    if event.population <= 0:
        return scores
    weight = _event_weight(event)
    parties = set(event.winner_shares) | set(event.predecessor_shares)
    for party in parties:
        diff = event.winner_shares.get(party, 0.0) - event.predecessor_shares.get(party, 0.0)
        delta = diff if gain else -diff
        if delta > 0:
            scores[party] = scores.get(party, 0.0) + weight * delta
    return scores


def _score_event(event: TurnoverEvent) -> dict[str, float]:
    """1件のTurnoverEventをW_p^turnoverへの寄与({政党: 加点})に変換する。"""
    return _delta_scores(event, gain=True)


def _loss_score_event(event: TurnoverEvent) -> dict[str, float]:
    """1件のTurnoverEventをL_p^turnover(奪われた側)への寄与に変換する。"""
    return _delta_scores(event, gain=False)


def _net_score_event(event: TurnoverEvent) -> dict[str, float]:
    """1件のTurnoverEventの正味の党派間シェア移動({政党: 符号付きスコア})。
    $W_p^{\\text{turnover}} - L_p^{\\text{turnover}}$、すなわち$\\max(\\cdot,0)$の
    クリップを外した$\\sqrt{P}\\cdot \\Delta s_p(e)$そのもの。winner_shares・
    predecessor_sharesは共に合計1.0なので、1件のイベントについて全政党で合計すると
    常に0になる(ある政党の純増は別の政党の純減の裏返し、というゼロサム)。
    $W_p^{\\text{turnover}}$は「奪取」だけを見るため常に非負(累積も単調増加)になる
    設計上の性質があり、「勢いが落ちている」政党を負の値として表現できない。
    この符号付きの版は、月次・累積のどちらでも実際に負の値を取りうる。
    """
    scores: dict[str, float] = {}
    if event.population <= 0:
        return scores
    weight = _event_weight(event)
    parties = set(event.winner_shares) | set(event.predecessor_shares)
    for party in parties:
        diff = event.winner_shares.get(party, 0.0) - event.predecessor_shares.get(party, 0.0)
        if diff != 0:
            scores[party] = scores.get(party, 0.0) + weight * diff
    return scores


def turnover_events(days: int | None = 30) -> list[TurnoverEvent]:
    """首長選挙(知事・市区町村長)のturnoverイベント一覧を返す。

    days=Noneなら期間で絞り込まず、as_ofが確認できる全首長を対象にする
    (data/turnover_predecessors.jsonの事前構築キャッシュがあれば優先して使い、
    無ければその場でライブ取得する)。
    """
    from .fetch import diet
    from .index import national_parties_from_diet

    cutoff = (date.today() - timedelta(days=days)).isoformat() if days is not None else None

    muni_populations = population.municipal_population_by_name()
    pref_populations = population.prefecture_population_by_name()
    muni_endorsements_by_year = jichisoken.municipal_head_endorsements_by_year()
    gov_endorsements_by_year = jichisoken.governor_endorsements_by_year()
    muni_endorsements = jichisoken.merge_latest(muni_endorsements_by_year)
    gov_endorsements = jichisoken.merge_latest(gov_endorsements_by_year)
    predecessor_cache = load_predecessor_cache()["entries"]
    national_parties = national_parties_from_diet(diet.fetch_diet_seats())

    events: list[TurnoverEvent] = []

    muni_state = municipal_registry.load_checkpoint()
    for jid_str, entry in muni_state["head"].items():
        as_of = entry.get("as_of")
        if not as_of or (cutoff is not None and as_of < cutoff):
            continue
        jid = int(jid_str)
        name = municipal_registry.jurisdiction_name(jid)
        if not name:
            continue
        endorsement = muni_endorsements.get(name)
        endorsing = endorsement.endorsing_parties if endorsement else []
        event = _turnover_event(
            jid, name, muni_populations.get(name), endorsing, predecessor_cache, national_parties,
            predecessor_endorsements_by_year=muni_endorsements_by_year,
        )
        if event is not None:
            events.append(event)

    gov_registry = registry.load_or_init_registry()
    for pref, entry in gov_registry.items():
        as_of = entry.get("as_of")
        if not as_of or (cutoff is not None and as_of < cutoff):
            continue
        jid = _governor_jichitai_id(pref)
        if jid is None:
            continue
        endorsement = gov_endorsements.get(pref)
        endorsing = endorsement.endorsing_parties if endorsement else []
        event = _turnover_event(
            jid, pref, pref_populations.get(pref), endorsing, predecessor_cache, national_parties,
            predecessor_endorsements_by_year=gov_endorsements_by_year,
        )
        if event is not None:
            events.append(event)

    return events


def turnover_index(days: int | None = 30) -> dict:
    """直近days日ぶんの首長選挙(知事・市区町村長)について $W_p^{\\text{turnover}}(T)$ と、
    奪われた側を見る補集指標 $L_p^{\\text{turnover}}(T)$、その差である符号付きの
    正味スコア(net_raw、$W_p - L_p$、全政党で合計すると常に0)を計算する。
    days=Noneならas_ofが確認できる全首長を対象にする。ただし各自治体につき
    「現職とその直前の前任者」の1組しか比較しないため、実際に遡れる範囲は
    任期4年ぶん程度に限られる(design_document.texの党派転換指数の節を参照)。

    net_rawは対象イベント数・自治体規模に応じて絶対値が伸び縮みするため、
    期間の異なるnet_raw同士(例: 先月と今月)をそのまま比較できない。net_share
    は$\\sum_e\\sqrt{P_e}$(その期間の全イベントの重み)で割った、期間をまたいで
    比較可能な版(2026-09にユーザー指摘で追加、$C_p(T)$と同じ分母を使うがゼロサム
    なので合計は0のまま、100%には正規化されない)。
    """
    events = turnover_events(days)

    combined: dict[str, float] = {}
    loss: dict[str, float] = {}
    net: dict[str, float] = {}
    total_weight = 0.0
    for event in events:
        total_weight += _event_weight(event)
        for party, score in _score_event(event).items():
            combined[party] = combined.get(party, 0) + score
        for party, score in _loss_score_event(event).items():
            loss[party] = loss.get(party, 0) + score
        for party, score in _net_score_event(event).items():
            net[party] = net.get(party, 0) + score

    total = sum(combined.values())
    share = {p: v / total for p, v in combined.items()} if total else {}
    loss_total = sum(loss.values())
    loss_share = {p: v / loss_total for p, v in loss.items()} if loss_total else {}
    net_share = {p: v / total_weight for p, v in net.items()} if total_weight else {}

    return {
        "period_days": days,
        "n_events": len(events),
        "raw": combined,
        "share": share,
        "loss_raw": loss,
        "loss_share": loss_share,
        "net_raw": net,
        "net_share": net_share,
    }


@dataclass
class TurnoverMonthSnapshot:
    year: int
    month: int
    W_p: dict[str, float]
    L_p: dict[str, float]
    net_share: dict[str, float]
    n_events: int


def build_turnover_month_snapshots(min_year: int = 2018, window_months: int = 12) -> list[TurnoverMonthSnapshot]:
    """在任履歴チェーン全体を使い、min_yearまで遡って月次の$W_p^{\\text{turnover}}(T)$・
    $L_p^{\\text{turnover}}(T)$を再構成する。turnover_index()(現職とその直前の
    前任者のみ)と異なり、各自治体の在任履歴チェーンにある\\textbf{隣接する任期の組すべて}
    を転換イベントとして扱うため、2018年まで遡れる(design_document.texの
    党派転換指数の節を参照)。政党要件を満たす政党の集合は、monthly_index.pyと同じく
    直近の国政選挙時点の判定を全期間に固定で適用する。
    """
    from .fetch import diet
    from .index import national_parties_meeting_requirement
    from .monthly_index import (
        _latest_sangiin_district_pct,
        _latest_shugiin_district_pct,
        _month_range,
        _months_back,
        _ym,
    )

    national_parties = national_parties_meeting_requirement(
        diet.fetch_diet_seats(),
        shugiin_district_pct=_latest_shugiin_district_pct(),
        sangiin_district_pct=_latest_sangiin_district_pct(),
    )

    _ensure_governor_ids_loaded()
    gov_id_to_name = {jid: name for name, jid in _GOVERNOR_JICHITAI_IDS.items()}
    chains = load_term_chain_cache()["chains"]

    pref_pop = population.prefecture_population_by_name()
    muni_pop = population.municipal_population_by_name()
    gov_by_year = jichisoken.governor_endorsements_by_year()
    muni_by_year = jichisoken.municipal_head_endorsements_by_year()

    # 月ごとの生イベント(winner_shares, predecessor_shares, weight)。
    entries_by_month: dict[tuple[int, int], list[tuple[dict[str, float], dict[str, float], float]]] = {}

    for jid_str, chain in chains.items():
        jid = int(jid_str)
        if jid in gov_id_to_name:
            name, size, by_year = gov_id_to_name[jid], pref_pop.get(gov_id_to_name[jid]), gov_by_year
        else:
            juris_name = municipal_registry.jurisdiction_name(jid)
            name = juris_name
            size, by_year = (muni_pop.get(juris_name), muni_by_year) if juris_name else (None, None)
        if not name or size is None:
            continue
        weight = math.sqrt(size)

        for i in range(len(chain) - 1):
            later, earlier = chain[i], chain[i + 1]
            ym = _ym(later.get("vote_date"))
            if ym is None or ym < (min_year, 1):
                continue
            later_endorsement = jichisoken.endorsement_for_vote_year(by_year, name, later["vote_date"])
            later_endorsing = later_endorsement.endorsing_parties if later_endorsement else []
            earlier_endorsement = jichisoken.endorsement_for_vote_year(by_year, name, earlier["vote_date"])
            earlier_endorsing = earlier_endorsement.endorsing_parties if earlier_endorsement else []
            winner_shares = _effective_party_shares(later["party"], later_endorsing, national_parties)
            predecessor_shares = _effective_party_shares(earlier["party"], earlier_endorsing, national_parties)
            entries_by_month.setdefault(ym, []).append((winner_shares, predecessor_shares, weight))

    today = date.today()
    months = _month_range((min_year, 1), (today.year, today.month))

    results: list[TurnoverMonthSnapshot] = []
    for ym in months:
        window_entries: list[tuple[dict[str, float], dict[str, float], float]] = []
        for w in _months_back(ym, window_months):
            window_entries.extend(entries_by_month.get(w, []))
        if not window_entries:
            continue

        gain: dict[str, float] = {}
        loss: dict[str, float] = {}
        net: dict[str, float] = {}
        total_weight = 0.0
        for winner_shares, predecessor_shares, weight in window_entries:
            total_weight += weight
            parties = set(winner_shares) | set(predecessor_shares)
            for party in parties:
                diff = winner_shares.get(party, 0.0) - predecessor_shares.get(party, 0.0)
                if diff > 0:
                    gain[party] = gain.get(party, 0.0) + weight * diff
                elif diff < 0:
                    loss[party] = loss.get(party, 0.0) - weight * diff
                if diff != 0:
                    net[party] = net.get(party, 0.0) + weight * diff

        gain_total = sum(gain.values())
        loss_total = sum(loss.values())
        W_p = {p: v / gain_total for p, v in gain.items()} if gain_total else {}
        L_p = {p: v / loss_total for p, v in loss.items()} if loss_total else {}
        # net_shareはC_p(T)と同じ分母(sum sqrt(P))で割った期間比較可能な版
        # (turnover_indexのnet_shareと同じ理由、2026-09にユーザー指摘)。
        net_share = {p: v / total_weight for p, v in net.items()} if total_weight else {}
        results.append(
            TurnoverMonthSnapshot(
                year=ym[0], month=ym[1], W_p=W_p, L_p=L_p, net_share=net_share, n_events=len(window_entries)
            )
        )

    return results


def latest_turnover_snapshot(
    window_months: int = 12,
) -> tuple[TurnoverMonthSnapshot, TurnoverMonthSnapshot | None]:
    """月次記事での実際の使い方に対応する取得口。党派転換指数は「その時点の断面」を
    見るための指標で、月をまたいだトレンドとして素朴に線を追う設計にはなっていない
    (12か月の後方ウィンドウを使うため、隣接する月は11か月ぶん重なっており、
    $C_p(T)$と同じ「ウィンドウの機械的な重なり」の問題がそのまま当てはまる、
    2026-09にユーザー指摘)。そこで、直近window_monthsか月累積の断面を1点だけ、
    前月分の断面と合わせて返す(2番目の戻り値、比較対象が無ければNone)。
    """
    snaps = build_turnover_month_snapshots(window_months=window_months)
    if not snaps:
        raise ValueError("転換イベントが1件も見つかりませんでした")
    latest = snaps[-1]
    prev = snaps[-2] if len(snaps) >= 2 else None
    return latest, prev


_GOVERNOR_JICHITAI_IDS: dict[str, int] | None = None


def _governor_jichitai_id(prefecture_name: str) -> int | None:
    """都道府県名からgo2senkyoのjichitai_id(知事)を引く。1788件のIDは
    「都道府県知事の直後にその都道府県内の市区町村」という順で並んでおり、
    47件が単純に先頭に固まっているわけではない([[seiryoku_shisu_design]]参照)。
    そのため全件を走査して知事選挙(history[0]が「知事選挙」で終わるもの)を
    拾う必要があるが、go2senkyoのjurisdiction_historyは既にクロール済みで
    キャッシュされているため新規のネットワークアクセスは発生しない。
    """
    _ensure_governor_ids_loaded()
    return _GOVERNOR_JICHITAI_IDS.get(prefecture_name)


def _GOVERNOR_JICHITAI_IDS_LIST() -> list[int]:
    _ensure_governor_ids_loaded()
    return list(_GOVERNOR_JICHITAI_IDS.values())


def _ensure_governor_ids_loaded() -> None:
    global _GOVERNOR_JICHITAI_IDS
    if _GOVERNOR_JICHITAI_IDS is not None:
        return
    _GOVERNOR_JICHITAI_IDS = {}
    for jid in municipal_registry.load_jichitai_ids():
        try:
            history = go2senkyo.jurisdiction_history(jid, "head")
        except Exception:
            # 前回のクロールでエラーだった数件(表\ref{tab:coverage}参照)は
            # ここで生のネットワークアクセスになりうるため、失敗は無視して進む。
            continue
        if not history or not history[0].name.endswith("知事選挙"):
            continue
        name = municipal_registry._municipality_name(history[0].name)
        if name.endswith("知事"):
            name = name[: -len("知事")]
        _GOVERNOR_JICHITAI_IDS[name] = jid
