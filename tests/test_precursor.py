from seiryoku import precursor
from seiryoku.fetch.diet_history import Snapshot


def test_sign():
    assert precursor._sign(0.5) == 1
    assert precursor._sign(-0.5) == -1
    assert precursor._sign(0.0) == 0


def test_share_computes_fraction_of_total_seats():
    assert precursor._share({"自由民主党": 60, "公明党": 40}, "自由民主党") == 0.6
    assert precursor._share({"自由民主党": 60, "公明党": 40}, "日本共産党") == 0.0


def test_share_returns_zero_when_total_is_zero():
    assert precursor._share({}, "自由民主党") == 0.0


def test_consecutive_election_pairs_sorts_by_date_and_zips_adjacent():
    snapshots = [
        Snapshot(session="c", date="2025-07-20", seats={}),
        Snapshot(session="a", date="2019-07-21", seats={}),
        Snapshot(session="b", date="2022-07-10", seats={}),
    ]
    pairs = precursor.consecutive_election_pairs(snapshots)
    assert [(a.date, b.date) for a, b in pairs] == [
        ("2019-07-21", "2022-07-10"),
        ("2022-07-10", "2025-07-20"),
    ]


def test_local_cp_before_returns_value_from_month_before_election():
    local_history = [
        {"year": 2022, "month": 6, "C_p": {"自由民主党": 0.3}},
        {"year": 2022, "month": 7, "C_p": {"自由民主党": 0.9}},
    ]
    # 2022年7月の選挙の直前月は2022年6月
    assert precursor._local_cp_before(local_history, 2022, 7, "自由民主党") == 0.3


def test_local_cp_before_handles_january_crossing_into_previous_year():
    local_history = [{"year": 2021, "month": 12, "C_p": {"自由民主党": 0.4}}]
    assert precursor._local_cp_before(local_history, 2022, 1, "自由民主党") == 0.4


def test_local_cp_before_returns_none_when_month_missing():
    assert precursor._local_cp_before([], 2022, 7, "自由民主党") is None


def test_compute_verification_rows_matches_direction(monkeypatch):
    from seiryoku import forecast

    monkeypatch.setattr(forecast, "ADOPTED_PARTIES", ["自由民主党"])
    monkeypatch.setattr(precursor, "ADOPTED_PARTIES", ["自由民主党"])

    from seiryoku.fetch import diet_history

    monkeypatch.setattr(
        diet_history,
        "fetch_sangiin_election_history",
        lambda: [
            Snapshot(session="a", date="2019-07-21", seats={"自由民主党": 50, "他": 50}),
            Snapshot(session="b", date="2022-07-10", seats={"自由民主党": 60, "他": 40}),
        ],
    )
    monkeypatch.setattr(diet_history, "fetch_shugiin_history", lambda: [])

    local_history = [
        {"year": 2019, "month": 6, "C_p": {"自由民主党": 0.2}},
        {"year": 2022, "month": 6, "C_p": {"自由民主党": 0.5}},  # 地方も国政も上昇 → 一致
    ]

    rows = precursor.compute_verification_rows(local_history)
    assert len(rows) == 1
    assert rows[0]["match"] is True
    assert rows[0]["local_direction"] == 1
    assert rows[0]["actual_direction"] == 1


def test_summarize_by_party_counts_matches_and_totals():
    rows = [
        {"party": "自由民主党", "match": True},
        {"party": "自由民主党", "match": False},
        {"party": "公明党", "match": True},
    ]
    summary = precursor.summarize_by_party(rows)
    assert summary["自由民主党"] == {"match": 1, "total": 2}
    assert summary["公明党"]["match"] == 1


def test_update_and_load_precursor_table_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(precursor, "TABLE_PATH", tmp_path / "precursor_verification.json")
    monkeypatch.setattr(precursor, "compute_verification_rows", lambda local_history: [{"party": "x", "match": True}])

    written = precursor.update_precursor_table([])
    assert written == [{"party": "x", "match": True}]
    assert precursor.load_precursor_table() == written


def test_load_precursor_table_returns_empty_list_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(precursor, "TABLE_PATH", tmp_path / "missing.json")
    assert precursor.load_precursor_table() == []
