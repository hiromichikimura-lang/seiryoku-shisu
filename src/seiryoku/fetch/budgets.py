"""国・都道府県・市区町村の歳出総額(決算ベース)を取得する。"""
from __future__ import annotations

import json
import re
from io import BytesIO
from pathlib import Path

import openpyxl
from bs4 import BeautifulSoup

from .util import fetch

MOF_BUDGET_URL = "https://www.mof.go.jp/policy/budget/reference/statistics/01.xlsx"
# 財務省のシート名は元号が変わるたびに増える。次の元号になったら追加する必要がある。
MOF_LATEST_SHEET = "1.-5令和"
# 過去時点のI_p(t)再現(2010年以降)には平成・令和の2シートで十分なため、
# 明治・大正・昭和の古い元号ラベル形式(本シートとは書式が異なる)には対応していない。
_HISTORY_SHEETS = {"平成": "1.-4平成", "令和": "1.-5令和"}
_HISTORY_ERA_START_YEAR = {"平成": 1989, "令和": 2019}
_HISTORY_YEAR_TOKEN = re.compile(r"^(元|\d+)(年度)?$")

CARD_TOP_URL = "https://www.soumu.go.jp/iken/zaisei/card.html"


def fetch_national_budget() -> int:
    """国の一般会計歳出総額(直近で決算額が確定している年度、千円単位)を返す。"""
    wb = openpyxl.load_workbook(BytesIO(fetch(MOF_BUDGET_URL)), data_only=True, read_only=True)
    ws = wb[MOF_LATEST_SHEET]
    latest_kessan = None
    latest_yosan = None
    for row in ws.iter_rows(values_only=True):
        if isinstance(row[1], str) and row[1].strip() == "計":
            if row[5] is not None:
                latest_kessan = row[5]
            elif row[4] is not None:
                latest_yosan = row[4]
    if latest_kessan is not None:
        return int(latest_kessan)
    if latest_yosan is not None:
        return int(latest_yosan)
    raise RuntimeError("国の歳出データが見つかりません")


def fetch_national_budget_history() -> dict[int, int]:
    """{西暦年度: 国の一般会計歳出総額(千円単位、決算優先・無ければ予算)}を返す。

    既にダウンロード済みの単一ファイル(01.xlsx)に明治期〜令和の全期間が
    シートごとに分かれて収録されているため、追加のネットワークアクセスは
    発生しない。1行目の年度ラベル(「元年度」「2」「7年度」等、書式が途中で
    ゆらぐ)を手がかりに現在の年度を追跡し、「計」行に出会うたびにその年度の
    歳出額として記録する。
    """
    wb = openpyxl.load_workbook(BytesIO(fetch(MOF_BUDGET_URL)), data_only=True, read_only=True)
    result: dict[int, int] = {}
    for era, sheet_name in _HISTORY_SHEETS.items():
        ws = wb[sheet_name]
        current_year: int | None = None
        for row in ws.iter_rows(values_only=True):
            if not row:
                continue
            if row[0] not in (None, ""):
                token = str(row[0]).strip()
                m = _HISTORY_YEAR_TOKEN.match(token)
                if m:
                    year_in_era = 1 if m.group(1) == "元" else int(m.group(1))
                    current_year = _HISTORY_ERA_START_YEAR[era] + year_in_era - 1
            if (
                current_year is not None
                and len(row) > 1
                and isinstance(row[1], str)
                and row[1].strip() == "計"
            ):
                value = row[5] if row[5] is not None else row[4]
                if value is not None:
                    result[current_year] = int(value)
    return result


def _find_shutsugaku_total(ws) -> int:
    """決算カードのシートから「歳出合計」の値(千円単位)を取り出す。"""
    for row in ws.iter_rows(values_only=True):
        if row and row[1] == "歳出合計":
            for val in row[2:]:
                if isinstance(val, (int, float)):
                    return int(val)
    raise RuntimeError("歳出合計の行が見つかりません")


def _find_latest_pref_card_url() -> str:
    """都道府県決算カードトップページから最新年のExcelリンクを見つける。

    都道府県決算カードの節は年ごとにmain_content配下のExcelへ直接リンクしており、
    市町村決算カードの節(card-N.htmlという別ページ経由)より先に出現する。
    """
    html = fetch(CARD_TOP_URL).decode("shift_jis", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/iken/zaisei/card-"):
            break  # 市町村決算カードの節に入ったら探索終了
        if href.startswith("/main_content/") and href.endswith(".xlsx"):
            return "https://www.soumu.go.jp" + href
    raise RuntimeError("都道府県決算カードへのリンクが見つかりません")


def fetch_prefecture_budget_total() -> int:
    """47都道府県の歳出決算総額の合計(千円単位)を返す。"""
    return sum(prefecture_budget_by_name().values())


_NENDO_LABEL = re.compile(r"(令和|平成)(\d+|元)年度")
_NENDO_ERA_START_YEAR = {"令和": 2019, "平成": 1989}


def _nendo_label_to_year(label: str) -> int:
    """「令和6年度都道府県決算カード」のような表記から西暦年度を返す。"""
    m = _NENDO_LABEL.search(label)
    if not m:
        raise ValueError(f"年度表記を解釈できません: {label}")
    era, year_s = m.groups()
    year_in_era = 1 if year_s == "元" else int(year_s)
    return _NENDO_ERA_START_YEAR[era] + year_in_era - 1


def _pref_card_year_urls() -> list[tuple[int, str]]:
    """(西暦年度, xlsx URL) を返す。都道府県決算カードがExcelでも配布されている
    平成27年度(2015年度)以降のみが対象(それ以前はPDFのみで本関数では扱わない)。
    """
    html = fetch(CARD_TOP_URL).decode("shift_jis", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[int, str]] = []
    pending_label: str | None = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/iken/zaisei/card-"):
            break  # 市町村決算カードの節に入ったら探索終了
        text = a.get_text(strip=True)
        if "都道府県決算カード" in text:
            pending_label = text
        elif pending_label and href.startswith("/main_content/") and href.endswith(".xlsx"):
            try:
                year = _nendo_label_to_year(pending_label)
            except ValueError:
                pending_label = None
                continue
            results.append((year, "https://www.soumu.go.jp" + href))
            pending_label = None
    return results


_PREF_BUDGET_HISTORY_CACHE_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "prefecture_budget_history.json"
)


def prefecture_budget_total_history() -> dict[int, int]:
    """{西暦年度: 47都道府県の歳出決算総額合計(千円)}。Excel配布分(2015年度〜)のみ。

    年度ごとにExcelを再パースするため重く、結果をJSONにキャッシュする
    (municipal_budget_by_nameと同じ発想、[[seiryoku_shisu_design]]参照)。
    """
    if _PREF_BUDGET_HISTORY_CACHE_PATH.exists():
        cached = json.loads(_PREF_BUDGET_HISTORY_CACHE_PATH.read_text(encoding="utf-8"))
        return {int(year): total for year, total in cached.items()}

    result: dict[int, int] = {}
    for year, url in _pref_card_year_urls():
        wb = openpyxl.load_workbook(BytesIO(fetch(url)), data_only=True, read_only=True)
        result[year] = sum(_find_shutsugaku_total(wb[name]) for name in wb.sheetnames if name != "目次")

    _PREF_BUDGET_HISTORY_CACHE_PATH.parent.mkdir(exist_ok=True)
    _PREF_BUDGET_HISTORY_CACHE_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _municipal_card_year_urls() -> list[tuple[int, str]]:
    """(西暦年度, 市町村決算カード索引ページURL) を返す。Excel配布分
    (平成27年度(2015年度)以降)のみが対象。
    """
    html = fetch(CARD_TOP_URL).decode("shift_jis", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[int, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if not href.startswith("/iken/zaisei/card-") or "市町村決算カード" not in text:
            continue
        try:
            year = _nendo_label_to_year(text)
        except ValueError:
            continue
        results.append((year, "https://www.soumu.go.jp" + href))
    return results


_MUNI_BUDGET_HISTORY_CACHE_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "municipal_budget_history.json"
)


def municipal_budget_total_history() -> dict[int, int]:
    """{西暦年度: 全市区町村の歳出決算総額合計(千円)}。Excel配布分(2015年度〜)のみ。

    年度ごとに47都道府県ぶんのExcelを読むため重い(1年度あたり約1700シート、
    2〜3分)。11年度ぶん通しで実行すると数十分かかるため、結果をJSONにキャッシュする
    (municipal_budget_by_nameと同じ発想、[[seiryoku_shisu_design]]参照)。
    """
    if _MUNI_BUDGET_HISTORY_CACHE_PATH.exists():
        cached = json.loads(_MUNI_BUDGET_HISTORY_CACHE_PATH.read_text(encoding="utf-8"))
        return {int(year): total for year, total in cached.items()}

    result: dict[int, int] = {}
    for year, index_url in _municipal_card_year_urls():
        html = fetch(index_url).decode("shift_jis", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        file_urls = {
            "https://www.soumu.go.jp" + a["href"]
            for a in soup.find_all("a", href=True)
            if a["href"].startswith("/main_content/") and a["href"].endswith(".xlsx")
        }
        if not file_urls:
            continue  # この年度はPDF配布のみ(Excel無し)なので対象外
        total = 0
        for url in file_urls:
            wb = openpyxl.load_workbook(BytesIO(fetch(url)), data_only=True, read_only=True)
            total += sum(_find_shutsugaku_total(wb[name]) for name in wb.sheetnames if name != "目次")
        result[year] = total

    _MUNI_BUDGET_HISTORY_CACHE_PATH.parent.mkdir(exist_ok=True)
    _MUNI_BUDGET_HISTORY_CACHE_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _find_latest_municipal_card_index_url() -> str:
    """市町村決算カードトップページから最新年の都道府県別インデックスページを見つける。"""
    html = fetch(CARD_TOP_URL).decode("shift_jis", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one('a[href^="/iken/zaisei/card-"]')
    if link is None:
        raise RuntimeError("市町村決算カードへのリンクが見つかりません")
    return "https://www.soumu.go.jp" + link["href"]


_SHEET_NAME_PREFIX = re.compile(r"^\d+")  # シート名先頭の通し番号(例: 「2札幌市」)


def municipal_budget_by_name() -> dict[str, int]:
    """{市区町村名: 歳出決算総額(千円)} を全市区町村ぶん返す(東京都特別区を含む)。

    「注目度指数」用の自治体ごとの重み付けに使う([[seiryoku_shisu_design]]参照)。
    都道府県ごとに1〜2ファイルへ分割されているため、47都道府県ぶんダウンロードする。
    Excelの再パースが重い(約1700シート、2〜3分)ため、結果をJSONにキャッシュする。
    """
    cache_path = Path(__file__).resolve().parents[3] / "data" / "municipal_budgets.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    index_url = _find_latest_municipal_card_index_url()
    html = fetch(index_url).decode("shift_jis", errors="ignore")
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
            name = _SHEET_NAME_PREFIX.sub("", sheet_name)
            by_name[name] = _find_shutsugaku_total(wb[sheet_name])

    cache_path.parent.mkdir(exist_ok=True)
    cache_path.write_text(json.dumps(by_name, ensure_ascii=False, indent=2), encoding="utf-8")
    return by_name


def fetch_municipal_budget_total() -> int:
    """全市区町村(東京都特別区を含む)の歳出決算総額の合計(千円単位)を返す。"""
    return sum(municipal_budget_by_name().values())


def prefecture_budget_by_name() -> dict[str, int]:
    """{都道府県名: 歳出決算総額(千円)} を47都道府県ぶん返す。

    自治体ごとの重み付け($I_p(t)$の個別自治体加重・$E_p(t)$)で毎回呼ばれるように
    なったため、municipal_budget_by_name()と同様にJSONキャッシュする。
    """
    cache_path = Path(__file__).resolve().parents[3] / "data" / "prefecture_budgets.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    url = _find_latest_pref_card_url()
    wb = openpyxl.load_workbook(BytesIO(fetch(url)), data_only=True, read_only=True)
    by_name: dict[str, int] = {}
    for sheet_name in wb.sheetnames:
        if sheet_name == "目次":
            continue
        name = _SHEET_NAME_PREFIX.sub("", sheet_name)
        by_name[name] = _find_shutsugaku_total(wb[sheet_name])

    cache_path.parent.mkdir(exist_ok=True)
    cache_path.write_text(json.dumps(by_name, ensure_ascii=False, indent=2), encoding="utf-8")
    return by_name


def fetch_budgets() -> dict[str, int]:
    """体ごとの歳出総額(千円単位)をまとめて返す。

    都道府県議会と都道府県知事は同じ都道府県予算を共有するため同じ値を用いる
    (市区町村議会・市区町村長も同様)。歳出総額の取得(Excel解析)は重いため、
    議会用・首長用で別々に計算せず1回だけ行う。
    """
    national = fetch_national_budget()
    prefecture = fetch_prefecture_budget_total()
    municipal = fetch_municipal_budget_total()
    return {
        "国会": national,
        "都道府県議会": prefecture,
        "都道府県知事": prefecture,
        "市区町村議会": municipal,
        "市区町村長": municipal,
    }
