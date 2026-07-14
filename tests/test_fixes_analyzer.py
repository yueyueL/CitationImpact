"""Regression tests for bug fixes in citationimpact.core.analyzer."""

from datetime import datetime

import pytest

import citationimpact.clients as clients_module
from citationimpact.cache import get_author_cache
from citationimpact.core.analyzer import (
    CitationImpactAnalyzer,
    analyze_paper_impact,
    _names_compatible,
)
from citationimpact.models import Author, AuthorInfo, Citation


class FakeClient:
    """Minimal offline API-client stub for exercising the analyzer."""

    def __init__(self, paper=None, citations=None, authors_by_name=None,
                 authors_by_gs_id=None):
        self.paper = paper
        self.citations = citations or []
        self.authors_by_name = authors_by_name or {}
        self.authors_by_gs_id = authors_by_gs_id or {}
        self.get_citations_limits = []
        self.gs_id_calls = []
        self.last_error = None

    def search_paper(self, title):
        return self.paper

    def get_citations(self, paper_id, limit=100):
        self.get_citations_limits.append(limit)
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


def make_citation(title, authors, year=2020, intents=None, is_influential=False,
                  citation_count=0, url='', paper_id='', authors_with_ids=None,
                  venue='Some Venue'):
    return Citation(
        citing_paper_title=title,
        citing_authors=authors,
        venue=venue,
        year=year,
        is_influential=is_influential,
        contexts=[],
        intents=intents or [],
        paper_id=paper_id,
        url=url,
        authors_with_ids=authors_with_ids,
        citation_count=citation_count,
    )


def make_paper(title='My Paper', citation_count=10):
    return {
        'title': title,
        'paperId': 'p1',
        'citationCount': citation_count,
        'influentialCitationCount': 1,
    }


# ---------------------------------------------------------------------------
# Bug: methodological citations always empty (case-sensitive intent match)
# ---------------------------------------------------------------------------

def test_methodological_citations_detected_with_lowercase_intents():
    analyzer = CitationImpactAnalyzer(FakeClient())
    citations = [
        make_citation('Paper A', ['X'], intents=['background', 'methodology']),
        make_citation('Paper B', ['Y'], intents=['background']),
        make_citation('Paper C', ['Z'], intents=['Methodology']),  # legacy casing
    ]
    result = analyzer._analyze_influence(citations)
    titles = [c.citing_paper_title for c in result['methodological_citations']]
    assert titles == ['Paper A', 'Paper C']


# ---------------------------------------------------------------------------
# Bug: operator precedence dropped valid URLs when paper_id is empty
# ---------------------------------------------------------------------------

def test_highly_cited_citing_paper_keeps_url_when_paper_id_missing():
    analyzer = CitationImpactAnalyzer(FakeClient())
    citations = [
        make_citation('Doi paper', ['X'], citation_count=60,
                      url='https://doi.org/10.1000/xyz', paper_id=''),
        make_citation('S2 paper', ['Y'], citation_count=70, url='',
                      paper_id='abc123'),
        make_citation('No link paper', ['Z'], citation_count=80, url='',
                      paper_id=''),
    ]
    stats = analyzer._analyze_impact_stats(citations, {})
    urls = {p['title']: p['url'] for p in stats['highly_cited_citing_papers']}
    assert urls['Doi paper'] == 'https://doi.org/10.1000/xyz'
    assert urls['S2 paper'] == 'https://www.semanticscholar.org/paper/abc123'
    assert urls['No link paper'] == ''


# ---------------------------------------------------------------------------
# Bug: 'last 2 years' actually spanned three calendar years
# ---------------------------------------------------------------------------

def test_recent_citations_cover_exactly_two_calendar_years():
    current_year = datetime.now().year
    analyzer = CitationImpactAnalyzer(FakeClient())
    citations = [
        make_citation('this year', ['A'], year=current_year),
        make_citation('last year', ['B'], year=current_year - 1),
        make_citation('two years ago', ['C'], year=current_year - 2),
        make_citation('three years ago', ['D'], year=current_year - 3),
    ]
    stats = analyzer._analyze_impact_stats(citations, {})
    assert stats['recent_citations_count'] == 2


# ---------------------------------------------------------------------------
# Bug: grant statement conflated author count with university count
# ---------------------------------------------------------------------------

def test_impact_statement_counts_researchers_not_universities():
    analyzer = CitationImpactAnalyzer(FakeClient())
    statements = analyzer._generate_impact_statements(
        {'over_1000': 0, 'over_500': 0, 'over_100': 0, 'over_50': 0},
        {'high_profile_count': 0, 'max_h_index': 0},
        {'from_qs_top_100': 5, 'industry_percentage': 0,
         'university_percentage': 0},
        10,
    )
    qs_statements = [s for s in statements if 'QS Top 100' in s]
    assert len(qs_statements) == 1
    assert '5 researchers' in qs_statements[0]
    assert '5 QS Top 100 universities' not in qs_statements[0]


# ---------------------------------------------------------------------------
# Bug: dedup key was surname-only, merging distinct authors
# ---------------------------------------------------------------------------

def test_distinct_authors_with_same_surname_are_not_merged():
    wei = Author(name='Wei Zhang', h_index=8,
                 affiliation='Tsinghua University', institution_type='University')
    li = Author(name='Li Zhang', h_index=45,
                affiliation='Tsinghua University', institution_type='University')
    api = FakeClient(authors_by_name={'Wei Zhang': wei, 'Li Zhang': li})
    analyzer = CitationImpactAnalyzer(api)
    citations = [
        make_citation('Paper by Wei about deep learning systems', ['Wei Zhang']),
        make_citation('Paper by Li about program analysis tools', ['Li Zhang']),
    ]
    data = analyzer._analyze_authors(citations, h_index_threshold=20)
    names = sorted(a['name'] for a in data['all_authors'])
    assert names == ['Li Zhang', 'Wei Zhang']
    assert len(data['high_profile_scholars']) == 1
    assert data['high_profile_scholars'][0]['name'] == 'Li Zhang'


def test_abbreviated_and_full_first_names_still_merge():
    full = Author(name='Chakkrit Tantithamthavorn', h_index=40,
                  affiliation='Monash University', institution_type='University')
    abbrev = Author(name='C. Tantithamthavorn', h_index=35,
                    affiliation='Monash University', institution_type='University')
    api = FakeClient(authors_by_name={
        'Chakkrit Tantithamthavorn': full,
        'C. Tantithamthavorn': abbrev,
    })
    analyzer = CitationImpactAnalyzer(api)
    citations = [
        make_citation('First citing paper about defect prediction', ['Chakkrit Tantithamthavorn']),
        make_citation('Second citing paper about code review', ['C. Tantithamthavorn']),
    ]
    data = analyzer._analyze_authors(citations, h_index_threshold=20)
    assert len(data['all_authors']) == 1
    entry = data['all_authors'][0]
    assert entry['name'] == 'Chakkrit Tantithamthavorn'
    assert len(entry['citing_papers']) == 2


# ---------------------------------------------------------------------------
# Bug: repeat citers lost all but their first citing paper
# ---------------------------------------------------------------------------

def test_repeat_citer_keeps_all_citing_papers():
    scholar = Author(name='Alice Jones', h_index=30, affiliation='MIT',
                     institution_type='University')
    api = FakeClient(authors_by_name={'Alice Jones': scholar})
    titles = [f'Citing paper number {i} on software testing' for i in range(1, 5)]
    citations = [
        make_citation(
            t, ['Alice Jones'],
            authors_with_ids=[AuthorInfo(name='Alice Jones', author_id='12345')],
        )
        for t in titles
    ]
    analyzer = CitationImpactAnalyzer(api)
    data = analyzer._analyze_authors(citations, h_index_threshold=20)
    assert len(data['all_authors']) == 1
    assert data['all_authors'][0]['citing_papers'] == titles


# ---------------------------------------------------------------------------
# Bug: single-publication cache match adopted co-authors' profiles
# ---------------------------------------------------------------------------

def test_names_compatible_helper():
    assert _names_compatible('Alice Smith', 'A. Smith')
    assert _names_compatible('A. Smith', 'Alice Smith')
    assert _names_compatible('Alice Smith', 'Alice Smith')
    assert not _names_compatible('Bob Jones', 'Alice Smith')
    assert not _names_compatible('Wei Zhang', 'Li Zhang')
    assert not _names_compatible('', 'Alice Smith')
    assert not _names_compatible('Alice Smith', '')
    # Bare surname is compatible when nothing contradicts it
    assert _names_compatible('Smith', 'Alice Smith')


def test_publication_match_rejects_coauthor_profile(monkeypatch):
    citing_title = 'A shared publication with quite a long descriptive title'
    author_cache = get_author_cache()
    # Simulate the cache resolving the citing paper to co-author Bob's profile
    bob_info = {'name': 'Bob Jones', 'google_scholar_id': 'BOB123',
                'h_index': 50, 'affiliation': 'MIT',
                'institution_type': 'University'}
    monkeypatch.setattr(author_cache, 'find_by_publications',
                        lambda publications, min_overlap=2: bob_info)
    bob = Author(name='Bob Jones', h_index=50, affiliation='MIT',
                 institution_type='University', google_scholar_id='BOB123')
    alice = Author(name='Alice Smith', h_index=5, affiliation='CMU',
                   institution_type='University')
    api = FakeClient(authors_by_name={'Alice Smith': alice},
                     authors_by_gs_id={'BOB123': bob})
    analyzer = CitationImpactAnalyzer(api)
    citations = [make_citation(citing_title, ['Alice Smith'])]
    data = analyzer._analyze_authors(citations, h_index_threshold=20)
    # Alice must remain Alice; Bob's profile must never be fetched for her
    assert [a['name'] for a in data['all_authors']] == ['Alice Smith']
    assert api.gs_id_calls == []


def test_publication_match_accepts_compatible_name(monkeypatch):
    citing_title = 'Another shared publication with quite a long descriptive title'
    author_cache = get_author_cache()
    # Simulate the cache resolving the citing paper to Alice's own profile
    alice_info = {'name': 'Alice Smith', 'google_scholar_id': 'ALICE9',
                  'h_index': 22, 'affiliation': 'CMU',
                  'institution_type': 'University'}
    monkeypatch.setattr(author_cache, 'find_by_publications',
                        lambda publications, min_overlap=2: alice_info)
    alice_full = Author(name='Alice Smith', h_index=22, affiliation='CMU',
                        institution_type='University',
                        google_scholar_id='ALICE9',
                        h_index_source='google_scholar')
    api = FakeClient(authors_by_gs_id={'ALICE9': alice_full})
    analyzer = CitationImpactAnalyzer(api)
    citations = [make_citation(citing_title, ['A. Smith'])]
    data = analyzer._analyze_authors(citations, h_index_threshold=20)
    assert api.gs_id_calls == [('ALICE9', 'A. Smith')]
    assert [a['name'] for a in data['all_authors']] == ['Alice Smith']


# ---------------------------------------------------------------------------
# Bug: API failures during citation fetch reported as 'paper may be too new'
# ---------------------------------------------------------------------------

def test_citation_fetch_failure_reports_api_error():
    api = FakeClient(paper=make_paper(citation_count=100), citations=[])
    api.last_error = "Semantic Scholar HTTP 400: 'limit' must be <= 1000"
    analyzer = CitationImpactAnalyzer(api, data_source='api')
    result = analyzer.analyze_paper('My Paper')
    assert "'limit' must be <= 1000" in result['error']
    assert 'too new' not in result['error']


def test_no_citations_without_api_error_keeps_generic_message():
    api = FakeClient(paper=make_paper(citation_count=0), citations=[])
    analyzer = CitationImpactAnalyzer(api, data_source='api')
    result = analyzer.analyze_paper('My Paper')
    assert 'too new' in result['error']


def test_max_citations_clamped_to_s2_limit():
    api = FakeClient(paper=make_paper(),
                     citations=[make_citation('Some citing paper', ['Unknown'])])
    analyzer = CitationImpactAnalyzer(api, data_source='api')
    analyzer.analyze_paper('My Paper', max_citations=2000)
    assert api.get_citations_limits == [1000]


def test_max_citations_not_clamped_for_google_scholar():
    api = FakeClient(paper=make_paper(),
                     citations=[make_citation('Some citing paper', ['Unknown'])])
    analyzer = CitationImpactAnalyzer(api, data_source='google_scholar')
    analyzer.analyze_paper('My Paper', max_citations=2000)
    assert api.get_citations_limits == [2000]


# ---------------------------------------------------------------------------
# Bug: existing_client reused across data_source switches
# ---------------------------------------------------------------------------

def test_mismatched_existing_client_is_ignored(monkeypatch):
    class GoogleScholarClient:
        """Stands in for a stale Google Scholar client."""

        def __init__(self):
            self.search_calls = []

        def search_paper(self, title):
            self.search_calls.append(title)
            return None

    stale = GoogleScholarClient()
    fresh = FakeClient(paper=make_paper(title='T'),
                       citations=[make_citation('Citing paper about testing',
                                                ['Unknown'])])
    monkeypatch.setattr(clients_module, 'get_api_client',
                        lambda *args, **kwargs: fresh)
    result = analyze_paper_impact('T', data_source='api', use_cache=False,
                                  existing_client=stale)
    assert stale.search_calls == []
    assert result['_client'] is fresh


def test_matching_existing_client_is_reused():
    class UnifiedAPIClient(FakeClient):
        """Class name matches the client expected for data_source='api'."""

    client = UnifiedAPIClient(paper=make_paper(title='T'),
                              citations=[make_citation('Citing paper about testing',
                                                       ['Unknown'])])
    result = analyze_paper_impact('T', data_source='api', use_cache=False,
                                  existing_client=client)
    assert result['_client'] is client
    assert client.get_citations_limits  # the provided client did the work
