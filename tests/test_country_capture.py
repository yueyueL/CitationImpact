"""Regression tests for institution COUNTRY capture (Author.country).

Covers:
- models/data_models.py: Author.country field (string validation, upper() normalization)
- clients/unified.py: country extracted defensively from OpenAlex author JSON
  (get_author / _search_openalex_author / _get_openalex_author_by_affiliation /
  get_author_by_s2_id enrichment); S2-only paths leave country ''
- clients/hybrid.py: merges/enrichment preserve a non-empty country from either
  side (never overwritten by ''), and country round-trips the persistent cache
"""

from unittest.mock import MagicMock

import pytest

import citationimpact.cache as cache_module
import citationimpact.clients.hybrid as hybrid_module
from citationimpact.cache import get_author_cache
from citationimpact.clients.hybrid import HybridAPIClient
from citationimpact.clients.unified import UnifiedAPIClient, _extract_openalex_country
from citationimpact.models import Author


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_hybrid_client(s2_client=None, gs_client=None, gs_available=False,
                       gs_cites_id=None):
    """Build a HybridAPIClient without running __init__ (no network/browser)."""
    client = HybridAPIClient.__new__(HybridAPIClient)
    client.gs_cites_id = gs_cites_id
    client.s2_client = s2_client
    client.gs_client = gs_client
    client.gs_available = gs_available
    client._paper_cache = {}
    client._author_cache = {}
    client._venue_cache = {}
    client._paper_id_to_title = {}
    client._paper_id_to_cites_id = {}
    client.last_sources_used = {}
    return client


def make_author(name='Carol Smith', h_index=7, **kwargs):
    return Author(name=name, h_index=h_index, affiliation='Uni',
                  institution_type='education', **kwargs)


class FakeAuthorCache:
    """Stand-in for the persistent AuthorProfileCache; records lookups."""

    def __init__(self, profile=None, pub_match=None):
        self.profile = profile
        self.pub_match = pub_match
        self.updated = []

    def get_by_any_id(self, **kwargs):
        return self.profile

    def find_by_publications(self, publications, min_overlap=2):
        return self.pub_match

    def update_profile(self, author_info, publications=None):
        self.updated.append((author_info, publications))
        return True


def patch_author_cache(monkeypatch, fake):
    """Patch both the module-level binding and the lazy in-function imports."""
    monkeypatch.setattr(hybrid_module, 'get_author_cache', lambda: fake)
    monkeypatch.setattr(cache_module, 'get_author_cache', lambda: fake)


def gs_cached_profile(**overrides):
    profile = {
        'name': 'Carol Smith',
        'h_index': 20,
        'affiliation': 'Uni',
        'institution_type': 'education',
        'works_count': 40,
        'citation_count': 900,
        'semantic_scholar_id': '',
        'google_scholar_id': '',
        'orcid_id': '',
        'homepage': '',
        'h_index_source': 'google_scholar',
    }
    profile.update(overrides)
    return profile


class StubS2:
    """Configurable stub for the unified S2 client."""

    def __init__(self, author=None, author_by_id=None):
        self.author = author
        self.author_by_id = author_by_id

    def get_author(self, name):
        return self.author

    def get_author_by_s2_id(self, author_id, author_name=None):
        return self.author_by_id

    def get_author_publications(self, author_id, limit=100):
        return []


OPENALEX_AUTHOR = {
    'display_name': 'Jane Doe',
    'summary_stats': {'h_index': 12},
    'works_count': 30,
    'cited_by_count': 800,
    'last_known_institutions': [
        {'display_name': 'University of Toronto', 'type': 'education',
         'country_code': 'ca'},
    ],
}


# ---------------------------------------------------------------------------
# models: Author.country validation and normalization
# ---------------------------------------------------------------------------

def test_author_country_defaults_to_empty_string():
    assert make_author().country == ''


def test_author_country_normalized_to_uppercase():
    assert make_author(country='us').country == 'US'
    assert make_author(country=' de ').country == 'DE'
    assert make_author(country='GB').country == 'GB'
    assert make_author(country='').country == ''


def test_author_country_must_be_string():
    with pytest.raises(ValueError):
        make_author(country=None)
    with pytest.raises(ValueError):
        make_author(country=840)  # numeric ISO code is not accepted


# ---------------------------------------------------------------------------
# unified: _extract_openalex_country (defensive JSON parsing)
# ---------------------------------------------------------------------------

def test_extract_country_from_last_known_institutions():
    assert _extract_openalex_country(OPENALEX_AUTHOR) == 'CA'


def test_extract_country_skips_entries_without_code():
    data = {'last_known_institutions': [
        'not-a-dict',
        {'display_name': 'No Code Uni'},
        {'display_name': 'Coded Uni', 'country_code': 'jp'},
    ]}
    assert _extract_openalex_country(data) == 'JP'


def test_extract_country_falls_back_to_affiliations_institution():
    data = {
        'last_known_institutions': [],
        'affiliations': [
            'not-a-dict',
            {'institution': 'not-a-dict'},
            {'institution': {'display_name': 'KAIST', 'country_code': 'kr'}},
        ],
    }
    assert _extract_openalex_country(data) == 'KR'


def test_extract_country_handles_missing_and_malformed_shapes():
    assert _extract_openalex_country({}) == ''
    assert _extract_openalex_country(None) == ''
    assert _extract_openalex_country('not-a-dict') == ''
    assert _extract_openalex_country({'last_known_institutions': None}) == ''
    # Non-string / blank country codes are ignored
    assert _extract_openalex_country(
        {'last_known_institutions': [{'country_code': None}]}) == ''
    assert _extract_openalex_country(
        {'last_known_institutions': [{'country_code': 123}]}) == ''
    assert _extract_openalex_country(
        {'last_known_institutions': [{'country_code': '  '}]}) == ''


# ---------------------------------------------------------------------------
# unified: OpenAlex-built Authors carry country
# ---------------------------------------------------------------------------

def test_get_author_sets_country_from_openalex(monkeypatch):
    client = UnifiedAPIClient()
    monkeypatch.setattr(client, '_make_request',
                        lambda url, params, api: {'results': [OPENALEX_AUTHOR]})
    author = client.get_author('Jane Doe')
    assert author is not None
    assert author.country == 'CA'  # uppercased from 'ca'


def test_get_author_country_empty_when_openalex_has_none(monkeypatch):
    client = UnifiedAPIClient()
    candidate = {
        'display_name': 'Jane Doe',
        'summary_stats': {'h_index': 12},
        'works_count': 30,
        'cited_by_count': 800,
        'last_known_institutions': [
            {'display_name': 'Mystery Institute', 'type': 'education'},
        ],
    }
    monkeypatch.setattr(client, '_make_request',
                        lambda url, params, api: {'results': [candidate]})
    author = client.get_author('Jane Doe')
    assert author is not None
    assert author.country == ''


def test_get_openalex_author_by_affiliation_sets_country(monkeypatch):
    client = UnifiedAPIClient()
    candidate = {
        'display_name': 'Jane Doe',
        'summary_stats': {'h_index': 12},
        'works_count': 30,
        'cited_by_count': 800,
        'last_known_institutions': [
            {'display_name': 'Stanford University', 'type': 'education',
             'country_code': 'US'},
        ],
    }
    monkeypatch.setattr(client, '_make_request',
                        lambda url, params, api: {'results': [candidate]})
    author = client._get_openalex_author_by_affiliation('Jane Doe',
                                                        'Stanford University')
    assert author is not None
    assert author.country == 'US'
    assert author.match_confidence == 'verified'


def test_get_author_by_s2_id_fills_country_from_openalex(monkeypatch):
    client = UnifiedAPIClient()
    s2_data = {'authorId': '123', 'name': 'Jane Doe', 'hIndex': 5,
               'affiliations': ['MIT'], 'paperCount': 3, 'citationCount': 10}
    monkeypatch.setattr(client, '_make_request',
                        lambda url, params, api: s2_data)
    openalex_mock = MagicMock(return_value=make_author(
        name='Jane Doe', h_index=8, country='US', match_confidence='verified'))
    monkeypatch.setattr(client, '_get_openalex_author_by_affiliation',
                        openalex_mock)

    author = client.get_author_by_s2_id('123')
    assert author is not None
    assert author.country == 'US'
    assert author.match_confidence == 'id'
    openalex_mock.assert_called_once_with('Jane Doe', 'MIT')


def test_get_author_by_s2_id_s2_only_leaves_country_empty(monkeypatch):
    client = UnifiedAPIClient()
    s2_data = {'authorId': '123', 'name': 'Jane Doe', 'hIndex': 5,
               'affiliations': [], 'paperCount': 3, 'citationCount': 10}
    monkeypatch.setattr(client, '_make_request',
                        lambda url, params, api: s2_data)
    # No OpenAlex match at all -> S2-only path
    monkeypatch.setattr(client, 'get_author', MagicMock(return_value=None))

    author = client.get_author_by_s2_id('123')
    assert author is not None
    assert author.country == ''


# ---------------------------------------------------------------------------
# hybrid: merging never drops a non-empty country
# ---------------------------------------------------------------------------

def test_hybrid_get_author_merge_keeps_s2_country_over_empty_gs(monkeypatch):
    # Cached profile provides the GS ID but not a GS h-index (no early return)
    fake = FakeAuthorCache(profile=gs_cached_profile(
        google_scholar_id='G1', h_index_source='semantic_scholar'))
    patch_author_cache(monkeypatch, fake)

    s2 = StubS2(author=make_author(name='Carol Smith', h_index=7, country='US',
                                   match_confidence='name'))
    gs = MagicMock()
    gs.get_author_by_gs_id.return_value = make_author(
        name='Carol Smith', h_index=42, google_scholar_id='G1',
        h_index_source='google_scholar')  # GS side has NO country
    client = make_hybrid_client(s2_client=s2, gs_client=gs, gs_available=True)

    author = client.get_author('Carol Smith')
    assert author is not None
    assert author.h_index == 42                 # GS h-index preferred
    assert author.country == 'US'               # OpenAlex country preserved
    # Persistent cache save carries the country forward
    assert fake.updated[-1][0]['country'] == 'US'


def test_hybrid_get_author_by_s2_id_no_gs_keeps_s2_country(monkeypatch):
    fake = FakeAuthorCache(profile=None)
    patch_author_cache(monkeypatch, fake)
    s2 = StubS2(author_by_id=make_author(name='Carol Smith', h_index=7,
                                         country='JP', match_confidence='id'))
    client = make_hybrid_client(s2_client=s2, gs_available=False)

    author = client.get_author_by_s2_id('123', 'Carol Smith')
    assert author is not None
    assert author.country == 'JP'
    assert fake.updated[-1][0]['country'] == 'JP'


def test_hybrid_get_author_by_s2_id_gs_merge_preserves_country_both_ways(monkeypatch):
    # S2 side has the country, GS side does not
    fake = FakeAuthorCache(profile=gs_cached_profile(
        semantic_scholar_id='123', google_scholar_id='G1',
        h_index_source='semantic_scholar'))
    patch_author_cache(monkeypatch, fake)
    s2 = StubS2(author_by_id=make_author(name='Carol Smith', h_index=7,
                                         country='CN'))
    gs = MagicMock()
    gs.get_author_by_gs_id.return_value = make_author(name='Carol Smith',
                                                      h_index=50)
    client = make_hybrid_client(s2_client=s2, gs_client=gs, gs_available=True)
    author = client.get_author_by_s2_id('123', 'Carol Smith')
    assert author is not None
    assert author.h_index == 50
    assert author.country == 'CN'  # '' from GS must not clobber real code

    # GS side has the country, S2 side does not
    fake2 = FakeAuthorCache(profile=gs_cached_profile(
        semantic_scholar_id='456', google_scholar_id='G2',
        h_index_source='semantic_scholar'))
    patch_author_cache(monkeypatch, fake2)
    s2b = StubS2(author_by_id=make_author(name='Dana Jones', h_index=7))
    gsb = MagicMock()
    gsb.get_author_by_gs_id.return_value = make_author(name='Dana Jones',
                                                       h_index=50, country='NL')
    client2 = make_hybrid_client(s2_client=s2b, gs_client=gsb, gs_available=True)
    author2 = client2.get_author_by_s2_id('456', 'Dana Jones')
    assert author2 is not None
    assert author2.country == 'NL'


# ---------------------------------------------------------------------------
# hybrid: cached-profile rebuilds carry country (and tolerate legacy entries)
# ---------------------------------------------------------------------------

def test_hybrid_get_author_cached_gs_profile_returns_country(monkeypatch):
    fake = FakeAuthorCache(profile=gs_cached_profile(country='de'))
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(gs_available=False)

    author = client.get_author('Carol Smith')
    assert author is not None
    assert author.country == 'DE'  # normalized to uppercase on rebuild


def test_hybrid_get_author_legacy_cache_entry_without_country(monkeypatch):
    # Old cache entries have no 'country' key (and may carry None) - must not crash
    fake = FakeAuthorCache(profile=gs_cached_profile())
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(gs_available=False)
    author = client.get_author('Carol Smith')
    assert author is not None
    assert author.country == ''

    fake2 = FakeAuthorCache(profile=gs_cached_profile(country=None))
    patch_author_cache(monkeypatch, fake2)
    client2 = make_hybrid_client(gs_available=False)
    author2 = client2.get_author('Carol Smith')
    assert author2 is not None
    assert author2.country == ''


def test_hybrid_get_author_by_s2_id_cached_profile_returns_country(monkeypatch):
    fake = FakeAuthorCache(profile=gs_cached_profile(
        semantic_scholar_id='123', country='FR'))
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(gs_available=False)

    author = client.get_author_by_s2_id('123', 'Carol Smith')
    assert author is not None
    assert author.country == 'FR'


def test_hybrid_get_author_by_gs_id_cached_profile_returns_country(monkeypatch):
    fake = FakeAuthorCache(profile=gs_cached_profile(
        google_scholar_id='waVL0PgAAAAJ', country='AU'))
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(gs_available=False)

    author = client.get_author_by_gs_id('waVL0PgAAAAJ')
    assert author is not None
    assert author.country == 'AU'


def test_hybrid_batch_fetch_gs_authors_cached_profile_returns_country(monkeypatch):
    fake = FakeAuthorCache(profile=gs_cached_profile(
        google_scholar_id='G3', country='AU'))
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(gs_available=False)

    results = client.batch_fetch_gs_authors(['G3'])
    assert results['G3'].country == 'AU'


def test_hybrid_get_cached_author_by_name_returns_country(monkeypatch):
    fake = FakeAuthorCache(profile=gs_cached_profile(country='SE'))
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(gs_available=False)

    author = client._get_cached_author_by_name('Carol Smith')
    assert author is not None
    assert author.country == 'SE'


def test_hybrid_get_author_by_paper_publication_match_returns_country(monkeypatch):
    fake = FakeAuthorCache(profile=None,
                           pub_match=gs_cached_profile(country='IT'))
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(gs_available=False)

    author = client.get_author_by_paper('Carol Smith', 'Some Cited Paper')
    assert author is not None
    assert author.country == 'IT'
    assert author.match_confidence == 'verified'


# ---------------------------------------------------------------------------
# hybrid + real persistent cache: country survives a full round trip
# ---------------------------------------------------------------------------

def test_country_round_trips_real_persistent_cache():
    s2 = StubS2(author_by_id=make_author(name='Carol Smith', h_index=7,
                                         country='JP', match_confidence='id',
                                         semantic_scholar_id='777'))
    client = make_hybrid_client(s2_client=s2, gs_available=False)
    author = client.get_author_by_s2_id('777', 'Carol Smith')
    assert author is not None
    assert author.country == 'JP'

    # The real (temp-dir isolated) cache stored the country...
    stored = get_author_cache().get_by_any_id(semantic_scholar_id='777')
    assert stored is not None
    assert stored.get('country') == 'JP'

    # ...and a fresh client rebuilding from that cache keeps it. Mark the
    # entry GS-sourced so the cached fast path is taken (no API client used).
    get_author_cache().update_profile(
        dict(stored, h_index=30, h_index_source='google_scholar'))
    client2 = make_hybrid_client(gs_available=False)
    rebuilt = client2.get_author_by_s2_id('777', 'Carol Smith')
    assert rebuilt is not None
    assert rebuilt.country == 'JP'
