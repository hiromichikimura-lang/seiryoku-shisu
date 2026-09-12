"""月次実行のエントリポイント。データを取得して指数を計算し、JSONで保存する。"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import attention_index, municipal_registry, registry, turnover
from .fetch import diet
from .index import compute_combined_index

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"


def run() -> dict:
    diet_seats = diet.fetch_diet_seats()

    gov_registry = registry.refresh_from_seijiyama(registry.load_or_init_registry())
    registry.save_registry(gov_registry)

    # municipal_registry_coverageは運用監視用に残す(市区町村長データのクロール進捗)。
    muni_state = municipal_registry.load_checkpoint()
    muni_coverage = municipal_registry.coverage_report(muni_state)

    # C_p(t): 国会+既知の知事・市区町村長を人口の平方根で一律に加重した合成指数
    # (2026-09にユーザー指示でI_p(t)・E_p(t)の別建てから統合、index.py参照)。
    C_p = compute_combined_index()
    W_p = attention_index.attention_index(days=30)
    # W_p^turnoverは首長(知事・市区町村長)のみ実装(議会側は前回選挙結果の新規取得が
    # 必要なため未着手、[[seiryoku_shisu_design]]参照)。
    W_p_turnover = turnover.turnover_index(days=30)

    return {
        "date": date.today().isoformat(),
        "C_p": C_p["share"],
        "C_p_coverage": {
            "known_jurisdictions": C_p["known_jurisdictions"],
            "total_jurisdictions": C_p["total_jurisdictions"],
        },
        "W_p": W_p,
        "W_p_turnover": W_p_turnover,
        "governor_registry_coverage": registry.coverage_report(gov_registry),
        "municipal_registry_coverage": muni_coverage,
        "raw": {
            "diet_seats": diet_seats,
        },
    }


def main() -> None:
    result = run()
    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / f"{result['date']}.json"
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"saved: {out_path}")

    print("\n政党インパクト指数 C_p:")
    for party, v in sorted(result["C_p"].items(), key=lambda kv: -kv[1]):
        print(f"  {party}: {v:.4f}")

    print(f"\n党派転換指数 W_p^turnover(直近{result['W_p_turnover']['period_days']}日、{result['W_p_turnover']['n_events']}件):")
    for party, v in sorted(result["W_p_turnover"]["share"].items(), key=lambda kv: -kv[1]):
        print(f"  {party}: {v:.4f}")

    print("\n党派転換の補集指標 L_p^turnover(奪われた側):")
    for party, v in sorted(result["W_p_turnover"]["loss_share"].items(), key=lambda kv: -kv[1]):
        print(f"  {party}: {v:.4f}")

    print("\n党派転換の正味スコア(W_p - L_p、符号付き):")
    for party, v in sorted(result["W_p_turnover"]["net_raw"].items(), key=lambda kv: -kv[1]):
        print(f"  {party}: {v:+.1f}")

    print("\n知事の議席台帳カバー率:", result["governor_registry_coverage"])


if __name__ == "__main__":
    main()
