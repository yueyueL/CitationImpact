"""Tests for citationimpact.export report builders."""

import pytest

from citationimpact.export import (
    build_report,
    build_markdown_report,
    build_latex_report,
    build_csv_report,
    build_bibtex_report,
    default_export_filename,
    export_report,
    latex_escape,
)
from citationimpact.models import Citation


@pytest.fixture
def sample_result():
    return {
        'paper_title': 'Deep Learning for Program Repair',
        'total_citations': 250,
        'influential_citations_count': 18,
        'analyzed_citations': 100,
        'error': None,
        'impact_stats': {
            'summary_statements': ['Cited by 12 papers with 100+ citations.'],
            'author_stats': {
                'total_unique_authors': 70,
                'high_profile_count': 9,
                'max_h_index': 88,
            },
            'institution_stats': {'from_qs_top_100': 5},
            'citation_thresholds': {'over_100': 12},
            'highly_cited_citing_papers': [
                {'title': 'A | Pipe Paper', 'citations': 400, 'year': 2023,
                 'venue': 'ICSE', 'url': 'https://example.com/p'},
            ],
            'recent_citations_count': 40,
        },
        'high_profile_scholars': [
            {'name': 'Grace Hopper', 'h_index': 60, 'affiliation': 'Yale',
             'google_scholar_id': 'gh123', 'university_rank': 18},
        ],
        'institutions': {'University': 50, 'Industry': 12, 'Government': 3, 'Other': 5},
        'venues': {
            'total': 90, 'unique': 30, 'top_tier_percentage': 42.0,
            'most_common': [('ICSE', 8), ('FSE', 5)],
            'rankings': {'ICSE': {'core_rank': 'A*', 'ccf_rank': 'A'}, 'FSE': {}},
        },
        'yearly_stats': [(2022, 30), (2023, 60)],
        'influential_citations': [
            Citation(
                citing_paper_title='Repair Transformers',
                citing_authors=['A. Turing'],
                venue='FSE', year=2023, is_influential=True,
                contexts=[], intents=['Methodology'],
                doi='10.1145/x', url='https://example.com/c', citation_count=55,
            ),
        ],
        'methodological_citations': [],
        'all_authors': [
            {'name': 'Grace Hopper', 'citing_paper': 'Repair Transformers',
             'paper_url': 'https://example.com/c', 'paper_id': 'p1',
             'venue': 'FSE', 'year': 2023, 'paper_citations': 55},
        ],
    }


def test_markdown_report_contains_key_sections(sample_result):
    md = build_markdown_report(sample_result)
    assert '# Citation Impact Report' in md
    assert 'Deep Learning for Program Repair' in md
    assert '## Impact Statements' in md
    assert '## High-Profile Scholars' in md
    assert 'Grace Hopper' in md
    assert '| 2023 | 60 |' in md
    # Pipe characters inside table cells must be escaped
    assert 'A \\| Pipe Paper' in md


def test_markdown_scholar_links_to_google_scholar(sample_result):
    md = build_markdown_report(sample_result)
    assert 'https://scholar.google.com/citations?user=gh123' in md


def test_latex_escape_specials():
    assert latex_escape('50% of A&B_c #1 {x} $5 ~^') == (
        r'50\% of A\&B\_c \#1 \{x\} \$5 \textasciitilde{}\textasciicircum{}'
    )


def test_latex_report_escapes_title():
    result = {'paper_title': 'C# & F# _rock_', 'total_citations': 1,
              'influential_citations_count': 0, 'impact_stats': {}}
    tex = build_latex_report(result)
    assert r'C\# \& F\# \_rock\_' in tex


def test_csv_report_has_all_citing_papers(sample_result):
    csv_text = build_csv_report(sample_result)
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith('title,authors,venue,year')
    # Dataclass citation + highly-cited paper (all_authors row dedups with Citation)
    assert any('Repair Transformers' in line for line in lines[1:])
    assert any('A | Pipe Paper' in line for line in lines[1:])


def test_csv_dedupes_same_paper_from_multiple_sections(sample_result):
    csv_text = build_csv_report(sample_result)
    count = sum('Repair Transformers' in line for line in csv_text.splitlines())
    assert count == 1


def test_bibtex_report_entries(sample_result):
    bib = build_bibtex_report(sample_result)
    assert '@article{' in bib
    assert 'title = {Repair Transformers}' in bib
    assert 'doi = {10.1145/x}' in bib


def test_bibtex_keys_unique_for_duplicate_titles():
    result = {
        'paper_title': 'X',
        'influential_citations': [],
        'methodological_citations': [],
        'impact_stats': {},
        'all_authors': [
            {'name': 'A', 'citing_paper': 'Same Title', 'year': 2020},
        ],
    }
    # Same title in two sections but different case still dedupes to one entry
    bib = build_bibtex_report(result)
    assert bib.count('@article{') == 1


def test_build_report_rejects_unknown_format(sample_result):
    with pytest.raises(ValueError):
        build_report(sample_result, 'docx')


def test_build_report_accepts_aliases(sample_result):
    assert build_report(sample_result, 'md') == build_report(sample_result, 'markdown')
    assert build_report(sample_result, 'bib') == build_report(sample_result, 'bibtex')


def test_default_export_filename_slug(sample_result):
    name = default_export_filename(sample_result, 'markdown')
    assert name.startswith('impact_deep-learning-for-program-repair')
    assert name.endswith('.md')


def test_export_report_writes_file(sample_result, tmp_path):
    path = export_report(sample_result, 'markdown', str(tmp_path / 'out.md'))
    assert path.exists()
    assert 'Citation Impact Report' in path.read_text()


def test_export_report_to_directory_generates_name(sample_result, tmp_path):
    path = export_report(sample_result, 'csv', str(tmp_path))
    assert path.parent == tmp_path
    assert path.suffix == '.csv'


def test_export_report_default_dir_uses_config(sample_result, isolated_config):
    path = export_report(sample_result, 'json')
    assert path.exists()
    assert isolated_config.get_config_path() in path.parents


def test_builders_tolerate_minimal_result():
    minimal = {'paper_title': 'Lonely Paper'}
    for fmt in ('markdown', 'latex', 'csv', 'bibtex', 'json'):
        out = build_report(minimal, fmt)
        assert isinstance(out, str)
