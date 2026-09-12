"""地方選の増減が国政選挙に先行するかを簡易的に検証する。

現状は参議院(会派別所属議員数の変遷)を国政側の代理として用いる
(衆議院には単一の通史ページが無いため、[[seiryoku_shisu_design]]参照)。
地方側は総務省の年次党派別人員調(都道府県議会、12月31日時点)を用いる。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .fetch import diet_history, local_history, local_history_pdf
from .lineage import canonicalize

_ERA_START = {
    "R": (2019, 5, 1),
    "H": (1989, 1, 8),
    "S": (1926, 12, 25),
}


def _era_to_year(label: str) -> int | None:
    """「R7.8.1」のような表記から西暦年を返す。「元」は1年目として扱う。"""
    m = re.match(r"([RHS])(\d+|元)\.(\d+)\.(\d+)", label)
    if not m:
        return None
    era, year_s, month, _day = m.groups()
    year_in_era = 1 if year_s == "元" else int(year_s)
    start_year = _ERA_START[era][0]
    return start_year + year_in_era - 1


def _local_label_to_year(label: str) -> int | None:
    """「令和6年12月31日現在」のような表記から西暦年を返す。"""
    m = re.search(r"(令和|平成)(\d+|元)年", label)
    if not m:
        return None
    era_name, year_s = m.groups()
    era = "R" if era_name == "令和" else "H"
    year_in_era = 1 if year_s == "元" else int(year_s)
    return _ERA_START[era][0] + year_in_era - 1


@dataclass
class YearSeries:
    years: list[int]
    values: list[float]  # 自由民主党の議席占有率


def _pref_share_series() -> YearSeries:
    by_year: dict[int, float] = {}

    snaps = local_history.fetch_local_history(max_years=30)
    for s in snaps:
        year = _local_label_to_year(s.label)
        pref = s.seats.get("都道府県議会")
        if year is None or not pref:
            continue
        merged: dict[str, float] = {}
        for name, n in pref.items():
            merged[canonicalize(name)] = merged.get(canonicalize(name), 0) + n
        total = sum(merged.values())
        by_year[year] = merged.get("自由民主党", 0) / total

    for label, pref in local_history_pdf.fetch_pref_assembly_history_pdf():
        year = _local_label_to_year(label)
        if year is None or year in by_year:
            continue
        merged: dict[str, float] = {}
        for name, n in pref.items():
            merged[canonicalize(name)] = merged.get(canonicalize(name), 0) + n
        total = sum(merged.values())
        by_year[year] = merged.get("自由民主党", 0) / total

    years = sorted(by_year)
    return YearSeries(years=years, values=[by_year[y] for y in years])


def _sangiin_share_series() -> YearSeries:
    """各年の最後の召集日時点での自民党議席占有率を取る。"""
    snaps = diet_history.fetch_sangiin_history()
    by_year: dict[int, tuple[str, float]] = {}  # year -> (date_label, share)
    for s in snaps:
        year = _era_to_year(s.date)
        if year is None:
            continue
        merged: dict[str, float] = {}
        for name, n in s.seats.items():
            merged[canonicalize(name)] = merged.get(canonicalize(name), 0) + n
        total = sum(v for k, v in merged.items() if k != "欠員")
        if total == 0:
            continue
        share = merged.get("自由民主党", 0) / total
        prev = by_year.get(year)
        if prev is None or s.date > prev[0]:
            by_year[year] = (s.date, share)
    years = sorted(by_year)
    return YearSeries(years=years, values=[by_year[y][1] for y in years])


def _diffs(series: YearSeries) -> dict[int, float]:
    """年ごとの前年差分 Δφ を返す(キーは差分の終点の年)。"""
    return {
        series.years[i]: series.values[i] - series.values[i - 1]
        for i in range(1, len(series.years))
        if series.years[i] - series.years[i - 1] == 1
    }


def lead_lag_report() -> str:
    pref = _diffs(_pref_share_series())
    kokkai = _diffs(_sangiin_share_series())
    common_years = sorted(set(pref) & set(kokkai))

    lines = ["年, 都道府県議会Δ(自民), 参議院Δ(自民,同年)"]
    for y in common_years:
        lines.append(f"{y}, {pref[y]:+.4f}, {kokkai[y]:+.4f}")

    def corr(xs: list[float], ys: list[float]) -> float | None:
        n = len(xs)
        if n < 3:
            return None
        mx, my = sum(xs) / n, sum(ys) / n
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        vx = sum((x - mx) ** 2 for x in xs)
        vy = sum((y - my) ** 2 for y in ys)
        if vx == 0 or vy == 0:
            return None
        return cov / (vx * vy) ** 0.5

    # ラグ0: 同年の地方Δと国政Δ
    lag0_years = common_years
    lag0_pref = [pref[y] for y in lag0_years]
    lag0_kokkai = [kokkai[y] for y in lag0_years]

    # ラグ1: 地方のΔ(year)が翌年の国政Δ(year+1)と関係するか
    lag1_years = [y for y in pref if (y + 1) in kokkai]
    lag1_pref = [pref[y] for y in lag1_years]
    lag1_kokkai = [kokkai[y + 1] for y in lag1_years]

    lines.append("")
    lines.append(f"サンプル年数(共通): {len(common_years)}")
    lines.append(f"ラグ0(同年)相関係数: {corr(lag0_pref, lag0_kokkai)}")
    lines.append(
        f"ラグ1(地方→翌年国政)相関係数(n={len(lag1_years)}): {corr(lag1_pref, lag1_kokkai)}"
    )
    return "\n".join(lines)
