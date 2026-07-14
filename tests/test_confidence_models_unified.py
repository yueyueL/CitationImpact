"""Regression tests for Author.match_confidence (data model, unified client,
Google Scholar client) and UnifiedAPIClient.search_author_candidates.

Covers the author-disambiguation upgrade: authors resolved via a unique ID are
tagged 'id', corroborated name searches 'verified', bare name searches 'name'.
"""

import pytest

import citationimpact.clients.google_scholar as gs_module
from citationimpact.clients.google_scholar import GoogleScholarClient
from citationimpact.clients.unified import UnifiedAPIClient
from citationimpact.models import Author


# ---------------------------------------------------------------------------
# Author.match_confidence: field default and validation
# ---------------------------------------------------------------------------

def _make_author(**kwargs):
    return Author(
        name='Jane Roe',
        h_index=10,
        affiliation='Test University',
        institution_type='education',
        **kwargs
    )


def test_author_match_confidence_defaults_to_empty():
    author = _make_author()
    assert author.match_confidence == ''


@pytest.mark.parametrize('value', ['', 'id', 'verified', 'name'])
def test_author_match_confidence_accepts_allowed_values(value):
    author = _make_author(match_confidence=value)
    assert author.match_confidence == value


@pytest.mark.parametrize('value', ['guess', 'ID', 'Verified', 'unknown', None, 5])
def test_author_match_confidence_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        _make_author(match_confidence=value)


# ---------------------------------------------------------------------------
# UnifiedAPIClient: confidence assignment
# ---------------------------------------------------------------------------

OPENALEX_RESULTS = {
    'results': [
        {
            'display_name': 'Jane Roe',
            'last_known_institutions': [
                {'display_name': 'Stanford University', 'type': 'education'},
            ],
            'summary_stats': {'h_index': 25},
            'works_count': 40,
            'cited_by_count': 900,
        },
    ]
}


def test_unified_get_author_name_search_is_name_confidence(monkeypatch):
    client = UnifiedAPIClient()
    monkeypatch.setattr(client, '_make_request',
                        lambda url, params, api: OPENALEX_RESULTS)

    author = client.get_author('Jane Roe')

    assert author is not None
    assert author.match_confidence == 'name'


def test_unified_get_author_by_s2_id_is_id_confidence(monkeypatch):
    client = UnifiedAPIClient()

    def fake_make_request(url, params, api):
        if 'semanticscholar' in url:
            return {
                'authorId': '12345',
                'name': 'Jane Roe',
                'affiliations': ['Stanford University'],
                'paperCount': 40,
                'citationCount': 900,
                'hIndex': 25,
            }
        return OPENALEX_RESULTS

    monkeypatch.setattr(client, '_make_request', fake_make_request)

    author = client.get_author_by_s2_id('12345', 'Jane Roe')

    assert author is not None
    # Even though OpenAlex enrichment ran, the final author is ID-resolved
    assert author.match_confidence == 'id'
    assert author.h_index == 25


def test_unified_get_author_by_s2_id_falls_back_to_name_confidence(monkeypatch):
    """Without an S2 ID the lookup degrades to a name search → 'name'."""
    client = UnifiedAPIClient()
    monkeypatch.setattr(client, '_make_request',
                        lambda url, params, api: OPENALEX_RESULTS)

    author = client.get_author_by_s2_id('', 'Jane Roe')

    assert author is not None
    assert author.match_confidence == 'name'


def test_openalex_affiliation_match_is_verified_confidence(monkeypatch):
    client = UnifiedAPIClient()
    monkeypatch.setattr(client, '_make_request',
                        lambda url, params, api: OPENALEX_RESULTS)

    author = client._get_openalex_author_by_affiliation(
        'Jane Roe', 'Stanford University')

    assert author is not None
    assert author.match_confidence == 'verified'


def test_openalex_affiliation_mismatch_is_name_confidence(monkeypatch):
    """When no candidate's institution matches, the fallback is name-only."""
    client = UnifiedAPIClient()
    monkeypatch.setattr(client, '_make_request',
                        lambda url, params, api: OPENALEX_RESULTS)

    author = client._get_openalex_author_by_affiliation(
        'Jane Roe', 'Completely Unrelated Institute')

    assert author is not None
    assert author.match_confidence == 'name'


def test_openalex_no_institution_candidates_is_name_confidence(monkeypatch):
    """First-result fallback (no candidate had institutions) is name-only."""
    client = UnifiedAPIClient()
    monkeypatch.setattr(client, '_make_request', lambda url, params, api: {
        'results': [
            {
                'display_name': 'Jane Roe',
                'last_known_institutions': [],
                'summary_stats': {'h_index': 5},
                'works_count': 3,
                'cited_by_count': 50,
            },
        ]
    })

    author = client._get_openalex_author_by_affiliation(
        'Jane Roe', 'Stanford University')

    assert author is not None
    assert author.match_confidence == 'name'


# ---------------------------------------------------------------------------
# UnifiedAPIClient.search_author_candidates
# ---------------------------------------------------------------------------

def test_search_author_candidates_maps_s2_response(monkeypatch):
    client = UnifiedAPIClient()
    captured = {}

    def fake_make_request(url, params, api):
        captured['url'] = url
        captured['params'] = params
        captured['api'] = api
        return {
            'data': [
                {
                    'authorId': '111',
                    'name': 'Jane Roe',
                    'affiliations': ['Stanford University', 'MIT'],
                    'hIndex': 25,
                    'paperCount': 40,
                },
                {
                    'authorId': 222,  # non-string IDs must be coerced
                    'name': None,
                    'affiliations': None,
                    'hIndex': None,
                    'paperCount': None,
                },
            ]
        }

    monkeypatch.setattr(client, '_make_request', fake_make_request)

    candidates = client.search_author_candidates('Jane Roe', limit=5)

    assert captured['url'] == 'https://api.semanticscholar.org/graph/v1/author/search'
    assert captured['params']['query'] == 'Jane Roe'
    assert captured['params']['limit'] == 5
    assert captured['params']['fields'] == 'name,affiliations,hIndex,paperCount'
    assert captured['api'] == 'semantic_scholar'

    assert candidates == [
        {
            'author_id': '111',
            'name': 'Jane Roe',
            'affiliation': 'Stanford University',
            'h_index': 25,
            'paper_count': 40,
        },
        {
            'author_id': '222',
            'name': '',
            'affiliation': '',
            'h_index': 0,
            'paper_count': 0,
        },
    ]


def test_search_author_candidates_truncates_to_limit(monkeypatch):
    client = UnifiedAPIClient()
    monkeypatch.setattr(client, '_make_request', lambda url, params, api: {
        'data': [
            {'authorId': str(i), 'name': f'A{i}', 'affiliations': [],
             'hIndex': i, 'paperCount': i}
            for i in range(10)
        ]
    })

    candidates = client.search_author_candidates('Jane Roe', limit=3)

    assert len(candidates) == 3
    assert [c['author_id'] for c in candidates] == ['0', '1', '2']


def test_search_author_candidates_empty_on_failure(monkeypatch):
    client = UnifiedAPIClient()
    monkeypatch.setattr(client, '_make_request', lambda url, params, api: None)
    assert client.search_author_candidates('Jane Roe') == []


def test_search_author_candidates_empty_on_blank_name():
    client = UnifiedAPIClient()
    assert client.search_author_candidates('') == []
    assert client.search_author_candidates('   ') == []


# ---------------------------------------------------------------------------
# GoogleScholarClient: confidence assignment
# ---------------------------------------------------------------------------

bs4 = pytest.importorskip('bs4')


class FakeDriver:
    """Minimal stand-in for a Selenium WebDriver."""

    def __init__(self, pages=None, default_page='<html><body></body></html>'):
        self.pages = pages or {}  # substring of URL -> page_source
        self.default_page = default_page
        self.page_source = default_page
        self.current_url = 'about:blank'
        self.visited = []

    def get(self, url):
        self.visited.append(url)
        self.current_url = url
        for key, html in self.pages.items():
            if key in url:
                self.page_source = html
                return
        self.page_source = self.default_page

    def quit(self):
        pass


def _no_sleep(monkeypatch):
    monkeypatch.setattr(gs_module.time, 'sleep', lambda *a, **k: None)


PROFILE_PAGE = """
<html><body>
  <div id="gsc_prf_in">Jane Roe</div>
  <div class="gsc_prf_il">Test University</div>
  <table id="gsc_rsb_st">
    <tr><td>Citations</td><td>12345</td><td>6789</td></tr>
    <tr><td>h-index</td><td>42</td><td>30</td></tr>
  </table>
</body></html>
"""

AUTHOR_SEARCH_PAGE = """
<html><body>
  <div class="gs_r gs_or gs_scl" data-rp="0">
    <div class="gs_ri">
      <h3 class="gs_rt"><a href="/p1">Paper By Jane Roe</a></h3>
      <div class="gs_a"><a href="/citations?user=RIGHTID&amp;hl=en">J Roe</a> - Venue B, 2020</div>
    </div>
  </div>
</body></html>
"""


def test_gs_get_author_by_gs_id_is_id_confidence(monkeypatch):
    _no_sleep(monkeypatch)
    client = GoogleScholarClient()
    driver = FakeDriver(default_page=PROFILE_PAGE)
    monkeypatch.setattr(client, '_get_driver', lambda: driver)

    author = client.get_author_by_gs_id('RIGHTID', 'Jane Roe')

    assert author is not None
    assert author.match_confidence == 'id'
    assert author.google_scholar_id == 'RIGHTID'


def test_gs_batch_fetch_is_id_confidence(monkeypatch):
    _no_sleep(monkeypatch)
    client = GoogleScholarClient()
    driver = FakeDriver(default_page=PROFILE_PAGE)
    monkeypatch.setattr(client, '_get_driver', lambda: driver)

    results = client.get_authors_by_gs_ids_batch(['ID1', 'ID2'])

    assert set(results.keys()) == {'ID1', 'ID2'}
    for author in results.values():
        assert author.match_confidence == 'id'


def test_gs_get_author_via_browser_is_name_confidence(monkeypatch):
    _no_sleep(monkeypatch)
    client = GoogleScholarClient()
    driver = FakeDriver(pages={
        'scholar?q=author:': AUTHOR_SEARCH_PAGE,
        'citations?user=RIGHTID': PROFILE_PAGE,
    })
    monkeypatch.setattr(client, '_get_driver', lambda: driver)

    author = client._get_author_via_browser('Jane Roe')

    assert author is not None
    # Found via name search - the profile may belong to a same-named person
    assert author.match_confidence == 'name'


def test_gs_get_author_scholarly_fallback_is_name_confidence(monkeypatch):
    _no_sleep(monkeypatch)

    class FakeScholarly:
        def search_author(self, name):
            return iter([{'name': 'Jane Roe', 'scholar_id': 'XYZ'}])

        def fill(self, author, **kwargs):
            author.update({
                'hindex': 30,
                'affiliation': 'Test University',
                'homepage': '',
                'citedby': 12000,
                'publications': [{'n': 1}],
            })
            return author

    monkeypatch.setattr(gs_module, 'scholarly', FakeScholarly())
    client = GoogleScholarClient(use_selenium=False)

    author = client.get_author('Jane Roe')

    assert author is not None
    assert author.match_confidence == 'name'
