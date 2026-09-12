"""直近の選挙結果だけを見る「注目度指数」$W_p(T)$を計算する。

議席占有率(ストック)を維持するには「誰が辞めたか」まで追う必要があるが、
そちらは全国ニュースになりにくい。一方「誰が勝ったか」は選挙のたびに確実に
報じられるため、勝敗(フロー)だけを見れば before状態を追跡する必要が無い
([[seiryoku_shisu_design]]参照)。

$$W_p(T) = \\sum_{e:\\ 勝者(e)=p,\\ 投票日(e) \\in T} \\log B_{自治体(e)}$$

各選挙の勝者の政党に、その自治体の歳出規模(千円)の対数を重みとして積算する。
「予算配分」ではなく「注目度」の意味付けなので、都道府県計・市区町村計のような
合算値ではなく自治体ごとの歳出額を使う。線形の$B$だと自治体間の桁違いの差
(小さな村と東京都で1000倍以上)により最大の自治体の勝敗だけで指数がほぼ
決まってしまい、注目度は予算規模に対して逓減的なはずだという直感にも
合わないため、対数を取る。

市区町村長・地方議会は municipal_registry(go2senkyo由来)の as_of を、
知事は registry(governor台帳)の as_of をそのまま流用する。両方とも
バックグラウンドのクロールが進むにつれてカバレッジが上がっていく。
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from . import municipal_registry, registry
from .fetch import budgets


def recent_municipal_wins(days: int = 30) -> dict[str, float]:
    """直近days日ぶんの市区町村長・議会選挙の勝敗を、歳出規模で重み付けして集計する。"""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    state = municipal_registry.load_checkpoint()
    muni_budgets = budgets.municipal_budget_by_name()

    scores: dict[str, float] = {}

    for jid_str, entry in state["head"].items():
        as_of = entry.get("as_of")
        if not as_of or as_of < cutoff:
            continue
        name = municipal_registry.jurisdiction_name(int(jid_str))
        b = muni_budgets.get(name)
        if b is None or b <= 0:
            continue
        scores[entry["party"]] = scores.get(entry["party"], 0) + math.log(b)

    return scores


def recent_governor_wins(days: int = 30) -> dict[str, float]:
    """直近days日ぶんの知事選挙の勝敗を、歳出規模で重み付けして集計する。"""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    gov_registry = registry.load_or_init_registry()
    pref_budgets = budgets.prefecture_budget_by_name()

    scores: dict[str, float] = {}
    for pref, entry in gov_registry.items():
        as_of = entry.get("as_of")
        if not as_of or as_of < cutoff or entry.get("source") != "seijiyama":
            continue
        b = pref_budgets.get(pref)
        if b is None or b <= 0:
            continue
        scores[entry["party"]] = scores.get(entry["party"], 0) + math.log(b)

    return scores


def attention_index(days: int = 30) -> dict:
    """W_p(T)を政党ごとに集計し、正規化した割合とあわせて返す。"""
    muni = recent_municipal_wins(days)
    gov = recent_governor_wins(days)

    combined: dict[str, float] = dict(muni)
    for party, score in gov.items():
        combined[party] = combined.get(party, 0) + score

    total = sum(combined.values())
    share = {p: v / total for p, v in combined.items()} if total else {}

    return {
        "period_days": days,
        "raw": combined,
        "share": share,
    }
