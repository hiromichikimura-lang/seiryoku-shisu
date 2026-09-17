"""TimesFM-3を使った翌月予測(design_document.tex \\S7.2「採用ルール」)。

バックテスト(2026-09)の結論:
- 国政選挙が絡まない月は、ゼロ予測を含むどの手法も追加の情報を持たない
  (ランダムウォークで近似できる)。よって予測自体を出さない。
- 国政選挙が絡む月は、個別政党の有意性ではなくプールした検定結果を優先し、
  バックテスト対象の6党全てにTimesFM-3を使う。

したがって`forecast_next_month`は、来月が国政選挙に絡まないなら`None`を返す
(ゼロという「予測値」を返すのではなく、そもそも予測しない——2026-09に
ユーザー指摘「ゼロ予測するぐらいなら何も出さないほうがいい」)。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import national_elections

FORECAST_HISTORY_PATH = Path(__file__).resolve().parents[2] / "data" / "forecast_history.json"

# バックテストで安定した時系列を持つと確認された6党のみを対象にする
# (中道改革連合・チームみらい・参政党・いのちの党は履歴不足等で対象外、
# note記事「予測とサプライズについて」参照)。
ADOPTED_PARTIES = [
    "自由民主党", "公明党", "立憲民主党", "日本維新の会", "国民民主党", "日本共産党",
]


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def should_forecast(year: int, month: int, election_months: list[tuple[int, int]]) -> bool:
    """(year, month)の翌月が「国政選挙が絡む月」かどうか。"""
    return national_elections.is_election_linked_month(*_next_month(year, month), election_months)


def _party_diff_series(history: list[dict], party: str) -> list[float]:
    """historyの月次差分を返す(先頭月は差分が定義できないため含めない)。
    欠測月(その政党の値が無い月)は0.0として扱う——バックテストで使った
    windowed12_dataと同じ穴埋め方針。"""
    values = [h["C_p"].get(party, 0.0) for h in history]
    return [values[i] - values[i - 1] for i in range(1, len(values))]


def _covariate_series(history: list[dict], election_months: list[tuple[int, int]]) -> list[float]:
    """バックテストで使ったcovariate(国政選挙が絡む月は非ゼロ)と同じ定義。
    月tの差分に対応するcovariateは、月t自体が選挙月なら+1、月tのavailableな
    直前12か月に選挙があってその選挙がちょうど窓から抜けるタイミングなら-1
    (両方に該当する場合は加算)。"""
    months = [(h["year"], h["month"]) for h in history]
    election_set = set(election_months)
    cov = []
    for i in range(1, len(months)):
        y, m = months[i]
        val = 0.0
        if (y, m) in election_set:
            val += 1.0
        if (y - 1, m) in election_set:  # 12か月前(=1年前の同じ月)が選挙月なら窓から抜ける
            val -= 1.0
        cov.append(val)
    return cov


def forecast_next_month(
    history: list[dict],
    election_months: list[tuple[int, int]] | None = None,
    min_context: int = 12,
) -> dict[str, float] | None:
    """来月がADOPTED_PARTIESの予測対象月でなければNone。対象月なら
    {政党: 来月の差分の予測値}を返す。

    timesfmパッケージが無い環境でもimportエラーで落ちないよう、実際に使う
    タイミングまでimportを遅延する(データ取得・チャート生成はtimesfm無しでも
    動く必要があるため)。
    """
    if not history:
        return None
    history = sorted(history, key=lambda h: (h["year"], h["month"]))
    if election_months is None:
        election_months = national_elections.load_election_months()

    last = history[-1]
    if not should_forecast(last["year"], last["month"], election_months):
        return None
    if len(history) <= min_context:
        return None

    import numpy as np
    import timesfm

    model = timesfm.TimesFM3Forecaster.from_pretrained("google/timesfm-3.0-pytorch", device="cpu")
    cov_full = np.array(_covariate_series(history, election_months), dtype=np.float32)

    result: dict[str, float] = {}
    for party in ADOPTED_PARTIES:
        diffs = _party_diff_series(history, party)
        ctx = np.array(diffs, dtype=np.float32)
        out = model.predict(context=ctx, horizon=1, past_future_covariates=cov_full)
        result[party] = float(out.forecast[0])
    return result


def load_forecast_history() -> dict[str, dict[str, float]]:
    if FORECAST_HISTORY_PATH.exists():
        return json.loads(FORECAST_HISTORY_PATH.read_text(encoding="utf-8"))
    return {}


def record_forecast(year: int, month: int, forecast_values: dict[str, float]) -> dict[str, dict[str, float]]:
    """forecast_next_month()の結果を、予測対象の年月をキーにして保存する
    (翌月の実際の差分と答え合わせするため、draft.py参照)。"""
    history = load_forecast_history()
    history[f"{year:04d}-{month:02d}"] = forecast_values
    FORECAST_HISTORY_PATH.parent.mkdir(exist_ok=True)
    FORECAST_HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    return history
