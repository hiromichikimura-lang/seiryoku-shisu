from types import SimpleNamespace

from seiryoku import draft, forecast, national_elections, precursor


def _history():
    return [
        {"year": 2022, "month": 5, "C_p": {"自由民主党": 0.4, "公明党": 0.15},
         "n_events": 1, "level_weight_share": {"市区町村議会": 1.0}},
        {"year": 2022, "month": 6, "C_p": {"自由民主党": 0.5, "公明党": 0.1},
         "n_events": 1, "level_weight_share": {"市区町村議会": 1.0}},
        {"year": 2022, "month": 7, "C_p": {"自由民主党": 0.55, "公明党": 0.08},
         "n_events": 2, "level_weight_share": {"衆院選": 1.0}},
    ]


def test_build_month_facts_defaults_to_latest_single_month_when_no_last_report(monkeypatch):
    monkeypatch.setattr(national_elections, "compute_election_events", lambda: [((2022, 7), "衆院選")])
    monkeypatch.setattr(forecast, "load_forecast_history", lambda: {})
    monkeypatch.setattr(precursor, "load_precursor_table", lambda: [])
    monkeypatch.setattr(draft, "load_last_report", lambda: None)

    facts = draft.build_month_facts(_history(), election_months=[(2022, 7)])

    assert facts["year"] == 2022
    assert facts["month"] == 7
    assert facts["period_start"] == {"year": 2022, "month": 7}
    assert facts["diffs"]["自由民主党"] == 0.55 - 0.5
    assert facts["n_events"] == 2
    assert facts["events_in_period"] == ["衆院選"]


def test_build_month_facts_covers_multiple_months_since_last_report(monkeypatch):
    monkeypatch.setattr(national_elections, "compute_election_events", lambda: [((2022, 7), "衆院選")])
    monkeypatch.setattr(forecast, "load_forecast_history", lambda: {})
    monkeypatch.setattr(precursor, "load_precursor_table", lambda: [])

    # 前回更新が2022年5月時点だったので、6月・7月の2か月分をまとめて報告する
    facts = draft.build_month_facts(_history(), election_months=[(2022, 7)], since=(2022, 5))

    assert facts["period_start"] == {"year": 2022, "month": 6}
    assert facts["year"] == 2022 and facts["month"] == 7
    # 差分は期間開始直前(5月)から直近(7月)までの合計
    assert facts["diffs"]["自由民主党"] == 0.55 - 0.4
    # イベント数は6月・7月の合計
    assert facts["n_events"] == 1 + 2
    assert facts["events_in_period"] == ["衆院選"]


def test_build_month_facts_falls_back_to_single_month_when_since_not_older_than_latest(monkeypatch):
    monkeypatch.setattr(national_elections, "compute_election_events", lambda: [])
    monkeypatch.setattr(forecast, "load_forecast_history", lambda: {})
    monkeypatch.setattr(precursor, "load_precursor_table", lambda: [])

    # 前回更新がすでに直近月(7月)そのものだった(同月内の再実行)場合
    facts = draft.build_month_facts(_history(), election_months=[], since=(2022, 7))
    assert facts["period_start"] == {"year": 2022, "month": 7}
    assert facts["diffs"]["自由民主党"] == 0.55 - 0.5  # 直前月との単純差分にフォールバック


def test_build_month_facts_forecast_check_covers_every_month_in_period_with_a_recorded_forecast(monkeypatch):
    monkeypatch.setattr(national_elections, "compute_election_events", lambda: [])
    monkeypatch.setattr(precursor, "load_precursor_table", lambda: [])
    monkeypatch.setattr(
        forecast,
        "load_forecast_history",
        lambda: {"2022-06": {"自由民主党": 0.11}, "2022-07": {"自由民主党": 0.04}},
    )

    facts = draft.build_month_facts(_history(), election_months=[], since=(2022, 5))

    assert set(facts["forecast_check"].keys()) == {"2022-06", "2022-07"}
    assert facts["forecast_check"]["2022-06"]["自由民主党"]["predicted"] == 0.11
    assert facts["forecast_check"]["2022-06"]["自由民主党"]["actual"] == 0.5 - 0.4
    assert facts["forecast_check"]["2022-07"]["自由民主党"]["actual"] == 0.55 - 0.5


def test_build_month_facts_no_diffs_when_history_has_only_one_month(monkeypatch):
    monkeypatch.setattr(national_elections, "compute_election_events", lambda: [])
    monkeypatch.setattr(forecast, "load_forecast_history", lambda: {})
    monkeypatch.setattr(precursor, "load_precursor_table", lambda: [])

    facts = draft.build_month_facts([_history()[0]], election_months=[], since=None)
    assert facts["diffs"] == {}


def test_format_facts_for_prompt_describes_multi_month_period():
    facts = {
        "year": 2022, "month": 7,
        "period_start": {"year": 2022, "month": 6},
        "C_p": {"自由民主党": 0.55},
        "diffs": {"自由民主党": 0.05},
        "n_events": 3,
        "level_weight_share": {"衆院選": 1.0},
        "events_in_period": ["衆院選"],
        "forecast_check": {"2022-07": {"自由民主党": {"predicted": 0.03, "actual": 0.05}}},
        "next_month": {"year": 2022, "month": 8, "will_forecast": False},
        "precursor_summary": {"自由民主党": {"match": 3, "total": 4}},
    }
    text = draft._format_facts_for_prompt(facts)
    assert "2022年6月〜2022年7月" in text
    assert "+0.0500" in text
    assert "衆院選" in text
    assert "3/4" in text
    assert "2022-07" in text


def test_format_facts_for_prompt_single_month_when_period_start_equals_latest():
    facts = {
        "year": 2022, "month": 7,
        "period_start": {"year": 2022, "month": 7},
        "C_p": {}, "diffs": {}, "n_events": 0, "level_weight_share": {},
        "events_in_period": [], "forecast_check": None,
        "next_month": {"year": 2022, "month": 8, "will_forecast": False},
        "precursor_summary": {},
    }
    text = draft._format_facts_for_prompt(facts)
    assert "対象月: 2022年7月" in text


def test_generate_monthly_draft_uses_injected_client_and_extracts_text():
    fake_block = SimpleNamespace(type="text", text="下書き本文")
    fake_message = SimpleNamespace(content=[fake_block])

    calls = {}

    class FakeMessages:
        def create(self, **kwargs):
            calls.update(kwargs)
            return fake_message

    fake_client = SimpleNamespace(messages=FakeMessages())

    facts = {
        "year": 2022, "month": 7, "period_start": {"year": 2022, "month": 7},
        "C_p": {}, "diffs": {}, "n_events": 0,
        "level_weight_share": {}, "events_in_period": [], "forecast_check": None,
        "next_month": {"year": 2022, "month": 8, "will_forecast": False},
        "precursor_summary": {},
    }
    text = draft.generate_monthly_draft(facts, client=fake_client)

    assert text == "下書き本文"
    assert calls["system"] == draft.SYSTEM_PROMPT
    assert "2022年7月更新" in calls["messages"][0]["content"]


def test_save_draft_writes_file_named_by_year_month(tmp_path):
    path = draft.save_draft("本文", 2022, 7, out_dir=tmp_path)
    assert path == tmp_path / "draft_2022-07.md"
    assert path.read_text(encoding="utf-8") == "本文"


def test_save_facts_writes_formatted_text_named_by_year_month(tmp_path):
    facts = {
        "year": 2022, "month": 7, "period_start": {"year": 2022, "month": 7},
        "C_p": {"自由民主党": 0.55},
        "diffs": {"自由民主党": 0.05}, "n_events": 2,
        "level_weight_share": {"衆院選": 1.0}, "events_in_period": ["衆院選"],
        "forecast_check": None,
        "next_month": {"year": 2022, "month": 8, "will_forecast": False},
        "precursor_summary": {},
    }
    path = draft.save_facts(facts, out_dir=tmp_path)
    assert path == tmp_path / "draft_facts_2022-07.txt"
    text = path.read_text(encoding="utf-8")
    assert "自由民主党" in text
    assert "+0.0500" in text


def test_forecast_history_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(forecast, "FORECAST_HISTORY_PATH", tmp_path / "forecast_history.json")
    assert forecast.load_forecast_history() == {}

    forecast.record_forecast(2022, 8, {"自由民主党": 0.02})
    assert forecast.load_forecast_history() == {"2022-08": {"自由民主党": 0.02}}


def test_last_report_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(draft, "LAST_REPORT_PATH", tmp_path / "last_report.json")
    assert draft.load_last_report() is None

    draft.save_last_report(2022, 7)
    assert draft.load_last_report() == (2022, 7)
