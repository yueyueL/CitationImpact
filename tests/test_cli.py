"""Tests for the non-interactive CLI."""

import citationimpact
from citationimpact.cli import main


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
        'venues': {},
        'yearly_stats': [],
        'influential_citations': [],
        'methodological_citations': [],
        'all_authors': [],
    }
    result.update(overrides)
    return result


def test_analyze_writes_markdown_to_stdout(monkeypatch, capsys):
    monkeypatch.setattr(citationimpact, 'analyze_paper_impact',
                        lambda **kwargs: _fake_result())
    exit_code = main(['analyze', 'Fake Paper', '--format', 'md', '-o', '-'])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert '# Citation Impact Report' in captured.out
    assert 'Fake Paper' in captured.out


def test_analyze_writes_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(citationimpact, 'analyze_paper_impact',
                        lambda **kwargs: _fake_result())
    out_file = tmp_path / 'report.tex'
    exit_code = main(['analyze', 'Fake Paper', '-f', 'latex', '-o', str(out_file)])
    assert exit_code == 0
    assert out_file.exists()
    assert 'Citation Impact' in out_file.read_text()


def test_analyze_error_result_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(citationimpact, 'analyze_paper_impact',
                        lambda **kwargs: _fake_result(error='Paper not found'))
    exit_code = main(['analyze', 'Missing Paper', '-o', '-'])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert 'Paper not found' in captured.err


def test_analyze_passes_flags_through(monkeypatch):
    seen = {}

    def fake_analyze(**kwargs):
        seen.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(citationimpact, 'analyze_paper_impact', fake_analyze)
    main(['analyze', 'Fake Paper', '--max-citations', '42',
          '--h-index-threshold', '15', '--data-source', 'api',
          '--no-cache', '-o', '-'])
    assert seen['max_citations'] == 42
    assert seen['h_index_threshold'] == 15
    assert seen['data_source'] == 'api'
    assert seen['use_cache'] is False


def test_cache_list_empty(capsys):
    exit_code = main(['cache', 'list'])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert 'No cached analyses' in captured.out


def test_analyze_closes_client(monkeypatch):
    closed = []

    class FakeClient:
        def close(self):
            closed.append(True)

    monkeypatch.setattr(citationimpact, 'analyze_paper_impact',
                        lambda **kwargs: _fake_result(_client=FakeClient()))
    main(['analyze', 'Fake Paper', '-o', '-'])
    assert closed == [True]
