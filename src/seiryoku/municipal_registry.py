"""市区町村長・地方議会の議席台帳(go2senkyoを主、Wikidataを補完として使う)。

総務省は都道府県単位の集計しか無く個々の自治体を特定できないため、
governor向けのregistryモジュールのような「総務省を基準点、go2senkyoを差分」
という設計が使えない([[seiryoku_shisu_design]]参照)。代わりに、
各自治体の「直近の完了済み選挙の当選者」がその時点での現在の構成である、
という代表制民主主義の性質をそのまま使う。

完璧な単一の情報源は存在しない前提で、拾えるだけ拾って網羅率を明示する
方針を取る: go2senkyoで取れなかった首長はWikidataで補い、それでも
取れなかった分は「不明」として集計から除外する(推測で埋めない)。
議会(gikai)は個々の議席の情報がWikidataに無いため、go2senkyoのみ。

1788自治体 x (head+gikai) x (履歴取得+候補者取得) で数千リクエストになり
時間がかかるため、チェックポイント保存(中断・再開可能)を行う。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .fetch import go2senkyo, wikidata
from .lineage import canonicalize

IDS_PATH = Path(__file__).resolve().parents[2] / "data" / "jichitai_ids.txt"
MUNI_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "data" / "municipal_registry.json"

_PREFECTURE_SUFFIX = "知事選挙"
_HEAD_SUFFIXES = ("市長選挙", "区長選挙", "町長選挙", "村長選挙")
# 都道府県議会(道・都・府・県議会議員選挙)は総務省の年次集計で100%カバーできて
# いるため、gikaiの集計対象は市区町村議会に限る。選挙名は「補欠選挙」等の接尾辞が
# 付くことがあるため、末尾一致ではなく部分一致で見る。
_PREFECTURE_GIKAI_MARKERS = ("道議会議員", "都議会議員", "府議会議員", "県議会議員")


def load_jichitai_ids() -> list[int]:
    return [int(line) for line in IDS_PATH.read_text().splitlines() if line.strip()]


def load_checkpoint() -> dict:
    if MUNI_REGISTRY_PATH.exists():
        return json.loads(MUNI_REGISTRY_PATH.read_text(encoding="utf-8"))
    return {"head": {}, "gikai": {}, "done_ids": [], "errors": {}}


def save_checkpoint(state: dict) -> None:
    MUNI_REGISTRY_PATH.parent.mkdir(exist_ok=True)
    MUNI_REGISTRY_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def reset_errors(state: dict) -> dict:
    """前回エラーになったIDをdone_idsから外し、build_registryで再試行できるようにする。

    成功済みのhead/gikaiデータはそのまま残す(取り直さない)。
    """
    error_ids = set(state["errors"])
    state["done_ids"] = [jid for jid in state["done_ids"] if str(jid) not in error_ids]
    state["errors"] = {}
    return state


def jurisdiction_name(jichitai_id: int) -> str | None:
    """jichitai_idから自治体名を取得する(head履歴の1行目から)。

    既に処理済みのIDであればutil.fetchのキャッシュにヒットするため
    ネットワークアクセスは発生しない。
    """
    history = go2senkyo.jurisdiction_history(jichitai_id, "head")
    if not history:
        return None
    return _municipality_name(history[0].name)


_NOT_GENERAL_ELECTION = ("補欠", "再選挙", "増員")


def _latest_completed(history: list, general_only: bool = False) -> object | None:
    """直近の完了済み選挙を返す。general_only=Trueなら補欠・再選挙・増員選挙を除外する。

    議会選挙(gikai)は補欠選挙が一部の議席しか改選しないため、全体の構成を
    知るには直近の「通常」選挙を使う必要がある(general_only=True)。
    首長選挙(head)は1議席なので補欠選挙でも現職を正しく表せる。
    """
    for row in history:
        if general_only and any(s in row.name for s in _NOT_GENERAL_ELECTION):
            continue
        if row.vote_date != "未定" and row.turnout not in ("-%", "") and row.detail_url:
            return row
    return None


def _municipality_name(election_name: str) -> str:
    """「小樽市長選挙」→「小樽市」のように選挙名から自治体名を取り出す。"""
    for suffix in ("長選挙", "長補欠選挙", "長再選挙"):
        if election_name.endswith(suffix):
            return election_name[: -len(suffix)]
    return re.sub(r"(議会議員)?(補欠|再)?選挙$", "", election_name)


def _process_head(jichitai_id: int) -> tuple[str, dict | None]:
    """戻り値: (種別"prefecture"|"municipality", {party, as_of, source} または None)。"""
    history = go2senkyo.jurisdiction_history(jichitai_id, "head")
    if not history:
        return "unknown", None
    kind = "prefecture" if history[0].name.endswith(_PREFECTURE_SUFFIX) else "municipality"
    if kind != "municipality":
        return kind, None

    latest = _latest_completed(history)
    if latest is not None:
        try:
            candidates = go2senkyo.parse_candidates(latest.detail_url)
        except Exception:
            # 候補者詳細ページの取得だけがWAF等で失敗した場合でも、履歴ページの
            # 取得(history)は既に成功しており自治体名は分かっているため、
            # ここで諦めずWikidataへフォールバックする。
            candidates = []
        winner = next((c for c in candidates if c.elected), None)
        if winner is not None:
            return kind, {
                "party": canonicalize(winner.party) if winner.party else "無所属",
                "as_of": latest.vote_date.replace("/", "-"),
                "source": "go2senkyo",
            }

    # go2senkyoで取れなければWikidataで補う
    name = _municipality_name(history[0].name)
    party = wikidata.current_head_party(name)
    if party is not None:
        return kind, {"party": canonicalize(party), "as_of": None, "source": "wikidata"}

    return kind, None


def _process_gikai(jichitai_id: int) -> dict[str, int] | None:
    """市区町村議会の直近の通常選挙結果を返す。都道府県議会は総務省の年次集計を
    使うためNoneを返す(kindの判定はheadに頼らずgikai自身の選挙名で行う。
    headの取得に失敗していてもgikaiは独立に試行できるようにするため)。
    """
    history = go2senkyo.jurisdiction_history(jichitai_id, "gikai")
    if not history or any(m in history[0].name for m in _PREFECTURE_GIKAI_MARKERS):
        return None
    latest = _latest_completed(history, general_only=True)
    if latest is None:
        return None
    candidates = go2senkyo.parse_candidates(latest.detail_url)
    winners = [c for c in candidates if c.elected]
    if not winners:
        return None
    seats: dict[str, int] = {}
    for c in winners:
        party = canonicalize(c.party) if c.party else "無所属"
        seats[party] = seats.get(party, 0) + 1
    return seats


def build_registry(limit: int | None = None, checkpoint_every: int = 20) -> dict:
    """全自治体(または先頭limit件)をクロールし、チェックポイント保存しながら台帳を構築する。"""
    ids = load_jichitai_ids()
    if limit is not None:
        ids = ids[:limit]

    state = load_checkpoint()
    done = set(state["done_ids"])

    for i, jid in enumerate(ids):
        if jid in done:
            continue
        errors = []
        try:
            kind, head_result = _process_head(jid)
            if kind == "municipality" and head_result is not None:
                state["head"][str(jid)] = head_result
        except Exception as e:
            errors.append(f"head: {e}")
        try:
            # gikaiはheadの成否に関わらず独立に試行する(headが例外で落ちても
            # gikaiだけは取得できる場合があるため)。
            gikai_result = _process_gikai(jid)
            if gikai_result is not None:
                state["gikai"][str(jid)] = gikai_result
        except Exception as e:
            errors.append(f"gikai: {e}")
        if errors:
            state["errors"][str(jid)] = "; ".join(errors)
        elif str(jid) in state["errors"]:
            del state["errors"][str(jid)]
        state["done_ids"].append(jid)
        done.add(jid)

        if (i + 1) % checkpoint_every == 0:
            save_checkpoint(state)
            print(f"checkpoint: {i + 1}/{len(ids)} processed")

    save_checkpoint(state)
    return state


def aggregate(state: dict) -> dict[str, dict[str, int]]:
    """台帳から{体: {政党: 議席数/自治体数}}を集計する。"""
    mayor_counts: dict[str, int] = {}
    for entry in state["head"].values():
        mayor_counts[entry["party"]] = mayor_counts.get(entry["party"], 0) + 1

    assembly_counts: dict[str, int] = {}
    for seats in state["gikai"].values():
        for party, n in seats.items():
            assembly_counts[party] = assembly_counts.get(party, 0) + n

    return {"市区町村長": mayor_counts, "市区町村議会": assembly_counts}


GIKAI_TERM_CHAIN_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "gikai_term_chains.json"


def _all_completed_gikai(history: list) -> list:
    """未定・投票率不明・補欠/再選挙/増員選挙を除いた完了済みの「通常」議会選挙を
    新しい順に全件返す(_latest_completedの「全件版」、[[seiryoku_shisu_design]]の
    月次$I_p(t)$再構成参照)。"""
    return [
        row
        for row in history
        if row.vote_date != "未定"
        and row.turnout not in ("-%", "")
        and row.detail_url
        and not any(s in row.name for s in _NOT_GENERAL_ELECTION)
    ]


def _tally_seats(candidates: list) -> dict[str, int]:
    seats: dict[str, int] = {}
    for c in candidates:
        if not c.elected:
            continue
        party = canonicalize(c.party) if c.party else "無所属"
        seats[party] = seats.get(party, 0) + 1
    return seats


def _build_gikai_term_chain(jichitai_id: int, min_year: int) -> list[dict]:
    """1議会ぶんの選挙履歴を新しい順に遡り、{vote_date, seats}のリストを返す。
    turnover._build_term_chain(首長)の議会版——1回の選挙で複数議席が同時に
    改選されるため、単一の政党ではなく党派別議席数の辞書を保持する点が異なる。
    都道府県議会・市区町村議会のどちらも対象にする(現行のI_p(t)は総務省の年次
    集計に頼っている都道府県議会を含め、月次再構成には両方の個別選挙結果が要る)。
    """
    history = go2senkyo.jurisdiction_history(jichitai_id, "gikai")
    chain: list[dict] = []
    for row in _all_completed_gikai(history):
        try:
            candidates = go2senkyo.parse_candidates(row.detail_url)
        except Exception:
            break
        seats = _tally_seats(candidates)
        if not seats:
            continue
        vote_date = row.vote_date.replace("/", "-")
        chain.append({"vote_date": vote_date, "seats": seats})
        year = vote_date[:4]
        if year.isdigit() and int(year) <= min_year:
            break
    return chain


def load_gikai_term_chain_cache() -> dict:
    if GIKAI_TERM_CHAIN_CACHE_PATH.exists():
        return json.loads(GIKAI_TERM_CHAIN_CACHE_PATH.read_text(encoding="utf-8"))
    return {"chains": {}, "done_ids": [], "errors": {}}


def save_gikai_term_chain_cache(state: dict) -> None:
    GIKAI_TERM_CHAIN_CACHE_PATH.parent.mkdir(exist_ok=True)
    GIKAI_TERM_CHAIN_CACHE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def build_gikai_term_chain_cache(
    jichitai_ids: list[int] | None = None, min_year: int = 2018, checkpoint_every: int = 20
) -> dict:
    """全1788自治体(都道府県議会・市区町村議会とも)の議会選挙履歴を、前回選挙・
    その前……とmin_year以前に到達するまで遡ってdata/gikai_term_chains.jsonへ
    チェックポイント保存する(中断・再開可能)。turnover.build_term_chain_cache()の
    議会版。都道府県議会は現行のI_p(t)計算では総務省の年次集計を使っており
    go2senkyoの個別選挙結果を一度も取得していないため、選挙履歴一覧(history)は
    既存クロールでキャッシュ済みでも候補者詳細は全件新規リクエストになる。
    """
    ids = jichitai_ids if jichitai_ids is not None else load_jichitai_ids()
    state = load_gikai_term_chain_cache()
    done = set(state["done_ids"])

    for i, jid in enumerate(ids):
        if jid in done:
            continue
        try:
            chain = _build_gikai_term_chain(jid, min_year)
            if chain:
                state["chains"][str(jid)] = chain
        except Exception as e:
            state["errors"][str(jid)] = str(e)
        state["done_ids"].append(jid)
        done.add(jid)
        if (i + 1) % checkpoint_every == 0:
            save_gikai_term_chain_cache(state)
            print(f"checkpoint: {i + 1}/{len(ids)} processed", flush=True)

    save_gikai_term_chain_cache(state)
    return state


def refresh_stale_gikai_term_chains(jichitai_ids: list[int] | None = None) -> dict:
    """turnover.refresh_stale_term_chains()の議会版。done_ids入りした自治体は
    build_gikai_term_chain_cache()が二度と再取得しないため、新しい議会選挙が
    実施されても永久に反映されない同じ不具合がある(2026-09発覚)。

    既にdone_idsに入っている自治体について、go2senkyoの最新ページを強制的に
    再取得し、キャッシュ済みチェーンの先頭より新しい完了済み選挙が無いか確認する。
    見つかればdone_idsから外す。"""
    state = load_gikai_term_chain_cache()
    ids = jichitai_ids if jichitai_ids is not None else list(state["done_ids"])

    stale: list[int] = []
    for jid in ids:
        try:
            history = go2senkyo.jurisdiction_history(jid, "gikai", force=True)
        except Exception:
            continue
        completed = _all_completed_gikai(history)
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
        save_gikai_term_chain_cache(state)

    return {"checked": len(ids), "stale": stale}


def refresh_and_rebuild_gikai_term_chains(jichitai_ids: list[int] | None = None) -> dict:
    """refresh_stale_gikai_term_chains()で見つかった更新対象だけを、その場で
    build_gikai_term_chain_cache()により再構築する(引数無しで呼ぶと未処理の
    全自治体まで対象になってしまうため、見つかったIDだけを明示的に渡す)。"""
    stats = refresh_stale_gikai_term_chains(jichitai_ids)
    if stats["stale"]:
        build_gikai_term_chain_cache(jichitai_ids=stats["stale"])
    return stats


def coverage_report(state: dict, ids: list[int] | None = None) -> dict:
    """網羅率を返す。「不明」を推測で埋めていないことが分かるよう明示する。"""
    ids = ids if ids is not None else load_jichitai_ids()
    total = len(ids)
    head_by_source: dict[str, int] = {}
    for entry in state["head"].values():
        src = entry.get("source", "unknown")
        head_by_source[src] = head_by_source.get(src, 0) + 1
    return {
        "total_jichitai": total,
        "processed": len(state["done_ids"]),
        "head_covered": len(state["head"]),
        "head_by_source": head_by_source,
        "gikai_covered": len(state["gikai"]),
        "errors": len(state["errors"]),
    }
