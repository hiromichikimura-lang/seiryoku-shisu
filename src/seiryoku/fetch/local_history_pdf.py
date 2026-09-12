"""総務省の旧年度(PDFのみ配布、平成18〜21年)から都道府県議会の党派別議席数を取る。

PDFは表ではなく「自由民主党が最も多く1,277人(47.2%)、次いで無所属の575人...」
という文章形式のため、正規表現で抽出する。平成19年分は画像PDF(テキスト層なし)で
本方法では読めないため対象外([[seiryoku_shisu_design]]の今後の課題)。
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from .util import fetch

# (表記ラベル, PDF URL)
PDF_YEARS: list[tuple[str, str]] = [
    ("平成21年12月31日現在", "https://www.soumu.go.jp/main_content/000058817.pdf"),
    ("平成20年12月31日現在", "https://www.soumu.go.jp/main_content/000014238.pdf"),
    ("平成18年12月31日現在", "https://www.soumu.go.jp/main_content/000318026.pdf"),
]

_ZEN2HAN = str.maketrans("０１２３４５６７８９，", "0123456789,")


def _pdf_to_text(content: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(content)
        f.flush()
        out = subprocess.run(
            ["pdftotext", "-layout", f.name, "-"],
            capture_output=True,
            check=True,
        )
    return out.stdout.decode("utf-8", errors="ignore")


def _extract_section(text: str, heading: str, next_headings: list[str]) -> str:
    start = text.find(heading)
    if start == -1:
        return ""
    end = len(text)
    for h in next_headings:
        pos = text.find(h, start + len(heading))
        if pos != -1:
            end = min(end, pos)
    return text[start:end]


def _parse_pref_assembly_seats(text: str) -> dict[str, int]:
    heading = "（２）都道府県議会議員"
    section = _extract_section(
        text, heading, ["（３）", "（４）", "２　地方公共団体の長の連続就任回数"]
    )[len(heading):]
    joined = re.sub(r"\s+", "", section)  # PDF由来の強制改行を除去
    joined = joined.translate(_ZEN2HAN)

    seats: dict[str, int] = {}
    for m in re.finditer(r"([^\d、。,()（）%]+?)(?:が最も多く|の)(\d[\d,]*)人", joined):
        name, num = m.group(1), m.group(2)
        name = re.sub(r"^次いで", "", name)
        seats[name] = int(num.replace(",", ""))
    return seats


def fetch_pref_assembly_history_pdf() -> list[tuple[str, dict[str, int]]]:
    results = []
    for label, url in PDF_YEARS:
        text = _pdf_to_text(fetch(url))
        seats = _parse_pref_assembly_seats(text)
        if seats:
            results.append((label, seats))
    return results
