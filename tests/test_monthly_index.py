from seiryoku import monthly_index, municipal_registry, turnover
from seiryoku.fetch import diet_history, jichisoken, population
from seiryoku.fetch.diet_history import Snapshot
from seiryoku.fetch.jichisoken import Endorsement


def test_ym_parses_iso_date():
    assert monthly_index._ym("2023-04-09") == (2023, 4)
    assert monthly_index._ym(None) is None
    assert monthly_index._ym("") is None


def test_sangiin_ym_converts_era_notation():
    assert monthly_index._sangiin_ym("R4.7.10") == (2022, 7)
    assert monthly_index._sangiin_ym("not a date") is None


def test_months_back_crosses_year_boundary():
    assert monthly_index._months_back((2024, 2), 3) == [(2024, 2), (2024, 1), (2023, 12)]
    assert monthly_index._months_back((2024, 6), 1) == [(2024, 6)]


def test_snapshots_from_windows_sums_entries_across_the_window():
    entries_by_month = {
        (2024, 1): [({"自由民主党": 1.0}, 4.0)],
        (2024, 2): [],
        (2024, 3): [({"公明党": 1.0}, 4.0)],
    }
    months = [(2024, 1), (2024, 2), (2024, 3)]

    single = monthly_index._snapshots_from_windows(entries_by_month, months, window_months=1)
    by_month = {(s.year, s.month): s for s in single}
    assert (2024, 2) not in by_month  # その月単独では選挙が無い
    assert by_month[(2024, 1)].C_p == {"自由民主党": 1.0}
    assert by_month[(2024, 3)].C_p == {"公明党": 1.0}

    windowed = monthly_index._snapshots_from_windows(entries_by_month, months, window_months=3)
    by_month_w = {(s.year, s.month): s for s in windowed}
    # 2024-02は単独では選挙が無いが、3か月ウィンドウなら1月ぶんを含む
    assert by_month_w[(2024, 2)].C_p == {"自由民主党": 1.0}
    assert by_month_w[(2024, 2)].n_events == 1
    # 2024-03は1月・3月の両方を含む(自民・公明が半々)
    assert by_month_w[(2024, 3)].C_p == {"自由民主党": 0.5, "公明党": 0.5}
    assert by_month_w[(2024, 3)].n_events == 2


def test_month_range_crosses_year_boundary():
    assert monthly_index._month_range((2023, 11), (2024, 2)) == [
        (2023, 11),
        (2023, 12),
        (2024, 1),
        (2024, 2),
    ]


def test_terms_in_month_returns_exact_month_matches():
    chain = [
        {"vote_date": "2023-04-09", "seats": {"A": 1}},
        {"vote_date": "2019-04-07", "seats": {"B": 1}},
    ]
    parsed = monthly_index._parsed_chain(chain)
    assert monthly_index._terms_in_month(parsed, (2023, 4)) == [{"vote_date": "2023-04-09", "seats": {"A": 1}}]
    assert monthly_index._terms_in_month(parsed, (2023, 5)) == []
    assert monthly_index._terms_in_month(parsed, (2020, 1)) == []


def test_is_sangiin_election_year_matches_known_cycle():
    assert monthly_index._is_sangiin_election_year(2019)
    assert monthly_index._is_sangiin_election_year(2022)
    assert monthly_index._is_sangiin_election_year(2025)
    assert not monthly_index._is_sangiin_election_year(2020)
    assert not monthly_index._is_sangiin_election_year(2024)


def test_real_sangiin_election_snapshots_drops_non_election_sessions():
    """常会・臨時会など選挙の無い召集は除外し、選挙年の最初の8月以降だけ拾う。"""
    snapshots = [
        Snapshot(session="常会", date="H31.1.28", seats={"自由民主党": 1}),  # 2019年、選挙前
        Snapshot(session="臨時", date="R1.8.1", seats={"自由民主党": 2}),  # 2019年選挙直後(採用)
        Snapshot(session="臨時", date="R1.10.4", seats={"自由民主党": 2}),  # 同じ選挙年の別会期(除外)
        Snapshot(session="常会", date="R2.1.20", seats={"自由民主党": 2}),  # 非選挙年(除外)
        Snapshot(session="臨時会", date="R4.8.3", seats={"自由民主党": 3}),  # 2022年選挙直後(採用)
    ]
    result = monthly_index._real_sangiin_election_snapshots(snapshots)
    assert dict(result) == {(2019, 8): {"自由民主党": 2}, (2022, 8): {"自由民主党": 3}}


def test_current_national_parties_uses_strict_requirement(monkeypatch):
    from seiryoku.fetch import diet

    monkeypatch.setattr(
        diet, "fetch_diet_seats", lambda: {"衆議院": {"自由民主党": 5, "小政党": 1, "無所属": 1}}
    )
    monkeypatch.setattr(monthly_index, "_latest_shugiin_district_pct", lambda: {"小政党": 0.5})
    monkeypatch.setattr(monthly_index, "_latest_sangiin_district_pct", lambda: {})
    assert monthly_index._current_national_parties() == {"自由民主党"}


def test_build_month_snapshots_only_includes_months_with_an_actual_election(monkeypatch):
    """フロー指標なので、選挙が無かった月は結果に出てこない(2026-09の設計変更)。"""
    from seiryoku.fetch import diet

    monkeypatch.setattr(
        diet_history,
        "fetch_sangiin_history",
        lambda: [
            Snapshot(session="old", date="H31.1.1", seats={"自由民主党": 1, "公明党": 0}),
            Snapshot(session="a", date="R4.7.10", seats={"自由民主党": 1, "公明党": 0}),
        ],
    )
    monkeypatch.setattr(
        diet_history,
        "fetch_shugiin_history",
        lambda: [Snapshot(session="48", date="2017-10-22", seats={"自由民主党": 1, "無所属": 1, "公明党": 0}),
                 Snapshot(session="49", date="2021-10-31", seats={"自由民主党": 1, "無所属": 1, "公明党": 0})],
    )
    # 政党要件は「直近の国政選挙時点」を全期間に固定で適用する(2026-09にユーザー指示、簡略化)
    monkeypatch.setattr(diet, "fetch_diet_seats", lambda: {"衆議院": {"自由民主党": 5, "公明党": 5}})
    monkeypatch.setattr(monthly_index, "_latest_shugiin_district_pct", lambda: {})
    monkeypatch.setattr(monthly_index, "_latest_sangiin_district_pct", lambda: {})
    monkeypatch.setattr(population, "national_population", lambda: 10000)
    monkeypatch.setattr(turnover, "_ensure_governor_ids_loaded", lambda: None)
    monkeypatch.setattr(turnover, "_GOVERNOR_JICHITAI_IDS", {"石川県": 100})
    monkeypatch.setattr(
        turnover,
        "load_term_chain_cache",
        lambda: {
            "chains": {
                "100": [{"vote_date": "2022-03-13", "party": "無所属"}],  # 知事選(2022年3月)
                "1": [{"vote_date": "2019-04-07", "party": "自由民主党"}],  # 市長選(2019年4月)
            }
        },
    )
    monkeypatch.setattr(municipal_registry, "jurisdiction_name", lambda jid: "A市" if jid == 1 else None)
    monkeypatch.setattr(population, "prefecture_population_by_name", lambda: {"石川県": 10000})
    monkeypatch.setattr(population, "municipal_population_by_name", lambda: {"A市": 10000})
    monkeypatch.setattr(
        jichisoken,
        "governor_endorsements_by_year",
        lambda: {"2022": {"石川県": Endorsement("石川県", "無所属", ["公明党"], "2022-03-13", "2022")}},
    )
    monkeypatch.setattr(jichisoken, "municipal_head_endorsements_by_year", lambda: {})
    monkeypatch.setattr(
        jichisoken,
        "endorsement_for_vote_year",
        lambda by_year, name, vote_date: by_year.get(vote_date[:4], {}).get(name),
    )

    snapshots = monthly_index.build_month_snapshots(min_year=2019, window_months=1)
    by_month = {(s.year, s.month): s for s in snapshots}

    # 選挙のあった3か月分だけが結果に含まれる(市長選・知事選・衆院選、
    # 参院選2022-07は国会側の構成としては反映されるが同月に選挙イベントは無い)
    assert (2019, 4) in by_month  # 市長選(A市、自由民主党)
    assert (2022, 3) in by_month  # 知事選(石川県、無所属→公明党推薦)
    assert (2021, 10) in by_month  # 衆院選

    # 選挙が無い月(例: 2020年1月)は含まれない
    assert (2020, 1) not in by_month

    muni_snapshot = by_month[(2019, 4)]
    assert muni_snapshot.C_p == {"自由民主党": 1.0}
    assert muni_snapshot.n_events == 1

    gov_snapshot = by_month[(2022, 3)]
    assert gov_snapshot.C_p == {"公明党": 1.0}
    assert gov_snapshot.n_events == 1
