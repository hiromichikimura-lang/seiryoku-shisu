"""結合テスト: モックを使わず、cli.run()を実データ(ネットワーク越し、util.fetchの
キャッシュ経由)で通しで実行し、各構成要素が正しく組み合わさることを確認する。
"""
from seiryoku.cli import run


def test_run_produces_consistent_indices():
    result = run()

    assert result["C_p"], "C_pが空です"

    c_p_total = sum(result["C_p"].values())
    assert 0.99 <= c_p_total <= 1.01, f"C_pの合計が1にならない: {c_p_total}"

    assert all(v >= 0 for v in result["C_p"].values())

    # 無所属・諸派は必ず1つの勢力として含まれる([[seiryoku_shisu_design]]の設計方針)
    assert "無所属" in result["C_p"]

    assert result["C_p_coverage"]["known_jurisdictions"] > 0
    assert result["municipal_registry_coverage"]["total_jichitai"] == 1788
    assert isinstance(result["W_p"], dict)

    turnover_share = result["W_p_turnover"]["share"]
    turnover_total = sum(turnover_share.values())
    assert 0.99 <= turnover_total <= 1.01 or turnover_total == 0, (
        f"W_p^turnoverの合計が1にならない: {turnover_total}"
    )
    assert all(v >= 0 for v in turnover_share.values())

    # net_raw(W_p - L_p)は1イベントごとにゼロサムなので、全政党で合計すると常に0
    net_total = sum(result["W_p_turnover"]["net_raw"].values())
    assert abs(net_total) < 1e-6, f"net_rawの合計が0にならない: {net_total}"
