"""Tests for the CSV bundle export (build_csv_bundle / export_bundle / CLI)."""

import csv

import pytest

import citationimpact
from citationimpact.cli import main
from citationimpact.export import (
    build_csv_bundle,
    build_csv_report,
    export_bundle,
)
from citationimpact.models import Citation

BUNDLE_FILES = ['citing_papers.csv', 'authors.csv', 'venues.csv', 'timeline.csv']


@pytest.fixture
def sample_result():
    return {
        'paper_title': 'Deep Learning for Program Repair',
        'total_citations': 250,
        'influential_citations_count': 18,
        'analyzed_citations': 100,
        'error': None,
        'impact_stats': {
            'highly_cited_citing_papers': [
                {'title': 'Highly Cited Paper', 'citations': 400, 'year': 2023,
                 'venue': 'ICSE', 'url': 'https://example.com/p'},
            ],
        },
        'high_profile_scholars': [],
        'institutions': {},
        'venues': {
            'total': 90, 'unique': 2, 'top_tier_percentage': 42.0,
            'most_common': [('ICSE', 8), ('FSE', 5)],
            'rankings': {
                'ICSE': {
                    'h_index': 120, 'rank_tier': 'Tier 1 (Top venue)',
                    'core_rank': 'A*', 'ccf_rank': 'A', 'icore_rank': 'A*',
                    'citations': [
                        {'title': 'Repair Transformers', 'year': 2023},
                        {'title': 'Another ICSE Paper', 'year': 2022},
                    ],
                },
                'FSE': {},  # every field missing → defensive defaults
            },
        },
        'yearly_stats': [(2022, 30), [2023, 60]],
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
            {'name': 'Grace Hopper', 'h_index': 60, 'h_index_source': 'semantic_scholar',
             'affiliation': 'Yale', 'institution_type': 'University',
             'country': 'USA', 'match_confidence': 'id', 'university_rank': 18,
             'google_scholar_id': 'gh123', 'semantic_scholar_id': 'ss456',
             'total_citations': 9000, 'works_count': 120,
             'citing_papers': ['Repair Transformers', 'Another ICSE Paper']},
            # No country / ids / counts → defaults; not even citing_papers
            {'name': 'Ada Lovelace', 'h_index': 12},
        ],
    }


def _read_csv(path):
    with path.open(newline='', encoding='utf-8') as fh:
        return list(csv.reader(fh))


# --------------------------------------------------------------------------- #
# build_csv_bundle
# --------------------------------------------------------------------------- #

def test_bundle_writes_four_files(sample_result, tmp_path):
    paths = build_csv_bundle(sample_result, tmp_path)
    assert [p.name for p in paths] == BUNDLE_FILES
    for p in paths:
        assert p.exists()
        assert p.parent == tmp_path


def test_bundle_creates_missing_target_dir(sample_result, tmp_path):
    target = tmp_path / 'nested' / 'bundle'
    build_csv_bundle(sample_result, target)
    assert target.is_dir()
    assert sorted(p.name for p in target.iterdir()) == sorted(BUNDLE_FILES)


def test_bundle_citing_papers_matches_csv_report(sample_result, tmp_path):
    build_csv_bundle(sample_result, tmp_path)
    # newline='' keeps the CSV \r\n terminators intact for the comparison
    with (tmp_path / 'citing_papers.csv').open(newline='', encoding='utf-8') as fh:
        content = fh.read()
    assert content == build_csv_report(sample_result)
    assert 'Repair Transformers' in content
    assert 'Highly Cited Paper' in content


def test_bundle_authors_rows(sample_result, tmp_path):
    build_csv_bundle(sample_result, tmp_path)
    rows = _read_csv(tmp_path / 'authors.csv')
    assert rows[0] == ['name', 'h_index', 'h_index_source', 'affiliation',
                       'institution_type', 'country', 'match_confidence',
                       'university_rank', 'google_scholar_id', 'semantic_scholar_id',
                       'total_citations', 'works_count', 'citing_papers_count']
    assert len(rows) == 3
    assert rows[1] == ['Grace Hopper', '60', 'semantic_scholar', 'Yale', 'University',
                       'USA', 'id', '18', 'gh123', 'ss456', '9000', '120', '2']
    # Missing fields fall back to defaults ('' for text, 0 for counts)
    assert rows[2] == ['Ada Lovelace', '12', '', '', '', '', '', '', '', '', '0', '0', '0']


def test_bundle_authors_none_values_become_empty(sample_result, tmp_path):
    sample_result['all_authors'] = [
        {'name': 'N. One', 'h_index': 5, 'university_rank': None,
         'country': None, 'affiliation': None},
    ]
    build_csv_bundle(sample_result, tmp_path)
    rows = _read_csv(tmp_path / 'authors.csv')
    assert rows[1][3] == ''   # affiliation
    assert rows[1][5] == ''   # country
    assert rows[1][7] == ''   # university_rank


def test_bundle_authors_skips_non_dict_entries(sample_result, tmp_path):
    sample_result['all_authors'] = ['just a name string', {'name': 'Real Author'}]
    build_csv_bundle(sample_result, tmp_path)
    rows = _read_csv(tmp_path / 'authors.csv')
    assert len(rows) == 2
    assert rows[1][0] == 'Real Author'


def test_bundle_venues_rows(sample_result, tmp_path):
    build_csv_bundle(sample_result, tmp_path)
    rows = _read_csv(tmp_path / 'venues.csv')
    assert rows[0] == ['venue', 'citations_from_venue', 'h_index', 'rank_tier',
                       'core_rank', 'ccf_rank', 'icore_rank']
    by_venue = {r[0]: r for r in rows[1:]}
    assert by_venue['ICSE'] == ['ICSE', '2', '120', 'Tier 1 (Top venue)', 'A*', 'A', 'A*']
    # Venue with no ranking info at all → count 0 and empty fields
    assert by_venue['FSE'] == ['FSE', '0', '', '', '', '', '']


def test_bundle_timeline_rows(sample_result, tmp_path):
    build_csv_bundle(sample_result, tmp_path)
    rows = _read_csv(tmp_path / 'timeline.csv')
    # Both tuple and list entries (as loaded back from JSON cache) are accepted
    assert rows == [['year', 'count'], ['2022', '30'], ['2023', '60']]


def test_bundle_empty_result_produces_header_only_files(tmp_path):
    build_csv_bundle({'paper_title': 'Lonely Paper'}, tmp_path)
    for name in BUNDLE_FILES:
        rows = _read_csv(tmp_path / name)
        assert len(rows) == 1, f"{name} should be header-only"


def test_bundle_tolerates_malformed_sections(tmp_path):
    result = {
        'paper_title': 'Odd Data',
        'all_authors': None,
        'venues': {'rankings': {'X': 'not-a-dict'}},
        'yearly_stats': ['bad', (2021,), (2022, 5)],
    }
    build_csv_bundle(result, tmp_path)
    venue_rows = _read_csv(tmp_path / 'venues.csv')
    assert venue_rows[1] == ['X', '0', '', '', '', '', '']
    timeline_rows = _read_csv(tmp_path / 'timeline.csv')
    assert timeline_rows == [['year', 'count'], ['2022', '5']]


# --------------------------------------------------------------------------- #
# export_bundle
# --------------------------------------------------------------------------- #

def test_export_bundle_explicit_dir(sample_result, tmp_path):
    target = export_bundle(sample_result, str(tmp_path / 'my_bundle'))
    assert target == tmp_path / 'my_bundle'
    assert sorted(p.name for p in target.iterdir()) == sorted(BUNDLE_FILES)


def test_export_bundle_default_dir_uses_config(sample_result, isolated_config):
    target = export_bundle(sample_result)
    assert target.is_dir()
    assert isolated_config.get_config_path() in target.parents
    assert target.name.startswith('impact_deep-learning-for-program-repair')
    assert target.name.endswith('_bundle')
    assert sorted(p.name for p in target.iterdir()) == sorted(BUNDLE_FILES)


# --------------------------------------------------------------------------- #
# CLI integration
# --------------------------------------------------------------------------- #

def _fake_result(**overrides):
    result = {
        'paper_title': 'Fake Paper',
        'total_citations': 10,
        'influential_citations_count': 2,
        'analyzed_citations': 10,
        'error': None,
        'impact_stats': {},
        'high_profile_scholars': [],
        'institutions': {},
        'venues': {'rankings': {'ICSE': {'core_rank': 'A*', 'citations': [{'title': 'T'}]}}},
        'yearly_stats': [(2024, 3)],
        'influential_citations': [],
        'methodological_citations': [],
        'all_authors': [{'name': 'Grace Hopper', 'h_index': 60}],
    }
    result.update(overrides)
    return result


def test_cli_bundle_writes_directory(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(citationimpact, 'analyze_paper_impact',
                        lambda **kwargs: _fake_result())
    out_dir = tmp_path / 'bundle_out'
    exit_code = main(['analyze', 'Fake Paper', '--format', 'bundle', '-o', str(out_dir)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert sorted(p.name for p in out_dir.iterdir()) == sorted(BUNDLE_FILES)
    assert str(out_dir) in captured.out
    for name in BUNDLE_FILES:
        assert name in captured.out


def test_cli_bundle_default_dir(monkeypatch, isolated_config, capsys):
    monkeypatch.setattr(citationimpact, 'analyze_paper_impact',
                        lambda **kwargs: _fake_result())
    exit_code = main(['analyze', 'Fake Paper', '-f', 'bundle'])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert 'Bundle written to:' in captured.out
    exports = isolated_config.get_config_path() / 'exports'
    bundles = [p for p in exports.iterdir() if p.is_dir() and p.name.endswith('_bundle')]
    assert len(bundles) == 1
    assert bundles[0].name.startswith('impact_fake-paper')


def test_cli_bundle_rejects_stdout_before_analysis(monkeypatch, capsys):
    def should_not_run(**kwargs):
        raise AssertionError('analyze_paper_impact must not be called')

    monkeypatch.setattr(citationimpact, 'analyze_paper_impact', should_not_run)
    exit_code = main(['analyze', 'Fake Paper', '--format', 'bundle', '-o', '-'])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert 'bundle' in captured.err
    assert 'directory' in captured.err


def test_cli_bundle_error_result_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(citationimpact, 'analyze_paper_impact',
                        lambda **kwargs: _fake_result(error='Paper not found'))
    exit_code = main(['analyze', 'Missing Paper', '-f', 'bundle'])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert 'Paper not found' in captured.err
