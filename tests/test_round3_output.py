"""Regression tests for round-3 CLI output fixes."""

import json

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


def test_stdout_report_keeps_progress_off_stdout(monkeypatch, capsys):
    """With '-o -', pipeline progress prints must go to stderr, not stdout."""

    def noisy_analyze(**kwargs):
        # Simulates analyzer banners and cache-hit messages printed to stdout.
        print("[Cache] Using cached result from 2026-07-12")
        print("ANALYSIS COMPLETE")
        return _fake_result()

    monkeypatch.setattr(citationimpact, 'analyze_paper_impact', noisy_analyze)
    exit_code = main(['analyze', 'Fake Paper', '--format', 'json', '-o', '-'])
    captured = capsys.readouterr()
    assert exit_code == 0
    # stdout is a clean, parseable report
    parsed = json.loads(captured.out)
    assert parsed['paper_title'] == 'Fake Paper'
    # progress noise landed on stderr instead
    assert '[Cache]' in captured.err
    assert 'ANALYSIS COMPLETE' in captured.err


def test_file_report_keeps_progress_on_stdout(monkeypatch, tmp_path, capsys):
    """Without '-o -', progress prints still appear on stdout as before."""

    def noisy_analyze(**kwargs):
        print("[Cache] Using cached result from 2026-07-12")
        return _fake_result()

    monkeypatch.setattr(citationimpact, 'analyze_paper_impact', noisy_analyze)
    out_file = tmp_path / 'report.md'
    exit_code = main(['analyze', 'Fake Paper', '-f', 'md', '-o', str(out_file)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert out_file.exists()
    assert '[Cache]' in captured.out


def test_explicit_zero_flags_are_not_replaced_by_config(monkeypatch):
    """--h-index-threshold 0 / --max-citations 0 must reach the analyzer as 0."""
    seen = {}

    def fake_analyze(**kwargs):
        seen.update(kwargs)
        return _fake_result()

    monkeypatch.setattr(citationimpact, 'analyze_paper_impact', fake_analyze)
    main(['analyze', 'Fake Paper', '--h-index-threshold', '0',
          '--max-citations', '0', '-o', '-'])
    assert seen['h_index_threshold'] == 0
    assert seen['max_citations'] == 0


def test_omitted_flags_still_fall_back_to_config(monkeypatch, isolated_config):
    """Flags left unset keep resolving from config."""
    seen = {}

    def fake_analyze(**kwargs):
        seen.update(kwargs)
        return _fake_result()

    isolated_config.set('h_index_threshold', 33)
    isolated_config.set('max_citations', 77)
    monkeypatch.setattr(citationimpact, 'analyze_paper_impact', fake_analyze)
    main(['analyze', 'Fake Paper', '-o', '-'])
    assert seen['h_index_threshold'] == 33
    assert seen['max_citations'] == 77
