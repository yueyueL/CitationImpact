"""Regression tests for author match-confidence tracking in the analyzer.

Bug: author search was name-based, so citations by a same-named different
person could be attributed to the wrong profile. The analyzer now records
HOW each author profile was matched ('id' / 'verified' / 'name' / '') and
verifies name-only persistent-cache hits against the citing paper title.
"""

import pytest

from citationimpact.cache import get_author_cache
from citationimpact.core.analyzer import CitationImpactAnalyzer, _confidence_rank
from citationimpact.models import Author, AuthorInfo, Citation


# ---------------------------------------------------------------------------
# Offline client stubs
# ---------------------------------------------------------------------------

class FakeClient:
    """Minimal offline API-client stub (name + GS-ID lookups only)."""

    def __init__(self, paper=None, citations=None, authors_by_name=None,
                 authors_by_gs_id=None):
        self.paper = paper
        self.citations = citations or []
        self.authors_by_name = authors_by_name or {}
        self.authors_by_gs_id = authors_by_gs_id or {}
        self.gs_id_calls = []
        self.last_error = None

    def search_paper(self, title):
        return self.paper

    def get_citations(self, paper_id, limit=100):
        return self.citations

    def get_author(self, name):
        return self.authors_by_name.get(name)

    def get_author_by_gs_id(self, gs_id, name):
        self.gs_id_calls.append((gs_id, name))
        return self.authors_by_gs_id.get(gs_id)

    def get_venue(self, name):
        return None

    def categorize_institution(self, institution_type, affiliation):
        if institution_type in ('University', 'Industry', 'Government'):
            return institution_type
        return 'Other'


class S2Client(FakeClient):
    """Adds an S2 author-ID lookup."""

    def __init__(self, authors_by_s2_id=None, **kwargs):
        super().__init__(**kwargs)
        self.authors_by_s2_id = authors_by_s2_id or {}
        self.s2_id_calls = []

    def get_author_by_s2_id(self, s2_id, name):
        self.s2_id_calls.append((s2_id, name))
        return self.authors_by_s2_id.get(s2_id)


class PaperSearchClient(FakeClient):
    """Adds a get_author_by_paper lookup."""

    def __init__(self, authors_by_paper=None, **kwargs):
        super().__init__(**kwargs)
        self.authors_by_paper = authors_by_paper or {}
        self.paper_calls = []

    def get_author_by_paper(self, name, paper_title):
        self.paper_calls.append((name, paper_title))
        return self.authors_by_paper.get(name)


class ContextTitleClient(FakeClient):
    """get_author accepts context_title (like HybridAPIClient)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.context_calls = []

    def get_author(self, name, context_title=None):
        self.context_calls.append((name, context_title))
        return self.authors_by_name.get(name)


def make_citation(title, authors, authors_with_ids=None, year=2020):
    return Citation(
        citing_paper_title=title,
        citing_authors=authors,
        venue='Some Venue',
        year=year,
        is_influential=False,
        contexts=[],
        intents=[],
        authors_with_ids=authors_with_ids,
    )


def make_author(name='Alice Smith', h_index=10, affiliation='MIT', **kwargs):
    return Author(name=name, h_index=h_index, affiliation=affiliation,
                  institution_type='University', **kwargs)


CITING_TITLE = 'A study of automated program repair techniques in practice'


# ---------------------------------------------------------------------------
# Confidence ranking helper
# ---------------------------------------------------------------------------

def test_confidence_rank_ordering():
    assert (_confidence_rank('id') > _confidence_rank('verified')
            > _confidence_rank('name') > _confidence_rank(''))
    # Unknown / garbage values rank lowest, like ''
    assert _confidence_rank('bogus') == _confidence_rank('')
    assert _confidence_rank(None) == _confidence_rank('')


# ---------------------------------------------------------------------------
# PRIORITY 1: GS ID straight from the citation -> 'id'
# ---------------------------------------------------------------------------

def test_gs_id_from_citation_marks_id():
    alice = make_author(google_scholar_id='ALICE9')
    api = FakeClient(authors_by_gs_id={'ALICE9': alice})
    citations = [make_citation(
        CITING_TITLE, ['Alice Smith'],
        authors_with_ids=[AuthorInfo(name='Alice Smith', author_id='gs:ALICE9')],
    )]
    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)
    assert data['all_authors'][0]['match_confidence'] == 'id'


# ---------------------------------------------------------------------------
# PRIORITY 2: persistent-cache lookups
# ---------------------------------------------------------------------------

def test_cache_name_hit_verified_by_citing_title():
    # Cached Alice's profile contains the citing paper -> trustworthy
    author_cache = get_author_cache()
    author_cache.update_profile(
        {'name': 'Alice Smith', 'google_scholar_id': 'ALICE9',
         'h_index': 22, 'affiliation': 'CMU', 'institution_type': 'University'},
        publications=[{'title': CITING_TITLE}],
    )
    alice = make_author(h_index=22, affiliation='CMU', google_scholar_id='ALICE9')
    api = FakeClient(authors_by_gs_id={'ALICE9': alice})
    citations = [make_citation(CITING_TITLE, ['Alice Smith'])]
    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)
    assert api.gs_id_calls == [('ALICE9', 'Alice Smith')]
    assert data['all_authors'][0]['match_confidence'] == 'verified'


def test_cache_name_hit_without_title_overlap_is_rejected():
    # A DIFFERENT researcher who happens to share the name is cached with
    # unrelated publications: her GS profile must NOT be adopted.
    author_cache = get_author_cache()
    author_cache.update_profile(
        {'name': 'Alice Smith', 'google_scholar_id': 'OTHER1',
         'h_index': 60, 'affiliation': 'Oxford', 'institution_type': 'University'},
        publications=[{'title': 'Deep learning methods for protein structure prediction'}],
    )
    plain_alice = make_author(h_index=5)
    api = FakeClient(authors_by_name={'Alice Smith': plain_alice})
    citations = [make_citation(CITING_TITLE, ['Alice Smith'])]
    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)
    # The cached same-named profile was never fetched
    assert api.gs_id_calls == []
    entry = data['all_authors'][0]
    assert entry['h_index'] == 5  # fell through to plain name lookup
    assert entry['match_confidence'] == 'name'


def test_cache_hit_via_s2_id_marks_id():
    author_cache = get_author_cache()
    author_cache.update_profile(
        {'name': 'Alice Smith', 'google_scholar_id': 'ALICE9',
         'semantic_scholar_id': 'S123', 'h_index': 22,
         'affiliation': 'CMU', 'institution_type': 'University'},
        publications=[{'title': 'Some unrelated cached publication title here'}],
    )
    alice = make_author(google_scholar_id='ALICE9', semantic_scholar_id='S123')
    api = FakeClient(authors_by_gs_id={'ALICE9': alice})
    citations = [make_citation(
        CITING_TITLE, ['Alice Smith'],
        authors_with_ids=[AuthorInfo(name='Alice Smith', author_id='s2:S123')],
    )]
    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)
    # Matched through the real S2 ID (title overlap not required)
    assert data['all_authors'][0]['match_confidence'] == 'id'


def test_cache_publication_match_marks_verified(monkeypatch):
    author_cache = get_author_cache()
    alice_info = {'name': 'Alice Smith', 'google_scholar_id': 'ALICE9',
                  'h_index': 22, 'affiliation': 'CMU',
                  'institution_type': 'University'}
    monkeypatch.setattr(author_cache, 'find_by_publications',
                        lambda publications, min_overlap=2: alice_info)
    alice = make_author(google_scholar_id='ALICE9')
    api = FakeClient(authors_by_gs_id={'ALICE9': alice})
    citations = [make_citation(CITING_TITLE, ['A. Smith'])]
    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)
    assert data['all_authors'][0]['match_confidence'] == 'verified'


# ---------------------------------------------------------------------------
# PRIORITY 3: S2 author ID -> 'id', but honor client fallback stamps
# ---------------------------------------------------------------------------

def test_s2_id_lookup_marks_id():
    alice = make_author(match_confidence='id')
    api = S2Client(authors_by_s2_id={'S123': alice})
    citations = [make_citation(
        CITING_TITLE, ['Alice Smith'],
        authors_with_ids=[AuthorInfo(name='Alice Smith', author_id='S123')],
    )]
    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)
    assert api.s2_id_calls == [('S123', 'Alice Smith')]
    assert data['all_authors'][0]['match_confidence'] == 'id'


def test_s2_id_lookup_defaults_unstamped_author_to_id():
    # Legacy client that does not stamp confidence: the analyzer queried by
    # a real S2 ID, so the resolution is ID-based.
    alice = make_author()  # match_confidence defaults to ''
    api = S2Client(authors_by_s2_id={'S123': alice})
    citations = [make_citation(
        CITING_TITLE, ['Alice Smith'],
        authors_with_ids=[AuthorInfo(name='Alice Smith', author_id='S123')],
    )]
    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)
    assert data['all_authors'][0]['match_confidence'] == 'id'


def test_s2_id_lookup_keeps_client_name_stamp_on_fallback():
    # Client fell back to a name search internally and said so
    alice = make_author(match_confidence='name')
    api = S2Client(authors_by_s2_id={'S123': alice})
    citations = [make_citation(
        CITING_TITLE, ['Alice Smith'],
        authors_with_ids=[AuthorInfo(name='Alice Smith', author_id='S123')],
    )]
    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)
    assert data['all_authors'][0]['match_confidence'] == 'name'


# ---------------------------------------------------------------------------
# PRIORITY 4: get_author_by_paper -> keep client stamp, default 'verified'
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('stamped, expected', [
    ('verified', 'verified'),  # publication-membership check passed
    ('name', 'name'),          # client fell through to bare name search
    ('', 'verified'),          # legacy client without stamps
])
def test_get_author_by_paper_confidence(stamped, expected):
    alice = make_author(match_confidence=stamped)
    api = PaperSearchClient(authors_by_paper={'Alice Smith': alice})
    citations = [make_citation(CITING_TITLE, ['Alice Smith'])]
    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)
    assert api.paper_calls == [('Alice Smith', CITING_TITLE)]
    assert data['all_authors'][0]['match_confidence'] == expected


# ---------------------------------------------------------------------------
# PRIORITY 5: bare name lookup -> 'name' (client corroboration wins)
# ---------------------------------------------------------------------------

def test_name_lookup_marks_name():
    alice = make_author()  # unstamped legacy Author
    api = FakeClient(authors_by_name={'Alice Smith': alice})
    citations = [make_citation(CITING_TITLE, ['Alice Smith'])]
    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)
    assert data['all_authors'][0]['match_confidence'] == 'name'


@pytest.mark.parametrize('stamped', ['verified', 'id'])
def test_name_lookup_keeps_stronger_client_stamp(stamped):
    # e.g. hybrid clients serve ID-resolved profiles from their cache, or
    # corroborate via publication overlap - do not downgrade to 'name'
    alice = make_author(match_confidence=stamped)
    api = FakeClient(authors_by_name={'Alice Smith': alice})
    citations = [make_citation(CITING_TITLE, ['Alice Smith'])]
    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)
    assert data['all_authors'][0]['match_confidence'] == stamped


def test_name_lookup_passes_context_title_when_supported():
    alice = make_author(match_confidence='verified')
    api = ContextTitleClient(authors_by_name={'Alice Smith': alice})
    citations = [make_citation(CITING_TITLE, ['Alice Smith'])]
    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)
    assert api.context_calls == [('Alice Smith', CITING_TITLE)]
    assert data['all_authors'][0]['match_confidence'] == 'verified'


def test_name_lookup_without_context_support_uses_plain_call():
    alice = make_author()
    api = FakeClient(authors_by_name={'Alice Smith': alice})
    citations = [make_citation(CITING_TITLE, ['Alice Smith'])]
    # Must not raise TypeError from an unexpected context_title kwarg
    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)
    assert len(data['all_authors']) == 1


# ---------------------------------------------------------------------------
# Dedup merge: keep max confidence, prefer identity fields from stronger match
# ---------------------------------------------------------------------------

def test_dedup_merge_upgrades_confidence_and_identity_fields():
    # First citation resolves by name (weak), second by GS ID (strong)
    name_alice = make_author(h_index=5, semantic_scholar_id='S_OLD')
    id_alice = make_author(h_index=22, semantic_scholar_id='S_NEW',
                           google_scholar_id='ALICE9')
    api = FakeClient(authors_by_name={'Alice Smith': name_alice},
                     authors_by_gs_id={'ALICE9': id_alice})
    citations = [
        make_citation('First citing paper about software testing', ['Alice Smith']),
        make_citation(
            'Second citing paper about program analysis', ['Alice Smith'],
            authors_with_ids=[AuthorInfo(name='Alice Smith', author_id='gs:ALICE9')],
        ),
    ]
    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)
    assert len(data['all_authors']) == 1
    entry = data['all_authors'][0]
    assert entry['match_confidence'] == 'id'
    # Identity fields come from the higher-confidence record
    assert entry['google_scholar_id'] == 'ALICE9'
    assert entry['semantic_scholar_id'] == 'S_NEW'


def test_dedup_merge_never_downgrades_confidence():
    id_alice = make_author(h_index=22, semantic_scholar_id='S_GOOD',
                           google_scholar_id='ALICE9')
    name_alice = make_author(h_index=5, semantic_scholar_id='S_BAD')
    api = FakeClient(authors_by_name={'Alice Smith': name_alice},
                     authors_by_gs_id={'ALICE9': id_alice})
    citations = [
        make_citation(
            'First citing paper about software testing', ['Alice Smith'],
            authors_with_ids=[AuthorInfo(name='Alice Smith', author_id='gs:ALICE9')],
        ),
        make_citation('Second citing paper about program analysis', ['Alice Smith']),
    ]
    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)
    assert len(data['all_authors']) == 1
    entry = data['all_authors'][0]
    assert entry['match_confidence'] == 'id'
    # The weaker record's identity fields must not clobber the strong ones
    assert entry['semantic_scholar_id'] == 'S_GOOD'
    assert entry['google_scholar_id'] == 'ALICE9'


# ---------------------------------------------------------------------------
# impact_stats['author_stats'] confidence counters
# ---------------------------------------------------------------------------

def test_author_stats_confidence_counts():
    all_authors = [
        {'name': 'A', 'h_index': 10, 'match_confidence': 'id'},
        {'name': 'B', 'h_index': 10, 'match_confidence': 'id'},
        {'name': 'C', 'h_index': 10, 'match_confidence': 'verified'},
        {'name': 'D', 'h_index': 10, 'match_confidence': 'name'},
        {'name': 'E', 'h_index': 10, 'match_confidence': ''},  # legacy
        {'name': 'F', 'h_index': 10},  # key missing entirely (old cached result)
    ]
    analyzer = CitationImpactAnalyzer(FakeClient())
    stats = analyzer._analyze_impact_stats(
        [], {'all_authors': all_authors, 'high_profile_scholars': []})
    author_stats = stats['author_stats']
    assert author_stats['id_matched_count'] == 2
    assert author_stats['verified_count'] == 1
    # '' and missing count as name-only per contract
    assert author_stats['name_only_count'] == 3


def test_empty_result_has_zero_confidence_counts():
    analyzer = CitationImpactAnalyzer(FakeClient())
    result = analyzer._empty_result('Some Paper', 'boom')
    author_stats = result['impact_stats']['author_stats']
    assert author_stats['id_matched_count'] == 0
    assert author_stats['verified_count'] == 0
    assert author_stats['name_only_count'] == 0


# ---------------------------------------------------------------------------
# End-to-end: analyze_paper carries confidence into the final result
# ---------------------------------------------------------------------------

def test_analyze_paper_reports_confidence_breakdown():
    id_alice = make_author(name='Alice Smith', h_index=30,
                           google_scholar_id='ALICE9')
    bob = make_author(name='Bob Jones', h_index=8, affiliation='CMU')
    paper = {'title': 'My Paper', 'paperId': 'p1',
             'citationCount': 2, 'influentialCitationCount': 0}
    citations = [
        make_citation(
            'Citing paper one about software testing', ['Alice Smith'],
            authors_with_ids=[AuthorInfo(name='Alice Smith', author_id='gs:ALICE9')],
        ),
        make_citation('Citing paper two about program analysis', ['Bob Jones']),
    ]
    api = FakeClient(paper=paper, citations=citations,
                     authors_by_name={'Bob Jones': bob},
                     authors_by_gs_id={'ALICE9': id_alice})
    result = CitationImpactAnalyzer(api).analyze_paper('My Paper')
    confidences = {a['name']: a['match_confidence'] for a in result['all_authors']}
    assert confidences == {'Alice Smith': 'id', 'Bob Jones': 'name'}
    author_stats = result['impact_stats']['author_stats']
    assert author_stats['id_matched_count'] == 1
    assert author_stats['verified_count'] == 0
    assert author_stats['name_only_count'] == 1
