from seiryoku import cp_history
from seiryoku.monthly_index import MonthSnapshot


def test_save_history_writes_and_load_history_reads_back(tmp_path, monkeypatch):
    monkeypatch.setattr(cp_history, "HISTORY_PATH", tmp_path / "cp_history.json")

    snapshots = [
        MonthSnapshot(
            year=2024, month=1, C_p={"自由民主党": 1.0}, n_events=1,
            level_weight_share={"衆院選": 1.0},
        ),
        MonthSnapshot(
            year=2024, month=2, C_p={"公明党": 1.0}, n_events=1,
            level_weight_share={"市区町村議会": 1.0},
        ),
    ]

    written = cp_history.save_history(snapshots)
    assert written == [
        {"year": 2024, "month": 1, "C_p": {"自由民主党": 1.0}, "n_events": 1,
         "level_weight_share": {"衆院選": 1.0}},
        {"year": 2024, "month": 2, "C_p": {"公明党": 1.0}, "n_events": 1,
         "level_weight_share": {"市区町村議会": 1.0}},
    ]

    assert cp_history.load_history() == written


def test_load_history_returns_empty_list_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(cp_history, "HISTORY_PATH", tmp_path / "does_not_exist.json")
    assert cp_history.load_history() == []


def test_save_history_overwrites_previous_contents(tmp_path, monkeypatch):
    """jichisokenの新しい年版で過去月の値が変わりうるため、追記ではなく
    丸ごと置き換えであることを確認する。"""
    monkeypatch.setattr(cp_history, "HISTORY_PATH", tmp_path / "cp_history.json")

    cp_history.save_history(
        [MonthSnapshot(year=2024, month=1, C_p={"自由民主党": 1.0}, n_events=1, level_weight_share={})]
    )
    cp_history.save_history(
        [MonthSnapshot(year=2024, month=1, C_p={"自由民主党": 0.9, "公明党": 0.1}, n_events=2, level_weight_share={})]
    )

    history = cp_history.load_history()
    assert len(history) == 1
    assert history[0]["C_p"] == {"自由民主党": 0.9, "公明党": 0.1}
