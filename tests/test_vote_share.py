from seiryoku.fetch import vote_share


def test_sangiin_ordinal_for_year_matches_known_elections():
    assert vote_share.sangiin_ordinal_for_year(2019) == 25
    assert vote_share.sangiin_ordinal_for_year(2022) == 26
    assert vote_share.sangiin_ordinal_for_year(2025) == 27


def _rows(header, konkai_pct_row, extra_after=()):
    return [
        ["（４）届出政党等別得票数（小選挙区）"],
        [],
        [],
        ["区　分", *header],
        [],
        ["今　回", *["1,000    "] * len(header)],
        [0.0] * (len(header) + 1),
        ["", *konkai_pct_row],
        ["前　回", *["900    "] * len(header)],
        *extra_after,
    ]


def test_parse_sheet_rows_extracts_percentage_row():
    rows = _rows(["自由民主党", "公明党"], [48.5, 10.2])
    result = vote_share._parse_sheet_rows(rows)
    assert result == {"自由民主党": 48.5, "公明党": 10.2}


def test_parse_sheet_rows_strips_footnote_markers():
    rows = _rows(["立憲民主党※１", "国民民主党※２"], [30.0, 2.5])
    result = vote_share._parse_sheet_rows(rows)
    assert result == {"立憲民主党": 30.0, "国民民主党": 2.5}


def test_parse_sheet_rows_converts_fractional_scale_to_percent():
    rows = _rows(["自由民主党", "公明党"], [0.485, 0.102])
    result = vote_share._parse_sheet_rows(rows)
    assert result == {"自由民主党": 48.5, "公明党": 10.2}


def test_parse_sheet_rows_drops_total_column():
    rows = _rows(["自由民主党", "合計"], [60.0, 100.0])
    result = vote_share._parse_sheet_rows(rows)
    assert result == {"自由民主党": 60.0}
    assert "合計" not in result


def test_parse_sheet_rows_empty_when_header_not_found():
    assert vote_share._parse_sheet_rows([["something else"]]) == {}
