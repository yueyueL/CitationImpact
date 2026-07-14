"""Regression tests for round-3 client fixes in clients/hybrid.py and clients/unified.py.

Covers:
1. hybrid.search_paper must record a GS paper's cites_id PER PAPER instead of
   poisoning the client-level gs_cites_id (the client is reused across
   analyses in a session, so a stale cites_id would merge a previous paper's
   Google Scholar citers into later analyses).
2. unified.get_field_normalized_metrics must sanitize commas in the OpenAlex
   title.search filter (commas separate filter clauses and make OpenAlex
   reject the request).
3. unified.search_paper must request externalIds so the analyzer's FWCI DOI
   fast-path receives the paper's DOI.
4. hybrid.get_author_by_s2_id must not stamp match_confidence='id' when the
   unified client fell back to a name-only search.
"""

import pytest

import citationimpact.cache as cache_module
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


def make_author(name='Carol Smith', h_index=7, **kwargs):
    return Author(name=name, h_index=h_index, affiliation='Uni',
                  institution_type='education', **kwargs)


def make_citation(title='Citing Paper', paper_id='S2CIT'):
    return Citation(
        citing_paper_title=title,
        citing_authors=['X Y'],
        venue='ICSE',
        year=2023,
        is_influential=False,
        contexts=[],
        intents=[],
        paper_id=paper_id,
        authors_with_ids=[AuthorInfo(name='X Y', author_id='9')],
    )


class FakeAuthorCache:
    """Stand-in for the persistent AuthorProfileCache."""

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
    monkeypatch.setattr(hybrid_module, 'get_author_cache', lambda: fake)
    monkeypatch.setattr(cache_module, 'get_author_cache', lambda: fake)


class StubCrossrefClient:
    def __init__(self, *args, **kwargs):
        pass

    def search_paper(self, title):
        return None


@pytest.fixture
def stub_crossref(monkeypatch):
    monkeypatch.setattr('citationimpact.clients.crossref.CrossrefClient',
                        StubCrossrefClient)
    return StubCrossrefClient


# ---------------------------------------------------------------------------
# 1. hybrid.search_paper must not poison the client-level gs_cites_id
# ---------------------------------------------------------------------------

class NoneS2:
    def search_paper(self, title):
        return None


class S2WithCitations:
    """S2 stub for a paper found on S2 with its own citations."""

    def search_paper(self, title):
        return {'paperId': 'S2PAPER', 'title': title, 'citationCount': 42}

    def get_citations(self, paper_id, limit=100):
        assert paper_id == 'S2PAPER'
        return [make_citation('S2 Citer Paper')]


class RecordingGS:
    """GS stub that records how citations were requested."""

    def __init__(self):
        self.cites_id_calls = []
        self.search_calls = []

    def search_paper(self, title):
        return {
            'title': 'My GS-Only Paper',
            'paperId': 'gs_abc',
            'citationCount': 50,
            'cites_id': '999',
        }

    def get_citations_by_cites_id(self, cites_ids, limit=100):
        self.cites_id_calls.append(list(cites_ids))
        return [make_citation('GS Citer Of Old Paper', paper_id='')]

    def get_citations(self, paper_id, limit=100):
        self.search_calls.append(paper_id)
        return []


def test_search_paper_gs_fallback_does_not_mutate_client_gs_cites_id():
    gs = RecordingGS()
    client = make_hybrid_client(s2_client=NoneS2(), gs_client=gs,
                                gs_available=True)
    paper = client.search_paper('My GS-Only Paper')
    assert paper['paperId'] == 'gs_abc'
    # Recorded per paper, NOT on the client (reused across analyses)
    assert client._paper_id_to_cites_id['gs_abc'] == ['999']
    assert client.gs_cites_id is None


def test_get_citations_uses_per_paper_cites_id(stub_crossref):
    gs = RecordingGS()
    client = make_hybrid_client(s2_client=NoneS2(), gs_client=gs,
                                gs_available=True)
    client.search_paper('My GS-Only Paper')

    citations = client.get_citations('gs_abc', limit=10)
    assert gs.cites_id_calls == [['999']]  # direct access with THIS paper's id
    assert len(citations) == 1


def test_stale_cites_id_not_reused_for_later_paper(stub_crossref):
    """A GS cites_id from an earlier analysis must not leak into the next one."""
    gs = RecordingGS()
    client = make_hybrid_client(s2_client=S2WithCitations(), gs_client=gs,
                                gs_available=True)
    # Analysis 1: earlier paper found only on GS records its cites_id
    client._paper_id_to_cites_id['gs_abc'] = ['999']
    client._paper_id_to_title['S2PAPER'] = 'A Different Paper'

    # Analysis 2: a different, S2-found paper (client reused across analyses)
    citations = client.get_citations('S2PAPER', limit=10)

    # The old paper's citers were NOT fetched and merged
    assert gs.cites_id_calls == []
    titles = [c.citing_paper_title for c in citations]
    assert 'GS Citer Of Old Paper' not in titles
    assert titles == ['S2 Citer Paper']


def test_constructor_gs_cites_id_still_used_for_my_papers_flow(stub_crossref):
    gs = RecordingGS()
    client = make_hybrid_client(s2_client=S2WithCitations(), gs_client=gs,
                                gs_available=True, gs_cites_id=['777'])
    client.get_citations('S2PAPER', limit=10)
    assert gs.cites_id_calls == [['777']]  # My Papers direct access preserved


# ---------------------------------------------------------------------------
# 2. unified.get_field_normalized_metrics: commas in the title must not break
#    the OpenAlex filter (commas separate filter clauses)
# ---------------------------------------------------------------------------

def test_field_normalized_metrics_sanitizes_commas_in_title_filter(monkeypatch):
    client = UnifiedAPIClient()
    captured = {}

    def fake_make_request(url, params, api):
        captured['url'] = url
        captured['params'] = params
        return {'results': [{
            'title': 'Attention, Please: A Survey of Distraction',
            'fwci': 2.5,
            'citation_normalized_percentile': {
                'value': 97.0,
                'is_in_top_1_percent': False,
                'is_in_top_10_percent': True,
            },
            'cited_by_count': 120,
        }]}

    monkeypatch.setattr(client, '_make_request', fake_make_request)
    result = client.get_field_normalized_metrics(
        'Attention, Please: A Survey of Distraction')

    # The comma must be stripped from the filter value (OpenAlex parses a
    # comma as the start of a second filter clause and rejects the request)
    assert ',' not in captured['params']['filter']
    assert captured['params']['filter'].startswith('title.search:')

    # The normalized exact-title match still finds the comma-containing work
    assert result is not None
    assert result['fwci'] == 2.5
    assert result['citation_percentile'] == 97.0
    assert result['is_top_10_percent'] is True


# ---------------------------------------------------------------------------
# 3. unified.search_paper must request externalIds (FWCI DOI fast-path)
# ---------------------------------------------------------------------------

def test_search_paper_requests_external_ids(monkeypatch):
    client = UnifiedAPIClient()
    captured = {}
    candidate = {
        'paperId': 'x',
        'title': 'Deep Learning Survey',
        'externalIds': {'DOI': '10.1/xyz'},
    }

    def fake_make_request(url, params, api):
        captured['params'] = params
        return {'data': [candidate]}

    monkeypatch.setattr(client, '_make_request', fake_make_request)
    paper = client.search_paper('Deep Learning Survey')

    assert 'externalIds' in captured['params']['fields']
    # The DOI flows through to the analyzer's FWCI fast-path
    assert (paper.get('externalIds') or {}).get('DOI') == '10.1/xyz'


# ---------------------------------------------------------------------------
# 4. hybrid.get_author_by_s2_id: name-search fallback must not be stamped 'id'
# ---------------------------------------------------------------------------

class FallbackS2:
    """Unified-client stub whose ID lookup fell back to a name search."""

    def get_author_by_s2_id(self, author_id, author_name=None):
        # unified.get_author_by_s2_id returns get_author(author_name) when the
        # S2 request fails; that path stamps match_confidence='name'
        return make_author(match_confidence='name')

    def get_author_publications(self, author_id, limit=100):
        return []


class IdResolvedS2:
    def get_author_by_s2_id(self, author_id, author_name=None):
        return make_author(match_confidence='id')

    def get_author_publications(self, author_id, limit=100):
        return []


def test_get_author_by_s2_id_name_fallback_not_stamped_id(monkeypatch):
    fake = FakeAuthorCache(profile=None)
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(s2_client=FallbackS2(), gs_available=False)

    author = client.get_author_by_s2_id('A1', 'Carol Smith')
    assert author is not None
    assert author.match_confidence == 'name'  # NOT 'id': same-name risk
    # The unverified S2 ID is not claimed by the name-matched profile
    assert getattr(author, 'semantic_scholar_id', '') == ''


def test_get_author_by_s2_id_name_fallback_stays_name_on_repeat_lookup(monkeypatch):
    # The memory caches must not re-upgrade the fallback profile to 'id'
    # when the same author is looked up again (common: one author cites
    # the analyzed paper from several papers)
    fake = FakeAuthorCache(profile=None)
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(s2_client=FallbackS2(), gs_available=False)

    first = client.get_author_by_s2_id('A1', 'Carol Smith')
    second = client.get_author_by_s2_id('A1', 'Carol Smith')
    assert first.match_confidence == 'name'
    assert second.match_confidence == 'name'
    # And the fallback profile was not cached under the ID-verified s2: key
    assert 's2:A1' not in client._author_cache


def test_get_author_by_s2_id_genuine_id_resolution_still_stamped_id(monkeypatch):
    fake = FakeAuthorCache(profile=None)
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(s2_client=IdResolvedS2(), gs_available=False)

    author = client.get_author_by_s2_id('A1', 'Carol Smith')
    assert author.match_confidence == 'id'
    assert author.semantic_scholar_id == 'A1'
    assert 's2:A1' in client._author_cache
