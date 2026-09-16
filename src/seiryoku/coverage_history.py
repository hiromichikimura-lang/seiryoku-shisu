"""知事・市区町村のデータ網羅率(カバレッジ)を日付ごとに記録する。

cli.run()を実行するたびに1件記録することで、note記事のカバレッジ推移グラフに
使う月次の実データを積み上げる(2026-09にユーザー指示——「今後は毎月記録し、
基準値を下回ったらコードを見直す」という運用のため、手作業のスナップショットでは
なく自動記録にした)。同じ日付に複数回実行しても、その日付の最後の値で
上書きする(同日の再実行で履歴が重複・分裂しないように)。
"""
from __future__ import annotations

import json
from pathlib import Path

HISTORY_PATH = Path(__file__).resolve().parents[2] / "data" / "coverage_history.json"


def load_history() -> list[dict]:
    if HISTORY_PATH.exists():
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    return []


def record_snapshot(
    date_str: str,
    *,
    gov_covered: int,
    gov_total: int,
    muni_head_covered: int,
    muni_gikai_covered: int,
    muni_total: int,
) -> list[dict]:
    """その日付のカバレッジを記録し、更新後の全履歴を返す。"""
    history = [h for h in load_history() if h["date"] != date_str]
    history.append(
        {
            "date": date_str,
            "gov_covered": gov_covered,
            "gov_total": gov_total,
            "muni_head_covered": muni_head_covered,
            "muni_gikai_covered": muni_gikai_covered,
            "muni_total": muni_total,
        }
    )
    history.sort(key=lambda h: h["date"])
    HISTORY_PATH.parent.mkdir(exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return history
