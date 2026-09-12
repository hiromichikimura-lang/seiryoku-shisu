"""都道府県・市区町村の人口(令和2年国勢調査)を取得する。

決算カード(budgets.py)と同じExcelファイルに人口も同梱されているため、
追加のクロールは発生しない。ペンローズの平方根則([[seiryoku_shisu_design]]参照、
2026-09にユーザー指摘で採用)に基づき$I_p(t)/E_p(t)$の自治体別重み$\\sqrt{P_j}$の
算出に使う。
"""
from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import openpyxl

from . import budgets
from .util import fetch

_DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def _find_population(ws) -> int | None:
    """決算カードのシートから「令和２年国調」時点の人口を取り出す。

    ラベルの位置(何列目に人口の値があるか)は都道府県カード・市区町村カードで
    異なるため、列を決め打ちせず「令和...国調」というラベルがある行を探し、
    同じ行にある最初の大きな数値を人口とみなす。
    """
    target_row = None
    for row in ws.iter_rows(min_row=1, max_row=10):
        for cell in row:
            if isinstance(cell.value, str) and "令和" in cell.value and "国調" in cell.value:
                target_row = cell.row
                break
        if target_row:
            break
    if target_row is None:
        return None
    for cell in ws[target_row]:
        if isinstance(cell.value, (int, float)) and cell.value > 1000:
            return int(cell.value)
    return None


def prefecture_population_by_name() -> dict[str, int]:
    """{都道府県名: 令和2年国勢調査人口} を47都道府県ぶん返す。"""
    cache_path = _DATA_DIR / "prefecture_populations.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    url = budgets._find_latest_pref_card_url()
    wb = openpyxl.load_workbook(BytesIO(fetch(url)), data_only=True, read_only=True)
    by_name: dict[str, int] = {}
    for sheet_name in wb.sheetnames:
        if sheet_name == "目次":
            continue
        name = budgets._SHEET_NAME_PREFIX.sub("", sheet_name)
        pop = _find_population(wb[sheet_name])
        if pop is not None:
            by_name[name] = pop

    cache_path.parent.mkdir(exist_ok=True)
    cache_path.write_text(json.dumps(by_name, ensure_ascii=False, indent=2), encoding="utf-8")
    return by_name


def municipal_population_by_name() -> dict[str, int]:
    """{市区町村名: 令和2年国勢調査人口} を全市区町村ぶん返す(東京都特別区を含む)。

    data/municipal_population.json に既存のキャッシュがあればそれを使う
    (2026-09-02の「自治体予算と人口の相関検証」で作成済み、同じ抽出方法)。
    """
    cache_path = _DATA_DIR / "municipal_population.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    index_url = budgets._find_latest_municipal_card_index_url()
    html = fetch(index_url).decode("shift_jis", errors="ignore")
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    file_urls = {
        "https://www.soumu.go.jp" + a["href"]
        for a in soup.find_all("a", href=True)
        if a["href"].startswith("/main_content/") and a["href"].endswith(".xlsx")
    }

    by_name: dict[str, int] = {}
    for url in file_urls:
        wb = openpyxl.load_workbook(BytesIO(fetch(url)), data_only=True, read_only=True)
        for sheet_name in wb.sheetnames:
            if sheet_name == "目次":
                continue
            name = budgets._SHEET_NAME_PREFIX.sub("", sheet_name)
            pop = _find_population(wb[sheet_name])
            if pop is not None:
                by_name[name] = pop

    cache_path.parent.mkdir(exist_ok=True)
    cache_path.write_text(json.dumps(by_name, ensure_ascii=False, indent=2), encoding="utf-8")
    return by_name


def national_population() -> int:
    """日本全体の人口(令和2年国勢調査、47都道府県人口の合計)。"""
    return sum(prefecture_population_by_name().values())
