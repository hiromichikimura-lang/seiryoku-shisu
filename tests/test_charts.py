from seiryoku import charts, national_elections
from seiryoku.fetch import diet_history, jichisoken
from seiryoku.fetch.diet_history import Snapshot


def _fixture_history():
    return [
        {"year": 2022, "month": m, "C_p": {"自由民主党": 0.6, "公明党": 0.4},
         "n_events": 1, "level_weight_share": {"衆院選": 1.0} if m == 7 else {"市区町村議会": 1.0}}
        for m in range(1, 13)
    ]


def test_generate_main_chart_writes_a_png(tmp_path, monkeypatch):
    monkeypatch.setattr(diet_history, "fetch_sangiin_election_history",
                         lambda: [Snapshot(session="a", date="2022-07-10", seats={})])
    monkeypatch.setattr(diet_history, "fetch_shugiin_history", lambda: [])
    monkeypatch.setattr(jichisoken, "governor_endorsements_by_year", lambda: {"2025": {}})

    out_path = tmp_path / "chart.png"
    result = charts.generate_main_chart(_fixture_history(), out_path=out_path)

    assert result == out_path
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_provisional_start_derives_may_of_latest_jichisoken_version(monkeypatch):
    monkeypatch.setattr(jichisoken, "governor_endorsements_by_year", lambda: {"2023": {}, "2025": {}})
    assert charts._provisional_start() == (2025, 5)


def test_provisional_start_returns_none_when_no_data(monkeypatch):
    monkeypatch.setattr(jichisoken, "governor_endorsements_by_year", lambda: {})
    assert charts._provisional_start() is None


def test_unified_local_election_months_every_four_years_in_april():
    months = charts._unified_local_election_months(2018, 2027)
    assert (2019, 4) in months
    assert (2023, 4) in months
    assert (2027, 4) in months
    assert (2021, 4) not in months
