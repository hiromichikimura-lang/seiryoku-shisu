from seiryoku import national_elections
from seiryoku.fetch import diet_history
from seiryoku.fetch.diet_history import Snapshot


def test_compute_election_months_dedupes_and_sorts(monkeypatch):
    monkeypatch.setattr(
        diet_history,
        "fetch_sangiin_election_history",
        lambda: [
            Snapshot(session="a", date="2022-07-10", seats={}),
            Snapshot(session="b", date="2025-07-20", seats={}),
        ],
    )
    monkeypatch.setattr(
        diet_history,
        "fetch_shugiin_history",
        lambda: [
            Snapshot(session="c", date="2021-10-31", seats={}),
            Snapshot(session="d", date="2022-07-10", seats={}),  # 参院選と同月(重複除去の確認)
        ],
    )

    assert national_elections.compute_election_months() == [
        (2021, 10), (2022, 7), (2025, 7),
    ]


def test_compute_election_events_labels_by_chamber(monkeypatch):
    monkeypatch.setattr(
        diet_history,
        "fetch_sangiin_election_history",
        lambda: [Snapshot(session="a", date="2022-07-10", seats={})],
    )
    monkeypatch.setattr(
        diet_history,
        "fetch_shugiin_history",
        lambda: [Snapshot(session="c", date="2021-10-31", seats={})],
    )
    assert national_elections.compute_election_events() == [
        ((2021, 10), "衆院選"),
        ((2022, 7), "参院選"),
    ]


def test_save_and_load_election_months_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(national_elections, "MONTHS_PATH", tmp_path / "national_election_months.json")
    national_elections.save_election_months([(2021, 10), (2022, 7)])
    assert national_elections.load_election_months() == [(2021, 10), (2022, 7)]


def test_load_election_months_returns_empty_list_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(national_elections, "MONTHS_PATH", tmp_path / "missing.json")
    assert national_elections.load_election_months() == []


def test_is_election_linked_month_true_for_election_month_itself():
    elections = [(2022, 7)]
    assert national_elections.is_election_linked_month(2022, 7, elections) is True


def test_is_election_linked_month_true_for_window_exit_month():
    """選挙の12か月後(C_p(T)の後方ウィンドウから抜ける月)もTrue。"""
    elections = [(2022, 7)]
    assert national_elections.is_election_linked_month(2023, 7, elections) is True


def test_is_election_linked_month_handles_year_boundary():
    elections = [(2021, 10)]
    assert national_elections.is_election_linked_month(2022, 10, elections) is True


def test_is_election_linked_month_false_otherwise():
    elections = [(2022, 7)]
    assert national_elections.is_election_linked_month(2022, 8, elections) is False
    assert national_elections.is_election_linked_month(2023, 6, elections) is False
