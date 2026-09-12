import pytest

from seiryoku.fetch.budgets import _HISTORY_YEAR_TOKEN, _nendo_label_to_year


def test_nendo_label_to_year_reiwa():
    assert _nendo_label_to_year("令和6年度都道府県決算カード") == 2024


def test_nendo_label_to_year_heisei():
    assert _nendo_label_to_year("平成27年度市町村決算カード") == 2015


def test_nendo_label_to_year_gannen():
    assert _nendo_label_to_year("令和元年度市町村決算カード") == 2019


def test_nendo_label_to_year_raises_without_match():
    with pytest.raises(ValueError):
        _nendo_label_to_year("決算カードについて")


@pytest.mark.parametrize(
    "token,expected",
    [
        ("元年度", "元"),
        ("2", "2"),
        ("7年度", "7"),
        ("30", "30"),
    ],
)
def test_history_year_token_matches_expected_tokens(token, expected):
    m = _HISTORY_YEAR_TOKEN.match(token)
    assert m is not None
    assert m.group(1) == expected


@pytest.mark.parametrize("token", ["平成", "令和", "(注）本表の各年度の補正予算額は増額減額差引後の計数である。", ""])
def test_history_year_token_does_not_match_non_year_labels(token):
    assert _HISTORY_YEAR_TOKEN.match(token) is None
