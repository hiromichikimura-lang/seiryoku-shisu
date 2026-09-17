"""月次更新のnote記事下書きを、事実データ(数値)を元にAnthropic APIで生成する。

数値の確定・整形はこのモジュール(Python側)で行い、Anthropic APIには
「与えられた数値をもとに文章を書く」役割だけを持たせる——数値の計算・比較を
LLMに委ねると誤りうるため(design_document.tex \\S7.2のTimesFM-3採用ルール自体も
プールした検定結果に基づく数値であり、記事の文章がそれと矛盾しないように、
事実は必ずこちらで確定させてから渡す)。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import national_elections, precursor
from . import forecast as forecast_mod

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"

# 前回、実際に記事(下書き)を書いた対象月の末尾を記録する。月一更新を時計のように
# 正確に回す気はなく、実行間隔が空くこともある前提のため、「今月」固定ではなく
# 「前回の更新月の次の月から、データが取得できる直近の月まで」を対象期間として
# 扱う(2026-09にユーザー指示)。
LAST_REPORT_PATH = Path(__file__).resolve().parents[2] / "data" / "last_report.json"


def load_last_report() -> tuple[int, int] | None:
    if LAST_REPORT_PATH.exists():
        d = json.loads(LAST_REPORT_PATH.read_text(encoding="utf-8"))
        return (d["year"], d["month"])
    return None


def save_last_report(year: int, month: int) -> None:
    LAST_REPORT_PATH.parent.mkdir(exist_ok=True)
    LAST_REPORT_PATH.write_text(
        json.dumps({"year": year, "month": month}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


SYSTEM_PROMPT = """あなたは「党勢指数」というnote連載の月次更新記事の下書きを書く。
読者は既に第0回の記事(指数の設計・TimesFM-3採用ルール・前哨戦検証の説明)を
読んでいる前提でよく、指数の定義自体を説明し直す必要はない。

厳守するスタイル:
- ダッシュ(——)を使わない。区切りたければ句点で文を分けるか括弧書きにする。
- 太字・箇条書きは実際に列挙可能な内容にのみ使い、機械的に増やさない。
- 「実測」「疑う」「照合」「入口」「土台」「事故」(比喩として)「別物」「既定」
  「定番」「効く」「瞬間」「静かに」「壊れる」「黙って」のような語彙を避け、
  普通の言い回しに置き換える。
- 「まとめ」という見出しを安易に付けない。
- 数値の変化が大きくても原因を断定せず、「要確認」「詳細は不明」のように留保する。
  因果関係を勝手に説明しない。
- 与えられた事実(数値)以外を創作しない。事実に無い数値・出来事を書かない。
- 常体(である調)で書く。
"""


def build_month_facts(
    history: list[dict],
    election_months: list[tuple[int, int]] | None = None,
    precursor_rows: list[dict] | None = None,
    since: tuple[int, int] | None = None,
) -> dict:
    """cp_history.load_history()の結果(年月順である必要はない)から、
    下書きに必要な事実だけを取り出して整形する。

    対象期間は「前回更新した月の次の月」から「データが取得できる直近の月」まで
    (sinceを省略した場合はload_last_report()の値を使う)。前回更新が無ければ
    (初回、またはsinceが履歴の範囲外なら)直近1か月だけを対象にする。複数か月分を
    まとめて報告する場合、C_pの差分は期間の合計(期間開始の直前月から直近月まで)
    で見る——月ごとに分けても、間の月の値は結局「まだ報告していない中間状態」に
    過ぎず読者には意味がないため。"""
    history = sorted(history, key=lambda h: (h["year"], h["month"]))
    latest = history[-1]
    year, month = latest["year"], latest["month"]

    if since is None:
        since = load_last_report()

    if since is None:
        period = [latest]
    else:
        period = [h for h in history if (h["year"], h["month"]) > since]
        if not period:
            period = [latest]

    period_start_idx = history.index(period[0])
    baseline = history[period_start_idx - 1] if period_start_idx > 0 else None

    diffs: dict[str, float] = {}
    if baseline is not None:
        parties = set(latest["C_p"]) | set(baseline["C_p"])
        diffs = {p: latest["C_p"].get(p, 0.0) - baseline["C_p"].get(p, 0.0) for p in parties}

    if election_months is None:
        election_months = national_elections.load_election_months()
    period_yms = {(h["year"], h["month"]) for h in period}
    events_in_period = sorted(
        {label for ym, label in national_elections.compute_election_events() if ym in period_yms}
    )

    n_events = sum(h["n_events"] for h in period)

    forecast_history = forecast_mod.load_forecast_history()
    forecast_check: dict[str, dict[str, dict[str, float]]] = {}
    for i, h in enumerate(history):
        if (h["year"], h["month"]) not in period_yms or i == 0:
            continue
        predicted = forecast_history.get(f"{h['year']:04d}-{h['month']:02d}")
        if predicted is None:
            continue
        prev_h = history[i - 1]
        forecast_check[f"{h['year']:04d}-{h['month']:02d}"] = {
            party: {
                "predicted": predicted.get(party, 0.0),
                "actual": h["C_p"].get(party, 0.0) - prev_h["C_p"].get(party, 0.0),
            }
            for party in predicted
        }

    next_year, next_month = forecast_mod._next_month(year, month)
    will_forecast_next = national_elections.is_election_linked_month(next_year, next_month, election_months)

    if precursor_rows is None:
        precursor_rows = precursor.load_precursor_table()
    precursor_summary = {
        party: s for party, s in precursor.summarize_by_party(precursor_rows).items() if s["total"] > 0
    }

    return {
        "year": year,
        "month": month,
        "period_start": {"year": period[0]["year"], "month": period[0]["month"]},
        "C_p": latest["C_p"],
        "diffs": diffs,
        "n_events": n_events,
        "level_weight_share": latest["level_weight_share"],
        "events_in_period": events_in_period,
        "forecast_check": forecast_check or None,
        "next_month": {"year": next_year, "month": next_month, "will_forecast": will_forecast_next},
        "precursor_summary": precursor_summary,
    }


def _format_facts_for_prompt(facts: dict) -> str:
    ps = facts["period_start"]
    if (ps["year"], ps["month"]) == (facts["year"], facts["month"]):
        lines = [f"対象月: {facts['year']}年{facts['month']}月(前回更新のすぐ翌月)"]
    else:
        lines = [
            f"対象期間: {ps['year']}年{ps['month']}月〜{facts['year']}年{facts['month']}月"
            "(前回の更新から間が空いたため、複数か月分をまとめて報告する)"
        ]
    lines.append(f"この期間にあった選挙イベント数の合計(直近12か月窓内の合計ではなく単純合計): {facts['n_events']}")
    if facts["events_in_period"]:
        lines.append(f"この期間に投票日があった国政選挙: {', '.join(facts['events_in_period'])}")

    if facts["diffs"]:
        lines.append(f"政党ごとのC_p(期間開始直前から{facts['year']}年{facts['month']}月までの差分、絶対値が大きい順):")
        for party, d in sorted(facts["diffs"].items(), key=lambda kv: -abs(kv[1])):
            current = facts["C_p"].get(party, 0.0)
            lines.append(f"  - {party}: {d:+.4f}(現在の値 {current:.4f})")
    else:
        lines.append("比較対象の月のデータが無いため、差分を計算していない(今回が初回の可能性)。")

    if facts["level_weight_share"]:
        lines.append(f"直近({facts['year']}年{facts['month']}月)の重みシェア内訳(どの種類の選挙がC_pを動かしたか):")
        for level, share in sorted(facts["level_weight_share"].items(), key=lambda kv: -kv[1]):
            lines.append(f"  - {level}: {share:.2f}")

    if facts["forecast_check"]:
        lines.append("この期間中にTimesFM-3で事前に出していた予測との答え合わせ(月ごと):")
        for ym, per_party in sorted(facts["forecast_check"].items()):
            lines.append(f"  {ym}:")
            for party, c in per_party.items():
                lines.append(f"    - {party}: 予測 {c['predicted']:+.4f} / 実際 {c['actual']:+.4f}")
    else:
        lines.append("この期間分の事前予測は無かった(対象月が予測対象月ではなかった)。")

    nm = facts["next_month"]
    if nm["will_forecast"]:
        lines.append(f"{nm['year']}年{nm['month']}月は国政選挙が絡む月にあたるため、次回更新でTimesFM-3による予測を行う予定である。")
    else:
        lines.append(f"{nm['year']}年{nm['month']}月は国政選挙が絡まない月にあたるため、次回更新では予測を出さない予定である。")

    if facts["precursor_summary"]:
        lines.append("「地方選は国政選挙の前哨戦か」の検証(地方限定C_pの増減方向と実際の議席シェア増減方向の一致数、これまでに確定した選挙ペアの累計):")
        for party, s in facts["precursor_summary"].items():
            lines.append(f"  - {party}: {s['match']}/{s['total']}")

    return "\n".join(lines)


def generate_monthly_draft(facts: dict, client=None) -> str:
    """factsを事実として渡し、Anthropic APIに月次更新記事の下書き本文を書かせる。

    テストではclientに偽オブジェクトを注入できるようにし、anthropicパッケージが
    未インストールの環境でも(実際にAPIを呼ばない限り)importエラーにならない
    ようにする(forecast.pyのtimesfmと同じ方針)。"""
    if client is None:
        import anthropic

        client = anthropic.Anthropic()

    user_prompt = (
        "以下は今回の更新分の党勢指数の事実データである(更新間隔は一定ではなく、"
        "複数か月分をまとめて報告することもある)。これをもとに、note連載の"
        "更新記事の下書き(Markdown形式)を書いてほしい。見出しは"
        f"「# 党勢指数 {facts['year']}年{facts['month']}月更新」から始めること。\n\n"
        + _format_facts_for_prompt(facts)
    )

    message = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in message.content if getattr(block, "type", None) == "text")


def save_draft(text: str, year: int, month: int, out_dir: Path = OUTPUT_DIR) -> Path:
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"draft_{year:04d}-{month:02d}.md"
    path.write_text(text, encoding="utf-8")
    return path


def save_facts(facts: dict, out_dir: Path = OUTPUT_DIR) -> Path:
    """ANTHROPIC_API_KEY未設定の場合のフォールバック。API課金無しで自動化できる
    範囲(数値の整形)まではここで済ませ、実際の文章化は人間が対話環境(Claude Code等、
    従量課金APIとは別のサブスクリプションで無料)で行う運用にする(2026-09に
    ユーザー指示「無料の範囲でなるべく自動化する」)。"""
    out_dir.mkdir(exist_ok=True)
    year, month = facts["year"], facts["month"]
    path = out_dir / f"draft_facts_{year:04d}-{month:02d}.txt"
    header = (
        f"# {year}年{month}月の党勢指数、下書き用の事実データ\n"
        "# このファイルをClaude Code等の対話環境に渡して記事の文章を書いてもらう想定。\n"
        "# スタイルの指示はdraft.SYSTEM_PROMPTを参照。\n\n"
    )
    path.write_text(header + _format_facts_for_prompt(facts), encoding="utf-8")
    return path
