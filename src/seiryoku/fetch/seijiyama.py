"""政治山(seijiyama.jp)から地方選挙の一覧・候補者(党派込み)を取得する。

非公式の第三者サイトであり、[[seiryoku_shisu_design]]で検討した通り
結果確定後は選挙管理委員会の公表データを出所としていると明記されている。
一覧は `_limit_3624=200` かつ `_page_3624=N` で200件ずつページングできる
(調査時点で全14,614件、74ページ)。
"""
from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup

from .util import fetch

_BASE = "https://seijiyama.jp/area/table/3624/BjtDe5/M"
_S_TOKEN = "qipe2lcqbo"  # このクエリ設定(絞り込みなし・全件)に対応する固定トークン


@dataclass
class ElectionListing:
    vote_date: str
    announce_date: str
    name: str
    prefecture: str
    detail_url: str | None


@dataclass
class Candidate:
    name: str
    party: str | None
    elected: bool


def list_elections_page(page: int, limit: int = 200) -> list[ElectionListing]:
    url = f"{_BASE}?S={_S_TOKEN}&_limit_3624={limit}&_page_3624={page}"
    html = fetch(url).decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    table = next(t for t in soup.find_all("table") if t.get("class") == ["smp-table"])

    results = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) != 6:
            continue
        texts = [c.get_text(strip=True) for c in cells]
        if texts[0] in ("投票日", ""):
            continue
        link = cells[4].find("a", href=True)
        results.append(
            ElectionListing(
                vote_date=texts[0],
                announce_date=texts[1],
                name=texts[2],
                prefecture=texts[3],
                detail_url=("https://seijiyama.jp" + link["href"]) if link else None,
            )
        )
    return results


def parse_candidates(detail_url: str) -> list[Candidate]:
    html = fetch(detail_url).decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    table = next((t for t in soup.find_all("table", class_="smp-table") if "党派" in t.get_text()), None)
    if table is None:
        return []

    rows = table.find_all("tr")
    header_row = next(
        (r for r in rows if "氏名" in [c.get_text(strip=True) for c in r.find_all("td")]),
        None,
    )
    if header_row is None:
        return []

    header = [c.get_text(strip=True) for c in header_row.find_all("td")]
    name_col = header.index("氏名")
    party_col = header.index("党派") if "党派" in header else None
    elected_col = 0  # 「当」マークは無題の先頭列に入る

    candidates = []
    for row in rows[rows.index(header_row) + 1 :]:
        cells = row.find_all("td")
        if len(cells) != len(header):
            continue
        texts = [c.get_text(strip=True) for c in cells]
        if not texts[name_col]:
            continue
        candidates.append(
            Candidate(
                name=texts[name_col],
                party=texts[party_col] if party_col is not None else None,
                elected=texts[elected_col] == "当",
            )
        )
    return candidates
