from seiryoku.lineage import canonicalize


def test_canonicalize_independent_labels():
    assert canonicalize("無所属") == "無所属"
    assert canonicalize("無所属(諸派系)") == "無所属"
    assert canonicalize("諸派") == "無所属"
    assert canonicalize("各派に属しない議員") == "無所属"


def test_canonicalize_strips_coalition_suffix():
    assert canonicalize("自由民主党・無所属の会") == "自由民主党"


def test_canonicalize_applies_explicit_alias():
    assert canonicalize("れいわ新選組") == "いのちの党"
    assert canonicalize("立憲民主") == "立憲民主党"


def test_canonicalize_passthrough_for_unknown_party():
    assert canonicalize("公明党") == "公明党"
