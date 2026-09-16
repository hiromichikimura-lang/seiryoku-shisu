from seiryoku import index, municipal_registry, registry
from seiryoku.fetch import diet, jichisoken, population
from seiryoku.fetch.jichisoken import Endorsement
from seiryoku.index import (
    _effective_party_shares,
    _phi,
    _restrict_to_national,
    compute_assembly_index,
    compute_combined_index,
    national_parties_from_diet,
    national_parties_meeting_requirement,
    weighted_share_by_jurisdiction,
)


def test_effective_party_shares_prefers_formal_party():
    assert _effective_party_shares("自由民主党", ["公明党"]) == {"自由民主党": 1.0}


def test_effective_party_shares_independent_no_endorsement():
    assert _effective_party_shares("無所属", []) == {"無所属": 1.0}


def test_effective_party_shares_independent_single_endorsement():
    assert _effective_party_shares("無所属", ["公明党"]) == {"公明党": 1.0}


def test_effective_party_shares_splits_coalition_evenly():
    shares = _effective_party_shares("無所属", ["自由民主党", "公明党"])
    assert shares == {"自由民主党": 0.5, "公明党": 0.5}
    assert sum(shares.values()) == 1.0


def test_effective_party_shares_merges_duplicate_canonical_names():
    # 表記ゆれで同じ政党が複数回推薦欄に出ても、正規化後は1つに合算される
    shares = _effective_party_shares("無所属", ["立憲民主", "立憲民主党"])
    assert shares == {"立憲民主党": 1.0}


def test_phi_normalizes_including_independent_bucket():
    phi = _phi({"自由民主党": 3, "無所属": 1})
    assert phi["自由民主党"] == 0.75
    assert phi["無所属"] == 0.25


def test_phi_empty_when_no_seats():
    assert _phi({}) == {}


def test_weighted_share_by_jurisdiction_weights_by_given_weight():
    entries = [
        ({"自由民主党": 0.5, "無所属": 0.5}, 100.0),  # weight 0.25
        ({"自由民主党": 0.75, "無所属": 0.25}, 300.0),  # weight 0.75
    ]
    result = weighted_share_by_jurisdiction(entries)
    assert result["自由民主党"] == 0.25 * 0.5 + 0.75 * 0.75
    assert result["無所属"] == 0.25 * 0.5 + 0.75 * 0.25


def test_weighted_share_by_jurisdiction_empty_when_no_weight():
    assert weighted_share_by_jurisdiction([]) == {}


def test_compute_assembly_index_uses_diet_seats_only():
    diet_seats = {
        "衆議院": {"自由民主党": 3, "無所属": 1},
        "参議院": {"自由民主党": 1, "公明党": 1},
    }
    result = compute_assembly_index(diet_seats)
    assert result == {"自由民主党": 4 / 6, "無所属": 1 / 6, "公明党": 1 / 6}


def test_national_parties_from_diet_derives_from_actual_seats():
    diet_seats = {
        "衆議院": {"自由民主党・無所属の会": 200, "日本共産党": 10, "無所属": 5},
        "参議院": {"公明党": 20, "各派に属しない議員": 3},
    }
    parties = national_parties_from_diet(diet_seats)
    assert parties == {"自由民主党", "日本共産党", "公明党"}
    assert "無所属" not in parties


def test_restrict_to_national_passes_through_when_no_whitelist():
    assert _restrict_to_national("杉並", None) == "杉並"


def test_restrict_to_national_keeps_national_party():
    assert _restrict_to_national("自由民主党", {"自由民主党", "公明党"}) == "自由民主党"


def test_restrict_to_national_folds_local_party_into_independent():
    assert _restrict_to_national("杉並", {"自由民主党", "公明党"}) == "無所属"


def test_restrict_to_national_keeps_independent_label():
    assert _restrict_to_national("無所属", {"自由民主党"}) == "無所属"


def test_phi_folds_local_parties_when_national_parties_given():
    raw = {"自由民主党": 2, "杉並": 1, "地域政党鎌倉": 1, "無所属": 1}
    phi = _phi(raw, national_parties={"自由民主党"})
    assert phi["自由民主党"] == 2 / 5
    assert phi["無所属"] == 3 / 5
    assert "杉並" not in phi
    assert "地域政党鎌倉" not in phi


def test_effective_party_shares_folds_local_endorsement_into_independent():
    shares = _effective_party_shares("無所属", ["杉並"], national_parties={"自由民主党"})
    assert shares == {"無所属": 1.0}


def test_compute_combined_index_weights_diet_by_seat_count_times_sqrt_population(monkeypatch):
    """C_p(t)は国会だけ実際の議席数nも掛けたsqrt(n*人口)で加重し、知事・市区町村長は
    n=1のままsqrt(人口)で加重する(2026-09の設計変更、design_document.tex \\S2.2参照)。
    衆参は合算せず、それぞれ自院の議席数で別々に重みを立てる
    (sqrtの非線形性により合算した場合と値が変わるため)。"""
    diet_seats = {
        "衆議院": {"自由民主党": 4, "無所属": 1},
        "参議院": {"自由民主党": 1, "公明党": 5},  # どちらも5議席で政党要件(a)を満たす
    }
    monkeypatch.setattr(diet, "fetch_diet_seats", lambda: diet_seats)
    monkeypatch.setattr(index, "_latest_shugiin_district_pct", lambda: {})
    monkeypatch.setattr(index, "_latest_sangiin_district_pct", lambda: {})
    monkeypatch.setattr(population, "national_population", lambda: 10000)
    monkeypatch.setattr(population, "prefecture_population_by_name", lambda: {"A県": 10000})
    monkeypatch.setattr(population, "municipal_population_by_name", lambda: {})
    monkeypatch.setattr(registry, "load_or_init_registry", lambda: {"A県": {"party": "公明党", "source": "soumu"}})
    monkeypatch.setattr(jichisoken, "governor_endorsements", lambda: {})
    monkeypatch.setattr(jichisoken, "municipal_head_endorsements", lambda: {})
    monkeypatch.setattr(municipal_registry, "load_checkpoint", lambda: {"head": {}})
    monkeypatch.setattr(municipal_registry, "coverage_report", lambda state: {"total_jichitai": 1788})

    result = compute_combined_index()

    # 衆議院(自民4・無所属1、合計5議席)、参議院(自民1・公明5、合計6議席)、
    # A県知事(公明1人分、n=1)をそれぞれ別枠のsqrt(n*人口)で重み付けて合成する
    import math

    shugiin_w = math.sqrt(5 * 10000)
    sangiin_w = math.sqrt(6 * 10000)
    gov_w = math.sqrt(10000)
    total_w = shugiin_w + sangiin_w + gov_w

    ldp = shugiin_w * (4 / 5) + sangiin_w * (1 / 6)
    komei = sangiin_w * (5 / 6) + gov_w * 1.0
    ind = shugiin_w * (1 / 5)

    assert result["share"]["自由民主党"] == ldp / total_w
    assert result["share"]["公明党"] == komei / total_w
    assert result["share"]["無所属"] == ind / total_w
    assert result["known_jurisdictions"] == 1
    assert abs(sum(result["share"].values()) - 1.0) < 1e-9


def test_national_parties_meeting_requirement_five_seats_qualifies_alone():
    diet_seats = {"衆議院": {"自由民主党": 5, "小政党": 2, "無所属": 1}}
    result = national_parties_meeting_requirement(diet_seats)
    assert result == {"自由民主党"}


def test_national_parties_meeting_requirement_needs_two_percent_vote_below_five_seats():
    diet_seats = {"衆議院": {"参政党": 3, "諸派": 1, "無所属": 1}}
    # 参政党は小選挙区2.5%(要件を満たす)、諸派は1%(満たさない)
    result = national_parties_meeting_requirement(
        diet_seats, shugiin_district_pct={"参政党": 2.5, "諸派": 1.0}
    )
    assert result == {"参政党"}


def test_national_parties_meeting_requirement_zero_seats_never_qualifies():
    diet_seats = {"衆議院": {"自由民主党": 5}}
    # 得票率だけ2%以上でも議席が無ければ要件(b)の「1人以上」を満たさない
    result = national_parties_meeting_requirement(
        diet_seats, shugiin_district_pct={"泡沫政党": 3.0}
    )
    assert result == {"自由民主党"}


def test_national_parties_meeting_requirement_checks_either_chamber():
    diet_seats = {"参議院": {"小政党": 1}}
    result = national_parties_meeting_requirement(
        diet_seats, shugiin_district_pct={"小政党": 0.5}, sangiin_district_pct={"小政党": 2.1}
    )
    assert result == {"小政党"}
