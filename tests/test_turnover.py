from seiryoku import turnover
from seiryoku.fetch.go2senkyo import Candidate, ElectionHistoryRow
from seiryoku.fetch.jichisoken import Endorsement
from seiryoku.turnover import (
    TurnoverEvent,
    _build_term_chain,
    _loss_score_event,
    _net_score_event,
    _predecessor_endorsing_parties,
    _score_event,
    _turnover_event,
    _two_most_recent_completed,
)


def _row(name, vote_date, turnout="50.00%", detail_url="https://example.com/1"):
    return ElectionHistoryRow(
        vote_date=vote_date,
        announce_date="",
        name=name,
        turnout=turnout,
        num_candidates=2,
        detail_url=detail_url,
    )


def test_score_event_hold_scores_nothing():
    event = TurnoverEvent(
        name="秋田県",
        vote_date="2025-04-06",
        winner_shares={"自由民主党": 1.0},
        predecessor_shares={"自由民主党": 1.0},
        budget=1000,
    )
    assert _score_event(event) == {}
    assert _loss_score_event(event) == {}


def test_score_event_flip_scores_winner_only():
    event = TurnoverEvent(
        name="秋田県",
        vote_date="2025-04-06",
        winner_shares={"参政党": 1.0},
        predecessor_shares={"自由民主党": 1.0},
        budget=1000,
    )
    scores = _score_event(event)
    assert set(scores) == {"参政党"}
    assert scores["参政党"] > 0
    loss = _loss_score_event(event)
    assert set(loss) == {"自由民主党"}
    assert loss["自由民主党"] == scores["参政党"]


def test_score_event_coalition_winner_splits_credit():
    event = TurnoverEvent(
        name="A市",
        vote_date="2025-04-06",
        winner_shares={"公明党": 0.5, "国民民主党": 0.5},
        predecessor_shares={"自由民主党": 1.0},
        budget=1000,
    )
    scores = _score_event(event)
    assert set(scores) == {"公明党", "国民民主党"}
    assert scores["公明党"] == scores["国民民主党"]


def test_score_event_zero_or_negative_budget_scores_nothing():
    event = TurnoverEvent(
        name="A市", vote_date="2025-04-06", winner_shares={"参政党": 1.0},
        predecessor_shares={"自由民主党": 1.0}, budget=0,
    )
    assert _score_event(event) == {}


def test_score_event_no_actual_change_when_both_sides_share_endorser():
    # 当選者・前任者ともに無所属で同じ政党の推薦を受けていた場合、党派としては
    # 実質的な奪取ではないためW_pにもL_pにも計上されない([[seiryoku_shisu_design]]の
    # 「前任者側の推薦・支持政党」バグ修正のケース)。
    event = TurnoverEvent(
        name="B市",
        vote_date="2025-04-06",
        winner_shares={"公明党": 1.0},
        predecessor_shares={"公明党": 1.0},
        budget=1000,
    )
    assert _score_event(event) == {}
    assert _loss_score_event(event) == {}


def test_net_score_event_equals_gain_minus_loss():
    event = TurnoverEvent(
        name="A市",
        vote_date="2025-04-06",
        winner_shares={"公明党": 0.5, "国民民主党": 0.5},
        predecessor_shares={"自由民主党": 1.0},
        budget=1000,
    )
    gain = _score_event(event)
    loss = _loss_score_event(event)
    net = _net_score_event(event)
    for party in set(gain) | set(loss) | set(net):
        assert net.get(party, 0.0) == gain.get(party, 0.0) - loss.get(party, 0.0)


def test_net_score_event_sums_to_zero():
    event = TurnoverEvent(
        name="A市",
        vote_date="2025-04-06",
        winner_shares={"参政党": 1.0},
        predecessor_shares={"自由民主党": 1.0},
        budget=1000,
    )
    assert abs(sum(_net_score_event(event).values())) < 1e-9


def test_net_score_event_zero_when_no_actual_change():
    event = TurnoverEvent(
        name="B市",
        vote_date="2025-04-06",
        winner_shares={"公明党": 1.0},
        predecessor_shares={"公明党": 1.0},
        budget=1000,
    )
    assert _net_score_event(event) == {}


def test_two_most_recent_completed_filters_unheld_and_uncontested(monkeypatch):
    history = [
        _row("A市長選挙", "未定", turnout="-%"),  # 未来の予定、除外
        _row("A市長選挙", "2025/04/09"),  # 直近
        _row("A市長選挙", "2021/04/11"),  # 前回
        _row("A市長選挙", "2017/04/23"),  # さらに前(使わない)
    ]
    monkeypatch.setattr(turnover.go2senkyo, "jurisdiction_history", lambda jid, kind: history)
    rows = _two_most_recent_completed(1)
    assert [r.vote_date for r in rows] == ["2025/04/09", "2021/04/11"]


def test_turnover_event_none_when_only_one_past_election(monkeypatch):
    monkeypatch.setattr(
        turnover.go2senkyo, "jurisdiction_history", lambda jid, kind: [_row("A市長選挙", "2025/04/09")]
    )
    assert _turnover_event(1, "A市", 1000, []) is None


def test_turnover_event_detects_flip(monkeypatch):
    history = [_row("A市長選挙", "2025/04/09", detail_url="https://x/latest"),
               _row("A市長選挙", "2021/04/11", detail_url="https://x/prev")]
    monkeypatch.setattr(turnover.go2senkyo, "jurisdiction_history", lambda jid, kind: history)

    def fake_parse_candidates(url):
        if url == "https://x/latest":
            return [Candidate(name="甲", party="参政党", elected=True)]
        return [Candidate(name="乙", party="自由民主党", elected=True)]

    monkeypatch.setattr(turnover.go2senkyo, "parse_candidates", fake_parse_candidates)

    event = _turnover_event(1, "A市", 1000, [])
    assert event.predecessor_shares == {"自由民主党": 1.0}
    assert event.winner_shares == {"参政党": 1.0}


def test_turnover_event_uses_predecessor_cache_without_network(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("キャッシュがあるのにネットワーク取得を試みた")

    monkeypatch.setattr(turnover.go2senkyo, "jurisdiction_history", boom)
    monkeypatch.setattr(turnover.go2senkyo, "parse_candidates", boom)

    cache = {
        "1": {
            "latest_vote_date": "2025-04-09",
            "latest_party": "参政党",
            "predecessor_vote_date": "2021-04-11",
            "predecessor_party": "自由民主党",
        }
    }
    event = turnover._turnover_event(1, "A市", 1000, [], predecessor_cache=cache)
    assert event.predecessor_shares == {"自由民主党": 1.0}
    assert event.winner_shares == {"参政党": 1.0}


def test_build_predecessor_cache_is_resumable(monkeypatch, tmp_path):
    cache_path = tmp_path / "turnover_predecessors.json"
    monkeypatch.setattr(turnover, "PREDECESSOR_CACHE_PATH", cache_path)

    history = [_row("A市長選挙", "2025/04/09", detail_url="https://x/latest"),
               _row("A市長選挙", "2021/04/11", detail_url="https://x/prev")]
    monkeypatch.setattr(turnover.go2senkyo, "jurisdiction_history", lambda jid, kind: history)
    monkeypatch.setattr(
        turnover.go2senkyo,
        "parse_candidates",
        lambda url: [Candidate(name="甲", party="自由民主党", elected=True)],
    )

    state = turnover.build_predecessor_cache(jichitai_ids=[1], checkpoint_every=1)
    assert state["done_ids"] == [1]
    assert "1" in state["entries"]

    # 2回目はキャッシュ済みのIDをスキップし、ネットワークを再度叩かない
    def boom(*a, **kw):
        raise AssertionError("既に処理済みのIDを再取得しようとした")

    monkeypatch.setattr(turnover.go2senkyo, "jurisdiction_history", boom)
    state2 = turnover.build_predecessor_cache(jichitai_ids=[1], checkpoint_every=1)
    assert state2["done_ids"] == [1]


def test_turnover_event_folds_local_party_into_independent(monkeypatch):
    cache = {
        "1": {
            "latest_vote_date": "2025-04-09",
            "latest_party": "大阪維新の会",
            "predecessor_vote_date": "2021-04-11",
            "predecessor_party": "草の根運動いが",
        }
    }
    event = turnover._turnover_event(
        1, "A市", 1000, [], predecessor_cache=cache, national_parties={"自由民主党"}
    )
    assert event.winner_shares == {"無所属": 1.0}
    assert event.predecessor_shares == {"無所属": 1.0}


def test_predecessor_endorsing_parties_matches_by_election_year():
    by_year = {
        "2022": {
            "A市": Endorsement(
                name="A市", formal_party="無所属", endorsing_parties=["公明党"],
                vote_date="2021-04-11 00:00:00", year="2022",
            )
        },
        "2025": {
            "A市": Endorsement(
                name="A市", formal_party="無所属", endorsing_parties=["自由民主党"],
                vote_date="2025-04-09 00:00:00", year="2025",
            )
        },
    }
    # 前任者は2021年当選なので2022年版の推薦データ(公明党)を拾う
    assert _predecessor_endorsing_parties(by_year, "A市", "2021-04-11") == ["公明党"]


def test_predecessor_endorsing_parties_none_when_year_not_covered():
    by_year = {
        "2025": {
            "A市": Endorsement(
                name="A市", formal_party="無所属", endorsing_parties=["自由民主党"],
                vote_date="2025-04-09 00:00:00", year="2025",
            )
        },
    }
    # 2013年当選の前任者はどの年版にも登場しないので推薦なし扱い
    assert _predecessor_endorsing_parties(by_year, "A市", "2013-04-07") == []


def test_turnover_event_uses_predecessor_year_endorsement_not_latest_known_state(monkeypatch):
    """前任者側も『最新の既知の状態』ではなく当選時点の年版で判定することを
    end-to-endで確認する回帰テスト(2026-09-05発見のバグ修正)。前任者は当時
    無所属で公明党の推薦を受けていたが、jichisokenの最新年版では別の推薦状況に
    上書きされている——それでも当選時点(2021年)の年版データが使われれば、
    実質的には同じ政党の維持なのでW_p^turnoverには計上されない。
    """
    cache = {
        "1": {
            "latest_vote_date": "2025-04-09",
            "latest_party": "無所属",
            "predecessor_vote_date": "2021-04-11",
            "predecessor_party": "無所属",
        }
    }
    by_year = {
        "2022": {
            "A市": Endorsement(
                name="A市", formal_party="無所属", endorsing_parties=["公明党"],
                vote_date="2021-04-11 00:00:00", year="2022",
            )
        },
        # 最新の既知の状態(2025年版)は別の推薦状況に上書きされている
        "2025": {
            "A市": Endorsement(
                name="A市", formal_party="無所属", endorsing_parties=["自由民主党"],
                vote_date="2025-04-09 00:00:00", year="2025",
            )
        },
    }
    event = turnover._turnover_event(
        1, "A市", 1000, ["公明党"], predecessor_cache=cache,
        predecessor_endorsements_by_year=by_year,
    )
    assert event.predecessor_shares == {"公明党": 1.0}
    assert event.winner_shares == {"公明党": 1.0}
    assert _score_event(event) == {}


def test_build_term_chain_stops_once_min_year_reached(monkeypatch):
    history = [
        _row("A市長選挙", "2025/04/09", detail_url="https://x/1"),
        _row("A市長選挙", "2021/04/11", detail_url="https://x/2"),
        _row("A市長選挙", "2017/04/23", detail_url="https://x/3"),
        _row("A市長選挙", "2013/04/07", detail_url="https://x/4"),  # min_yearより前なので到達不要
    ]
    monkeypatch.setattr(turnover.go2senkyo, "jurisdiction_history", lambda jid, kind: history)

    parties = {
        "https://x/1": "自由民主党",
        "https://x/2": "無所属",
        "https://x/3": "民主党",
    }

    def fake_parse_candidates(url):
        assert url in parties, "min_year到達後に余分なリクエストをした"
        return [Candidate(name="甲", party=parties[url], elected=True)]

    monkeypatch.setattr(turnover.go2senkyo, "parse_candidates", fake_parse_candidates)

    chain = _build_term_chain(1, min_year=2017)

    assert chain == [
        {"vote_date": "2025-04-09", "party": "自由民主党"},
        {"vote_date": "2021-04-11", "party": "無所属"},
        {"vote_date": "2017-04-23", "party": "民主党"},
    ]


def test_build_term_chain_stops_at_end_of_history_before_min_year(monkeypatch):
    """min_year以前の選挙が無いまま履歴が尽きたら、そこで打ち切って返す。"""
    history = [
        _row("A市長選挙", "2021/04/11", detail_url="https://x/1"),
    ]
    monkeypatch.setattr(turnover.go2senkyo, "jurisdiction_history", lambda jid, kind: history)
    monkeypatch.setattr(
        turnover.go2senkyo,
        "parse_candidates",
        lambda url: [Candidate(name="甲", party="自由民主党", elected=True)],
    )

    chain = _build_term_chain(1, min_year=2000)

    assert chain == [{"vote_date": "2021-04-11", "party": "自由民主党"}]
