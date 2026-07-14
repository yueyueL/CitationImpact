"""Regression tests for round-3 UI fixes (markup escaping + GS ID heuristic)."""

from rich.console import Console

from citationimpact.ui.analysis_view import AnalysisView
from citationimpact.ui.app import TerminalUI
from citationimpact.ui.components.prompts import looks_like_author_id


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
# show_citation_contexts: untrusted quotes/titles must be markup-escaped
# --------------------------------------------------------------------------- #

def _contexts_result():
    return {
        'citation_insights': {
            'intent_counts': {},
            'context_samples': [
                {
                    # Lowercase bracketed tokens were silently dropped;
                    # closing-tag-like tokens raised MarkupError pre-fix
                    'context': 'As shown in [table 1], x[i] converges [sic] [/INST]',
                    'title': 'Prompt Templates [/spec] in LLM Papers',
                    'url': 'https://example.org/p1',
                    'year': 2025,
                    'is_influential': True,
                },
                {
                    'context': 'We adopt their method [/cite] directly.',
                    'title': None,  # present-but-null title must not crash
                    'url': '',
                    'year': None,
                },
            ],
        },
    }


def test_citation_contexts_bracketed_tokens_do_not_crash(monkeypatch):
    console = Console(record=True, width=200)
    view = AnalysisView(console)
    _patch_prompt(monkeypatch, [''])

    # Pre-fix: rich.errors.MarkupError propagated out of this call
    view.show_citation_contexts(_contexts_result())

    output = console.export_text()
    assert '[table 1]' in output
    assert 'x[i]' in output
    assert '[sic]' in output
    assert '[/INST]' in output
    assert '[/spec]' in output
    assert '[/cite]' in output


def test_citation_contexts_null_title_renders_unknown(monkeypatch):
    console = Console(record=True, width=200)
    view = AnalysisView(console)
    _patch_prompt(monkeypatch, [''])

    view.show_citation_contexts(_contexts_result())

    output = console.export_text()
    assert 'Unknown' in output
    assert 'None' not in output


# --------------------------------------------------------------------------- #
# _select_author_candidate: API names/affiliations must be markup-escaped
# --------------------------------------------------------------------------- #

class _FakeCandidateClient:
    def search_author_candidates(self, name, limit=5):
        return [
            {
                'author_id': 'id-1',
                'name': 'Alice Smith [applied ml group]',
                'affiliation': 'Dept. of CS [systems lab]',
                'h_index': 12,
                'paper_count': 40,
            },
            {
                'author_id': 'id-2',
                # Closing-tag-like token raised MarkupError on table print
                'name': 'Bob [/x] Jones',
                'affiliation': None,
                'h_index': 3,
                'paper_count': 9,
            },
        ]


def test_author_picker_escapes_candidate_fields(monkeypatch, isolated_config):
    ui = _make_ui(monkeypatch, isolated_config)
    ui.console = Console(record=True, width=200)
    monkeypatch.setattr('citationimpact.clients.get_api_client',
                        lambda **kwargs: _FakeCandidateClient())
    _patch_prompt(monkeypatch, ['2'])

    # Pre-fix: printing the picker table raised rich.errors.MarkupError
    selected = ui._select_author_candidate('Smith [test]')

    assert selected == 'id-2'
    output = ui.console.export_text()
    assert 'Alice Smith [applied ml group]' in output
    assert '[systems lab]' in output
    assert '[/x]' in output


# --------------------------------------------------------------------------- #
# looks_like_author_id: 12-letter surnames are names, real GS IDs still match
# --------------------------------------------------------------------------- #

def test_gs_twelve_letter_surname_is_not_an_id():
    assert looks_like_author_id('Ramachandran', 'google_scholar') is False
    assert looks_like_author_id('Christiansen', 'google_scholar') is False


def test_gs_digitless_id_with_aaaj_suffix_still_recognized():
    assert looks_like_author_id('JicYPdAAAAAJ', 'google_scholar') is True


def test_gs_id_with_digit_or_separator_still_recognized():
    assert looks_like_author_id('waVL0PgAAAAJ', 'google_scholar') is True
    assert looks_like_author_id('a1b2c3d4e5f6', 'google_scholar') is True
    assert looks_like_author_id('ab-cd_efghij', 'google_scholar') is True
