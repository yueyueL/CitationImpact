"""Regression tests for round-3 core analyzer fixes.

Bug: when a dedup merge upgraded an author's match confidence, the analyzer
copied the higher-confidence record's identity fields (GS/S2 IDs,
affiliation) into the registry entry but kept the earlier lower-confidence
profile's metrics (h_index, total_citations, works_count). The merged entry
then claimed ID-verified identity while displaying a possibly wrong-person
profile's numbers, inflating grant-facing impact stats.
"""

from citationimpact.core.analyzer import CitationImpactAnalyzer
from citationimpact.models import Author, AuthorInfo, Citation


class FakeClient:
    """Minimal offline API-client stub (name + GS-ID lookups only)."""

    def __init__(self, authors_by_name=None, authors_by_gs_id=None):
        self.authors_by_name = authors_by_name or {}
        self.authors_by_gs_id = authors_by_gs_id or {}
        self.last_error = None

    def get_author(self, name):
        return self.authors_by_name.get(name)

    def get_author_by_gs_id(self, gs_id, name):
        return self.authors_by_gs_id.get(gs_id)

    def get_venue(self, name):
        return None

    def categorize_institution(self, institution_type, affiliation):
        if institution_type in ('University', 'Industry', 'Government'):
            return institution_type
        return 'Other'


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


def test_confidence_upgrade_adopts_metrics_with_identity():
    """The ID-verified record's metrics must replace the name-match ones.

    First citation resolves 'Alice Smith' by bare name to a same-named
    OTHER person's Google Scholar profile (h-index 60). Second citation
    carries her real GS profile ID (h-index 12). The merged entry must not
    be a chimera of verified identity + wrong-person metrics.
    """
    wrong_alice = Author(
        name='Alice Smith', h_index=60, affiliation='MIT',
        institution_type='University', works_count=400,
        citation_count=90000, h_index_source='google_scholar',
    )
    real_alice = Author(
        name='Alice Smith', h_index=12, affiliation='MIT',
        institution_type='University', works_count=30,
        citation_count=800, google_scholar_id='ALICE9',
        semantic_scholar_id='S_REAL', h_index_source='semantic_scholar',
    )
    api = FakeClient(authors_by_name={'Alice Smith': wrong_alice},
                     authors_by_gs_id={'ALICE9': real_alice})
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
    assert entry['google_scholar_id'] == 'ALICE9'
    assert entry['semantic_scholar_id'] == 'S_REAL'
    # Metrics travel with the upgraded identity - no wrong-person numbers
    assert entry['h_index'] == 12
    assert entry['h_index_display'] == 12  # no stale '60 (GS)' marker
    assert entry['h_index_source'] == 'semantic_scholar'
    assert entry['total_citations'] == 800
    assert entry['works_count'] == 30
    # The wrong-person h-index must not leak into high-profile stats
    assert data['high_profile_scholars'] == []
