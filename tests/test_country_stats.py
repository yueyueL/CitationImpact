"""Regression tests for the COUNTRY aggregation stage.

Covers: analyzer carrying Author.country into author dicts, the new
result['countries'] key (counts + unknown bucket over the deduplicated
registry), institution_stats['countries_count'], the international-reach
impact statement, the summary-screen reach line, the all-authors 'Ctry'
column / dim fallback, and the markdown 'Citing countries' overview row.
"""

import pytest
from rich.console import Console

from citationimpact.core.analyzer import CitationImpactAnalyzer
from citationimpact.export import build_markdown_report
from citationimpact.models import Author, AuthorInfo, Citation
from citationimpact.ui.analysis_view import AnalysisView
from citationimpact.ui.drill_down import _country_column_fits, show_all_authors_view


# --------------------------------------------------------------------------- #
# Helpers (same patterns as tests/test_fixes_analyzer.py / test_fixes_ui.py)
# --------------------------------------------------------------------------- #

class FakeClient:
    """Minimal offline API-client stub for exercising the analyzer."""

    def __init__(self, paper=None, citations=None, authors_by_name=None):
        self.paper = paper
        self.citations = citations or []
        self.authors_by_name = authors_by_name or {}
        self.last_error = None

    def search_paper(self, title):
        return self.paper

    def get_citations(self, paper_id, limit=100):
        return self.citations

    def get_author(self, name):
        return self.authors_by_name.get(name)

    def get_venue(self, name):
        return None

    def categorize_institution(self, institution_type, affiliation):
        if institution_type in ('University', 'Industry', 'Government'):
            return institution_type
        return 'Other'


def make_citation(title, authors, year=2020, authors_with_ids=None):
    return Citation(
        citing_paper_title=title,
        citing_authors=authors,
        venue='Some Venue',
        year=year,
        is_influential=False,
        contexts=[],
        intents=[],
        paper_id='',
        url='',
        authors_with_ids=authors_with_ids,
        citation_count=0,
    )


def make_author(name, country='', h_index=5, affiliation='Some University'):
    return Author(name=name, h_index=h_index, affiliation=affiliation,
                  institution_type='University', country=country)


def _patch_prompt(monkeypatch, answers):
    """Patch rich Prompt.ask to return queued answers (last one repeats)."""
    from rich.prompt import Prompt

    def fake_ask(*args, **kwargs):
        if len(answers) > 1:
            return answers.pop(0)
        return answers[0]

    monkeypatch.setattr(Prompt, 'ask', fake_ask)


# --------------------------------------------------------------------------- #
# Analyzer: author_dict carries country + countries aggregation
# --------------------------------------------------------------------------- #

def test_author_dict_carries_country():
    api = FakeClient(authors_by_name={'Ada Lovelace': make_author('Ada Lovelace', country='GB')})
    analyzer = CitationImpactAnalyzer(api)
    data = analyzer._analyze_authors(
        [make_citation('Citing paper about analytical engines', ['Ada Lovelace'])],
        h_index_threshold=20,
    )
    assert data['all_authors'][0]['country'] == 'GB'


def test_author_without_country_attribute_defaults_to_empty():
    """Legacy Author objects without .country must not crash the analyzer."""
    legacy = make_author('Grace Hopper')
    # Simulate a legacy/cached object lacking the attribute entirely
    del legacy.__dict__['country']
    api = FakeClient(authors_by_name={'Grace Hopper': legacy})
    analyzer = CitationImpactAnalyzer(api)
    data = analyzer._analyze_authors(
        [make_citation('Citing paper about compilers', ['Grace Hopper'])],
        h_index_threshold=20,
    )
    assert data['all_authors'][0]['country'] == ''


def test_countries_aggregated_over_deduplicated_registry():
    """A repeat citer counts once; unknown ('') goes to the unknown bucket."""
    us = make_author('Alice Jones', country='US')
    de = make_author('Bruno Klein', country='DE')
    unknown = make_author('Carol Nakamura', country='')
    api = FakeClient(authors_by_name={
        'Alice Jones': us, 'Bruno Klein': de, 'Carol Nakamura': unknown,
    })
    citations = [
        make_citation('First paper by Alice on testing', ['Alice Jones'],
                      authors_with_ids=[AuthorInfo(name='Alice Jones', author_id='111')]),
        make_citation('Second paper by Alice on fuzzing', ['Alice Jones'],
                      authors_with_ids=[AuthorInfo(name='Alice Jones', author_id='111')]),
        make_citation('Paper by Bruno on verification', ['Bruno Klein']),
        make_citation('Paper by Carol on synthesis', ['Carol Nakamura']),
    ]
    analyzer = CitationImpactAnalyzer(api)
    data = analyzer._analyze_authors(citations, h_index_threshold=20)

    assert data['countries'] == {'counts': {'US': 1, 'DE': 1}, 'unknown': 1}


def test_dedup_merge_fills_missing_country():
    """Merging an abbreviated/full name pair keeps the known country."""
    no_country = make_author('C. Tantithamthavorn', country='', affiliation='Monash University')
    with_country = make_author('Chakkrit Tantithamthavorn', country='AU',
                               affiliation='Monash University')
    api = FakeClient(authors_by_name={
        'C. Tantithamthavorn': no_country,
        'Chakkrit Tantithamthavorn': with_country,
    })
    citations = [
        make_citation('First citing paper about defect prediction', ['C. Tantithamthavorn']),
        make_citation('Second citing paper about code review', ['Chakkrit Tantithamthavorn']),
    ]
    analyzer = CitationImpactAnalyzer(api)
    data = analyzer._analyze_authors(citations, h_index_threshold=20)

    assert len(data['all_authors']) == 1
    assert data['all_authors'][0]['country'] == 'AU'
    assert data['countries'] == {'counts': {'AU': 1}, 'unknown': 0}


def test_empty_result_has_countries_zeros():
    analyzer = CitationImpactAnalyzer(FakeClient())
    result = analyzer._empty_result('T', 'err')
    assert result['countries'] == {'counts': {}, 'unknown': 0}
    assert result['impact_stats']['institution_stats']['countries_count'] == 0


# --------------------------------------------------------------------------- #
# impact_stats: countries_count = distinct KNOWN countries
# --------------------------------------------------------------------------- #

def test_institution_stats_counts_distinct_known_countries():
    analyzer = CitationImpactAnalyzer(FakeClient())
    authors_data = {
        'all_authors': [
            {'name': 'A', 'h_index': 5, 'country': 'US'},
            {'name': 'B', 'h_index': 5, 'country': 'US'},
            {'name': 'C', 'h_index': 5, 'country': 'DE'},
            {'name': 'D', 'h_index': 5, 'country': ''},
        ],
    }
    stats = analyzer._analyze_impact_stats([], authors_data)
    assert stats['institution_stats']['countries_count'] == 2


def test_institution_stats_countries_count_zero_without_authors():
    analyzer = CitationImpactAnalyzer(FakeClient())
    stats = analyzer._analyze_impact_stats([], {})
    assert stats['institution_stats']['countries_count'] == 0


# --------------------------------------------------------------------------- #
# Impact statement: international reach at >= 5 countries
# --------------------------------------------------------------------------- #

def _base_inst_stats(**overrides):
    stats = {'from_qs_top_100': 0, 'industry_percentage': 0, 'university_percentage': 0}
    stats.update(overrides)
    return stats


def test_impact_statement_at_five_countries():
    analyzer = CitationImpactAnalyzer(FakeClient())
    statements = analyzer._generate_impact_statements(
        {'over_1000': 0, 'over_500': 0, 'over_100': 0, 'over_50': 0},
        {'high_profile_count': 0, 'max_h_index': 0},
        _base_inst_stats(countries_count=5),
        10,
    )
    assert ("Cited by researchers across 5 countries, "
            "demonstrating international reach.") in statements


def test_no_impact_statement_below_five_countries():
    analyzer = CitationImpactAnalyzer(FakeClient())
    statements = analyzer._generate_impact_statements(
        {'over_1000': 0, 'over_500': 0, 'over_100': 0, 'over_50': 0},
        {'high_profile_count': 0, 'max_h_index': 0},
        _base_inst_stats(countries_count=4),
        10,
    )
    assert not any('international reach' in s for s in statements)


def test_no_impact_statement_when_countries_count_missing():
    """Legacy institution_stats (no countries_count key) must not crash."""
    analyzer = CitationImpactAnalyzer(FakeClient())
    statements = analyzer._generate_impact_statements(
        {'over_1000': 0, 'over_500': 0, 'over_100': 0, 'over_50': 0},
        {'high_profile_count': 0, 'max_h_index': 0},
        _base_inst_stats(),
        10,
    )
    assert not any('international reach' in s for s in statements)


# --------------------------------------------------------------------------- #
# End-to-end: analyze_paper produces countries + statement
# --------------------------------------------------------------------------- #

def test_analyze_paper_end_to_end_countries():
    names_countries = [
        ('Alice Jones', 'US'), ('Bruno Klein', 'DE'), ('Carol Nakamura', 'JP'),
        ('Diego Marino', 'IT'), ('Emma Wilson', 'GB'), ('Frank Miller', ''),
    ]
    authors = {name: make_author(name, country=code) for name, code in names_countries}
    citations = [
        make_citation(f'Citing paper number {i} on software analysis', [name])
        for i, (name, _) in enumerate(names_countries, 1)
    ]
    paper = {'title': 'My Paper', 'paperId': 'p1',
             'citationCount': 6, 'influentialCitationCount': 0}
    api = FakeClient(paper=paper, citations=citations, authors_by_name=authors)
    analyzer = CitationImpactAnalyzer(api)

    result = analyzer.analyze_paper('My Paper', h_index_threshold=20, max_citations=10)

    assert result['countries']['counts'] == {'US': 1, 'DE': 1, 'JP': 1, 'IT': 1, 'GB': 1}
    assert result['countries']['unknown'] == 1
    assert result['impact_stats']['institution_stats']['countries_count'] == 5
    assert any('across 5 countries' in s
               for s in result['impact_stats']['summary_statements'])


# --------------------------------------------------------------------------- #
# Summary screen: international reach line
# --------------------------------------------------------------------------- #

def _summary_result(countries=None):
    result = {
        'paper_title': 'Test Paper',
        'total_citations': 10,
        'analyzed_citations': 5,
        'institutions': {'University': 3, 'Industry': 1},
        'impact_stats': {
            'author_stats': {},
            'institution_stats': {},
            'citation_thresholds': {},
        },
    }
    if countries is not None:
        result['countries'] = countries
    return result


def test_summary_shows_international_reach_line():
    console = Console(record=True, width=200)
    view = AnalysisView(console)
    view._render_summary(_summary_result(
        countries={'counts': {'US': 5, 'DE': 3, 'JP': 2, 'FR': 1}, 'unknown': 4},
    ))
    output = console.export_text()
    assert 'International reach: 4 countries (top: US 5, DE 3, JP 2)' in output


def test_summary_no_reach_line_without_known_countries():
    console = Console(record=True, width=200)
    view = AnalysisView(console)
    view._render_summary(_summary_result(countries={'counts': {}, 'unknown': 7}))
    assert 'International reach' not in console.export_text()


def test_summary_handles_legacy_result_without_countries_key():
    console = Console(record=True, width=200)
    view = AnalysisView(console)
    view._render_summary(_summary_result(countries=None))
    assert 'International reach' not in console.export_text()


# --------------------------------------------------------------------------- #
# All-authors view: Ctry column vs dim affiliation fallback
# --------------------------------------------------------------------------- #

def test_country_column_fits_only_on_wide_terminals():
    assert _country_column_fits(200) is True
    assert _country_column_fits(120) is False
    assert _country_column_fits(80) is False


def _authors_result():
    return {
        'all_authors': [
            {'name': 'Ada Lovelace', 'h_index': 30, 'h_index_source': '',
             'total_citations': 100, 'affiliation': 'MIT',
             'institution_type': 'University', 'match_confidence': 'id',
             'country': 'US', 'citing_paper': 'P1'},
            {'name': 'Bob Jones', 'h_index': 10, 'h_index_source': '',
             'total_citations': 50, 'affiliation': 'CMU',
             'institution_type': 'University', 'match_confidence': 'name',
             'country': '', 'citing_paper': 'P2'},
        ],
    }


def test_all_authors_wide_terminal_shows_ctry_column(monkeypatch):
    console = Console(record=True, width=200)
    _patch_prompt(monkeypatch, ['b'])
    show_all_authors_view(console, _authors_result())
    output = console.export_text()
    assert 'Ctry' in output
    assert 'US' in output
    # Unknown country renders as '-' (total_citations > 0, so the Cites
    # column never emits a competing bare dash)
    assert ' - ' in output


def test_all_authors_narrow_terminal_appends_country_after_affiliation(monkeypatch):
    console = Console(record=True, width=100)
    _patch_prompt(monkeypatch, ['b'])
    show_all_authors_view(console, _authors_result())
    output = console.export_text()
    assert 'Ctry' not in output
    assert 'MIT US' in output
    # Unknown country adds nothing after the affiliation
    assert 'CMU' in output


def test_all_authors_legacy_entries_without_country(monkeypatch):
    """Author dicts from old caches (no 'country' key) must not crash."""
    result = _authors_result()
    for author in result['all_authors']:
        author.pop('country')
    console = Console(record=True, width=200)
    _patch_prompt(monkeypatch, ['b'])
    show_all_authors_view(console, result)
    assert 'Ada Lovelace' in console.export_text()


# --------------------------------------------------------------------------- #
# Markdown export: Citing countries overview row
# --------------------------------------------------------------------------- #

def _export_result(inst_stats):
    return {
        'paper_title': 'Test Paper',
        'total_citations': 10,
        'analyzed_citations': 5,
        'impact_stats': {
            'author_stats': {'total_unique_authors': 4},
            'institution_stats': inst_stats,
            'citation_thresholds': {},
        },
    }


def test_markdown_includes_citing_countries_row():
    report = build_markdown_report(_export_result({'from_qs_top_100': 2, 'countries_count': 6}))
    assert '| Citing countries | 6 |' in report


def test_markdown_omits_citing_countries_row_when_zero():
    report = build_markdown_report(_export_result({'from_qs_top_100': 2, 'countries_count': 0}))
    assert 'Citing countries' not in report


def test_markdown_omits_citing_countries_row_when_missing():
    report = build_markdown_report(_export_result({'from_qs_top_100': 2}))
    assert 'Citing countries' not in report
