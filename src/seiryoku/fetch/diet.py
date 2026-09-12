"""衆議院・参議院の会派別所属議員数を取得する。"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .util import fetch

SHUGIIN_URL = (
    "https://www.shugiin.go.jp/internet/itdb_annai.nsf/html/statics/shiryo/kaiha_m.htm"
)
SANGIIN_URL = "https://www.sangiin.go.jp/japanese/joho1/kousei/giin/current/giinsu.htm"

# 議席数の集計に含めない行(小計・案内文など)
_NON_PARTY_ROWS = {"欠員", "会派名", "計", "合計", "総定数"}


def _seat_count(text: str) -> int | None:
    """「316（39）」のような文字列から総数だけを取り出す。"""
    m = re.match(r"(\d+)", text)
    return int(m.group(1)) if m else None


def fetch_shugiin_seats() -> dict[str, int]:
    """衆議院の会派別所属議員数を返す({会派名: 議席数})。"""
    raw = fetch(SHUGIIN_URL)
    html = raw.decode("shift_jis", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    seats: dict[str, int] = {}
    for row in table.find_all("tr"):
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 2 or cells[0] in _NON_PARTY_ROWS:
            continue
        name, seat_text = cells[0], cells[-1]
        n = _seat_count(seat_text)
        if n is not None:
            seats[name] = n
    return seats


def fetch_sangiin_seats() -> dict[str, int]:
    """参議院の会派別所属議員数を返す({会派名: 議席数})。

    トップページはJavaScriptのlocation.replaceでリダイレクトするため、
    まず一度取得してリダイレクト先を見つけてから改めて取得する。
    """
    raw = fetch(SANGIIN_URL)
    html = raw.decode("utf-8", errors="ignore")
    m = re.search(r'location\.replace\("([^"]+)"\)', html)
    if m:
        target = m.group(1)
        if target.startswith("/"):
            target = "https://www.sangiin.go.jp" + target
        raw = fetch(target)
        html = raw.decode("utf-8", errors="ignore")

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    seats: dict[str, int] = {}
    for row in table.find_all("tr"):
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 2 or cells[0] in _NON_PARTY_ROWS:
            continue
        name, seat_text = cells[0], cells[1]
        n = _seat_count(seat_text)
        if n is not None:
            seats[name] = n
    return seats


def fetch_diet_seats() -> dict[str, dict[str, int]]:
    """国会(衆議院+参議院)の会派別所属議員数をまとめて返す。"""
    return {
        "衆議院": fetch_shugiin_seats(),
        "参議院": fetch_sangiin_seats(),
    }
