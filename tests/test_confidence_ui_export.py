"""Regression tests for the author-disambiguation UI/export stage.

Covers: match-confidence markers + legends in the high-profile scholars
table and the all-authors view, the summary profile-quality line, the
browse-by-name candidate picker in the app, and the markdown export's
Match column + profile-quality line.
"""

import pytest
from rich.console import Console

from citationimpact.ui.app import TerminalUI
from citationimpact.ui.analysis_view import AnalysisView
from citationimpact.ui.components.tables import confidence_marker, CONFIDENCE_LEGEND
from citationimpact.ui.drill_down import show_all_authors_view
from citationimpact.export import build_markdown_report, build_csv_report, _match_label


# --------------------------------------------------------------------------- #
# Helpers (same patterns as tests/test_fixes_ui.py)
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
# confidence_marker mapping
# --------------------------------------------------------------------------- #

def test_confidence_marker_id():
    assert confidence_marker('id') == '[green]✓[/green]'


def test_confidence_marker_verified():
    assert confidence_marker('verified') == '[cyan]≈[/cyan]'


def test_confidence_marker_name():
    assert confidence_marker('name') == '[yellow]?[/yellow]'


def test_confidence_marker_empty_and_unknown():
    assert confidence_marker('') == '[dim]·[/dim]'
    assert confidence_marker(None) == '[dim]·[/dim]'
    assert confidence_marker('bogus') == '[dim]·[/dim]'


def test_confidence_legend_text():
    # The legend must explain all three real markers in one line
    assert 'ID-matched' in CONFIDENCE_LEGEND
    assert 'verified by publication' in CONFIDENCE_LEGEND
    assert 'name-only match (may be a different person with the same name)' in CONFIDENCE_LEGEND


# --------------------------------------------------------------------------- #
# Summary screen: high-profile scholars markers + legend + quality line
# --------------------------------------------------------------------------- #

def _summary_result(author_stats=None, scholars=None):
    return {
        'paper_title': 'Test Paper',
        'total_citations': 10,
        'analyzed_citations': 5,
        'high_profile_scholars': scholars if scholars is not None else [],
        'impact_stats': {
            'author_stats': author_stats or {},
            'institution_stats': {},
            'citation_thresholds': {},
        },
    }


def test_summary_scholar_table_shows_markers_and_legend():
    console = Console(record=True, width=200)
    view = AnalysisView(console)

    result = _summary_result(
        author_stats={'high_profile_count': 2, 'id_matched_count': 1,
                      'verified_count': 0, 'name_only_count': 1},
        scholars=[
            {'name': 'Ada', 'h_index': 50, 'h_index_display': '50',
             'affiliation': 'MIT', 'match_confidence': 'id', 'citing_paper': 'P1'},
            {'name': 'Bob', 'h_index': 40, 'h_index_display': '40',
             'affiliation': 'CMU', 'match_confidence': 'name', 'citing_paper': 'P2'},
        ],
    )

    view._render_summary(result)

    output = console.export_text()
    assert 'Ada ✓' in output
    assert 'Bob ?' in output
    assert 'name-only match (may be a different person with the same name)' in output


def test_summary_scholar_legacy_confidence_renders_dot():
    console = Console(record=True, width=200)
    view = AnalysisView(console)

    result = _summary_result(
        scholars=[{'name': 'Ada', 'h_index': 50, 'h_index_display': '50',
                   'affiliation': 'MIT', 'citing_paper': 'P1'}],
    )

    view._render_summary(result)

    output = console.export_text()
    assert 'Ada ·' in output


def test_summary_profile_quality_line_shown():
    console = Console(record=True, width=200)
    view = AnalysisView(console)

    result = _summary_result(author_stats={
        'high_profile_count': 0,
        'id_matched_count': 2, 'verified_count': 1, 'name_only_count': 3,
    })

    view._render_summary(result)

    output = console.export_text()
    assert 'Author profiles: 2 ID-matched, 1 verified, 3 name-only' in output


def test_summary_profile_quality_line_hidden_for_legacy_results():
    """Cached results predating match-confidence tracking lack the counts —
    the summary must not render a bogus 'Author profiles: 0, 0, 0' line."""
    console = Console(record=True, width=200)
    view = AnalysisView(console)

    result = _summary_result(author_stats={'high_profile_count': 3})

    view._render_summary(result)

    output = console.export_text()
    assert 'Author profiles:' not in output


def test_summary_profile_quality_line_hidden_when_no_authors():
    console = Console(record=True, width=200)
    view = AnalysisView(console)

    result = _summary_result(author_stats={
        'id_matched_count': 0, 'verified_count': 0, 'name_only_count': 0,
    })

    view._render_summary(result)

    assert 'Author profiles:' not in console.export_text()


# --------------------------------------------------------------------------- #
# All-authors view: markers next to names + legend line
# --------------------------------------------------------------------------- #

def test_all_authors_view_shows_markers_and_legend(monkeypatch):
    console = Console(record=True, width=220)
    _patch_prompt(monkeypatch, ['b'])

    result = {
        'all_authors': [
            {'name': 'Ada', 'h_index': 50, 'affiliation': 'MIT',
             'institution_type': 'University', 'citing_paper': 'P1',
             'match_confidence': 'verified'},
            {'name': 'Bob', 'h_index': 10, 'affiliation': 'CMU',
             'institution_type': 'University', 'citing_paper': 'P2',
             'match_confidence': 'name'},
            {'name': 'Cyd', 'h_index': 5, 'affiliation': 'UCL',
             'institution_type': 'University', 'citing_paper': 'P3'},
        ],
    }

    show_all_authors_view(console, result)

    output = console.export_text()
    assert 'Ada ≈' in output
    assert 'Bob ?' in output
    assert 'Cyd ·' in output  # legacy dict without match_confidence
    assert 'name-only match (may be a different person with the same name)' in output


# --------------------------------------------------------------------------- #
# Browse-by-name candidate picker (the reported same-name bug)
# --------------------------------------------------------------------------- #

class _CandidateAPIClient:
    """Fake API client exposing the candidate search + legacy name search."""

    def __init__(self, candidates):
        self.candidates = candidates
        self.candidate_calls = []
        self.search_calls = []
        self.pub_calls = []

    def search_author_candidates(self, author_name, limit=5):
        self.candidate_calls.append((author_name, limit))
        return self.candidates

    def search_author(self, name):
        self.search_calls.append(name)
        return '999'

    def get_author_publications(self, author_id, limit=50):
        self.pub_calls.append(author_id)
        return []


def _patch_api_client(monkeypatch, fake):
    import citationimpact.clients as clients_pkg
    monkeypatch.setattr(clients_pkg, 'get_api_client', lambda **kwargs: fake)


def test_browse_by_name_multiple_candidates_user_picks(monkeypatch, isolated_config, capsys):
    ui = _make_ui(monkeypatch, isolated_config)
    ui.config['data_source'] = 'api'

    fake = _CandidateAPIClient([
        {'author_id': '111', 'name': 'Ann Author', 'affiliation': 'MIT',
         'h_index': 30, 'paper_count': 100},
        {'author_id': '222', 'name': 'Ann Author', 'affiliation': 'Oxford',
         'h_index': 5, 'paper_count': 12},
    ])
    _patch_api_client(monkeypatch, fake)

    # Prompts: author name → picker selection (#2) → press Enter to continue
    _patch_prompt(monkeypatch, ['Ann Author', '2', ''])

    ui.browse_author_papers()

    assert fake.candidate_calls == [('Ann Author', 5)]
    assert fake.pub_calls == ['222'], "picked candidate's unique ID must be used"
    assert fake.search_calls == [], "legacy name search must be skipped"

    # The picker table must show the disambiguating details
    output = capsys.readouterr().out
    assert 'MIT' in output
    assert 'Oxford' in output


def test_browse_by_name_picker_default_is_first_candidate(monkeypatch, isolated_config):
    ui = _make_ui(monkeypatch, isolated_config)
    ui.config['data_source'] = 'api'

    fake = _CandidateAPIClient([
        {'author_id': '111', 'name': 'Ann Author', 'affiliation': 'MIT',
         'h_index': 30, 'paper_count': 100},
        {'author_id': '222', 'name': 'Ann Author', 'affiliation': 'Oxford',
         'h_index': 5, 'paper_count': 12},
    ])
    _patch_api_client(monkeypatch, fake)
    _patch_prompt(monkeypatch, ['Ann Author', '1', ''])

    ui.browse_author_papers()

    assert fake.pub_calls == ['111']
    assert fake.search_calls == []


def test_browse_by_name_single_candidate_used_directly(monkeypatch, isolated_config):
    ui = _make_ui(monkeypatch, isolated_config)
    ui.config['data_source'] = 'api'

    fake = _CandidateAPIClient([
        {'author_id': '111', 'name': 'Ann Author', 'affiliation': 'MIT',
         'h_index': 30, 'paper_count': 100},
    ])
    _patch_api_client(monkeypatch, fake)
    # No picker prompt with a single candidate: name → press Enter
    _patch_prompt(monkeypatch, ['Ann Author', ''])

    ui.browse_author_papers()

    assert fake.pub_calls == ['111']
    assert fake.search_calls == []


def test_browse_by_name_no_candidates_falls_back_to_search(monkeypatch, isolated_config):
    ui = _make_ui(monkeypatch, isolated_config)
    ui.config['data_source'] = 'api'

    fake = _CandidateAPIClient([])
    _patch_api_client(monkeypatch, fake)
    _patch_prompt(monkeypatch, ['Ann Author', ''])

    ui.browse_author_papers()

    # Today's fallback: legacy search_author name resolution
    assert fake.search_calls == ['Ann Author']
    assert fake.pub_calls == ['999']


def test_browse_by_name_client_without_candidate_search_falls_back(monkeypatch, isolated_config):
    """Older/mocked clients without search_author_candidates keep working."""

    class _LegacyClient:
        def __init__(self):
            self.search_calls = []
            self.pub_calls = []

        def search_author(self, name):
            self.search_calls.append(name)
            return '999'

        def get_author_publications(self, author_id, limit=50):
            self.pub_calls.append(author_id)
            return []

    ui = _make_ui(monkeypatch, isolated_config)
    ui.config['data_source'] = 'api'

    fake = _LegacyClient()
    _patch_api_client(monkeypatch, fake)
    _patch_prompt(monkeypatch, ['Ann Author', ''])

    ui.browse_author_papers()

    assert fake.search_calls == ['Ann Author']
    assert fake.pub_calls == ['999']


def test_browse_by_id_skips_candidate_picker(monkeypatch, isolated_config):
    """An explicit S2 author ID must go straight to publications."""
    ui = _make_ui(monkeypatch, isolated_config)
    ui.config['data_source'] = 'api'

    fake = _CandidateAPIClient([
        {'author_id': '111', 'name': 'X', 'affiliation': '', 'h_index': 1, 'paper_count': 1},
    ])
    _patch_api_client(monkeypatch, fake)
    _patch_prompt(monkeypatch, ['1745629', ''])

    ui.browse_author_papers()

    assert fake.candidate_calls == []
    assert fake.pub_calls == ['1745629']


def test_candidate_picker_skips_candidates_without_ids(monkeypatch, isolated_config):
    """Candidates missing author_id are unusable and must be filtered out."""
    ui = _make_ui(monkeypatch, isolated_config)
    ui.config['data_source'] = 'api'

    fake = _CandidateAPIClient([
        {'author_id': '', 'name': 'Ann Author', 'affiliation': 'MIT',
         'h_index': 30, 'paper_count': 100},
        {'author_id': '222', 'name': 'Ann Author', 'affiliation': 'Oxford',
         'h_index': 5, 'paper_count': 12},
    ])
    _patch_api_client(monkeypatch, fake)
    # Only one usable candidate remains → used directly, no picker prompt
    _patch_prompt(monkeypatch, ['Ann Author', ''])

    ui.browse_author_papers()

    assert fake.pub_calls == ['222']
    assert fake.search_calls == []


# --------------------------------------------------------------------------- #
# Markdown export: Match column + profile-quality line
# --------------------------------------------------------------------------- #

def test_match_label_mapping():
    assert _match_label('id') == 'ID'
    assert _match_label('verified') == 'verified'
    assert _match_label('name') == 'name-only'
    assert _match_label('') == 'name-only'
    assert _match_label(None) == 'name-only'


def _export_result():
    return {
        'paper_title': 'Test Paper',
        'total_citations': 10,
        'analyzed_citations': 5,
        'impact_stats': {
            'author_stats': {
                'high_profile_count': 4,
                'id_matched_count': 2, 'verified_count': 1, 'name_only_count': 3,
            },
        },
        'high_profile_scholars': [
            {'name': 'Ada', 'h_index': 50, 'affiliation': 'MIT', 'match_confidence': 'id'},
            {'name': 'Bob', 'h_index': 40, 'affiliation': 'CMU', 'match_confidence': 'verified'},
            {'name': 'Cyd', 'h_index': 30, 'affiliation': 'UCL', 'match_confidence': 'name'},
            {'name': 'Dee', 'h_index': 25, 'affiliation': 'ETH'},  # legacy: no key
        ],
    }


def test_markdown_scholars_table_has_match_column():
    md = build_markdown_report(_export_result())
    assert '| Scholar | h-index | Affiliation | Rankings | Match |' in md
    assert '| Ada | 50 | MIT | — | ID |' in md
    assert '| Bob | 40 | CMU | — | verified |' in md
    assert '| Cyd | 30 | UCL | — | name-only |' in md
    # Legacy scholars without the field are treated as name-only
    assert '| Dee | 25 | ETH | — | name-only |' in md


def test_markdown_profile_quality_line_after_overview():
    md = build_markdown_report(_export_result())
    quality = '*Author profiles: 2 ID-matched, 1 verified, 3 name-only.*'
    assert quality in md
    # The line belongs to the Overview section, before the scholars table
    assert md.index(quality) < md.index('## High-Profile Scholars')


def test_markdown_profile_quality_line_absent_for_legacy_results():
    result = _export_result()
    result['impact_stats']['author_stats'] = {'high_profile_count': 4}
    md = build_markdown_report(result)
    assert 'Author profiles:' not in md


def test_csv_report_unchanged():
    csv_text = build_csv_report(_export_result())
    header = csv_text.strip().splitlines()[0]
    assert header == 'title,authors,venue,year,citations,influential,doi,url'
    assert 'match' not in header.lower()
