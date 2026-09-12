"""Wikidataから自治体の現職首長・政党をフォールバックとして取得する。

go2senkyoが取得できなかった自治体を補うための情報源。大きい自治体ほど
充実し、小さい町村は「首長」項目自体が無いことが多い([[seiryoku_shisu_design]]参照)。
"""
from __future__ import annotations

import json

from .util import fetch

_API = "https://www.wikidata.org/w/api.php"
_ENTITY = "https://www.wikidata.org/wiki/Special:EntityData/{}.json"

P_HEAD_OF_GOVERNMENT = "P6"
P_PARTY = "P102"
P_END_TIME = "P582"


def _search_entity_id(name: str) -> str | None:
    url = f"{_API}?action=wbsearchentities&search={name}&language=ja&format=json"
    data = json.loads(fetch(url))
    results = data.get("search") or []
    return results[0]["id"] if results else None


def _get_entity(qid: str) -> dict:
    data = json.loads(fetch(_ENTITY.format(qid)))
    return data["entities"][qid]


def current_head_party(municipality_name: str) -> str | None:
    """自治体名から現職首長の所属政党名を返す(取れなければNone)。"""
    qid = _search_entity_id(municipality_name)
    if qid is None:
        return None
    entity = _get_entity(qid)
    heads = entity.get("claims", {}).get(P_HEAD_OF_GOVERNMENT, [])
    current = [c for c in heads if P_END_TIME not in c.get("qualifiers", {})]
    if not current:
        return None
    person_id = current[-1]["mainsnak"]["datavalue"]["value"]["id"]
    person = _get_entity(person_id)
    parties = person.get("claims", {}).get(P_PARTY, [])
    if not parties:
        return "無所属"  # 政党の記載が無い場合は無所属とみなす
    party_qid = parties[0]["mainsnak"]["datavalue"]["value"]["id"]
    party_entity = _get_entity(party_qid)
    return party_entity.get("labels", {}).get("ja", {}).get("value")
