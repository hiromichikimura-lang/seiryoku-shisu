from seiryoku.fetch.diet_history import _norm, _parse_shugiin_result_sheet


def _block(parties: list[str], totals: list[int]) -> list[tuple]:
    """1ブロックぶんの行を組み立てる(タイトル行・空行は呼び出し側で付ける)。
    小選挙区・比例代表の内訳は問わないので、合計の「計」行にだけ実際の値を入れる。
    """
    header = ["", ""] + [name for name in parties for _ in range(3)]
    kubun = ["区  分"] + [""] * (len(header) - 1)
    danjokei = ["", ""] + ["男", "女", "計"] * len(parties)
    filler = lambda label0, label1: [label0, label1] + [""] * (len(header) - 2)
    total_row = ["", "計"]
    for t in totals:
        total_row += ["", "", t]
    rows = [
        tuple(header),
        tuple(kubun),
        tuple(danjokei),
        tuple(filler("小", "新")),
        tuple(filler("選", "前")),
        tuple(filler("挙", "元")),
        tuple(filler("区", "計")),
        tuple(filler("比", "新")),
        tuple(filler("例", "前")),
        tuple(filler("代", "元")),
        tuple(filler("表", "計")),
        tuple(filler("", "新")),
        tuple(filler("合", "前")),
        tuple(filler("計", "元")),
        tuple(total_row),
    ]
    return rows


def test_norm_strips_fullwidth_and_ascii_whitespace():
    assert _norm("小　　計") == "小計"
    assert _norm("  無所属 ") == "無所属"
    assert _norm(None) == ""
    assert _norm(42) == ""


def test_parse_single_block_sheet():
    title = [("3. 開票結果", "", "", "", "", "（１）届出政党等別男女別新前元別当選人数(小選挙区、比例代表)")]
    blank = [("",)]
    rows = title + blank + _block(["自由民主党", "民主党"], [119, 308])
    assert _parse_shugiin_result_sheet(rows) == {"自由民主党": 119, "民主党": 308}


def test_parse_sheet_with_multiple_stacked_blocks():
    """1シートに政党名の見出し行が複数回繰り返されるケース(実データで確認済み)。
    ブロックをまたいで最後の「計」行を拾うと、後のブロックの値が前のブロックの
    政党に紐付いてしまうバグが過去にあったための回帰テスト。
    """
    title = [("3. 開票結果", "", "", "", "", "（１）届出政党等別男女別新前元別当選人数(小選挙区、比例代表)")]
    blank = [("",)]
    block1 = _block(["自由民主党", "公明党"], [281, 29])
    block2 = _block(["日本共産党", "社会民主党"], [12, 2])
    rows = title + blank + block1 + blank + block2
    assert _parse_shugiin_result_sheet(rows) == {
        "自由民主党": 281,
        "公明党": 29,
        "日本共産党": 12,
        "社会民主党": 2,
    }


def test_parse_sheet_excludes_rollup_columns_but_keeps_independents():
    """「政党等所属」「小計」「合計」は複数政党の再集計列であり政党名ではないので
    除外するが、「無所属」は正真正銘の1カテゴリとして残す(実データで確認済み)。
    """
    title = [("3. 開票結果", "", "", "", "", "（１）届出政党等別男女別新前元別当選人数(小選挙区、比例代表)")]
    subtitle = [("", "", "本人･推薦届出")]
    blank = [("", "", "", "", "", "", "", "", "", "", "", "　　     合　計")]
    header = ["区  分", "", "        政党等所属", "", "", "        無所属", "", "", "        小   計", "", "", ""]
    danjokei = ["", ""] + ["男", "女", "計"] * 3 + [""]
    filler = lambda label0, label1: [label0, label1] + [""] * (len(header) - 2)
    total_row = ["", "計", "", "", 439, "", "", 5, "", "", 444, "", "", 465]
    rows = (
        title
        + subtitle
        + blank
        + [tuple(header), tuple(danjokei)]
        + [tuple(filler(a, b)) for a, b in [("小", "新"), ("選", "前"), ("挙", "元"), ("区", "計")]]
        + [tuple(filler(a, b)) for a, b in [("比", "新"), ("例", "前"), ("代", "元"), ("表", "計")]]
        + [tuple(filler(a, b)) for a, b in [("", "新"), ("合", "前"), ("計", "元")]]
        + [tuple(total_row)]
    )
    seats = _parse_shugiin_result_sheet(rows)
    assert seats == {"無所属": 5}


def test_parse_sheet_raises_when_no_header_found():
    import pytest

    with pytest.raises(ValueError):
        _parse_shugiin_result_sheet([("", "", ""), ("", "", "")])
