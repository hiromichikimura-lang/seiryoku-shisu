"""総務省「地方公共団体の議会の議員及び長の所属党派別人員調」を取得・解析する。

議会(都道府県議会・市区議会・町村議会)と首長(都道府県知事・市区長・町村長)、
計6シートについて、シート末尾の「合計」行から全国集計値を取り出す。
"""
from __future__ import annotations

import re
from io import BytesIO

import openpyxl
from bs4 import BeautifulSoup

from .util import fetch

ICHIRAN_URL = "https://www.soumu.go.jp/senkyo/senkyo_s/data/syozoku/ichiran.html"
_TARGET_LINK_TEXT = "地方公共団体の議会の議員及び長の所属党派別人員調"

# シート名は年によって表記が異なる(例:「都道府県議会」の年もあれば「4（県議）」の年もある)
# ため、部分一致のキーワードで分類する。判定順序が重要(「町村議」は「議」を含むため
# 「議会」系より先に判定する必要がある、等)。
_SHEET_KEYWORDS: list[tuple[str, str]] = [
    ("知事", "都道府県知事"),
    ("県議", "都道府県議会"),
    ("都道府県議会", "都道府県議会"),
    ("市区長", "市区町村長"),
    ("町村長", "市区町村長"),
    ("市区議", "市区町村議会"),
    ("町村議", "市区町村議会"),
]


def _classify_sheet(sheet_name: str) -> str | None:
    for keyword, body in _SHEET_KEYWORDS:
        if keyword in sheet_name:
            return body
    return None


_ERA_START_YEAR = {"令和": 2019, "平成": 1989}


def _label_to_iso_date(label: str) -> str:
    """「令和7年12月31日現在」のような表記をISO日付(年は西暦)に変換する。"""
    m = re.search(r"(令和|平成)(\d+|元)年(\d+)月(\d+)日", label)
    if not m:
        raise ValueError(f"日付表記を解釈できません: {label}")
    era, year_s, month, day = m.groups()
    year_in_era = 1 if year_s == "元" else int(year_s)
    year = _ERA_START_YEAR[era] + year_in_era - 1
    return f"{year:04d}-{int(month):02d}-{int(day):02d}"


def _find_latest_workbook_url_and_date() -> tuple[str, str]:
    """一覧ページから最新年の党派別人員調Excelへのリンクと、その時点(ISO日付)を返す。"""
    html = fetch(ICHIRAN_URL).decode("shift_jis", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    year_link = soup.select_one("dd a")
    if year_link is None:
        raise RuntimeError("年次ページへのリンクが見つかりません")
    as_of_date = _label_to_iso_date(year_link.get_text(strip=True))
    year_url = "https://www.soumu.go.jp" + year_link["href"]

    year_html = fetch(year_url).decode("shift_jis", errors="ignore")
    year_soup = BeautifulSoup(year_html, "html.parser")
    for a in year_soup.find_all("a", href=True):
        if _TARGET_LINK_TEXT in a.get_text(strip=True) and a["href"].endswith(".xlsx"):
            return "https://www.soumu.go.jp" + a["href"], as_of_date
    raise RuntimeError("党派別人員調Excelへのリンクが見つかりません")


def _find_latest_workbook_url() -> str:
    """一覧ページから最新年の党派別人員調Excelへのリンクを見つける。"""
    return _find_latest_workbook_url_and_date()[0]


def _find_col(row: tuple, label: str) -> int | None:
    for col, val in enumerate(row):
        if val == label:
            return col
    return None


def _parse_sheet_totals(rows: list[tuple]) -> dict[str, int]:
    """1シート(行のリスト)から「合計」行を取り出し、{党派名: 議席数}を返す。

    「団体名」列の位置は年度によって0列目だったり1列目だったりするため、
    固定のインデックスを仮定せず「団体名」セルの位置を探して基準にする。
    """
    header_idx, name_col = next(
        (i, _find_col(r, "団体名"))
        for i, r in enumerate(rows)
        if r and _find_col(r, "団体名") is not None
    )
    name_row = rows[header_idx - 1]
    total_row = next(r for r in rows if r and len(r) > name_col and r[name_col] == "合計")

    _NOT_A_PARTY = {"合計", "欠員"}
    party_cols: dict[str, int] = {}
    for col, val in enumerate(name_row):
        if col < name_col + 2 or not val or val in _NOT_A_PARTY:
            continue
        party_cols[val] = col + 2  # 男(col), 女(col+1), 計(col+2)

    def _at(row: tuple, col: int) -> int:
        return (row[col] or 0) if col < len(row) else 0

    return {party: _at(total_row, col) for party, col in party_cols.items()}


def fetch_local_party_seats() -> dict[str, dict[str, int]]:
    """体(都道府県議会/市区町村議会/都道府県知事/市区町村長)ごとの全国集計を返す。"""
    url = _find_latest_workbook_url()
    wb = openpyxl.load_workbook(BytesIO(fetch(url)), data_only=True, read_only=True)

    merged: dict[str, dict[str, int]] = {}
    for sheet_name in wb.sheetnames:
        body = _classify_sheet(sheet_name)
        if body is None:
            continue
        totals = _parse_sheet_totals(list(wb[sheet_name].iter_rows(values_only=True)))
        bucket = merged.setdefault(body, {})
        for party, n in totals.items():
            bucket[party] = bucket.get(party, 0) + n
    return merged
