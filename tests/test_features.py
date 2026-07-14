"""Tests for the new analyzer features: self-citations, citation insights, FWCI."""

from unittest.mock import MagicMock

from citationimpact.core.analyzer import CitationImpactAnalyzer
from citationimpact.models import Citation
from citationimpact.models.data_models import AuthorInfo


def _analyzer():
    return CitationImpactAnalyzer(api_client=MagicMock(), data_source='api')


def _citation(title='Citing Paper', authors=None, authors_with_ids=None,
              intents=None, contexts=None, influential=False):
    return Citation(
        citing_paper_title=title,
        citing_authors=authors or ['Someone Else'],
        venue='ICSE',
        year=2024,
        is_influential=influential,
        contexts=contexts or [],
        intents=intents or [],
        authors_with_ids=authors_with_ids,
    )


class TestSelfCitations:
    PAPER = {
        'title': 'Original Paper',
        'authors': [
            {'authorId': '111', 'name': 'Chakkrit Tantithamthavorn'},
            {'authorId': '222', 'name': 'Jane Q. Doe'},
        ],
    }

    def test_id_match_counts_as_self(self):
        c = _citation(authors_with_ids=[AuthorInfo(name='X Y', author_id='s2:111')])
        stats = _analyzer()._analyze_self_citations(self.PAPER, [c])
        assert stats['self_count'] == 1
        assert stats['independent_count'] == 0

    def test_combined_id_match_counts_as_self(self):
        c = _citation(authors_with_ids=[AuthorInfo(name='X Y', author_id='gs:abc|s2:222')])
        stats = _analyzer()._analyze_self_citations(self.PAPER, [c])
        assert stats['self_count'] == 1

    def test_abbreviated_name_match_counts_as_self(self):
        c = _citation(authors=['C. Tantithamthavorn'])
        stats = _analyzer()._analyze_self_citations(self.PAPER, [c])
        assert stats['self_count'] == 1

    def test_unrelated_author_is_independent(self):
        c = _citation(authors=['Ada Lovelace'])
        stats = _analyzer()._analyze_self_citations(self.PAPER, [c])
        assert stats['self_count'] == 0
        assert stats['independent_count'] == 1
        assert stats['independent_percentage'] == 100.0

    def test_same_surname_different_initial_is_independent(self):
        c = _citation(authors=['Bob Doe'])
        stats = _analyzer()._analyze_self_citations(self.PAPER, [c])
        assert stats['self_count'] == 0

    def test_no_own_authors_returns_none(self):
        stats = _analyzer()._analyze_self_citations({'title': 'X'}, [_citation()])
        assert stats is None

    def test_percentage_over_mixed_citations(self):
        cites = [
            _citation(authors=['C. Tantithamthavorn']),
            _citation(authors=['Ada Lovelace']),
            _citation(authors=['Grace Hopper']),
            _citation(authors=['Alan Turing']),
        ]
        stats = _analyzer()._analyze_self_citations(self.PAPER, cites)
        assert stats['self_count'] == 1
        assert stats['independent_count'] == 3
        assert stats['independent_percentage'] == 75.0


class TestImpactStatementsThreshold:
    def test_statement_uses_configured_h_index_threshold(self):
        stmts = _analyzer()._generate_impact_statements(
            citation_thresholds={'over_100': 0},
            author_stats={'high_profile_count': 3, 'max_h_index': 40},
            institution_stats={'from_qs_top_100': 0, 'industry_percentage': 0,
                               'university_percentage': 0},
            total_analyzed=10,
            h_index_threshold=10,
        )
        assert any('h-index ≥ 10' in s for s in stmts)
        assert not any('h-index ≥ 20' in s for s in stmts)


class TestCitationInsights:
    def test_intent_counts_are_lowercased_and_counted(self):
        cites = [
            _citation(intents=['Methodology']),
            _citation(intents=['methodology', 'background']),
            _citation(intents=['background']),
        ]
        insights = _analyzer()._analyze_influence(cites)['citation_insights']
        assert insights['intent_counts'] == {'methodology': 2, 'background': 2}

    def test_context_samples_capture_metadata(self):
        c = _citation(contexts=['  We build on the approach of [12].  '],
                      intents=['methodology'], influential=True)
        insights = _analyzer()._analyze_influence([c])['citation_insights']
        samples = insights['context_samples']
        assert len(samples) == 1
        assert samples[0]['context'] == 'We build on the approach of [12].'
        assert samples[0]['is_influential'] is True
        assert samples[0]['intents'] == ['methodology']

    def test_context_samples_capped_at_15(self):
        cites = [_citation(title=f'P{i}', contexts=[f'ctx {i}']) for i in range(30)]
        insights = _analyzer()._analyze_influence(cites)['citation_insights']
        assert len(insights['context_samples']) == 15

    def test_empty_contexts_skipped(self):
        cites = [_citation(contexts=['', '   ']), _citation(contexts=['real snippet'])]
        insights = _analyzer()._analyze_influence(cites)['citation_insights']
        assert len(insights['context_samples']) == 1


class TestFieldNormalizedMetrics:
    def _client(self):
        from citationimpact.clients.unified import UnifiedAPIClient
        client = UnifiedAPIClient.__new__(UnifiedAPIClient)
        return client

    def test_doi_path_returns_metrics(self, monkeypatch):
        client = self._client()
        client._make_request = MagicMock(return_value={
            'title': 'Paper', 'fwci': 3.4,
            'citation_normalized_percentile': {'value': 0.97, 'is_in_top_1_percent': False,
                                               'is_in_top_10_percent': True},
            'cited_by_count': 150,
        })
        metrics = client.get_field_normalized_metrics('Paper', doi='10.1/x')
        assert metrics['fwci'] == 3.4
        assert metrics['is_top_10_percent'] is True
        assert metrics['openalex_cited_by_count'] == 150

    def test_title_search_requires_exact_normalized_match(self):
        client = self._client()
        client._make_request = MagicMock(return_value={
            'results': [
                {'title': 'A Different Paper Entirely', 'fwci': 9.0,
                 'citation_normalized_percentile': {'value': 0.9}},
                {'title': 'My Paper!', 'fwci': 2.0,
                 'citation_normalized_percentile': {'value': 0.8}},
            ]
        })
        metrics = client.get_field_normalized_metrics('My Paper')
        assert metrics is not None
        assert metrics['fwci'] == 2.0

    def test_no_match_returns_none(self):
        client = self._client()
        client._make_request = MagicMock(return_value={'results': [
            {'title': 'Unrelated', 'fwci': 1.0}
        ]})
        assert client.get_field_normalized_metrics('My Paper') is None

    def test_missing_metrics_returns_none(self):
        client = self._client()
        client._make_request = MagicMock(return_value={
            'results': [{'title': 'My Paper', 'fwci': None,
                         'citation_normalized_percentile': None}]
        })
        assert client.get_field_normalized_metrics('My Paper') is None


class TestExportIncludesNewMetrics:
    def test_markdown_has_fwci_self_citations_and_contexts(self):
        from citationimpact.export import build_markdown_report
        result = {
            'paper_title': 'P', 'total_citations': 10,
            'influential_citations_count': 1, 'analyzed_citations': 10,
            'field_normalized': {'fwci': 2.5, 'citation_percentile': 0.93},
            'self_citation_stats': {'self_count': 2, 'independent_count': 8,
                                    'independent_percentage': 80.0},
            'citation_insights': {
                'intent_counts': {'methodology': 4},
                'context_samples': [{'context': 'Uses the tool of P.',
                                     'title': 'Q', 'year': 2024}],
            },
            'impact_stats': {},
        }
        md = build_markdown_report(result)
        assert 'Field-Weighted Citation Impact (FWCI) | 2.50' in md
        assert 'Field citation percentile | 93' in md
        assert 'Independent citations (non-self) | 8 (80%)' in md
        assert '## How This Work Is Used' in md
        assert 'Uses the tool of P.' in md

    def test_latex_has_fwci_and_independence(self):
        from citationimpact.export import build_latex_report
        result = {
            'paper_title': 'P', 'total_citations': 10,
            'influential_citations_count': 1,
            'field_normalized': {'fwci': 2.5},
            'self_citation_stats': {'independent_count': 8,
                                    'independent_percentage': 80.0},
            'impact_stats': {},
        }
        tex = build_latex_report(result)
        assert 'FWCI): 2.50' in tex
        assert '80\\% of analyzed citations' in tex


class TestOpenAlexNullShapes:
    """OpenAlex returns explicit nulls for summary_stats/last_known_institutions
    on some authors - parsing must not crash (found by live e2e test)."""

    def _client(self):
        from citationimpact.clients.unified import UnifiedAPIClient
        client = UnifiedAPIClient.__new__(UnifiedAPIClient)
        client._author_cache = {}
        client._venue_cache = {}
        return client

    def test_search_openalex_author_with_null_fields(self):
        client = self._client()
        client._make_request = MagicMock(return_value={'results': [{
            'display_name': 'Jane Doe',
            'summary_stats': None,
            'last_known_institutions': None,
            'works_count': None,
            'cited_by_count': None,
        }]})
        author = client._search_openalex_author('Jane Doe', 'Jane Doe')
        assert author is not None
        assert author.h_index == 0
        assert author.affiliation == 'Unknown'

    def test_get_venue_with_null_summary_stats(self):
        client = self._client()
        client._make_request = MagicMock(return_value={'results': [{
            'display_name': 'Some Venue',
            'summary_stats': None,
        }]})
        venue = client.get_venue('Some Venue')
        assert venue is not None
        assert venue.h_index == 0
