"""国政選挙(衆院選小選挙区・参院選選挙区)の党派別得票率を取得する。

政党助成法上の「政党要件」判定に使う。政党要件は次のいずれかを満たすこと:
(a) 国会議員が5人以上
(b) 国会議員が1人以上、かつ直近の国政選挙(衆院選小選挙区・比例代表、参院選
    選挙区・比例代表のいずれか)で得票率2%以上

本モジュールは(b)のうち、小選挙区(衆院選)・選挙区(参院選)の得票率だけを扱う。
比例代表の「党派別得票数」総務省公表ファイルは、当選者が出た政党だけを掲載する
サマリ(0議席の政党は掲載されない)ため、2%要件の判定には使えないことが判明した
(2026-09に確認)。比例代表ブロック別の順位表(全政党を含む)まで遡れば比例代表も
判定できるが、ブロックごとに集計し直す実装が必要で今回は見送った——比例代表でのみ
2%を満たし小選挙区・選挙区ではどこも満たさない政党があれば、本モジュールでは
政党要件ありと判定できない既知の制約として残る。

総務省の選挙結果ページ(例: https://www.soumu.go.jp/senkyo/senkyo_s/data/shugiin50/)
が公表する「届出政党等別得票数（小選挙区）」「党派別得票数（選挙区）」のExcel
(xls/xlsx、選挙によって形式が異なる)から、総務省が既に計算済みの得票率をそのまま
読み取る(自前で計算し直さない)。
"""
from __future__ import annotations

from io import BytesIO

import openpyxl
import xlrd
from bs4 import BeautifulSoup

from .util import fetch

SOUMU_BASE = "https://www.soumu.go.jp"


def shugiin_index_url(ordinal: int) -> str:
    """第ordinal回衆議院議員総選挙の結果ページURL。"""
    return f"{SOUMU_BASE}/senkyo/senkyo_s/data/shugiin{ordinal}/index.html"


def sangiin_index_url(ordinal: int) -> str:
    """第ordinal回参議院議員通常選挙の結果ページURL。"""
    return f"{SOUMU_BASE}/senkyo/senkyo_s/data/sangiin{ordinal}/index.html"


def sangiin_ordinal_for_year(year: int) -> int:
    """参議院議員通常選挙は1947年から3年ごとの完全に規則的な周期のため
    (解散が無く早期実施されない)、年から回次を機械的に導出できる。
    """
    return 1 + (year - 1947) // 3


def _find_vote_total_link(html: str, must_include: str, must_exclude: tuple[str, ...]) -> str | None:
    """indexページのリンクテキストから、都道府県別・候補者別等の詳細版を除いた
    「党派別得票数」本体へのリンクを見つける(jichisoken.pyと同じ、リンクテキスト
    ベースの動的発見)。
    """
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        if must_include not in text:
            continue
        if any(ex in text for ex in must_exclude):
            continue
        href = a["href"]
        if href.endswith((".xls", ".xlsx")):
            return href if href.startswith("http") else SOUMU_BASE + href
    return None


def _clean_label(value: object) -> str:
    return str(value).replace("　", "").strip()


def _clean_party_name(value: object) -> str:
    """党名の脚注記号(「立憲民主党※１」等)を取り除く。"""
    name = _clean_label(value)
    return name.split("※")[0]


def _percentage_row(rows: list[list[object]], konkai_row_index: int) -> dict[int, float] | None:
    """「今回」の行より後で、最初に見つかる「得票率の行」(値が全て数値かつ
    絶対値が100以下、かつ全て0ではない行)を{列インデックス: 値}で返す。
    生の得票数(百万単位)の行と区別するための判定。
    """
    for r in range(konkai_row_index + 1, min(konkai_row_index + 6, len(rows))):
        row = rows[r]
        numeric = {c: v for c, v in enumerate(row) if isinstance(v, (int, float))}
        if not numeric or all(v == 0 for v in numeric.values()):
            continue
        if all(abs(v) <= 100 for v in numeric.values()):
            return numeric
    return None


def _parse_sheet_rows(rows: list[list[object]]) -> dict[str, float]:
    """1シートぶんの行データから{政党名: 得票率(%)}を取り出す。"""
    header_row = None
    for r, row in enumerate(rows):
        if row and isinstance(row[0], str) and _clean_label(row[0]) == "区分":
            header_row = r
            break
    if header_row is None:
        return {}

    konkai_row = None
    for r in range(header_row + 1, len(rows)):
        row = rows[r]
        if row and isinstance(row[0], str) and _clean_label(row[0]) == "今回":
            konkai_row = r
            break
    if konkai_row is None:
        return {}

    pct_by_col = _percentage_row(rows, konkai_row)
    if pct_by_col is None:
        return {}

    # 値が0〜1のフラクション表記(新しいxlsx形式)なら100倍してパーセントに揃える
    if all(abs(v) <= 1.5 for v in pct_by_col.values()):
        pct_by_col = {c: v * 100 for c, v in pct_by_col.items()}

    header = rows[header_row]
    result: dict[str, float] = {}
    for col, pct in pct_by_col.items():
        if col == 0 or col >= len(header):
            continue
        name = _clean_party_name(header[col])
        if name and name != "合計":
            result[name] = pct
    return result


def _rows_from_xls(content: bytes) -> list[list[list[object]]]:
    wb = xlrd.open_workbook(file_contents=content)
    return [
        [[ws.cell_value(r, c) for c in range(ws.ncols)] for r in range(ws.nrows)]
        for ws in (wb.sheet_by_name(name) for name in wb.sheet_names())
    ]


def _rows_from_xlsx(content: bytes) -> list[list[list[object]]]:
    wb = openpyxl.load_workbook(BytesIO(content), data_only=True, read_only=True)
    return [
        [[cell for cell in row] for row in ws.iter_rows(values_only=True)]
        for ws in (wb[name] for name in wb.sheetnames)
    ]


def _parse_vote_pct_workbook(content: bytes, url: str) -> dict[str, float]:
    """xls・xlsxいずれの形式でも{政党名: 得票率(%)}を返す(選挙によって配布形式が
    異なるため両対応、2026-09に確認)。政党が複数シートに分かれている場合は
    全シート分を合算する。
    """
    sheets = _rows_from_xlsx(content) if url.endswith(".xlsx") else _rows_from_xls(content)
    result: dict[str, float] = {}
    for rows in sheets:
        result.update(_parse_sheet_rows(rows))
    return result


def _district_vote_pct(index_url: str, must_include: str, must_exclude: tuple[str, ...]) -> dict[str, float]:
    html = fetch(index_url).decode("shift_jis", errors="ignore")
    link = _find_vote_total_link(html, must_include, must_exclude)
    if link is None:
        return {}
    content = fetch(link)
    return _parse_vote_pct_workbook(content, link)


def shugiin_district_vote_pct(ordinal: int) -> dict[str, float]:
    """第ordinal回衆院選・小選挙区の{政党名: 得票率(%)}(無所属・諸派を含む)。"""
    return _district_vote_pct(
        shugiin_index_url(ordinal),
        "得票数（小選挙区）",
        ("都道府県別", "候補者別", "選挙区別"),
    )


def sangiin_district_vote_pct(ordinal: int) -> dict[str, float]:
    """第ordinal回参院選・選挙区の{政党名: 得票率(%)}(無所属・諸派を含む)。"""
    return _district_vote_pct(
        sangiin_index_url(ordinal),
        "得票数（選挙区）",
        ("都道府県別", "候補者別", "得票順"),
    )
