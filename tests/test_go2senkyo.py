from bs4 import BeautifulSoup

from seiryoku.fetch import go2senkyo

_CANDIDATE_HTML = """
<table>
  <tr><td class="left red">
    <div class="m_senkyo_result_data">
      <div class="m_senkyo_result_data_ttl">甲<span class="m_senkyo_result_data_kana">こう</span></div>
      <div class="m_senkyo_result_data_circle">自由民主党</div>
    </div>
  </td></tr>
  <tr><td class="left">
    <div class="m_senkyo_result_data">
      <div class="m_senkyo_result_data_ttl">乙<span class="m_senkyo_result_data_kana">おつ</span></div>
      <div class="m_senkyo_result_data_circle">無所属</div>
    </div>
  </td></tr>
</table>
"""

_DISTRICT_LIST_HTML = """
<html><body>
  <a href="/local/senkyo/20194/39762">札幌市選挙区</a>
  <a href="/local/senkyo/20194/39763">函館市選挙区</a>
  <a href="/local/jichitai/1/gikai">議会トップへ戻る</a>
</body></html>
"""


def test_parse_candidates_from_soup_reads_name_party_and_elected_flag():
    soup = BeautifulSoup(_CANDIDATE_HTML, "html.parser")
    candidates = go2senkyo._parse_candidates_from_soup(soup)
    assert candidates == [
        go2senkyo.Candidate(name="甲", party="自由民主党", elected=True),
        go2senkyo.Candidate(name="乙", party="無所属", elected=False),
    ]


def test_district_sub_urls_finds_only_matching_numeric_children():
    soup = BeautifulSoup(_DISTRICT_LIST_HTML, "html.parser")
    urls = go2senkyo._district_sub_urls(soup, "https://go2senkyo.com/local/senkyo/20194")
    assert urls == [
        "https://go2senkyo.com/local/senkyo/20194/39762",
        "https://go2senkyo.com/local/senkyo/20194/39763",
    ]


def test_parse_candidates_falls_back_to_district_pages_when_master_page_is_empty(monkeypatch):
    """都道府県議会議員選挙のように、詳細ページ自体には候補者が無く選挙区ごとの
    下位ページに分かれている場合、それらを合算する([[seiryoku_shisu_design]]参照、
    北海道議会議員選挙(133人)で発覚した問題の回帰テスト)。
    """
    pages = {
        "https://go2senkyo.com/local/senkyo/20194": _DISTRICT_LIST_HTML.encode("utf-8"),
        "https://go2senkyo.com/local/senkyo/20194/39762": _CANDIDATE_HTML.encode("utf-8"),
        "https://go2senkyo.com/local/senkyo/20194/39763": _CANDIDATE_HTML.encode("utf-8"),
    }
    monkeypatch.setattr(go2senkyo, "fetch", lambda url: pages[url])

    candidates = go2senkyo.parse_candidates("https://go2senkyo.com/local/senkyo/20194")

    assert len(candidates) == 4
    assert sum(1 for c in candidates if c.elected) == 2


def test_parse_candidates_uses_master_page_directly_when_it_has_results(monkeypatch):
    """単一選挙区(市区町村)の選挙では下位ページへのフォールバックは発生しない。"""
    def boom(url):
        raise AssertionError(f"下位ページへの不要なリクエスト: {url}")

    monkeypatch.setattr(go2senkyo, "fetch", lambda url: _CANDIDATE_HTML.encode("utf-8") if url == "https://x" else boom(url))

    candidates = go2senkyo.parse_candidates("https://x")
    assert len(candidates) == 2
