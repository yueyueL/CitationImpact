"""Tests for batch S2 author fetching and the adaptive 429 throttle.

Live runs showed Semantic Scholar returning 429 (Retry-After: 60) under
sustained per-author GET loads even at 1.05s pacing. One POST to the S2
batch author endpoint replaces dozens of GETs; an adaptive throttle slows
the client down when FINAL 429s keep happening anyway.
"""

import time

import pytest
import requests

from citationimpact.clients.unified import UnifiedAPIClient
from citationimpact.core.analyzer import CitationImpactAnalyzer
from citationimpact.models import Author, AuthorInfo, Citation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeResponse:
    """Minimal stand-in for requests.Response (success path)."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def make_429_error():
    response = requests.models.Response()
    response.status_code = 429
    return requests.exceptions.HTTPError(response=response)


def make_author(name='Alice Smith', h_index=10, affiliation='MIT', **kwargs):
    return Author(name=name, h_index=h_index, affiliation=affiliation,
                  institution_type='University', **kwargs)


def make_citation(title, authors_with_ids):
    return Citation(
        citing_paper_title=title,
        citing_authors=[a.name for a in authors_with_ids],
        venue='Some Venue',
        year=2021,
        is_influential=False,
        contexts=[],
        intents=[],
        authors_with_ids=authors_with_ids,
    )


# ---------------------------------------------------------------------------
# get_authors_batch: parsing (null entries, null fields)
# ---------------------------------------------------------------------------

def test_get_authors_batch_parses_entries_and_skips_null_entries(monkeypatch):
    client = UnifiedAPIClient()
    captured = {}

    def fake_post(url, params, json_body, api):
        captured['url'] = url
        captured['params'] = params
        captured['json_body'] = json_body
        captured['api'] = api
        return [
            {'name': 'Alice Smith', 'hIndex': 42, 'affiliations': ['MIT'],
             'paperCount': 120, 'citationCount': 9000},
            None,  # unknown id -> null entry
            {'name': None, 'hIndex': None, 'affiliations': None,
             'paperCount': None, 'citationCount': None},  # all-null fields
        ]

    monkeypatch.setattr(client, '_make_post_request', fake_post)
    results = client.get_authors_batch(['A1', 'A2', 'A3'])

    assert captured['url'] == 'https://api.semanticscholar.org/graph/v1/author/batch'
    assert captured['params'] == {'fields': 'name,hIndex,affiliations,paperCount,citationCount'}
    assert captured['json_body'] == {'ids': ['A1', 'A2', 'A3']}
    assert captured['api'] == 'semantic_scholar'

    # Null entry (unknown id) is simply absent
    assert set(results) == {'A1', 'A3'}

    alice = results['A1']
    assert alice.name == 'Alice Smith'
    assert alice.h_index == 42
    assert alice.affiliation == 'MIT'
    assert alice.institution_type == 'other'  # S2 has no institution type
    assert alice.works_count == 120
    assert alice.citation_count == 9000
    assert alice.semantic_scholar_id == 'A1'
    assert alice.match_confidence == 'id'
    assert alice.country == ''  # S2 has no country

    # Every field null -> null-safe defaults
    ghost = results['A3']
    assert ghost.name == 'Unknown'
    assert ghost.h_index == 0
    assert ghost.affiliation == 'Unknown'
    assert ghost.works_count == 0
    assert ghost.citation_count == 0
    assert ghost.semantic_scholar_id == 'A3'


def test_get_authors_batch_handles_null_first_affiliation(monkeypatch):
    client = UnifiedAPIClient()
    monkeypatch.setattr(client, '_make_post_request', lambda url, params, json_body, api: [
        {'name': 'Bob Jones', 'hIndex': 3, 'affiliations': [None],
         'paperCount': 5, 'citationCount': 10},
    ])
    results = client.get_authors_batch(['B1'])
    assert results['B1'].affiliation == 'Unknown'


def test_batch_stages_raw_base_and_singles_skip_s2_get_but_still_enrich(monkeypatch):
    """The batch result is only a raw S2 base: it must NOT be cached under
    the enriched s2: key (that would silently skip the documented OpenAlex
    enrichment), and a subsequent single lookup reuses it without a second
    S2 GET while still enriching from OpenAlex."""
    client = UnifiedAPIClient()
    monkeypatch.setattr(client, '_make_post_request', lambda url, params, json_body, api: [
        {'name': 'Alice Smith', 'hIndex': 42, 'affiliations': ['MIT'],
         'paperCount': 120, 'citationCount': 9000},
    ])
    results = client.get_authors_batch(['A1'])

    # Staged under the raw key, NOT the enriched key get_author_by_s2_id
    # checks first
    assert 's2:A1' not in client._author_cache
    assert client._author_cache['s2raw:A1'] is results['A1']
    assert results['A1'].institution_type == 'other'  # raw: no OpenAlex yet

    # Single lookup: the OpenAlex enrichment still runs, but the id must
    # not be re-fetched from Semantic Scholar
    requested = []

    def fake_request(url, params, api):
        requested.append(api)
        assert api == 'openalex', 'batch-staged id re-fetched from S2'
        return {'results': [{
            'display_name': 'Alice Smith',
            'summary_stats': {'h_index': 45},
            'last_known_institutions': [{
                'display_name': 'MIT', 'type': 'education', 'country_code': 'US',
            }],
            'works_count': 130,
            'cited_by_count': 9500,
        }]}

    monkeypatch.setattr(client, '_make_request', fake_request)
    author = client.get_author_by_s2_id('A1')

    assert requested == ['openalex']
    assert author.h_index == 42            # S2 h-index kept (non-zero)
    assert author.affiliation == 'MIT'
    assert author.institution_type == 'education'  # filled from OpenAlex
    assert author.country == 'US'                  # filled from OpenAlex
    assert author.match_confidence == 'id'

    # Enriched profile supersedes the raw entry: next single is free
    assert client._author_cache['s2:A1'] is author

    def boom(*args, **kwargs):
        raise AssertionError('network request made despite warm cache')

    monkeypatch.setattr(client, '_make_request', boom)
    monkeypatch.setattr(client, '_make_post_request', boom)
    assert client.get_author_by_s2_id('A1') is author


def test_batch_staged_id_enriches_via_name_search_when_no_affiliation(monkeypatch):
    """A raw base without an S2 affiliation takes the OpenAlex name-search
    enrichment path (same as the pre-batch per-id flow)."""
    client = UnifiedAPIClient()
    monkeypatch.setattr(client, '_make_post_request', lambda url, params, json_body, api: [
        {'name': 'Bob Jones', 'hIndex': 0, 'affiliations': None,
         'paperCount': 5, 'citationCount': 10},
    ])
    client.get_authors_batch(['B1'])

    def fake_request(url, params, api):
        assert api == 'openalex'
        return {'results': [{
            'display_name': 'Bob Jones',
            'summary_stats': {'h_index': 9},
            'last_known_institutions': [{
                'display_name': 'CMU', 'type': 'education', 'country_code': 'US',
            }],
            'works_count': 12,
            'cited_by_count': 300,
        }]}

    monkeypatch.setattr(client, '_make_request', fake_request)
    author = client.get_author_by_s2_id('B1')

    assert author.h_index == 9              # zero S2 h-index filled from OpenAlex
    assert author.affiliation == 'CMU'      # missing affiliation filled
    assert author.institution_type == 'education'
    assert author.country == 'US'
    assert author.match_confidence == 'id'


def test_get_authors_batch_second_call_serves_raw_staged_ids(monkeypatch):
    client = UnifiedAPIClient()
    posted = []

    def fake_post(url, params, json_body, api):
        posted.append(json_body['ids'])
        return [{'name': 'Eve Adams', 'hIndex': 5, 'affiliations': [],
                 'paperCount': 2, 'citationCount': 8}]

    monkeypatch.setattr(client, '_make_post_request', fake_post)
    first = client.get_authors_batch(['E1'])
    second = client.get_authors_batch(['E1'])

    assert posted == [['E1']]  # raw staged entry served, no second POST
    assert second['E1'] is first['E1']


def test_get_authors_batch_serves_cached_ids_without_refetch(monkeypatch):
    client = UnifiedAPIClient()
    cached = make_author(name='Cached Carol', semantic_scholar_id='X1',
                         match_confidence='id')
    client._author_cache['s2:X1'] = cached
    posted = []

    def fake_post(url, params, json_body, api):
        posted.append(json_body['ids'])
        return [{'name': 'Dave New', 'hIndex': 1, 'affiliations': [],
                 'paperCount': 1, 'citationCount': 1}]

    monkeypatch.setattr(client, '_make_post_request', fake_post)
    results = client.get_authors_batch(['X1', 'X2', 'X1'])  # duplicate too

    assert posted == [['X2']]  # cached id not refetched, duplicates dropped
    assert results['X1'] is cached
    assert results['X2'].name == 'Dave New'


# ---------------------------------------------------------------------------
# get_authors_batch: chunking at 500
# ---------------------------------------------------------------------------

def test_get_authors_batch_chunks_ids_at_500(monkeypatch):
    client = UnifiedAPIClient()
    chunks = []

    def fake_post(url, params, json_body, api):
        ids = json_body['ids']
        chunks.append(ids)
        return [None] * len(ids)

    monkeypatch.setattr(client, '_make_post_request', fake_post)
    all_ids = [f'ID{i}' for i in range(1001)]
    results = client.get_authors_batch(all_ids)

    assert [len(c) for c in chunks] == [500, 500, 1]
    assert [i for chunk in chunks for i in chunk] == all_ids
    assert results == {}  # all entries were null


# ---------------------------------------------------------------------------
# get_authors_batch: failure handling
# ---------------------------------------------------------------------------

def test_get_authors_batch_total_failure_returns_empty_dict(monkeypatch):
    client = UnifiedAPIClient()
    monkeypatch.setattr(client, '_make_post_request',
                        lambda url, params, json_body, api: None)
    assert client.get_authors_batch(['A1', 'A2']) == {}


def test_get_authors_batch_failed_chunk_keeps_other_chunks(monkeypatch):
    client = UnifiedAPIClient()
    calls = []

    def fake_post(url, params, json_body, api):
        calls.append(json_body['ids'])
        if len(calls) == 1:
            return None  # first chunk fails permanently
        return [{'name': 'Last One', 'hIndex': 2, 'affiliations': [],
                 'paperCount': 3, 'citationCount': 4}]

    monkeypatch.setattr(client, '_make_post_request', fake_post)
    all_ids = [f'ID{i}' for i in range(501)]
    results = client.get_authors_batch(all_ids)

    assert len(calls) == 2
    assert set(results) == {'ID500'}


def test_get_authors_batch_empty_input_returns_empty_dict():
    client = UnifiedAPIClient()
    assert client.get_authors_batch([]) == {}


# ---------------------------------------------------------------------------
# _make_post_request: uses session.post with the JSON body
# ---------------------------------------------------------------------------

def test_make_post_request_posts_json_body(monkeypatch):
    client = UnifiedAPIClient()
    captured = {}

    def fake_post(url, params=None, json=None, timeout=None):
        captured['url'] = url
        captured['params'] = params
        captured['json'] = json
        captured['timeout'] = timeout
        return FakeResponse({'ok': True})

    monkeypatch.setattr(client.session, 'post', fake_post)
    result = client._make_post_request(
        'https://api.semanticscholar.org/graph/v1/author/batch',
        {'fields': 'name'}, {'ids': ['A1']}, 'semantic_scholar')

    assert result == {'ok': True}
    assert captured['json'] == {'ids': ['A1']}
    assert captured['params'] == {'fields': 'name'}
    assert captured['timeout'] == client.timeout


def test_make_post_request_counts_final_429_as_failure(monkeypatch):
    client = UnifiedAPIClient(max_retries=1)
    monkeypatch.setattr(time, 'sleep', lambda s: None)

    def fake_post(url, params=None, json=None, timeout=None):
        raise make_429_error()

    monkeypatch.setattr(client.session, 'post', fake_post)
    result = client._make_post_request('https://x', {}, {'ids': []}, 'semantic_scholar')
    assert result is None
    assert client.request_failures['semantic_scholar'] == 1
    assert 'rate limit' in client.last_error.lower()


# ---------------------------------------------------------------------------
# Adaptive throttle: raise on consecutive final 429s, decay on success
# ---------------------------------------------------------------------------

def test_throttle_doubles_after_two_consecutive_final_429s(monkeypatch, capsys):
    client = UnifiedAPIClient(max_retries=1)
    base = client.min_intervals['semantic_scholar']
    monkeypatch.setattr(time, 'sleep', lambda s: None)

    def fake_get(url, params=None, timeout=None):
        raise make_429_error()

    monkeypatch.setattr(client.session, 'get', fake_get)

    client._make_request('https://x', {}, 'semantic_scholar')
    assert client.min_intervals['semantic_scholar'] == base  # 1 failure: no change

    client._make_request('https://x', {}, 'semantic_scholar')
    assert client.min_intervals['semantic_scholar'] == pytest.approx(base * 2)
    out = capsys.readouterr().out
    assert out.count('[Throttle] Slowing semantic_scholar requests to') == 1


def test_throttle_caps_at_8x_base(monkeypatch, capsys):
    client = UnifiedAPIClient(max_retries=1)
    base = client.min_intervals['semantic_scholar']
    monkeypatch.setattr(time, 'sleep', lambda s: None)
    monkeypatch.setattr(client.session, 'get',
                        lambda url, params=None, timeout=None: (_ for _ in ()).throw(make_429_error()))

    for _ in range(8):
        client._make_request('https://x', {}, 'semantic_scholar')

    assert client.min_intervals['semantic_scholar'] == pytest.approx(base * 8)
    # 2 -> 2x, 3 -> 4x, 4 -> 8x: exactly three change notices, then silence
    out = capsys.readouterr().out
    assert out.count('[Throttle] Slowing semantic_scholar requests to') == 3


def test_throttle_decays_toward_base_on_success(monkeypatch):
    client = UnifiedAPIClient(max_retries=1)
    base = client.min_intervals['semantic_scholar']
    client.min_intervals['semantic_scholar'] = base * 8
    client._consecutive_429s['semantic_scholar'] = 4
    monkeypatch.setattr(client.session, 'get',
                        lambda url, params=None, timeout=None: FakeResponse({'ok': 1}))
    monkeypatch.setattr(time, 'sleep', lambda s: None)

    client._make_request('https://x', {}, 'semantic_scholar')
    assert client.min_intervals['semantic_scholar'] == pytest.approx(base * 4)
    assert client._consecutive_429s['semantic_scholar'] == 0

    for _ in range(5):
        client._make_request('https://x', {}, 'semantic_scholar')
    # Halves toward base and never dips below it
    assert client.min_intervals['semantic_scholar'] == pytest.approx(base)


def test_success_between_429s_resets_the_streak(monkeypatch):
    client = UnifiedAPIClient(max_retries=1)
    base = client.min_intervals['semantic_scholar']
    monkeypatch.setattr(time, 'sleep', lambda s: None)

    responses = ['429', 'ok', '429']

    def fake_get(url, params=None, timeout=None):
        step = responses.pop(0)
        if step == '429':
            raise make_429_error()
        return FakeResponse({'ok': 1})

    monkeypatch.setattr(client.session, 'get', fake_get)
    for _ in range(3):
        client._make_request('https://x', {}, 'semantic_scholar')

    # 429s were never consecutive: interval untouched
    assert client.min_intervals['semantic_scholar'] == base
    assert client._consecutive_429s['semantic_scholar'] == 1


def test_throttle_tracks_apis_independently(monkeypatch):
    client = UnifiedAPIClient(max_retries=1)
    s2_base = client.min_intervals['semantic_scholar']
    oa_base = client.min_intervals['openalex']
    monkeypatch.setattr(time, 'sleep', lambda s: None)
    monkeypatch.setattr(client.session, 'get',
                        lambda url, params=None, timeout=None: (_ for _ in ()).throw(make_429_error()))

    client._make_request('https://x', {}, 'semantic_scholar')
    client._make_request('https://x', {}, 'semantic_scholar')

    assert client.min_intervals['semantic_scholar'] == pytest.approx(s2_base * 2)
    assert client.min_intervals['openalex'] == oa_base  # untouched


# ---------------------------------------------------------------------------
# Analyzer wiring: prefetch once, enrichment path still runs for batch hits,
# per-id fallback for missing entries
# ---------------------------------------------------------------------------

class BatchClient:
    """Offline stub exposing get_authors_batch + get_author_by_s2_id."""

    def __init__(self, batch_authors=None, authors_by_s2_id=None):
        self.batch_authors = batch_authors or {}
        self.authors_by_s2_id = authors_by_s2_id or {}
        self.batch_calls = []
        self.s2_id_calls = []
        self.last_error = None

    def get_authors_batch(self, author_ids):
        self.batch_calls.append(sorted(author_ids))
        return {i: a for i, a in self.batch_authors.items() if i in author_ids}

    def get_author_by_s2_id(self, s2_id, name):
        self.s2_id_calls.append((s2_id, name))
        return self.authors_by_s2_id.get(s2_id)

    def get_author(self, name):
        return None

    def get_venue(self, name):
        return None

    def categorize_institution(self, institution_type, affiliation):
        if institution_type in ('University', 'Industry', 'Government'):
            return institution_type
        return 'Other'


def test_analyzer_prefetches_batch_once_and_enrichment_path_augments():
    """Batch results are only a fast base: every id still goes through
    get_author_by_s2_id (whose real implementations enrich from OpenAlex /
    merge Google Scholar), and its enriched profile wins over the raw batch
    entry. The raw batch hit is used only when the per-id path fails."""
    # Raw batch bases: S2-only (no country/institution type)
    raw_alice = Author(name='Alice Smith', h_index=42, affiliation='Unknown',
                       institution_type='other', semantic_scholar_id='S1',
                       match_confidence='id', country='')
    raw_bob = Author(name='Bob Jones', h_index=7, affiliation='CMU',
                     institution_type='other', semantic_scholar_id='S2',
                     match_confidence='id', country='')
    # What the enrichment path (get_author_by_s2_id) returns for Alice
    enriched_alice = Author(name='Alice Smith', h_index=42, affiliation='MIT',
                            institution_type='education',
                            semantic_scholar_id='S1',
                            match_confidence='id', country='US')
    carol = make_author(name='Carol White', h_index=3, affiliation='UBC',
                        semantic_scholar_id='S3', match_confidence='id')
    api = BatchClient(
        batch_authors={'S1': raw_alice, 'S2': raw_bob},  # S3 missing from batch
        # S2 absent: the per-id path fails for Bob -> batch hit is the fallback
        authors_by_s2_id={'S1': enriched_alice, 'S3': carol},
    )
    citations = [
        make_citation('Paper one about testing', [
            # Combined id: the s2: part must be extracted
            AuthorInfo(name='Alice Smith', author_id='gs:G1|s2:S1'),
            AuthorInfo(name='Bob Jones', author_id='s2:S2'),
        ]),
        make_citation('Paper two about repair', [
            # Plain id counts as S2
            AuthorInfo(name='Carol White', author_id='S3'),
        ]),
    ]

    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)

    # One batch call with every distinct S2 id
    assert api.batch_calls == [['S1', 'S2', 'S3']]
    # EVERY id still goes through the enrichment path (batch is only a base)
    assert api.s2_id_calls == [('S1', 'Alice Smith'), ('S2', 'Bob Jones'),
                               ('S3', 'Carol White')]

    by_name = {a['name']: a for a in data['all_authors']}
    assert set(by_name) == {'Alice Smith', 'Bob Jones', 'Carol White'}
    # Alice: the ENRICHED profile won, not the raw batch base
    assert by_name['Alice Smith']['affiliation'] == 'MIT'
    assert by_name['Alice Smith']['institution_type'] == 'education'
    assert by_name['Alice Smith']['country'] == 'US'
    assert by_name['Alice Smith']['h_index'] == 42
    # Bob: per-id path failed -> raw batch hit used as last resort
    assert by_name['Bob Jones']['affiliation'] == 'CMU'
    # All ids were resolved via real S2 ids -> confidence 'id'
    assert by_name['Alice Smith']['match_confidence'] == 'id'
    assert by_name['Bob Jones']['match_confidence'] == 'id'
    assert by_name['Carol White']['match_confidence'] == 'id'


def test_analyzer_skips_batch_below_three_distinct_ids():
    alice = make_author(name='Alice Smith', semantic_scholar_id='S1',
                        match_confidence='id')
    api = BatchClient(authors_by_s2_id={'S1': alice})
    citations = [
        make_citation('Paper one about testing', [
            AuthorInfo(name='Alice Smith', author_id='s2:S1'),
        ]),
    ]

    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)

    assert api.batch_calls == []  # too few ids: no batch request
    assert api.s2_id_calls == [('S1', 'Alice Smith')]
    assert data['all_authors'][0]['match_confidence'] == 'id'


def test_analyzer_batch_exception_falls_back_silently():
    class ExplodingBatchClient(BatchClient):
        def get_authors_batch(self, author_ids):
            self.batch_calls.append(sorted(author_ids))
            raise RuntimeError('batch endpoint down')

    authors = {
        f'S{i}': make_author(name=f'Person Number{i}', affiliation=f'Uni {i}',
                             semantic_scholar_id=f'S{i}', match_confidence='id')
        for i in range(1, 4)
    }
    api = ExplodingBatchClient(authors_by_s2_id=authors)
    citations = [
        make_citation('Paper one about testing', [
            AuthorInfo(name='Person Number1', author_id='s2:S1'),
            AuthorInfo(name='Person Number2', author_id='s2:S2'),
            AuthorInfo(name='Person Number3', author_id='s2:S3'),
        ]),
    ]

    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)

    assert len(api.batch_calls) == 1
    # Every author still resolved through the per-id path
    assert sorted(c[0] for c in api.s2_id_calls) == ['S1', 'S2', 'S3']
    assert len(data['all_authors']) == 3


def test_analyzer_without_batch_support_unchanged():
    """Clients lacking get_authors_batch (e.g. GS-only) keep the old path."""

    class NoBatchClient:
        def __init__(self, authors_by_s2_id):
            self.authors_by_s2_id = authors_by_s2_id
            self.s2_id_calls = []
            self.last_error = None

        def get_author_by_s2_id(self, s2_id, name):
            self.s2_id_calls.append((s2_id, name))
            return self.authors_by_s2_id.get(s2_id)

        def get_author(self, name):
            return None

        def get_venue(self, name):
            return None

        def categorize_institution(self, institution_type, affiliation):
            return 'Other'

    api = NoBatchClient(authors_by_s2_id={
        'S1': make_author(name='Alice Smith', semantic_scholar_id='S1',
                          match_confidence='id'),
    })

    citations = [
        make_citation('Paper one about testing', [
            AuthorInfo(name='Alice Smith', author_id='s2:S1'),
            AuthorInfo(name='Bob Jones', author_id='s2:S2'),
            AuthorInfo(name='Carol White', author_id='s2:S3'),
        ]),
    ]

    data = CitationImpactAnalyzer(api)._analyze_authors(citations, 20)
    assert sorted(c[0] for c in api.s2_id_calls) == ['S1', 'S2', 'S3']
    assert data['all_authors'][0]['name'] == 'Alice Smith'


# ---------------------------------------------------------------------------
# Hybrid passthrough
# ---------------------------------------------------------------------------

def test_hybrid_get_authors_batch_delegates_to_s2_client():
    from citationimpact.clients.hybrid import HybridAPIClient

    class StubS2:
        def __init__(self):
            self.calls = []

        def get_authors_batch(self, author_ids):
            self.calls.append(list(author_ids))
            return {'S1': make_author(name='Alice Smith',
                                      semantic_scholar_id='S1',
                                      match_confidence='id')}

    client = HybridAPIClient.__new__(HybridAPIClient)
    client.s2_client = StubS2()
    client.gs_client = None
    client.gs_available = False
    results = client.get_authors_batch(['S1', 'S2'])
    assert client.s2_client.calls == [['S1', 'S2']]
    assert set(results) == {'S1'}


def test_hybrid_get_authors_batch_swallows_s2_errors():
    from citationimpact.clients.hybrid import HybridAPIClient

    class BrokenS2:
        def get_authors_batch(self, author_ids):
            raise RuntimeError('boom')

    client = HybridAPIClient.__new__(HybridAPIClient)
    client.s2_client = BrokenS2()
    client.gs_client = None
    client.gs_available = False
    assert client.get_authors_batch(['S1']) == {}
