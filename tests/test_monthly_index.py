from seiryoku import monthly_index, municipal_registry, turnover
from seiryoku.fetch import diet_history, jichisoken, population
from seiryoku.fetch.diet_history import Snapshot
from seiryoku.fetch.jichisoken import Endorsement


def test_ym_parses_iso_date():
    assert monthly_index._ym("2023-04-09") == (2023, 4)
    assert monthly_index._ym(None) is None
    assert monthly_index._ym("") is None


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
        "fetch_sangiin_election_history",
        lambda: [Snapshot(session="第26回", date="2022-07-10", seats={"自由民主党": 1, "公明党": 0})],
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
    monkeypatch.setattr(municipal_registry, "load_gikai_term_chain_cache", lambda: {"chains": {}})
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

    # 選挙のあった月だけが結果に含まれる(市長選・知事選・衆院選)
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


def test_build_month_snapshots_weights_diet_by_seat_count(monkeypatch):
    """国会だけ実際の議席数n_eをsqrt(n_e * P_e)として掛ける(2026-09の設計変更、
    design_document.tex \\S2.2参照)。首長は常にn_e=1なのでsqrt(P_e)のまま。

    知事選(自民、P=10000、n_e=1、重みsqrt(10000)=100)と同じ12か月ウィンドウに
    参院選(公明、n_e=9議席、P=10000、重みsqrt(9*10000)=300)が入る設定にし、
    n_eを考慮しない旧式なら50:50になるところが25:75になることを確認する。
    """
    from seiryoku.fetch import diet

    monkeypatch.setattr(
        diet_history,
        "fetch_sangiin_election_history",
        lambda: [Snapshot(session="第26回", date="2022-08-03", seats={"公明党": 9})],
    )
    monkeypatch.setattr(diet_history, "fetch_shugiin_history", lambda: [])
    monkeypatch.setattr(diet, "fetch_diet_seats", lambda: {"参議院": {"公明党": 9, "自由民主党": 5}})
    monkeypatch.setattr(monthly_index, "_latest_shugiin_district_pct", lambda: {})
    monkeypatch.setattr(monthly_index, "_latest_sangiin_district_pct", lambda: {})
    monkeypatch.setattr(population, "national_population", lambda: 10000)
    monkeypatch.setattr(turnover, "_ensure_governor_ids_loaded", lambda: None)
    monkeypatch.setattr(turnover, "_GOVERNOR_JICHITAI_IDS", {"石川県": 100})
    monkeypatch.setattr(
        turnover,
        "load_term_chain_cache",
        lambda: {"chains": {"100": [{"vote_date": "2022-01-15", "party": "自由民主党"}]}},
    )
    monkeypatch.setattr(municipal_registry, "jurisdiction_name", lambda jid: None)
    monkeypatch.setattr(municipal_registry, "load_gikai_term_chain_cache", lambda: {"chains": {}})
    monkeypatch.setattr(population, "prefecture_population_by_name", lambda: {"石川県": 10000})
    monkeypatch.setattr(population, "municipal_population_by_name", lambda: {})
    monkeypatch.setattr(jichisoken, "governor_endorsements_by_year", lambda: {})
    monkeypatch.setattr(jichisoken, "municipal_head_endorsements_by_year", lambda: {})
    monkeypatch.setattr(
        jichisoken, "endorsement_for_vote_year", lambda by_year, name, vote_date: None
    )

    snapshots = monthly_index.build_month_snapshots(min_year=2022, window_months=12)
    by_month = {(s.year, s.month): s for s in snapshots}

    sangiin_snapshot = by_month[(2022, 8)]
    assert sangiin_snapshot.C_p == {"自由民主党": 0.25, "公明党": 0.75}
    assert sangiin_snapshot.n_events == 2


def test_build_month_snapshots_includes_assembly_elections_without_jichisoken_correction(monkeypatch):
    """都道府県議会・市区町村議会(gikai)も国会と同じく届出政党そのままでphi_p(e)を
    計算し、jichisoken補正は試みない(2026年9月にユーザー指摘、design_document.tex
    \\S2.1参照)。市長選(自民、P=10000、n_e=1、重みsqrt(10000)=100)と同じ窓に
    市議会選(自民6・無所属4、n_e=10議席、P=10000、重みsqrt(10*10000)≒316.2)が
    入る設定で、議会選のほうが大きな重みを持つことを確認する。"""
    from seiryoku.fetch import diet

    monkeypatch.setattr(diet_history, "fetch_sangiin_election_history", lambda: [])
    monkeypatch.setattr(diet_history, "fetch_shugiin_history", lambda: [])
    monkeypatch.setattr(diet, "fetch_diet_seats", lambda: {"衆議院": {"自由民主党": 5}})
    monkeypatch.setattr(monthly_index, "_latest_shugiin_district_pct", lambda: {})
    monkeypatch.setattr(monthly_index, "_latest_sangiin_district_pct", lambda: {})
    monkeypatch.setattr(population, "national_population", lambda: 10000)
    monkeypatch.setattr(turnover, "_ensure_governor_ids_loaded", lambda: None)
    monkeypatch.setattr(turnover, "_GOVERNOR_JICHITAI_IDS", {})
    monkeypatch.setattr(
        turnover,
        "load_term_chain_cache",
        lambda: {"chains": {"1": [{"vote_date": "2022-04-10", "party": "自由民主党"}]}},
    )
    monkeypatch.setattr(municipal_registry, "jurisdiction_name", lambda jid: "A市")
    monkeypatch.setattr(
        municipal_registry,
        "load_gikai_term_chain_cache",
        lambda: {
            "chains": {
                "1": [{"vote_date": "2022-04-10", "seats": {"自由民主党": 6, "無所属": 4}}],
            }
        },
    )
    monkeypatch.setattr(population, "prefecture_population_by_name", lambda: {})
    monkeypatch.setattr(population, "municipal_population_by_name", lambda: {"A市": 10000})
    monkeypatch.setattr(jichisoken, "governor_endorsements_by_year", lambda: {})
    monkeypatch.setattr(jichisoken, "municipal_head_endorsements_by_year", lambda: {})
    monkeypatch.setattr(
        jichisoken, "endorsement_for_vote_year", lambda by_year, name, vote_date: None
    )

    snapshots = monthly_index.build_month_snapshots(min_year=2022, window_months=1)
    by_month = {(s.year, s.month): s for s in snapshots}

    snapshot = by_month[(2022, 4)]
    assert snapshot.n_events == 2

    import math

    head_w = math.sqrt(10000)
    gikai_w = math.sqrt(10 * 10000)
    total_w = head_w + gikai_w
    expected_ldp = (head_w * 1.0 + gikai_w * 0.6) / total_w
    expected_ind = (gikai_w * 0.4) / total_w
    assert snapshot.C_p["自由民主党"] == expected_ldp
    assert snapshot.C_p["無所属"] == expected_ind
