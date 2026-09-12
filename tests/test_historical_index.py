from seiryoku import historical_index, municipal_registry, turnover
from seiryoku.fetch import jichisoken, population
from seiryoku.fetch.diet_history import Snapshot
from seiryoku.fetch.jichisoken import Endorsement


def test_build_year_snapshots_combines_i_p_and_e_p(monkeypatch):
    monkeypatch.setattr(
        historical_index,
        "_build_i_p_series",
        lambda min_year: {
            2018: ({"自由民主党": 0.6, "無所属": 0.4}, {"自由民主党"}),
            2019: ({"自由民主党": 0.5, "無所属": 0.5}, {"自由民主党"}),
        },
    )
    monkeypatch.setattr(
        historical_index,
        "_build_e_p_series",
        lambda years: {2018: ({"自由民主党": 0.3, "無所属": 0.7}, 10), 2019: ({"無所属": 1.0}, 3)},
    )

    snapshots = historical_index.build_year_snapshots()

    assert [s.year for s in snapshots] == [2018, 2019]
    assert snapshots[0].I_p == {"自由民主党": 0.6, "無所属": 0.4}
    assert snapshots[0].E_p == {"自由民主党": 0.3, "無所属": 0.7}
    assert snapshots[0].E_p_known_jurisdictions == 10
    assert snapshots[0].national_parties == {"自由民主党"}
    assert snapshots[1].E_p_known_jurisdictions == 3


def test_build_year_snapshots_missing_e_p_year_falls_back_to_empty(monkeypatch):
    """E_pが対象年ぶん再構成できなかった場合(自治体が1件も条件を満たさない等)、
    I_pだけは欠かさず返し、E_pは空・known=0にする。"""
    monkeypatch.setattr(
        historical_index,
        "_build_i_p_series",
        lambda min_year: {2018: ({"自由民主党": 1.0}, {"自由民主党"})},
    )
    monkeypatch.setattr(historical_index, "_build_e_p_series", lambda years: {})

    snapshots = historical_index.build_year_snapshots()

    assert len(snapshots) == 1
    assert snapshots[0].E_p == {}
    assert snapshots[0].E_p_known_jurisdictions == 0


def test_seats_as_of_picks_latest_snapshot_not_exceeding_year():
    snaps = [
        Snapshot(session="a", date="2009-08-30", seats={"A": 1}),
        Snapshot(session="b", date="2012-12-16", seats={"B": 2}),
        Snapshot(session="c", date="2017-10-22", seats={"C": 3}),
    ]

    def date_key(iso: str):
        import re

        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso)
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))

    assert historical_index._seats_as_of(snaps, 2015, date_key) == {"B": 2}
    assert historical_index._seats_as_of(snaps, 2009, date_key) == {"A": 1}
    assert historical_index._seats_as_of(snaps, 2005, date_key) is None


def test_year_of_extracts_leading_year():
    assert historical_index._year_of("2023-04-09") == 2023
    assert historical_index._year_of(None) is None
    assert historical_index._year_of("") is None


def test_pick_term_returns_the_term_covering_target_year():
    chain = [
        {"vote_date": "2022-03-13", "party": "無所属"},
        {"vote_date": "2018-03-11", "party": "民主党"},
    ]
    assert historical_index._pick_term(chain, 2023) == chain[0]
    assert historical_index._pick_term(chain, 2019) == chain[1]
    assert historical_index._pick_term(chain, 2010) is None


def test_build_e_p_series_uses_term_chain_to_reach_years_before_current_term(monkeypatch):
    """現在の任期がまだ始まっていない年(例: 2019年)でも、前任者以前まで遡った
    在任履歴チェーン(turnover.build_term_chain_cache())を使えば対象にできる
    ことを確認する回帰テスト——「現在の議席台帳だけをフィルタする」設計では
    2018〜2021年が対象0件になっていた問題の修正([[seiryoku_shisu_design]]参照)。
    """
    monkeypatch.setattr(turnover, "_ensure_governor_ids_loaded", lambda: None)
    monkeypatch.setattr(turnover, "_GOVERNOR_JICHITAI_IDS", {"石川県": 100})
    monkeypatch.setattr(
        turnover,
        "load_term_chain_cache",
        lambda: {
            "chains": {
                "100": [  # 知事: 現職(2022〜)は推薦付き無所属、前任(2018〜2022)は民主党
                    {"vote_date": "2022-03-13", "party": "無所属"},
                    {"vote_date": "2018-03-11", "party": "民主党"},
                ],
                "1": [{"vote_date": "2019-04-07", "party": "自由民主党"}],  # 市長
            }
        },
    )
    monkeypatch.setattr(municipal_registry, "jurisdiction_name", lambda jid: "A市" if jid == 1 else None)
    monkeypatch.setattr(population, "prefecture_population_by_name", lambda: {"石川県": 1000})
    monkeypatch.setattr(population, "municipal_population_by_name", lambda: {"A市": 1000})

    gov_by_year = {"2022": {"石川県": Endorsement("石川県", "無所属", ["公明党"], "2022-03-13", "2022")}}
    monkeypatch.setattr(jichisoken, "governor_endorsements_by_year", lambda: gov_by_year)
    monkeypatch.setattr(jichisoken, "municipal_head_endorsements_by_year", lambda: {})
    monkeypatch.setattr(
        jichisoken,
        "endorsement_for_vote_year",
        lambda by_year, name, vote_date: by_year.get(str(historical_index._year_of(vote_date)), {}).get(name),
    )

    # national_partiesはその年ごとの衆参構成由来のものを渡す(民主党は2019年当時は
    # 国政政党だったが現在は解党しているため、現在の構成だけで判定すると無所属に
    # 誤って一括されてしまう——この回帰を防ぐテストでもある)。
    result = historical_index._build_e_p_series(
        {2019: {"自由民主党", "民主党"}, 2023: {"自由民主党", "公明党"}}
    )

    share_2019, known_2019 = result[2019]
    assert known_2019 == 2  # 前任者チェーンのおかげで知事も対象にできる
    assert share_2019 == {"民主党": 0.5, "自由民主党": 0.5}

    share_2023, known_2023 = result[2023]
    assert known_2023 == 2
    assert share_2023 == {"公明党": 0.5, "自由民主党": 0.5}
