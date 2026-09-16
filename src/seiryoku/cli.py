"""月次実行のエントリポイント。データを取得して指数を計算し、JSONで保存する。"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import coverage_history, municipal_registry, registry, turnover
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

    # 実行のたびにカバレッジを1件記録し、note記事のカバレッジ推移グラフに使う
    # 月次の実データを積み上げる(2026-09にユーザー指示)。
    coverage_history.record_snapshot(
        date.today().isoformat(),
        gov_covered=sum(registry.coverage_report(gov_registry).values()),
        gov_total=len(gov_registry),
        muni_head_covered=muni_coverage["head_covered"],
        muni_gikai_covered=muni_coverage["gikai_covered"],
        muni_total=muni_coverage["total_jichitai"],
    )

    # C_p(t): 国会+既知の知事・市区町村長を人口の平方根で一律に加重した合成指数
    # (2026-09にユーザー指示でI_p(t)・E_p(t)の別建てから統合、index.py参照)。
    C_p = compute_combined_index()
    # 党派転換指数は「その時点の断面」を見る指標であり、月をまたいだトレンドとして
    # 素朴に線を追う設計にはなっていない(直近30日等の短いウィンドウは標本が薄く
    # 振れが大きい)。そこで$C_p(T)$と同じ12か月累積の断面を直近1点だけ、前月分と
    # 合わせて取得する(2026-09にユーザー指示、W_p^turnoverは首長のみ実装——議会側は
    # 前回選挙結果の新規取得が必要なため未着手、[[seiryoku_shisu_design]]参照)。
    turnover_latest, turnover_prev = turnover.latest_turnover_snapshot()

    return {
        "date": date.today().isoformat(),
        "C_p": C_p["share"],
        "C_p_coverage": {
            "known_jurisdictions": C_p["known_jurisdictions"],
            "total_jurisdictions": C_p["total_jurisdictions"],
        },
        "W_p_turnover": {
            "year": turnover_latest.year,
            "month": turnover_latest.month,
            "n_events": turnover_latest.n_events,
            "W_p": turnover_latest.W_p,
            "L_p": turnover_latest.L_p,
            "net_share": turnover_latest.net_share,
            "prev_net_share": turnover_prev.net_share if turnover_prev else {},
        },
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

    tw = result["W_p_turnover"]
    print(f"\n党派転換指数 W_p^turnover({tw['year']}-{tw['month']:02d}時点、直近12か月累積、{tw['n_events']}件):")
    for party, v in sorted(tw["W_p"].items(), key=lambda kv: -kv[1]):
        print(f"  {party}: {v:.4f}")

    print("\n党派転換の補集指標 L_p^turnover(被奪取側):")
    for party, v in sorted(tw["L_p"].items(), key=lambda kv: -kv[1]):
        print(f"  {party}: {v:.4f}")

    print("\n党派転換の正味スコア(sum sqrt(P)で正規化、前月比較可能):")
    for party, v in sorted(tw["net_share"].items(), key=lambda kv: -kv[1]):
        prev_v = tw["prev_net_share"].get(party, 0.0)
        print(f"  {party}: {v:+.4f} (前月 {prev_v:+.4f})")

    print("\n知事の議席台帳カバー率:", result["governor_registry_coverage"])


if __name__ == "__main__":
    main()
