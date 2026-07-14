"""Regression tests for bug fixes in clients/hybrid.py and clients/unified.py."""

import time

import pytest
import requests

import citationimpact.clients.hybrid as hybrid_module
from citationimpact.clients.hybrid import HybridAPIClient
from citationimpact.clients.unified import UnifiedAPIClient
from citationimpact.models import Author, AuthorInfo, Citation


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


class StubCrossrefClient:
    """Stand-in for CrossrefClient; class attribute `result` controls output."""
    result = None

    def __init__(self, *args, **kwargs):
        pass

    def search_paper(self, title):
        return type(self).result


@pytest.fixture
def stub_crossref(monkeypatch):
    StubCrossrefClient.result = None
    monkeypatch.setattr('citationimpact.clients.crossref.CrossrefClient',
                        StubCrossrefClient)
    return StubCrossrefClient


# ---------------------------------------------------------------------------
# unified.py: search_paper must not crash when no candidate overlaps the query
# ---------------------------------------------------------------------------

def test_search_paper_returns_none_when_no_word_overlap(monkeypatch):
    client = UnifiedAPIClient()
    monkeypatch.setattr(client, '_make_request', lambda url, params, api: {
        'data': [{'title': 'Something Else Entirely Different', 'paperId': 'x'}]
    })
    # Non-Latin query shares zero normalized words with the candidate
    assert client.search_paper('机器学习模型研究') is None


def test_search_paper_returns_none_when_query_normalizes_to_empty(monkeypatch):
    client = UnifiedAPIClient()
    monkeypatch.setattr(client, '_make_request', lambda url, params, api: {
        'data': [{'title': 'Some Paper', 'paperId': 'x'}]
    })
    assert client.search_paper('!!! ...') is None


def test_search_paper_low_score_still_returns_best_match(monkeypatch):
    client = UnifiedAPIClient()
    candidate = {'title': 'deep learning survey extras more words here', 'paperId': 'x'}
    monkeypatch.setattr(client, '_make_request',
                        lambda url, params, api: {'data': [candidate]})
    # Some overlap (score > 0 but < 0.5): keep pre-existing behavior of returning it
    assert client.search_paper('deep learning') == candidate


# ---------------------------------------------------------------------------
# unified.py: get_paper_by_id must request externalIds (S2 DOI enrichment)
# ---------------------------------------------------------------------------

def test_get_paper_by_id_requests_external_ids(monkeypatch):
    client = UnifiedAPIClient()
    captured = {}

    def fake_make_request(url, params, api):
        captured['params'] = params
        return {'paperId': 'abc'}

    monkeypatch.setattr(client, '_make_request', fake_make_request)
    assert client.get_paper_by_id('abc') == {'paperId': 'abc'}
    assert 'externalIds' in captured['params']['fields']


# ---------------------------------------------------------------------------
# unified.py: connection errors are retried with backoff
# ---------------------------------------------------------------------------

def test_connection_error_is_retried(monkeypatch):
    client = UnifiedAPIClient(max_retries=3)
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        raise requests.exceptions.ConnectionError('connection reset')

    monkeypatch.setattr(client.session, 'get', fake_get)
    monkeypatch.setattr(time, 'sleep', lambda s: None)

    result = client._make_request('https://example.org', {}, 'semantic_scholar')
    assert result is None
    assert len(calls) == 3  # all retries attempted, not just one
    assert 'connection error' in client.last_error.lower()


# ---------------------------------------------------------------------------
# unified.py: last_error names the API that actually failed
# ---------------------------------------------------------------------------

def test_last_error_names_openalex_on_openalex_timeout(monkeypatch):
    client = UnifiedAPIClient(max_retries=1)

    def fake_get(url, params=None, timeout=None):
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(client.session, 'get', fake_get)
    monkeypatch.setattr(time, 'sleep', lambda s: None)

    assert client._make_request('https://api.openalex.org/authors', {}, 'openalex') is None
    assert 'OpenAlex' in client.last_error
    assert 'Semantic Scholar' not in client.last_error


def test_last_error_names_semantic_scholar_on_s2_timeout(monkeypatch):
    client = UnifiedAPIClient(max_retries=1)

    def fake_get(url, params=None, timeout=None):
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(client.session, 'get', fake_get)
    monkeypatch.setattr(time, 'sleep', lambda s: None)

    assert client._make_request('https://api.semanticscholar.org/x', {}, 'semantic_scholar') is None
    assert 'Semantic Scholar' in client.last_error


# ---------------------------------------------------------------------------
# unified.py: get_author_publications tolerates null citationCount
# ---------------------------------------------------------------------------

def test_get_author_publications_handles_null_citation_count(monkeypatch):
    client = UnifiedAPIClient()
    monkeypatch.setattr(client, '_make_request', lambda url, params, api: {
        'data': [
            {'title': 'new preprint', 'citationCount': None},
            {'title': 'classic paper', 'citationCount': 50},
            {'title': 'mid paper', 'citationCount': 5},
        ]
    })
    papers = client.get_author_publications('A1')
    assert [p['title'] for p in papers] == ['classic paper', 'mid paper', 'new preprint']


# ---------------------------------------------------------------------------
# unified.py: OpenAlex affiliation disambiguation
# ---------------------------------------------------------------------------

def test_openalex_affiliation_match_checks_all_institutions(monkeypatch):
    client = UnifiedAPIClient()
    monkeypatch.setattr(client, '_make_request', lambda url, params, api: {
        'results': [
            {
                'display_name': 'Right Person',
                'last_known_institutions': [
                    {'display_name': 'Harvard Medical School', 'type': 'education'},
                    # Genuine match sits at index 1 - must not be skipped
                    {'display_name': 'Stanford University', 'type': 'education'},
                ],
                'summary_stats': {'h_index': 10},
                'works_count': 5,
                'cited_by_count': 100,
            },
            {
                'display_name': 'Wrong Person',
                # Empty display_name must NOT count as an affiliation match
                'last_known_institutions': [{}],
                'summary_stats': {'h_index': 80},
                'works_count': 500,
                'cited_by_count': 10000,
            },
        ]
    })
    author = client._get_openalex_author_by_affiliation('Some Name', 'Stanford University')
    assert author is not None
    assert author.name == 'Right Person'


# ---------------------------------------------------------------------------
# hybrid.py: module docstring restored (stray '1' removed)
# ---------------------------------------------------------------------------

def test_hybrid_module_docstring_present():
    assert hybrid_module.__doc__ is not None
    assert 'Hybrid API Client' in hybrid_module.__doc__


# ---------------------------------------------------------------------------
# hybrid.py: _merge_author_ids no longer truncates to 5 authors
# ---------------------------------------------------------------------------

def test_merge_author_ids_keeps_all_authors():
    client = make_hybrid_client()
    gs_authors = [AuthorInfo(name=f'Alice Lastname{i}', author_id=f'gs:{i}')
                  for i in range(8)]
    s2_authors = [AuthorInfo(name=f'Alice Lastname{i}', author_id=f'{100 + i}')
                  for i in range(8)]
    merged = client._merge_author_ids(gs_authors, s2_authors)
    assert len(merged) == 8


# ---------------------------------------------------------------------------
# hybrid.py: enhancement must not mark edges influential from the citing
# paper's own influentialCitationCount (and DOI enrichment via S2 works)
# ---------------------------------------------------------------------------

class StubS2ForEnhance:
    def search_paper(self, title):
        return {'title': 'Deep Learning for Code', 'paperId': 'S2X'}

    def get_paper_by_id(self, paper_id):
        return {
            'paperId': 'S2X',
            'title': 'Deep Learning for Code',
            'venue': 'ICSE',
            'year': 2023,
            'citationCount': 100,
            'influentialCitationCount': 20,  # popular citing paper
            'authors': [{'name': 'Alice Bob', 'authorId': '111'}],
            'externalIds': {'DOI': '10.1145/12345'},
        }


def test_enhance_keeps_edge_influential_flag_and_fills_doi(stub_crossref):
    client = make_hybrid_client(s2_client=StubS2ForEnhance())
    gs_citation = Citation(
        citing_paper_title='Deep Learning for Code',
        citing_authors=['Alice Bob'],
        venue='',
        year=0,
        is_influential=False,  # S2 never marked this EDGE influential
        contexts=[],
        intents=[],
    )
    enhanced = client._enhance_citations_with_s2([gs_citation])
    assert len(enhanced) == 1
    result = enhanced[0]
    assert result.is_influential is False  # not inflated by the >5 heuristic
    assert result.influential_citation_count == 20  # paper-level metric kept separately
    assert result.doi == '10.1145/12345'  # externalIds-based DOI enrichment works
    assert result.venue == 'ICSE'


# ---------------------------------------------------------------------------
# hybrid.py: Crossref merge fills venue/year even when a DOI already exists,
# and reads the normalized 'citationCount' key
# ---------------------------------------------------------------------------

class RaisingS2:
    def search_paper(self, title):
        raise AssertionError('S2 search must not run for citations with S2 data')

    def get_paper_by_id(self, paper_id):
        raise AssertionError('S2 lookup must not run for citations with S2 data')

    def get_citations(self, paper_id, limit=100):
        raise AssertionError('S2 citations must not be requested for gs_ paper ids')


def test_crossref_fills_venue_when_doi_already_present(stub_crossref):
    stub_crossref.result = {
        'title': 'A Study of Bugs',
        'doi': '10.9/ignored',
        'venue': 'IEEE Transactions on Software Engineering',
        'year': 2024,
        'citationCount': 57,
    }
    client = make_hybrid_client(s2_client=RaisingS2())
    citation = Citation(
        citing_paper_title='A Study of Bugs',
        citing_authors=['X Y'],
        venue='Unknown',
        year=2023,
        is_influential=False,
        contexts=[],
        intents=[],
        paper_id='S2Y',
        doi='10.1/existing',
        authors_with_ids=[AuthorInfo(name='X Y', author_id='1')],
    )
    enhanced = client._enhance_citations_with_s2([citation])
    result = enhanced[0]
    assert result.venue == 'IEEE Transactions on Software Engineering'
    assert result.doi == '10.1/existing'  # existing DOI preserved
    assert result.year == 2023  # existing year preserved
    assert result.citation_count == 57  # 'citationCount' key read correctly


def test_crossref_fills_missing_doi_and_citation_count(stub_crossref):
    stub_crossref.result = {
        'title': 'A Study of Bugs',
        'doi': '10.2/found',
        'venue': 'FSE',
        'year': 2022,
        'citationCount': 57,
    }
    client = make_hybrid_client(s2_client=RaisingS2())
    citation = Citation(
        citing_paper_title='A Study of Bugs',
        citing_authors=['X Y'],
        venue='Unknown',
        year=0,
        is_influential=False,
        contexts=[],
        intents=[],
        paper_id='S2Y',
        doi='',
        authors_with_ids=[AuthorInfo(name='X Y', author_id='1')],
    )
    enhanced = client._enhance_citations_with_s2([citation])
    result = enhanced[0]
    assert result.doi == '10.2/found'
    assert result.venue == 'FSE'
    assert result.year == 2022
    assert result.citation_count == 57
    assert result.url == 'https://doi.org/10.2/found'


# ---------------------------------------------------------------------------
# hybrid.py: papers found only via Google Scholar yield citations
# ---------------------------------------------------------------------------

class NoneS2:
    def search_paper(self, title):
        return None


class StubGSSearch:
    def search_paper(self, title):
        return {
            'title': 'My GS-Only Paper',
            'paperId': 'gs_abc',
            'citationCount': 50,
            'cites_id': '999',
        }


def test_search_paper_gs_fallback_records_title_and_cites_id():
    client = make_hybrid_client(s2_client=NoneS2(), gs_client=StubGSSearch(),
                                gs_available=True)
    paper = client.search_paper('My GS-Only Paper')
    assert paper['paperId'] == 'gs_abc'
    assert client._paper_id_to_title['gs_abc'] == 'My GS-Only Paper'
    # cites_id is recorded per paper; the client-level gs_cites_id (My Papers
    # constructor arg) must never be mutated - the client is reused across
    # analyses and a stale id would merge another paper's citers
    assert client._paper_id_to_cites_id['gs_abc'] == ['999']
    assert client.gs_cites_id is None


class StubGSCitations:
    def get_citations(self, paper_id, limit=100):
        assert paper_id == 'gs_abc123'
        return [Citation(
            citing_paper_title='Citing Paper',
            citing_authors=['X Y'],
            venue='ICSE',
            year=2023,
            is_influential=False,
            contexts=[],
            intents=[],
            paper_id='S2CIT',
            authors_with_ids=[AuthorInfo(name='X Y', author_id='9')],
        )]


def test_get_citations_for_gs_only_paper_uses_gs_client(stub_crossref):
    client = make_hybrid_client(s2_client=RaisingS2(), gs_client=StubGSCitations(),
                                gs_available=True)
    citations = client.get_citations('gs_abc123', limit=10)
    assert len(citations) == 1
    assert citations[0].citing_paper_title == 'Citing Paper'


# ---------------------------------------------------------------------------
# hybrid.py: ORCID fallback (Strategy 2) in get_author_by_paper
# ---------------------------------------------------------------------------

class S2NotFound:
    def search_paper(self, title):
        return None

    def get_author(self, name):
        return None


class StubORCID:
    def __init__(self, *args, **kwargs):
        pass

    def search_author(self, name, affiliation=None):
        return [{
            'name': 'Jane Doe',
            'orcid_id': '0000-0001-2345-6789',
            'affiliation': 'MIT',
            'affiliation_type': 'University',
            'works_count': 12,
            'profile_url': 'https://orcid.org/0000-0001-2345-6789',
            '_source': 'orcid',
        }]


def test_get_author_by_paper_orcid_fallback_returns_affiliation(monkeypatch):
    monkeypatch.setattr('citationimpact.clients.orcid.ORCIDClient', StubORCID)
    client = make_hybrid_client(s2_client=S2NotFound())
    author = client.get_author_by_paper('Jane Doe', 'Some Obscure Paper')
    assert author is not None
    assert author.name == 'Jane Doe'
    assert author.affiliation == 'MIT'
    assert author.institution_type == 'University'  # mapped from 'affiliation_type'
    assert author.orcid_id == '0000-0001-2345-6789'
    assert author.h_index_source == 'orcid'


# ---------------------------------------------------------------------------
# hybrid.py: get_author_by_paper must not short-circuit paper-based
# disambiguation with a fresh name search
# ---------------------------------------------------------------------------

class S2WithPaper:
    def search_paper(self, title):
        return {'paperId': 'P1', 'title': title}

    def get_paper_by_id(self, paper_id):
        return {'authors': [{'name': 'Carol Smith', 'authorId': 'A9'}]}


def test_get_author_by_paper_prefers_paper_match_over_name_search():
    client = make_hybrid_client(s2_client=S2WithPaper())
    sentinel = Author(name='Carol Smith', h_index=12,
                      affiliation='Small College', institution_type='education')
    client.get_author_by_s2_id = lambda s2_id, name=None: sentinel

    def fail_get_author(name):
        raise AssertionError('name-based get_author must not be called here')

    client.get_author = fail_get_author  # would be hit by the old short-circuit

    result = client.get_author_by_paper('C. Smith', 'Shared Paper Title')
    assert result is sentinel
