"""Regression tests for the citation tree view (tree_view + analysis_view wiring)."""

from rich.console import Console

from citationimpact.ui.analysis_view import AnalysisView
from citationimpact.ui.tree_view import (
    MAX_LEAVES_PER_GROUP,
    build_citation_tree_data,
    build_text_tree,
    show_citation_tree,
    _leaf_text,
)


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


def _sample_result():
    """A result dict exercising influential citations + all_authors merging."""
    return {
        'paper_title': 'My Analyzed Paper',
        'influential_citations': [
            {
                'citing_paper_title': 'Deep Learning for Bugs',
                'venue': 'ICSE',
                'year': 2024,
                'url': 'https://example.org/dl-bugs',
                'paper_id': 'abc123',
                'citation_count': 12,
            },
            {
                'citing_paper_title': 'Old Influential Study',
                'venue': 'FSE',
                'year': 2022,
                'url': '',
                'paper_id': '',
                'citation_count': 0,
            },
        ],
        'all_authors': [
            # Duplicate of the first influential citation (case differs)
            {
                'name': 'Alice Smith',
                'citing_paper': 'DEEP LEARNING FOR BUGS',
                'paper_url': 'https://example.org/dl-bugs',
                'paper_id': 'abc123',
                'year': 2024,
                'venue': 'ICSE',
                'institution_type': 'University',
                'paper_citations': 12,
            },
            # New paper, industry author
            {
                'name': 'Bob Jones',
                'citing_paper': 'A Survey of Testing',
                'paper_url': '',
                'paper_id': 'def456',
                'year': 2024,
                'venue': 'TSE',
                'institution_type': 'Industry',
                'paper_citations': 3,
            },
            # New paper with no year and no institution type
            {
                'name': 'Carol White',
                'citing_paper': 'Preprint Without Year',
                'paper_url': '',
                'paper_id': '',
                'year': 0,
                'venue': 'Unknown',
                'institution_type': '',
                'paper_citations': 0,
            },
        ],
    }


# --------------------------------------------------------------------------- #
# build_citation_tree_data: gathering + dedup
# --------------------------------------------------------------------------- #

def test_dedup_by_lowercased_title():
    groups = build_citation_tree_data(_sample_result(), group_by='year')
    all_titles = [p['title'].lower() for papers in groups.values() for p in papers]
    assert all_titles.count('deep learning for bugs') == 1
    assert len(all_titles) == 4  # 2 influential + 2 new from all_authors


def test_influential_flag_survives_dedup():
    groups = build_citation_tree_data(_sample_result(), group_by='year')
    papers_2024 = groups['2024']
    dl = next(p for p in papers_2024 if p['title'] == 'Deep Learning for Bugs')
    assert dl['is_influential'] is True
    survey = next(p for p in papers_2024 if p['title'] == 'A Survey of Testing')
    assert survey['is_influential'] is False


def test_paper_dict_fields():
    groups = build_citation_tree_data(_sample_result(), group_by='year')
    dl = groups['2024'][0]
    assert dl['url'] == 'https://example.org/dl-bugs'
    assert dl['paper_id'] == 'abc123'
    assert dl['venue'] == 'ICSE'
    assert dl['citation_count'] == 12


def test_handles_citation_objects_not_just_dicts():
    class Citation:
        citing_paper_title = 'Object Citation'
        venue = 'NeurIPS'
        year = 2023
        url = ''
        paper_id = 'xyz'
        citation_count = 5

    result = {'influential_citations': [Citation()], 'all_authors': []}
    groups = build_citation_tree_data(result, group_by='year')
    assert list(groups) == ['2023']
    assert groups['2023'][0]['title'] == 'Object Citation'
    assert groups['2023'][0]['is_influential'] is True


def test_empty_result_returns_empty_dict():
    assert build_citation_tree_data({}, group_by='year') == {}
    assert build_citation_tree_data({}, group_by='venue') == {}
    assert build_citation_tree_data({}, group_by='institution') == {}


# --------------------------------------------------------------------------- #
# build_citation_tree_data: grouping and ordering
# --------------------------------------------------------------------------- #

def test_group_by_year_descending_unknown_last():
    groups = build_citation_tree_data(_sample_result(), group_by='year')
    assert list(groups) == ['2024', '2022', 'Unknown']
    assert len(groups['2024']) == 2
    assert len(groups['2022']) == 1
    assert groups['Unknown'][0]['title'] == 'Preprint Without Year'


def test_group_by_venue():
    groups = build_citation_tree_data(_sample_result(), group_by='venue')
    # Largest groups first (all size 1 here → alphabetical), Unknown last
    assert list(groups) == ['FSE', 'ICSE', 'TSE', 'Unknown']
    assert groups['ICSE'][0]['title'] == 'Deep Learning for Bugs'


def test_group_by_institution_via_all_authors_lookup():
    groups = build_citation_tree_data(_sample_result(), group_by='institution')
    labels = list(groups)
    # Unknown bucket must always come last
    assert labels[-1] == 'Unknown'
    assert set(labels) == {'University', 'Industry', 'Unknown'}
    assert groups['University'][0]['title'] == 'Deep Learning for Bugs'
    assert groups['Industry'][0]['title'] == 'A Survey of Testing'
    # 'Old Influential Study' has no all_authors entry; 'Preprint Without
    # Year' has an empty institution_type — both land in Unknown
    unknown_titles = {p['title'] for p in groups['Unknown']}
    assert unknown_titles == {'Old Influential Study', 'Preprint Without Year'}


def test_institution_lookup_prefers_informative_type():
    result = {
        'influential_citations': [],
        'all_authors': [
            {'name': 'A', 'citing_paper': 'Paper P', 'institution_type': 'Unknown'},
            {'name': 'B', 'citing_paper': 'Paper P', 'institution_type': 'Government'},
        ],
    }
    groups = build_citation_tree_data(result, group_by='institution')
    assert list(groups) == ['Government']


def test_unknown_group_by_falls_back_to_year():
    groups = build_citation_tree_data(_sample_result(), group_by='nonsense')
    assert list(groups) == ['2024', '2022', 'Unknown']


def test_order_within_group_preserved():
    groups = build_citation_tree_data(_sample_result(), group_by='year')
    titles_2024 = [p['title'] for p in groups['2024']]
    # Influential citations are gathered first, then all_authors papers
    assert titles_2024 == ['Deep Learning for Bugs', 'A Survey of Testing']


def test_non_numeric_year_sorts_with_unknown_last():
    result = {
        'influential_citations': [],
        'all_authors': [
            {'name': 'A', 'citing_paper': 'P1', 'year': 'N/A', 'venue': 'V'},
            {'name': 'B', 'citing_paper': 'P2', 'year': 2020, 'venue': 'V'},
        ],
    }
    groups = build_citation_tree_data(result, group_by='year')
    assert list(groups) == ['2020', 'Unknown']


# --------------------------------------------------------------------------- #
# Leaf formatting
# --------------------------------------------------------------------------- #

def test_leaf_text_rich_has_link_and_star():
    paper = {'title': 'T', 'url': 'https://x.org/t', 'venue': 'ICSE',
             'citation_count': 4, 'is_influential': True}
    text = _leaf_text(paper, rich_markup=True)
    assert '[link=https://x.org/t]T[/link]' in text
    assert '(ICSE)' in text
    assert '4 cites' in text
    assert '⭐' in text


def test_leaf_text_rich_falls_back_to_paper_id_link():
    paper = {'title': 'T', 'url': '', 'paper_id': 'abc', 'venue': '',
             'citation_count': 0, 'is_influential': False}
    text = _leaf_text(paper, rich_markup=True)
    assert '[link=https://www.semanticscholar.org/paper/abc]T[/link]' in text
    assert '⭐' not in text


def test_leaf_text_plain_has_no_markup():
    paper = {'title': 'T', 'url': 'https://x.org/t', 'venue': 'ICSE',
             'citation_count': 4, 'is_influential': True}
    text = _leaf_text(paper, rich_markup=False)
    assert text == 'T (ICSE) [4 cites] ⭐'


def test_leaf_title_truncated_to_70_chars():
    long_title = 'X' * 100
    paper = {'title': long_title, 'venue': '', 'citation_count': 0}
    text = _leaf_text(paper, rich_markup=False)
    assert text == 'X' * 67 + '...'
    assert len(text) == 70


def test_leaf_text_zero_cites_and_unknown_venue_omitted():
    paper = {'title': 'T', 'venue': 'Unknown', 'citation_count': 0,
             'is_influential': False}
    assert _leaf_text(paper, rich_markup=False) == 'T'


# --------------------------------------------------------------------------- #
# build_text_tree
# --------------------------------------------------------------------------- #

def test_text_tree_structure_year():
    text = build_text_tree(_sample_result(), group_by='year')
    lines = text.splitlines()
    assert lines[0] == 'My Analyzed Paper'
    assert '├── 2024 — 2 citations' in lines
    assert '├── 2022 — 1 citation' in lines  # singular
    assert '└── Unknown — 1 citation' in lines
    # Leaves are indented under their group with box-drawing connectors
    assert '│   ├── Deep Learning for Bugs (ICSE) [12 cites] ⭐' in lines
    assert '│   └── A Survey of Testing (TSE) [3 cites]' in lines
    # Last group's children use spaces, not a vertical guide
    assert '    └── Preprint Without Year' in lines


def test_text_tree_has_no_rich_markup():
    text = build_text_tree(_sample_result(), group_by='venue')
    assert '[link=' not in text
    assert '[bold' not in text
    assert '[dim]' not in text


def test_text_tree_empty_result():
    text = build_text_tree({'paper_title': 'Lonely Paper'})
    assert text == 'Lonely Paper\n└── (no citing papers)'


def test_text_tree_includes_all_papers_no_cap():
    many = [{'name': f'A{i}', 'citing_paper': f'Paper {i}', 'year': 2024,
             'venue': 'V'} for i in range(MAX_LEAVES_PER_GROUP + 5)]
    result = {'paper_title': 'Root', 'influential_citations': [], 'all_authors': many}
    text = build_text_tree(result, group_by='year')
    for i in range(MAX_LEAVES_PER_GROUP + 5):
        assert f'Paper {i}' in text


def test_text_tree_institution_grouping():
    text = build_text_tree(_sample_result(), group_by='institution')
    assert 'University — 1 citation' in text
    assert 'Industry — 1 citation' in text
    assert 'Unknown — 2 citations' in text


# --------------------------------------------------------------------------- #
# show_citation_tree (interactive rendering)
# --------------------------------------------------------------------------- #

def test_show_citation_tree_renders_year_view(monkeypatch):
    console = Console(record=True, width=200)
    asked = _patch_prompt(monkeypatch, ['b'])

    show_citation_tree(console, _sample_result())

    output = console.export_text()
    assert 'CITATION TREE' in output
    assert 'My Analyzed Paper' in output
    assert '2024' in output
    assert '2 citations' in output
    assert 'Deep Learning for Bugs' in output
    assert '⭐' in output
    assert '4 citing papers grouped by Year' in output
    # Regrouping options are offered
    assert 'Group by Venue' in output
    assert asked  # the prompt loop ran


def test_show_citation_tree_switches_groupings(monkeypatch):
    console = Console(record=True, width=200)
    _patch_prompt(monkeypatch, ['v', 'i', 'b'])

    show_citation_tree(console, _sample_result())

    output = console.export_text()
    assert 'grouped by Year' in output
    assert 'grouped by Venue' in output
    assert 'grouped by Institution Type' in output
    assert 'ICSE' in output
    assert 'Industry' in output


def test_show_citation_tree_empty_result(monkeypatch):
    console = Console(record=True, width=200)
    asked = _patch_prompt(monkeypatch, [''])

    show_citation_tree(console, {'paper_title': 'Empty'})

    output = console.export_text()
    assert 'No citing papers found' in output
    assert any('Press Enter' in str(p) for p in asked)


def test_show_citation_tree_caps_leaves_per_group(monkeypatch):
    console = Console(record=True, width=200)
    _patch_prompt(monkeypatch, ['b'])

    many = [{'name': f'A{i}', 'citing_paper': f'Paper number {i:03d}', 'year': 2024,
             'venue': 'V'} for i in range(MAX_LEAVES_PER_GROUP + 5)]
    result = {'paper_title': 'Root', 'all_authors': many}

    show_citation_tree(console, result)

    output = console.export_text()
    assert 'and 5 more' in output


def test_show_citation_tree_title_with_brackets_is_escaped(monkeypatch):
    """A citing paper title containing [brackets] must not crash markup."""
    console = Console(record=True, width=200)
    _patch_prompt(monkeypatch, ['b'])

    result = {
        'paper_title': 'Root [v2]',
        'all_authors': [
            {'name': 'A', 'citing_paper': 'Fuzzing [extended abstract]',
             'year': 2024, 'venue': 'ISSTA [tool track]'},
        ],
    }

    show_citation_tree(console, result)

    output = console.export_text()
    assert 'Fuzzing [extended abstract]' in output
    assert 'Root [v2]' in output


# --------------------------------------------------------------------------- #
# analysis_view wiring: menu option 8 opens the tree
# --------------------------------------------------------------------------- #

def test_display_results_menu_lists_citation_tree(monkeypatch):
    console = Console(record=True, width=200)
    view = AnalysisView(console)
    _patch_prompt(monkeypatch, ['b'])

    view.display_results({'paper_title': 'Test Paper', 'total_citations': 1})

    output = console.export_text()
    assert 'Citation Tree' in output


def test_display_results_option_8_opens_tree(monkeypatch):
    console = Console(record=True, width=200)
    view = AnalysisView(console)
    # '8' opens the tree, 'b' leaves the tree, 'b' leaves the results menu
    _patch_prompt(monkeypatch, ['8', 'b', 'b'])

    view.display_results(_sample_result())

    output = console.export_text()
    assert 'CITATION TREE' in output
    assert 'Deep Learning for Bugs' in output
