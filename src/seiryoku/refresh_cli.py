"""選挙結果キャッシュ(首長・議会それぞれのterm chain)の更新クロール。

turnover.build_term_chain_cache()・municipal_registry.build_gikai_term_chain_cache()は
「一度処理した自治体は二度と再取得しない」設計(中断・再開可能にするための恒久
done_ids)なので、新しい首長・議会選挙が実施されても自動では反映されない
(2026-09、沖縄県知事選で発覚)。

この対応として、対象の約1788自治体を毎回強制的に(util.fetchのキャッシュを
無視して)確認し直すrefresh_and_rebuild_*_term_chains()を用意した。go2senkyo.com
のレート制限(4秒間隔)により首長・議会それぞれ単独で1788件を舐めるだけでも
2時間程度かかり、両方で約4時間の見込み(2026-09にユーザー確認済み)。記事生成
(cli.py、月次)とは別のsystemdタイマーで、記事生成より数日前倒しで実行する。
"""
from __future__ import annotations

from . import municipal_registry, turnover


def main() -> None:
    print("首長の選挙結果キャッシュを確認中...")
    head_stats = turnover.refresh_and_rebuild_term_chains()
    print(f"  確認: {head_stats['checked']}件, 更新対象: {len(head_stats['stale'])}件 {head_stats['stale']}")

    print("議会の選挙結果キャッシュを確認中...")
    gikai_stats = municipal_registry.refresh_and_rebuild_gikai_term_chains()
    print(f"  確認: {gikai_stats['checked']}件, 更新対象: {len(gikai_stats['stale'])}件 {gikai_stats['stale']}")


if __name__ == "__main__":
    main()
