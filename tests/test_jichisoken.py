from seiryoku.fetch.jichisoken import (
    Endorsement,
    _date_column_index,
    _endorsing_parties,
    _find_header_row,
    _find_sheet,
    endorsement_for_vote_year,
    extract_vote_year,
    merge_latest,
)


def _row(header: list[str], values: dict[str, object]) -> list:
    return [values.get(col) for col in header]


def test_endorsing_parties_detects_marked_columns():
    header = ["自治体名", "党派", "自", "立民", "国民", "公", "共", "社", "維"]
    row = _row(header, {"公": "〇", "社": "△"})
    assert set(_endorsing_parties(row, header)) == {"公明党", "社会民主党"}


def test_endorsing_parties_empty_when_no_marks():
    header = ["自治体名", "党派", "自", "立民"]
    row = _row(header, {"自治体名": "秋田県", "党派": "無所属"})
    assert _endorsing_parties(row, header) == []


def test_endorsing_parties_handles_shikucyouson_column_variant():
    # 市区町村シートは「立」「国」「大」表記(都道府県シートは「立民」「国民」「社大」)
    header = ["自治体名", "党派", "自", "立", "国", "公", "共", "社", "維", "大"]
    row = _row(header, {"立": "〇"})
    assert _endorsing_parties(row, header) == ["立憲民主党"]


def test_endorsing_parties_ignores_non_national_columns():
    # 「大」(沖縄独自の地域政党)は国政政党ではないため対象外
    header = ["自治体名", "党派", "大", "その他1"]
    row = _row(header, {"大": "〇", "その他1": "〇"})
    assert _endorsing_parties(row, header) == []


def test_find_header_row_locates_row_with_jichitaimei():
    rows = [
        (None, "A", "K", None),
        ("コード", "自治体名", "選挙執行日", "党派"),
        ("010001", "北海道", "2024年", "無所属"),
    ]
    assert _find_header_row(rows) == 1


def test_find_header_row_returns_none_when_absent():
    rows = [("A", "B"), ("C", "D")]
    assert _find_header_row(rows) is None


def test_find_sheet_matches_by_substring():
    assert _find_sheet(["都道府県知事", "都道府県議会"], "知事") == "都道府県知事"
    assert _find_sheet(["知事2019", "議会2019"], "知事") == "知事2019"
    assert _find_sheet(["首長", "議会"], "首長") == "首長"


def test_find_sheet_returns_none_when_no_match():
    assert _find_sheet(["都道府県議会"], "知事") is None


def test_date_column_index_tries_multiple_candidate_names():
    assert _date_column_index(["自治体名", "選挙執行月日", "党派"]) == 1
    assert _date_column_index(["自治体名", "選挙執行日", "党派"]) == 1
    assert _date_column_index(["自治体名", "党派"]) is None


def test_extract_vote_year_handles_multiple_formats():
    assert extract_vote_year("2019年") == "2019"
    assert extract_vote_year("2020-09-08 00:00:00") == "2020"
    assert extract_vote_year("2021/04/11") == "2021"
    assert extract_vote_year("") is None
    assert extract_vote_year(None) is None


def _endorsement(name, endorsing, vote_date, year):
    return Endorsement(name=name, formal_party="無所属", endorsing_parties=endorsing, vote_date=vote_date, year=year)


def test_endorsement_for_vote_year_matches_actual_election_year_not_version_label():
    # 「都道府県知事」シートは各都道府県の現職の実際の当選年をそのまま記録しており、
    # 年版のラベル(2023)とEndorsement自身のvote_date(2019)は一致しないことがある
    # (実データで確認済み)。年版ラベルではなくvote_dateの年で照合する。
    by_year = {
        "2023": {"青森県": _endorsement("青森県", ["公明党"], "2019年", "2023")},
    }
    entry = endorsement_for_vote_year(by_year, "青森県", "2019-06-02")
    assert entry is not None
    assert entry.endorsing_parties == ["公明党"]


def test_endorsement_for_vote_year_returns_none_when_no_year_matches():
    by_year = {
        "2023": {"青森県": _endorsement("青森県", ["公明党"], "2019年", "2023")},
    }
    assert endorsement_for_vote_year(by_year, "青森県", "2015-06-02") is None


def test_endorsement_for_vote_year_returns_none_when_name_absent():
    by_year = {"2023": {"青森県": _endorsement("青森県", ["公明党"], "2019年", "2023")}}
    assert endorsement_for_vote_year(by_year, "秋田県", "2019-06-02") is None


def test_merge_latest_prefers_newer_year_version():
    by_year = {
        "2020": {"A市": _endorsement("A市", ["自由民主党"], "2019年", "2020")},
        "2023": {"A市": _endorsement("A市", ["公明党"], "2022年", "2023")},
    }
    merged = merge_latest(by_year)
    assert merged["A市"].endorsing_parties == ["公明党"]
