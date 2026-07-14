"""Regression tests for UI bug fixes (app, analysis_view, drill_down, settings, prompts)."""

import os

import pytest
from rich.console import Console

from citationimpact.ui.components.prompts import looks_like_author_id
from citationimpact.ui.app import TerminalUI, _display_value
from citationimpact.ui.analysis_view import AnalysisView
from citationimpact.ui.drill_down import show_venue_details
from citationimpact.ui.settings import SettingsManager
from citationimpact.cache import get_author_cache, get_my_publications_cache


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _patch_prompt(monkeypatch, answers):
    """Patch rich Prompt.ask to return queued answers (last one repeats)."""
    from rich.prompt import Prompt

    asked = []

    def fake_ask(*args, **kwargs):
        prompt_text = args[0] if args else ''
        asked.append(prompt_text)
        if len(answers) > 1:
            return answers.pop(0)
        return answers[0]

    monkeypatch.setattr(Prompt, 'ask', fake_ask)
    return asked


def _make_ui(monkeypatch, isolated_config):
    """Build a TerminalUI wired to the isolated (temp-dir) config manager."""
    monkeypatch.setattr('citationimpact.ui.app.ConfigManager', lambda: isolated_config)
    return TerminalUI()


# --------------------------------------------------------------------------- #
# looks_like_author_id (all-letter Google Scholar IDs)
# --------------------------------------------------------------------------- #

def test_gs_id_without_digits_is_recognized():
    assert looks_like_author_id('JicYPdAAAAAJ', 'google_scholar') is True


def test_gs_id_with_digits_is_recognized():
    assert looks_like_author_id('waVL0PgAAAAJ', 'google_scholar') is True


def test_gs_name_is_not_an_id():
    assert looks_like_author_id('Geoffrey Hinton', 'google_scholar') is False


def test_gs_wrong_length_is_not_an_id():
    assert looks_like_author_id('JicYPdAAAAA', 'google_scholar') is False  # 11 chars
    assert looks_like_author_id('JicYPdAAAAAJX', 'google_scholar') is False  # 13 chars


def test_api_ids_unchanged():
    assert looks_like_author_id('1745629', 'api') is True
    assert looks_like_author_id('Geoffrey Hinton', 'api') is False


# --------------------------------------------------------------------------- #
# _display_value (present-but-null keys rendering 'None')
# --------------------------------------------------------------------------- #

def test_display_value_skips_none():
    assert _display_value(None, 2020) == '2020'


def test_display_value_default_for_all_none():
    assert _display_value(None, None) == 'N/A'


def test_display_value_preserves_zero():
    assert _display_value(0) == '0'


def test_display_value_no_args_returns_default():
    assert _display_value() == 'N/A'


# --------------------------------------------------------------------------- #
# My Papers table: cache indicator params + null year rendering
# --------------------------------------------------------------------------- #

class _StubResultCache:
    def __init__(self):
        self.calls = []

    def has_cached_result(self, paper_title, data_source='comprehensive', params=None):
        self.calls.append((paper_title, data_source, params))
        return False


def test_my_publications_checks_cache_with_config_params(monkeypatch, isolated_config, capsys):
    ui = _make_ui(monkeypatch, isolated_config)
    ui.config['h_index_threshold'] = 10
    ui.config['max_citations'] = 50
    ui.config['data_source'] = 'google_scholar'

    stub = _StubResultCache()
    monkeypatch.setattr('citationimpact.cache.get_result_cache', lambda: stub)
    _patch_prompt(monkeypatch, ['b'])

    publications = [{'title': 'Paper T', 'year': None, 'citationCount': 3}]
    ui._display_my_publications(publications, gs_id=None, s2_id='123')

    assert stub.calls, "has_cached_result was never called"
    title, _, params = stub.calls[0]
    assert title == 'Paper T'
    assert params == {
        'h_index_threshold': 10,
        'max_citations': 50,
        'data_source': 'google_scholar',
    }

    # A null year must render as N/A, never the literal 'None'
    output = capsys.readouterr().out
    assert 'None' not in output
    assert 'N/A' in output


def test_cache_indicator_true_with_non_default_settings(monkeypatch, isolated_config, capsys):
    """A result cached under custom settings must show as analyzed (real cache)."""
    from citationimpact.cache import get_result_cache

    ui = _make_ui(monkeypatch, isolated_config)
    ui.config['h_index_threshold'] = 10
    ui.config['max_citations'] = 50
    ui.config['data_source'] = 'google_scholar'

    params = {'h_index_threshold': 10, 'max_citations': 50, 'data_source': 'google_scholar'}
    assert get_result_cache().set('Paper T', params, {'analyzed_citations': 1}) is True

    _patch_prompt(monkeypatch, ['b'])
    ui._display_my_publications([{'title': 'Paper T', 'year': 2020, 'citationCount': 3}],
                                gs_id=None, s2_id='123')

    output = capsys.readouterr().out
    assert '1/1 papers have cached analysis' in output


def test_display_publications_null_year_renders_na(monkeypatch, isolated_config, capsys):
    ui = _make_ui(monkeypatch, isolated_config)
    _patch_prompt(monkeypatch, ['b'])

    ui._display_publications([{'title': 'Paper X', 'year': None, 'citationCount': 7}], 'Some Author')

    output = capsys.readouterr().out
    assert 'None' not in output
    assert 'N/A' in output


# --------------------------------------------------------------------------- #
# Shared client invalidation on data_source change
# --------------------------------------------------------------------------- #

class _DummyClient:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_stale_shared_client_is_discarded(monkeypatch, isolated_config):
    ui = _make_ui(monkeypatch, isolated_config)
    dummy = _DummyClient()
    ui._shared_client = dummy
    ui._shared_client_source = 'api'
    ui.config['data_source'] = 'comprehensive'

    assert ui._get_reusable_client() is None
    assert dummy.closed is True
    assert ui._shared_client is None
    assert ui._shared_client_source is None


def test_matching_shared_client_is_reused(monkeypatch, isolated_config):
    ui = _make_ui(monkeypatch, isolated_config)
    dummy = _DummyClient()
    ui._shared_client = dummy
    ui._shared_client_source = 'api'
    ui.config['data_source'] = 'api'

    assert ui._get_reusable_client() is dummy
    assert dummy.closed is False


# --------------------------------------------------------------------------- #
# Browse-other-authors by name in API mode uses search_author
# --------------------------------------------------------------------------- #

class _FakeAPIClient:
    def __init__(self):
        self.search_calls = []
        self.pub_calls = []

    def search_author(self, name):
        self.search_calls.append(name)
        return '999'

    def get_author_publications(self, author_id, limit=50):
        self.pub_calls.append(author_id)
        return []


def test_browse_author_by_name_resolves_s2_id(monkeypatch, isolated_config):
    ui = _make_ui(monkeypatch, isolated_config)
    ui.config['data_source'] = 'api'

    fake = _FakeAPIClient()
    import citationimpact.clients as clients_pkg
    monkeypatch.setattr(clients_pkg, 'get_api_client', lambda **kwargs: fake)

    # First prompt: author name; later prompts: press Enter to continue
    _patch_prompt(monkeypatch, ['Geoffrey Hinton', ''])

    ui.browse_author_papers()

    assert fake.search_calls == ['Geoffrey Hinton']
    assert fake.pub_calls == ['999']


# --------------------------------------------------------------------------- #
# My Papers: locally-created Google Scholar client is closed, not leaked
# --------------------------------------------------------------------------- #

class _FakeGSClient:
    def __init__(self):
        self.closed = False

    def get_author_publications(self, author_id, limit=50):
        return []

    def close(self):
        self.closed = True


def test_my_papers_closes_local_gs_client(monkeypatch, isolated_config):
    ui = _make_ui(monkeypatch, isolated_config)
    ui.config['default_google_scholar_author_id'] = 'waVL0PgAAAAJ'

    fake = _FakeGSClient()
    import citationimpact.clients.google_scholar as gs_module
    monkeypatch.setattr(gs_module, 'get_google_scholar_client', lambda **kwargs: fake)
    _patch_prompt(monkeypatch, [''])

    ui.my_papers()

    assert fake.closed is True
    assert ui._shared_client is None


# --------------------------------------------------------------------------- #
# Venue details: CORE/CCF columns must not render the literal 'None'
# --------------------------------------------------------------------------- #

def test_venue_details_renders_dash_for_missing_rankings(monkeypatch):
    console = Console(record=True, width=200)
    _patch_prompt(monkeypatch, ['b'])

    result = {
        'venues': {
            'most_common': [('ICSE', 3)],
            'rankings': {
                'ICSE': {
                    'h_index': 50,
                    'rank_tier': 'Tier 1',
                    'core_rank': 'A*',
                    'ccf_rank': None,  # stored explicitly as None
                }
            },
        }
    }

    show_venue_details(console, result)

    output = console.export_text()
    assert 'None' not in output
    assert '—' in output
    assert 'A*' in output


# --------------------------------------------------------------------------- #
# Grant summary: configured h-index threshold, not hardcoded 20
# --------------------------------------------------------------------------- #

def test_grant_summary_uses_configured_threshold(monkeypatch):
    console = Console(record=True, width=200)
    view = AnalysisView(console, {'h_index_threshold': 10})
    _patch_prompt(monkeypatch, [''])

    result = {
        'paper_title': 'Test Paper',
        'total_citations': 42,
        'impact_stats': {
            'summary_statements': [],
            'author_stats': {'high_profile_count': 15, 'max_h_index': 18},
            'institution_stats': {'from_qs_top_100': 2, 'university_percentage': 80},
            'citation_thresholds': {'over_100': 1},
            'highly_cited_citing_papers': [],
            'recent_citations_count': 5,
        },
    }

    view.show_grant_impact_summary(result)

    output = console.export_text()
    assert 'h-index ≥ 10' in output
    assert '≥ 20' not in output


def test_grant_summary_rewrites_analyzer_statement_threshold(monkeypatch):
    """Analyzer-generated summary_statements hardcode 'h-index ≥ 20'; the
    grant view must rewrite them to the configured threshold before display."""
    console = Console(record=True, width=200)
    view = AnalysisView(console, {'h_index_threshold': 10})
    _patch_prompt(monkeypatch, [''])

    result = {
        'paper_title': 'Test Paper',
        'total_citations': 42,
        'impact_stats': {
            'summary_statements': [
                'Recognized by 15 high-profile researchers (h-index ≥ 20), '
                'including scholars with h-index up to 18.'
            ],
            'author_stats': {'high_profile_count': 15, 'max_h_index': 18},
            'institution_stats': {'from_qs_top_100': 2, 'university_percentage': 80},
            'citation_thresholds': {'over_100': 1},
            'highly_cited_citing_papers': [],
            'recent_citations_count': 5,
        },
    }

    view.show_grant_impact_summary(result)

    output = console.export_text()
    assert 'h-index ≥ 10' in output
    assert '≥ 20' not in output


def test_summary_highlights_use_configured_threshold(monkeypatch):
    console = Console(record=True, width=200)
    view = AnalysisView(console, {'h_index_threshold': 10})

    result = {
        'paper_title': 'Test Paper',
        'total_citations': 42,
        'analyzed_citations': 10,
        'impact_stats': {
            'author_stats': {'high_profile_count': 15},
            'institution_stats': {},
            'citation_thresholds': {},
        },
    }

    view._render_summary(result)

    output = console.export_text()
    assert 'h≥10' in output
    assert 'h≥20' not in output


# --------------------------------------------------------------------------- #
# Citation contexts: present-but-null year must not render '(None)'
# --------------------------------------------------------------------------- #

def test_citation_contexts_null_year_renders_na(monkeypatch):
    console = Console(record=True, width=200)
    view = AnalysisView(console)
    _patch_prompt(monkeypatch, [''])

    result = {
        'citation_insights': {
            'intent_counts': {},
            'context_samples': [
                {'context': 'We build on this method.', 'title': 'Citing Paper',
                 'url': '', 'year': None, 'is_influential': False},
            ],
        }
    }

    view.show_citation_contexts(result)

    output = console.export_text()
    assert 'None' not in output
    assert '(N/A)' in output


# --------------------------------------------------------------------------- #
# Export results: message survives (pause) and shows the absolute path
# --------------------------------------------------------------------------- #

def test_export_results_pauses_and_prints_abspath(monkeypatch, tmp_path):
    console = Console(record=True, width=300)
    view = AnalysisView(console)

    target = str(tmp_path / 'report.json')
    # New flow prompts for: format, filename, then the pause
    asked = _patch_prompt(monkeypatch, ['json', target, ''])

    result = {
        'paper_title': 'Test Paper',
        'total_citations': 42,
        'analyzed_citations': 10,
    }

    view.export_results(result)

    assert os.path.exists(target)
    output = console.export_text()
    assert os.path.abspath(target) in output
    # A pause prompt must follow the save message so it isn't wiped
    assert any('Press Enter' in str(p) for p in asked)


# --------------------------------------------------------------------------- #
# Settings: clearing author profiles keeps the My Papers publications cache
# --------------------------------------------------------------------------- #

def test_clear_author_profiles_preserves_publications(isolated_config):
    config = isolated_config.get_all()
    config['default_google_scholar_author_id'] = 'waVL0PgAAAAJ'

    manager = SettingsManager(Console(width=120), isolated_config, config)

    pub_cache = get_my_publications_cache()
    author_cache = get_author_cache()

    pubs = [{'title': 'My expensive scrape'}]
    assert pub_cache.set('waVL0PgAAAAJ', pubs, 'google_scholar') is True
    assert author_cache.set('some_author', 'api', {'name': 'Some Author'}, []) is True

    cleared = manager._clear_author_profiles(author_cache)

    # The author profile is gone, the publications cache survived
    assert cleared == 1
    assert author_cache.get('some_author', 'api') is None
    restored = pub_cache.get('waVL0PgAAAAJ', 'google_scholar')
    assert restored == pubs
