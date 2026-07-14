"""Regression tests for author match_confidence handling in clients/hybrid.py.

Covers the author-disambiguation upgrade: every Author produced by
HybridAPIClient must carry a match_confidence level ('id' > 'verified' >
'name' > ''), name-only cache lookups must be corroborated with
verify_titles when a paper title is available, and the client must expose
a search_author_candidates passthrough.
"""

import pytest

import citationimpact.cache as cache_module
import citationimpact.clients.hybrid as hybrid_module
from citationimpact.clients.hybrid import (
    HybridAPIClient,
    _apply_confidence,
    _confidence_rank,
    _highest_confidence,
    _normalize_name,
)
from citationimpact.models import Author, AuthorInfo


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
        self.get_by_any_id_calls = []
        self.find_by_publications_calls = []
        self.updated = []

    def get_by_any_id(self, **kwargs):
        self.get_by_any_id_calls.append(kwargs)
        return self.profile

    def find_by_publications(self, publications, min_overlap=2):
        self.find_by_publications_calls.append((publications, min_overlap))
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

    def __init__(self, author=None, author_by_id=None, paper=None,
                 detailed=None, candidates=None):
        self.author = author
        self.author_by_id = author_by_id
        self.paper = paper
        self.detailed = detailed
        self.candidates = candidates
        self.candidate_calls = []

    def get_author(self, name):
        return self.author

    def get_author_by_s2_id(self, author_id, author_name=None):
        return self.author_by_id

    def get_author_publications(self, author_id, limit=100):
        return []

    def search_paper(self, title):
        return self.paper

    def get_paper_by_id(self, paper_id):
        return self.detailed

    def search_author_candidates(self, author_name, limit=5):
        self.candidate_calls.append((author_name, limit))
        return self.candidates or []


class StubGS:
    def __init__(self, author=None):
        self.author = author
        self.calls = []

    def get_author_by_gs_id(self, gs_id):
        self.calls.append(gs_id)
        return self.author

    def get_authors_by_gs_ids_batch(self, gs_ids):
        return {gs_id: self.author for gs_id in gs_ids if self.author}

    def close(self):
        pass


class StubORCIDEmpty:
    def __init__(self, *args, **kwargs):
        pass

    def search_author(self, name, affiliation=None):
        return []


class StubORCIDHit:
    def __init__(self, *args, **kwargs):
        pass

    def search_author(self, name, affiliation=None):
        return [{
            'name': 'Jane Doe',
            'orcid_id': '0000-0001-2345-6789',
            'affiliation': 'MIT',
            'affiliation_type': 'University',
            'works_count': 12,
        }]


# ---------------------------------------------------------------------------
# Confidence helpers
# ---------------------------------------------------------------------------

def test_confidence_rank_ordering():
    assert (_confidence_rank('id') > _confidence_rank('verified')
            > _confidence_rank('name') > _confidence_rank(''))
    assert _confidence_rank(None) == 0
    assert _confidence_rank('bogus') == 0  # unknown values rank lowest


def test_highest_confidence_picks_strongest():
    assert _highest_confidence('name', 'id', 'verified') == 'id'
    assert _highest_confidence('', 'name') == 'name'
    assert _highest_confidence() == ''


def test_apply_confidence_keeps_highest_by_default():
    author = make_author(match_confidence='id')
    _apply_confidence(author, 'name')
    assert author.match_confidence == 'id'  # never downgraded without override

    author2 = make_author(match_confidence='name')
    _apply_confidence(author2, 'verified')
    assert author2.match_confidence == 'verified'


def test_apply_confidence_override_downgrades():
    author = make_author(match_confidence='id')
    _apply_confidence(author, 'verified', override=True)
    assert author.match_confidence == 'verified'


def test_apply_confidence_handles_none_author():
    assert _apply_confidence(None, 'id') is None


# ---------------------------------------------------------------------------
# search_author_candidates passthrough
# ---------------------------------------------------------------------------

def test_search_author_candidates_delegates_to_s2():
    candidates = [{'author_id': '123', 'name': 'Carol Smith',
                   'affiliation': 'Uni', 'h_index': 7, 'paper_count': 40}]
    s2 = StubS2(candidates=candidates)
    client = make_hybrid_client(s2_client=s2)
    assert client.search_author_candidates('Carol Smith', limit=3) == candidates
    assert s2.candidate_calls == [('Carol Smith', 3)]


def test_search_author_candidates_returns_empty_on_failure():
    class BrokenS2:
        def search_author_candidates(self, name, limit=5):
            raise RuntimeError('boom')

    client = make_hybrid_client(s2_client=BrokenS2())
    assert client.search_author_candidates('Carol Smith') == []

    # Also safe if the underlying client lacks the method entirely
    client2 = make_hybrid_client(s2_client=object())
    assert client2.search_author_candidates('Carol Smith') == []


# ---------------------------------------------------------------------------
# get_author_by_gs_id / batch_fetch_gs_authors -> 'id'
# ---------------------------------------------------------------------------

def test_get_author_by_gs_id_fresh_fetch_is_id(monkeypatch):
    fake = FakeAuthorCache(profile=None)
    patch_author_cache(monkeypatch, fake)
    gs = StubGS(author=make_author(h_index=30))
    client = make_hybrid_client(gs_client=gs, gs_available=True)

    author = client.get_author_by_gs_id('waVL0PgAAAAJ')
    assert author is not None
    assert author.match_confidence == 'id'


def test_get_author_by_gs_id_cache_rebuild_is_id(monkeypatch):
    fake = FakeAuthorCache(profile=gs_cached_profile(google_scholar_id='waVL0PgAAAAJ'))
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(gs_available=False)

    author = client.get_author_by_gs_id('waVL0PgAAAAJ')
    assert author is not None
    assert author.match_confidence == 'id'
    # Lookup used the real GS ID
    assert fake.get_by_any_id_calls[0].get('google_scholar_id') == 'waVL0PgAAAAJ'


def test_batch_fetch_gs_authors_cache_and_fresh_are_id(monkeypatch):
    fake = FakeAuthorCache(profile=None)
    patch_author_cache(monkeypatch, fake)
    gs = StubGS(author=make_author(name='Fresh Person', h_index=12))
    client = make_hybrid_client(gs_client=gs, gs_available=True)

    results = client.batch_fetch_gs_authors(['g1'])
    assert results['g1'].match_confidence == 'id'

    # Cached variant (no GS client needed)
    fake2 = FakeAuthorCache(profile=gs_cached_profile())
    patch_author_cache(monkeypatch, fake2)
    client2 = make_hybrid_client(gs_available=False)
    results2 = client2.batch_fetch_gs_authors(['g2'])
    assert results2['g2'].match_confidence == 'id'


# ---------------------------------------------------------------------------
# get_author_by_s2_id -> 'id' (real-ID resolution)
# ---------------------------------------------------------------------------

def test_get_author_by_s2_id_fresh_fetch_is_id(monkeypatch):
    fake = FakeAuthorCache(profile=None)
    patch_author_cache(monkeypatch, fake)
    s2 = StubS2(author_by_id=make_author())
    client = make_hybrid_client(s2_client=s2, gs_available=False)

    author = client.get_author_by_s2_id('A1', 'Carol Smith')
    assert author is not None
    assert author.match_confidence == 'id'


def test_get_author_by_s2_id_cache_rebuild_id_match(monkeypatch):
    fake = FakeAuthorCache(profile=gs_cached_profile(semantic_scholar_id='A1'))
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(gs_available=False)

    author = client.get_author_by_s2_id('A1', 'Carol Smith')
    assert author.match_confidence == 'id'


def test_get_author_by_s2_id_cache_rebuild_name_only_hit_is_name(monkeypatch):
    # Cached entry has NO matching S2 ID: it could only have matched by name
    fake = FakeAuthorCache(profile=gs_cached_profile(semantic_scholar_id=''))
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(gs_available=False)

    author = client.get_author_by_s2_id('A1', 'Carol Smith')
    assert author.match_confidence == 'name'  # same-name person risk


def test_get_author_by_s2_id_memory_name_hit_upgraded_when_id_matches():
    client = make_hybrid_client(gs_available=False)
    cached = make_author(semantic_scholar_id='A1', match_confidence='name')
    client._author_cache[f"name:{_normalize_name('Carol Smith')}"] = cached

    result = client.get_author_by_s2_id('A1', 'Carol Smith')
    assert result is cached
    assert result.match_confidence == 'id'  # ID-confirmed


def test_get_author_by_s2_id_memory_name_hit_not_upgraded_on_id_mismatch():
    client = make_hybrid_client(gs_available=False)
    cached = make_author(semantic_scholar_id='OTHER', match_confidence='name')
    client._author_cache[f"name:{_normalize_name('Carol Smith')}"] = cached

    result = client.get_author_by_s2_id('A1', 'Carol Smith')
    assert result is cached
    assert result.match_confidence == 'name'


def test_get_author_by_s2_id_memory_id_hit_restamps_id():
    # A shared object downgraded elsewhere is re-upgraded on a real ID lookup
    client = make_hybrid_client(gs_available=False)
    cached = make_author(semantic_scholar_id='A9', match_confidence='verified')
    client._author_cache['s2:A9'] = cached

    result = client.get_author_by_s2_id('A9')
    assert result is cached
    assert result.match_confidence == 'id'


# ---------------------------------------------------------------------------
# get_author (name search) -> 'name' / 'verified'
# ---------------------------------------------------------------------------

def test_get_author_s2_name_search_is_name(monkeypatch):
    fake = FakeAuthorCache(profile=None)
    patch_author_cache(monkeypatch, fake)
    s2 = StubS2(author=make_author())
    client = make_hybrid_client(s2_client=s2, gs_available=False)

    author = client.get_author('Carol Smith')
    assert author is not None
    assert author.match_confidence == 'name'
    # No context title -> no verify_titles passed to the cache
    assert 'verify_titles' not in fake.get_by_any_id_calls[0]


def test_get_author_keeps_higher_confidence_from_unified_client(monkeypatch):
    # If the unified client already corroborated (e.g. affiliation-verified
    # cache match), the hybrid client must not downgrade it to 'name'
    fake = FakeAuthorCache(profile=None)
    patch_author_cache(monkeypatch, fake)
    s2 = StubS2(author=make_author(match_confidence='verified'))
    client = make_hybrid_client(s2_client=s2, gs_available=False)

    author = client.get_author('Carol Smith')
    assert author.match_confidence == 'verified'


def test_get_author_cache_rebuild_without_context_is_name(monkeypatch):
    fake = FakeAuthorCache(profile=gs_cached_profile())
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(gs_available=False)

    author = client.get_author('Carol Smith')
    assert author is not None
    assert author.match_confidence == 'name'


def test_get_author_with_context_title_passes_verify_titles(monkeypatch):
    fake = FakeAuthorCache(profile=gs_cached_profile())
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(gs_available=False)

    author = client.get_author('Carol Smith', context_title='The Citing Paper')
    assert author is not None
    assert author.match_confidence == 'verified'  # corroborated by the title
    assert fake.get_by_any_id_calls[0].get('verify_titles') == ['The Citing Paper']


def test_get_author_merged_s2_gs_confidence_capped_at_name_level(monkeypatch):
    # GS profile fetched via an ID that came from a NAME-keyed cache entry:
    # the merged author must stay at name-search confidence, not 'id'
    fake = FakeAuthorCache(profile=gs_cached_profile(
        google_scholar_id='gsX', h_index_source='semantic_scholar'))
    patch_author_cache(monkeypatch, fake)
    s2 = StubS2(author=make_author(semantic_scholar_id='S9'))
    gs = StubGS(author=make_author(name='Carol Smith', h_index=33,
                                   match_confidence='id'))
    client = make_hybrid_client(s2_client=s2, gs_client=gs, gs_available=True)

    author = client.get_author('Carol Smith')
    assert author is not None
    assert author.h_index == 33  # GS h-index preferred
    assert author.match_confidence == 'name'


def test_get_author_gs_only_branch_capped_and_source_object_untouched(monkeypatch):
    fake = FakeAuthorCache(profile=gs_cached_profile(
        google_scholar_id='gsX', h_index_source='semantic_scholar'))
    patch_author_cache(monkeypatch, fake)
    gs_profile = make_author(name='Carol Smith', h_index=33, match_confidence='id')
    client = make_hybrid_client(s2_client=StubS2(author=None),
                                gs_client=StubGS(author=gs_profile),
                                gs_available=True)

    author = client.get_author('Carol Smith')
    assert author is not None
    assert author.match_confidence == 'name'  # capped: name-derived association
    # The GS client's own object was not downgraded (copy was stamped)
    assert gs_profile.match_confidence == 'id'


# ---------------------------------------------------------------------------
# get_author_by_paper -> 'verified' / 'name'
# ---------------------------------------------------------------------------

class S2WithPaper:
    def search_paper(self, title):
        return {'paperId': 'P1', 'title': title}

    def get_paper_by_id(self, paper_id):
        return {'authors': [{'name': 'Carol Smith', 'authorId': 'A9'}]}


def test_get_author_by_paper_membership_match_is_verified(monkeypatch):
    fake = FakeAuthorCache(profile=None, pub_match=None)
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(s2_client=S2WithPaper())
    sentinel = make_author(match_confidence='id')  # as stamped by get_author_by_s2_id
    client.get_author_by_s2_id = lambda s2_id, name=None: sentinel

    result = client.get_author_by_paper('C. Smith', 'Shared Paper Title')
    assert result is sentinel  # identity preserved (in-place stamp)
    # Publication-membership check passed, but the ID was derived via a
    # title search + name match, NOT taken from the citation itself
    assert result.match_confidence == 'verified'


def test_get_author_by_paper_checks_cache_with_verify_titles(monkeypatch):
    fake = FakeAuthorCache(profile=gs_cached_profile())
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(s2_client=StubS2())

    result = client.get_author_by_paper('Carol Smith', 'Shared Paper Title')
    assert result is not None
    assert result.match_confidence == 'verified'
    assert fake.get_by_any_id_calls[0].get('verify_titles') == ['Shared Paper Title']


def test_get_author_by_paper_publication_overlap_is_verified(monkeypatch):
    fake = FakeAuthorCache(profile=None,
                           pub_match=gs_cached_profile(name='Chakkrit T', h_index=15))
    patch_author_cache(monkeypatch, fake)
    monkeypatch.setattr('citationimpact.clients.orcid.ORCIDClient', StubORCIDEmpty)
    client = make_hybrid_client(s2_client=StubS2())  # no paper found on S2

    result = client.get_author_by_paper('C. T', 'Shared Paper Title')
    assert result is not None
    assert result.name == 'Chakkrit T'
    assert result.match_confidence == 'verified'


def test_get_author_by_paper_orcid_fallback_is_name(monkeypatch):
    fake = FakeAuthorCache(profile=None, pub_match=None)
    patch_author_cache(monkeypatch, fake)
    monkeypatch.setattr('citationimpact.clients.orcid.ORCIDClient', StubORCIDHit)
    client = make_hybrid_client(s2_client=StubS2())

    result = client.get_author_by_paper('Jane Doe', 'Some Obscure Paper')
    assert result is not None
    assert result.orcid_id == '0000-0001-2345-6789'
    assert result.match_confidence == 'name'  # ORCID hit was name-search based


def test_get_author_by_paper_bare_name_fallback_is_name(monkeypatch):
    fake = FakeAuthorCache(profile=None, pub_match=None)
    patch_author_cache(monkeypatch, fake)
    monkeypatch.setattr('citationimpact.clients.orcid.ORCIDClient', StubORCIDEmpty)
    client = make_hybrid_client(s2_client=StubS2(author=make_author(name='Zed')))

    result = client.get_author_by_paper('Zed', 'Unknown Paper')
    assert result is not None
    assert result.match_confidence == 'name'  # fell through to bare name search


def test_get_author_by_paper_s2_helper_is_verified(monkeypatch):
    fake = FakeAuthorCache(profile=None)
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client(s2_client=S2WithPaper())
    sentinel = make_author(match_confidence='id')
    client.get_author_by_s2_id = lambda s2_id, name=None: sentinel

    result = client._get_author_by_paper_s2('Carol Smith', 'Shared Paper Title')
    assert result is sentinel
    assert result.match_confidence == 'verified'


# ---------------------------------------------------------------------------
# _get_cached_author_by_name verify_title plumbing
# ---------------------------------------------------------------------------

def test_cached_author_by_name_with_verify_title(monkeypatch):
    fake = FakeAuthorCache(profile=gs_cached_profile())
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client()

    author = client._get_cached_author_by_name('Carol Smith', verify_title='A Paper')
    assert author is not None
    assert author.match_confidence == 'verified'
    assert fake.get_by_any_id_calls[0].get('verify_titles') == ['A Paper']


def test_cached_author_by_name_without_verify_title(monkeypatch):
    fake = FakeAuthorCache(profile=gs_cached_profile())
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client()

    author = client._get_cached_author_by_name('Carol Smith')
    assert author is not None
    assert author.match_confidence == 'name'
    assert 'verify_titles' not in fake.get_by_any_id_calls[0]


# ---------------------------------------------------------------------------
# _merge_author_ids verify_titles plumbing
# ---------------------------------------------------------------------------

def test_merge_author_ids_passes_verify_titles_when_title_known(monkeypatch):
    fake = FakeAuthorCache(profile=None)
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client()

    gs_authors = [AuthorInfo(name='Alice Wong', author_id='gs:AW')]
    s2_authors = [AuthorInfo(name='Bob Chen', author_id='B1')]  # unmatched -> cache lookup
    merged = client._merge_author_ids(gs_authors, s2_authors,
                                      paper_title='The Citing Paper')
    assert len(merged) == 2
    assert fake.get_by_any_id_calls[0].get('verify_titles') == ['The Citing Paper']


def test_merge_author_ids_backward_compatible_without_title(monkeypatch):
    fake = FakeAuthorCache(profile=None)
    patch_author_cache(monkeypatch, fake)
    client = make_hybrid_client()

    gs_authors = [AuthorInfo(name='Alice Wong', author_id='gs:AW')]
    s2_authors = [AuthorInfo(name='Bob Chen', author_id='B1')]
    merged = client._merge_author_ids(gs_authors, s2_authors)
    assert len(merged) == 2
    assert 'verify_titles' not in fake.get_by_any_id_calls[0]
