"""選挙ドットコム(go2senkyo.com)から自治体ごとの選挙履歴・候補者(党派込み)を取得する。

`/local/jichitai/<ID>/head`(首長)・`/local/jichitai/<ID>/gikai`(議会)という
自治体ごとの固定URLが直近まで追従していることを確認済み([[seiryoku_shisu_design]]参照)。
ただし全自治体ぶんの<ID>を網羅的に集める仕組みはまだ無く、既知のIDを渡して使う。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from .util import fetch

_BASE = "https://go2senkyo.com"


@dataclass
class ElectionHistoryRow:
    vote_date: str
    announce_date: str
    name: str
    turnout: str
    num_candidates: int | None
    detail_url: str | None


@dataclass
class Candidate:
    name: str
    party: str | None
    elected: bool


def jurisdiction_history(jichitai_id: int, kind: str = "head") -> list[ElectionHistoryRow]:
    """自治体(jichitai_id)の首長("head")または議会("gikai")の選挙履歴を返す。新しい順。"""
    url = f"{_BASE}/local/jichitai/{jichitai_id}/{kind}"
    html = fetch(url).decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    rows: list[ElectionHistoryRow] = []
    for tr in soup.select("table tr"):
        cells = tr.find_all("td")
        if len(cells) < 5:
            continue
        texts = [c.get_text(strip=True) for c in cells]
        if not re.match(r"\d{4}/\d{2}/\d{2}|未定", texts[0]):
            continue
        link = tr.find("a", href=True)
        m = re.search(r"(\d+)\s*人", texts[4])
        detail_url = None
        if link:
            href = link["href"]
            detail_url = href if href.startswith("http") else (_BASE + href)
        rows.append(
            ElectionHistoryRow(
                vote_date=texts[0],
                announce_date=texts[1],
                name=texts[2],
                turnout=texts[3],
                num_candidates=int(m.group(1)) if m else None,
                detail_url=detail_url,
            )
        )
    return rows


def _parse_candidates_from_soup(soup: BeautifulSoup) -> list[Candidate]:
    candidates = []
    for section in soup.select(".m_senkyo_result_data"):
        name_tag = section.select_one(".m_senkyo_result_data_ttl")
        if name_tag is None:
            continue
        kana = name_tag.select_one(".m_senkyo_result_data_kana")
        name = name_tag.get_text(strip=True)
        if kana:
            name = name.replace(kana.get_text(strip=True), "").strip()

        party_tag = section.select_one(".m_senkyo_result_data_circle")
        party = party_tag.get_text(strip=True) if party_tag else None

        row = section.find_parent("tr")
        elected = False
        if row is not None:
            first_cell = row.find("td")
            elected = first_cell is not None and "red" in (first_cell.get("class") or [])

        candidates.append(Candidate(name=name, party=party, elected=elected))
    return candidates


def _district_sub_urls(soup: BeautifulSoup, detail_url: str) -> list[str]:
    """都道府県議会議員選挙のように複数選挙区にまたがる場合、詳細ページ自体には
    候補者が載らず、選挙区ごとの下位ページ(detail_url + "/<区ID>")へのリンクが
    並ぶだけになっている(北海道議会議員選挙で確認済み)。そのリンク一覧を返す。
    """
    prefix = detail_url.rstrip("/") + "/"
    urls = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        full = href if href.startswith("http") else (_BASE + href)
        if full.startswith(prefix) and full not in seen and re.fullmatch(r"\d+", full[len(prefix):]):
            seen.add(full)
            urls.append(full)
    return urls


def parse_candidates(detail_url: str) -> list[Candidate]:
    """個別選挙ページから候補者ごとの党派・当落を取得する。

    都道府県議会議員選挙は複数の選挙区(市郡単位)に分かれており、detail_url自体は
    各選挙区ページへのリンク一覧を持つだけで候補者情報を持たない。その場合は
    選挙区ごとの下位ページを全て取得して候補者リストを合算する。
    """
    html = fetch(detail_url).decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    candidates = _parse_candidates_from_soup(soup)
    if candidates:
        return candidates

    sub_urls = _district_sub_urls(soup, detail_url)
    for sub_url in sub_urls:
        sub_html = fetch(sub_url).decode("utf-8", errors="ignore")
        candidates.extend(_parse_candidates_from_soup(BeautifulSoup(sub_html, "html.parser")))
    return candidates
