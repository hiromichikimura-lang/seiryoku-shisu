from seiryoku import coverage_history


def test_record_snapshot_appends_and_persists(tmp_path, monkeypatch):
    path = tmp_path / "coverage_history.json"
    monkeypatch.setattr(coverage_history, "HISTORY_PATH", path)

    coverage_history.record_snapshot(
        "2026-09-01", gov_covered=47, gov_total=47,
        muni_head_covered=27, muni_gikai_covered=22, muni_total=1788,
    )
    coverage_history.record_snapshot(
        "2026-09-04", gov_covered=47, gov_total=47,
        muni_head_covered=1738, muni_gikai_covered=1715, muni_total=1788,
    )

    history = coverage_history.load_history()
    assert [h["date"] for h in history] == ["2026-09-01", "2026-09-04"]
    assert history[1]["muni_head_covered"] == 1738


def test_record_snapshot_overwrites_same_date_instead_of_duplicating(tmp_path, monkeypatch):
    path = tmp_path / "coverage_history.json"
    monkeypatch.setattr(coverage_history, "HISTORY_PATH", path)

    coverage_history.record_snapshot(
        "2026-09-04", gov_covered=47, gov_total=47,
        muni_head_covered=1000, muni_gikai_covered=900, muni_total=1788,
    )
    coverage_history.record_snapshot(
        "2026-09-04", gov_covered=47, gov_total=47,
        muni_head_covered=1738, muni_gikai_covered=1715, muni_total=1788,
    )

    history = coverage_history.load_history()
    assert len(history) == 1
    assert history[0]["muni_head_covered"] == 1738


def test_load_history_returns_empty_list_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(coverage_history, "HISTORY_PATH", tmp_path / "does_not_exist.json")
    assert coverage_history.load_history() == []


def test_record_snapshot_keeps_history_sorted_by_date(tmp_path, monkeypatch):
    path = tmp_path / "coverage_history.json"
    monkeypatch.setattr(coverage_history, "HISTORY_PATH", path)

    coverage_history.record_snapshot(
        "2026-10-01", gov_covered=47, gov_total=47,
        muni_head_covered=1740, muni_gikai_covered=1716, muni_total=1788,
    )
    coverage_history.record_snapshot(
        "2026-09-04", gov_covered=47, gov_total=47,
        muni_head_covered=1738, muni_gikai_covered=1715, muni_total=1788,
    )

    history = coverage_history.load_history()
    assert [h["date"] for h in history] == ["2026-09-04", "2026-10-01"]
