"""党勢指数$C_p(T)$の月次履歴をdata/に永続化する。

monthly_index.build_month_snapshots()は呼び出すたびに全期間分(105か月分など)を
ゼロから再構成する。首長の推薦・支持データ(jichisoken)は新しい年版が出ると
過去の月の値も遡って変わりうる(確定値/速報値の切り替え、design_document.tex
\\S2.2参照)ため、coverage_history.pyのような「その日ぶんだけ追記」ではなく、
実行のたびに全履歴を丸ごと再計算して上書きする方式にする(2026-09にユーザー
指示「月一更新の自動化」を受けて追加)。
"""
from __future__ import annotations

import json
from pathlib import Path

from .monthly_index import MonthSnapshot

HISTORY_PATH = Path(__file__).resolve().parents[2] / "data" / "cp_history.json"


def load_history() -> list[dict]:
    if HISTORY_PATH.exists():
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    return []


def save_history(snapshots: list[MonthSnapshot]) -> list[dict]:
    """snapshotsを丸ごとdata/cp_history.jsonに書き出す(既存の内容は置き換える)。"""
    history = [
        {
            "year": s.year,
            "month": s.month,
            "C_p": s.C_p,
            "n_events": s.n_events,
            "level_weight_share": s.level_weight_share,
        }
        for s in snapshots
    ]
    HISTORY_PATH.parent.mkdir(exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return history
