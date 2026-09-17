from seiryoku import municipal_registry as mr
from seiryoku.fetch.go2senkyo import Candidate, ElectionHistoryRow


def _history_row(name, vote_date="2025/04/09", turnout="50.00%", detail_url="https://example.com/1"):
    return ElectionHistoryRow(
        vote_date=vote_date,
        announce_date="2025/03/31",
        name=name,
        turnout=turnout,
        num_candidates=2,
        detail_url=detail_url,
    )


def test_process_gikai_excludes_prefecture_assembly(monkeypatch):
    # 都道府県議会(道・都・府・県議会議員選挙)は総務省年次集計を使うため対象外
    monkeypatch.setattr(
        mr.go2senkyo, "jurisdiction_history", lambda jid, kind: [_history_row("北海道議会議員選挙")]
    )
    assert mr._process_gikai(1) is None


def test_process_gikai_counts_municipal_assembly_winners(monkeypatch):
    monkeypatch.setattr(
        mr.go2senkyo, "jurisdiction_history", lambda jid, kind: [_history_row("札幌市議会議員選挙")]
    )
    monkeypatch.setattr(
        mr.go2senkyo,
        "parse_candidates",
        lambda url: [
            Candidate(name="甲", party="自由民主党", elected=True),
            Candidate(name="乙", party="自由民主党", elected=True),
            Candidate(name="丙", party=None, elected=True),
            Candidate(name="丁", party="公明党", elected=False),
        ],
    )
    seats = mr._process_gikai(2)
    assert seats == {"自由民主党": 2, "無所属": 1}


def test_process_gikai_none_when_no_history():
    def empty_history(jid, kind):
        return []

    import seiryoku.municipal_registry as target

    orig = target.go2senkyo.jurisdiction_history
    target.go2senkyo.jurisdiction_history = empty_history
    try:
        assert target._process_gikai(3) is None
    finally:
        target.go2senkyo.jurisdiction_history = orig


def test_reset_errors_removes_only_errored_ids_and_keeps_successes():
    state = {
        "head": {"1": {"party": "無所属"}},
        "gikai": {"1": {"自由民主党": 5}},
        "done_ids": [1, 2, 3],
        "errors": {"2": "WAFチャレンジが解消しませんでした", "3": "接続エラー"},
    }
    result = mr.reset_errors(state)
    assert result["done_ids"] == [1]
    assert result["errors"] == {}
    # 成功済みデータは取り直さずそのまま残る
    assert result["head"] == {"1": {"party": "無所属"}}
    assert result["gikai"] == {"1": {"自由民主党": 5}}


def test_build_gikai_term_chain_tallies_seats_per_election(monkeypatch):
    history = [
        _history_row("A市議会議員選挙", "2023/04/09", detail_url="https://x/1"),
        _history_row("A市議会議員選挙", "2019/04/07", detail_url="https://x/2"),
        _history_row("A市議会議員選挙", "2015/04/12", detail_url="https://x/3"),
    ]
    monkeypatch.setattr(mr.go2senkyo, "jurisdiction_history", lambda jid, kind: history)

    results = {
        "https://x/1": [Candidate(name="甲", party="自由民主党", elected=True), Candidate(name="乙", party="無所属", elected=True), Candidate(name="丙", party="無所属", elected=False)],
        "https://x/2": [Candidate(name="丁", party="民主党", elected=True), Candidate(name="戊", party="自由民主党", elected=True)],
        "https://x/3": [Candidate(name="己", party="自由民主党", elected=True)],
    }
    monkeypatch.setattr(mr.go2senkyo, "parse_candidates", lambda url: results[url])

    chain = mr._build_gikai_term_chain(1, min_year=2018)

    # 2019年時点でまだmin_year(2018)に届いていないため、その1つ前(2015年、
    # 届いた回)まで含めて打ち切る。
    assert chain == [
        {"vote_date": "2023-04-09", "seats": {"自由民主党": 1, "無所属": 1}},
        {"vote_date": "2019-04-07", "seats": {"民主党": 1, "自由民主党": 1}},
        {"vote_date": "2015-04-12", "seats": {"自由民主党": 1}},
    ]


def test_build_gikai_term_chain_excludes_by_elections():
    """補欠選挙は一部の議席しか改選しないため、全体の党派別議席数を代表しない。"""
    history = [
        _history_row("A市議会議員補欠選挙", "2021/06/13", detail_url="https://x/by"),
        _history_row("A市議会議員選挙", "2019/04/07", detail_url="https://x/general"),
    ]
    completed = mr._all_completed_gikai(history)
    assert [row.detail_url for row in completed] == ["https://x/general"]


def test_all_completed_gikai_excludes_unheld_and_uncontested():
    history = [
        _history_row("A市議会議員選挙", "未定", turnout="-%"),
        _history_row("A市議会議員選挙", "2023/04/09", detail_url="https://x/1"),
    ]
    completed = mr._all_completed_gikai(history)
    assert [row.detail_url for row in completed] == ["https://x/1"]


def test_refresh_stale_gikai_term_chains_keeps_id_when_no_newer_election(monkeypatch, tmp_path):
    cache_path = tmp_path / "gikai_term_chains.json"
    monkeypatch.setattr(mr, "GIKAI_TERM_CHAIN_CACHE_PATH", cache_path)
    mr.save_gikai_term_chain_cache(
        {"chains": {"1": [{"vote_date": "2023-04-09", "seats": {"自由民主党": 1}}]}, "done_ids": [1], "errors": {}}
    )

    history = [_history_row("A市議会議員選挙", "2023/04/09", detail_url="https://x/1")]

    def fake_history(jid, kind, force=False):
        assert force is True, "強制再取得(force=True)でないと新しい選挙を見逃す"
        return history

    monkeypatch.setattr(mr.go2senkyo, "jurisdiction_history", fake_history)

    stats = mr.refresh_stale_gikai_term_chains([1])

    assert stats == {"checked": 1, "stale": []}
    assert mr.load_gikai_term_chain_cache()["done_ids"] == [1]


def test_refresh_stale_gikai_term_chains_removes_id_when_newer_election_found(monkeypatch, tmp_path):
    cache_path = tmp_path / "gikai_term_chains.json"
    monkeypatch.setattr(mr, "GIKAI_TERM_CHAIN_CACHE_PATH", cache_path)
    mr.save_gikai_term_chain_cache(
        {"chains": {"1": [{"vote_date": "2019-04-07", "seats": {"自由民主党": 1}}]}, "done_ids": [1], "errors": {}}
    )

    history = [
        _history_row("A市議会議員選挙", "2023/04/09", detail_url="https://x/new"),
        _history_row("A市議会議員選挙", "2019/04/07", detail_url="https://x/1"),
    ]
    monkeypatch.setattr(mr.go2senkyo, "jurisdiction_history", lambda jid, kind, force=False: history)

    stats = mr.refresh_stale_gikai_term_chains([1])

    assert stats == {"checked": 1, "stale": [1]}
    assert mr.load_gikai_term_chain_cache()["done_ids"] == []


def test_refresh_and_rebuild_gikai_term_chains_rebuilds_only_the_stale_id(monkeypatch, tmp_path):
    cache_path = tmp_path / "gikai_term_chains.json"
    monkeypatch.setattr(mr, "GIKAI_TERM_CHAIN_CACHE_PATH", cache_path)
    mr.save_gikai_term_chain_cache(
        {"chains": {"1": [{"vote_date": "2019-04-07", "seats": {"自由民主党": 1}}]}, "done_ids": [1], "errors": {}}
    )

    history = [
        _history_row("A市議会議員選挙", "2023/04/09", detail_url="https://x/new"),
        _history_row("A市議会議員選挙", "2019/04/07", detail_url="https://x/1"),
    ]
    monkeypatch.setattr(mr.go2senkyo, "jurisdiction_history", lambda jid, kind, force=False: history)
    monkeypatch.setattr(
        mr.go2senkyo,
        "parse_candidates",
        lambda url: [Candidate(name="甲", party="自由民主党", elected=True)],
    )

    stats = mr.refresh_and_rebuild_gikai_term_chains([1])

    assert stats["stale"] == [1]
    state = mr.load_gikai_term_chain_cache()
    assert state["done_ids"] == [1]
    assert state["chains"]["1"][0]["vote_date"] == "2023-04-09"
