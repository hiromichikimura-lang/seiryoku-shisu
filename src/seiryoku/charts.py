"""図1(党勢指数チャート)を生成する。

2026-09のセッションで作り込んだmatplotlibスクリプト(政党別リッジライン・
選挙種別の重みシェア・首相在任期間の3段構成、太字フォント、8:2.2:0.9の
高さ比、タイトル/説明文は画像に含めずキャプションはnote本文側に書く)を、
data/cp_history.json・data/national_election_months.jsonから再生成できる
形で正式なコードに昇格したもの(月一更新の自動化)。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import national_elections
from .fetch import jichisoken

OUT_PATH = Path(__file__).resolve().parents[2] / "notes" / "images" / "cp_and_level_share.png"

# 表示順・色は編集上の選択であり、データから機械的に決まるものではない
# (2026-09にユーザー指示で政党間の水準比較をしない設計にしたため、順序自体に
# 「大きい順」のような意味は無い。政党要件を満たす政党が増えたら末尾に追加する)。
PARTY_ORDER = [
    "自由民主党", "公明党", "立憲民主党", "中道改革連合", "日本維新の会",
    "国民民主党", "参政党", "チームみらい", "日本共産党", "いのちの党",
]

LEVEL_ORDER = ["衆院選", "参院選", "都道府県知事", "都道府県議会", "市区町村長", "市区町村議会"]
LEVEL_COLORS = ["#c0392b", "#e67e22", "#8e44ad", "#2980b9", "#27ae60", "#7f8c8d"]

# 首相の在任期間(発足月)。出典: 首相官邸・各内閣公式発表。更新頻度が低いため
# 定数として持ち、首相交代のたびに手動で追記する。
PM_PERIODS = [
    (2018, 1, "安倍晋三"),
    (2020, 9, "菅義偉"),
    (2021, 10, "岸田文雄"),
    (2024, 10, "石破茂"),
    (2025, 10, "高市早苗"),
]
PM_COLORS = ["#7f8c8d", "#16a085", "#2980b9", "#c0392b", "#8e44ad"]
# 内閣改造(政権交代を伴わないもの)の年月。首相交代と重なるものは含めない。
CABINET_RESHUFFLES = [(2018, 10), (2019, 9), (2022, 8), (2023, 9)]


def _ym_index(year: int, month: int, min_year: int) -> int:
    return (year - min_year) * 12 + (month - 1)


def _unified_local_election_months(min_year: int, max_year: int) -> list[tuple[int, int]]:
    """統一地方選は1947年以来4年に1度、4月に行われる(公職選挙法の統一選挙制度)。
    spike検出のようなデータ依存の推定はせず、周期から機械的に列挙する。"""
    return [(y, 4) for y in range(1947, max_year + 1, 4) if y >= min_year]


def _provisional_start() -> tuple[int, int] | None:
    """首長の推薦・支持データ(jichisoken)の最新版がどこまで収録しているかから、
    「速報値」の起点を動的に決める。全国首長名簿のNN年版は(NN-1)年5月1日から
    NN年4月30日までの選挙を収録する、という2026-09に実サイトで確認したパターンを
    使う(design_document.tex \\S2.2参照)。年版が見つからなければNoneを返し、
    呼び出し側は「速報値の塗り分けをしない」扱いにする。"""
    try:
        years = [int(y) for y in jichisoken.governor_endorsements_by_year().keys()]
    except Exception:
        return None
    if not years:
        return None
    return (max(years), 5)


def generate_main_chart(
    history: list[dict],
    out_path: Path = OUT_PATH,
    reshuffle: bool = True,
) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.font_manager as fm
    import matplotlib.pyplot as plt

    font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    if Path(font_path).exists():
        fm.fontManager.addfont(font_path)
        plt.rcParams["font.family"] = "Noto Sans CJK JP"
    plt.rcParams["axes.unicode_minus"] = False

    if not history:
        raise ValueError("historyが空です(cp_history.load_history()の結果を渡してください)")

    history = sorted(history, key=lambda h: (h["year"], h["month"]))
    min_year = history[0]["year"]
    n_months = len(history)
    x = list(range(n_months))

    party_order = list(PARTY_ORDER)
    for h in history:
        for party in h["C_p"]:
            if party not in party_order:
                party_order.append(party)
    party_colors = dict(zip(party_order, plt.cm.tab10(np.linspace(0, 1, max(10, len(party_order))))))

    election_events = national_elections.compute_election_events()
    local_events = _unified_local_election_months(min_year, history[-1]["year"])
    events = []
    for (y, m), label in election_events:
        idx = _ym_index(y, m, min_year)
        if 0 <= idx < n_months:
            events.append((idx, f"{y % 100}/{m} {label}"))
    for y, m in local_events:
        idx = _ym_index(y, m, min_year)
        if 0 <= idx < n_months:
            events.append((idx, f"{y % 100}/{m} 統一地方選"))
    events.sort()

    provisional_start = _provisional_start()
    provisional_idx = (
        _ym_index(*provisional_start, min_year) if provisional_start else None
    )

    pm_idx = [(_ym_index(y, m, min_year), name) for y, m, name in PM_PERIODS]
    pm_periods = []
    for i, (idx, name) in enumerate(pm_idx):
        end = pm_idx[i + 1][0] if i + 1 < len(pm_idx) else n_months - 1
        pm_periods.append((idx, end, name))
    reshuffle_idxs = [_ym_index(y, m, min_year) for y, m in CABINET_RESHUFFLES]

    fig, (ax1, ax2, ax3) = plt.subplots(
        3, 1, figsize=(11, 13.8), dpi=260, sharex=True,
        gridspec_kw={"height_ratios": [8, 2.2, 0.9], "hspace": 0.06},
    )

    band = 1.0
    n_party = len(party_order)
    for i, party in enumerate(party_order):
        baseline = (n_party - 1 - i) * band
        ys = [h["C_p"].get(party, 0.0) for h in history]
        party_max = max(ys) if max(ys) > 0 else 0.01
        normalized = [baseline + (v / party_max) * band * 0.85 for v in ys]
        ax1.plot(x, normalized, color=party_colors[party], linewidth=1.6, zorder=3)
        ax1.fill_between(x, [baseline] * n_months, normalized, color=party_colors[party], alpha=0.15, zorder=2)
        ax1.axhline(baseline, color="#cccccc", linewidth=0.8, zorder=1)
        ax1.text(-3, baseline, party, fontsize=13, ha="right", va="bottom", color=party_colors[party])

    for idx, _ in events:
        ax1.axvline(idx, color="#999999", linewidth=0.8, linestyle="--", zorder=1)
    for idx, label in events:
        ax1.text(idx, n_party * band + 0.3, label, fontsize=9.5, rotation=90, ha="left", va="bottom", color="#333333")

    if provisional_idx is not None and provisional_idx <= n_months - 1:
        ax1.axvspan(provisional_idx - 0.5, n_months - 1, color="#f2c14e", alpha=0.22, zorder=0)
        ax1.axvline(provisional_idx - 0.5, color="#b8860b", linewidth=1.4, zorder=1)
        ax1.text(
            provisional_idx - 0.5, n_party * band + 2.62, " 速報値 ", fontsize=12,
            ha="left", va="top", color="#5c4400", weight="bold",
            bbox=dict(boxstyle="round,pad=0.28", facecolor="#fff3cd", edgecolor="#b8860b", linewidth=1.3),
            zorder=6,
        )

    ax1.set_yticks([])
    ax1.set_ylim(-0.3, n_party * band + 2.7)
    ax1.set_xlim(-18, n_months - 1)
    for spine in ["top", "right", "left"]:
        ax1.spines[spine].set_visible(False)

    level_data = {t: [h["level_weight_share"].get(t, 0.0) * 100 for h in history] for t in LEVEL_ORDER}
    ax2.stackplot(x, [level_data[t] for t in LEVEL_ORDER], labels=LEVEL_ORDER, colors=LEVEL_COLORS, alpha=0.85, zorder=2)
    if provisional_idx is not None and provisional_idx <= n_months - 1:
        ax2.axvline(provisional_idx - 0.5, color="#b8860b", linewidth=1.0, linestyle=":", zorder=4)
    for idx, _ in events:
        ax2.axvline(idx, color="#555555", linewidth=0.8, linestyle="--", zorder=5)

    ax2.set_ylim(0, 100)
    ax2.set_yticks([0, 25, 50, 75, 100])
    ax2.set_ylabel("重みシェア (%)", fontsize=13)
    ax2.tick_params(axis="both", labelsize=11)
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.legend(loc="upper left", bbox_to_anchor=(1.0, 1.05), fontsize=11, frameon=False)

    for (start, end, name), color in zip(pm_periods, PM_COLORS):
        lo, hi = max(start, -18), min(end, n_months - 1)
        ax3.axvspan(lo, hi, color=color, alpha=0.55, zorder=1)
        ax3.text((lo + hi) / 2, 0.5, name, ha="center", va="center", fontsize=12, color="white", weight="bold", zorder=3)
    if reshuffle:
        for idx in reshuffle_idxs:
            ax3.axvline(idx, color="white", linewidth=1.4, linestyle=(0, (2, 1)), zorder=2)
    for idx, _ in events:
        ax3.axvline(idx, color="#333333", linewidth=0.8, linestyle="--", zorder=4)
    ax3.set_ylim(0, 1)
    ax3.set_yticks([])
    for spine in ["top", "right", "left"]:
        ax3.spines[spine].set_visible(False)

    tick_idx = list(range(0, n_months, 12))
    if (n_months - 1) - tick_idx[-1] < 6:
        tick_idx[-1] = n_months - 1
    else:
        tick_idx.append(n_months - 1)
    xlabels = [f"{history[i]['year']}/{history[i]['month']:02d}" for i in tick_idx]
    ax3.set_xticks(tick_idx)
    ax3.set_xticklabels(xlabels, fontsize=11, rotation=30, ha="right")

    fig.tight_layout(rect=[0.08, 0.02, 0.88, 1])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return out_path
