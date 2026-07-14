"""Tests for citationimpact.html_report (self-contained HTML report builder)."""

import re

import pytest

from citationimpact.export import (
    EXPORT_FORMATS,
    build_report,
    default_export_filename,
    export_report,
)
from citationimpact.html_report import (
    COUNTRY_CENTROIDS,
    COUNTRY_NAMES,
    build_html_report,
)
from citationimpact.models import Citation


@pytest.fixture
def full_result():
    return {
        'paper_title': 'Deep Learning for Program Repair',
        'total_citations': 250,
        'influential_citations_count': 18,
        'analyzed_citations': 100,
        'h_index_threshold': 20,
        'error': None,
        'impact_stats': {
            'summary_statements': ['Cited by 12 papers with 100+ citations.'],
            'author_stats': {
                'total_unique_authors': 70,
                'high_profile_count': 9,
                'max_h_index': 88,
                'id_matched_count': 4,
                'verified_count': 3,
                'name_only_count': 2,
            },
            'institution_stats': {'from_qs_top_100': 5, 'countries_count': 3},
            'citation_thresholds': {'over_100': 12},
            'highly_cited_citing_papers': [
                {'title': 'A Highly Cited Paper', 'citations': 400, 'year': 2023,
                 'venue': 'ICSE', 'url': 'https://example.com/p'},
            ],
            'recent_citations_count': 40,
        },
        'high_profile_scholars': [
            {'name': 'Grace Hopper', 'h_index': 60, 'affiliation': 'Yale',
             'google_scholar_id': 'gh123', 'university_rank': 18,
             'country': 'US', 'match_confidence': 'id'},
            {'name': 'Ada <Lovelace>', 'h_index': 45, 'affiliation': 'Cambridge & Co',
             'country': 'GB', 'match_confidence': 'name'},
        ],
        'institutions': {'University': 50, 'Industry': 12, 'Government': 3, 'Other': 5},
        'venues': {
            'total': 90, 'unique': 30, 'top_tier_percentage': 42.0,
            'most_common': [('ICSE', 8), ('FSE', 5)],
            'rankings': {'ICSE': {'core_rank': 'A*', 'ccf_rank': 'A'}, 'FSE': {}},
        },
        'yearly_stats': [(2022, 30), (2023, 60), (2024, 45)],
        'self_citation_stats': {'independent_count': 84, 'independent_percentage': 84.0},
        'field_normalized': {'fwci': 4.31, 'citation_percentile': 0.97,
                             'is_top_1_percent': False},
        'citation_insights': {
            'intent_counts': {'methodology': 14, 'background': 9, 'result': 3},
            'context_samples': [
                {'context': 'We adopt the repair pipeline of <this work>.',
                 'title': 'Repair Transformers', 'year': 2023},
            ],
        },
        'countries': {'counts': {'US': 30, 'CN': 18, 'DE': 6, 'XX': 2}, 'unknown': 4},
        'influential_citations': [
            Citation(
                citing_paper_title='Repair Transformers',
                citing_authors=['A. Turing'],
                venue='FSE', year=2023, is_influential=True,
                contexts=[], intents=['Methodology'],
                doi='10.1145/x', url='https://example.com/c', citation_count=55,
            ),
        ],
        'all_authors': [
            {'name': 'Grace Hopper', 'citing_paper': 'Repair Transformers',
             'paper_url': 'https://example.com/c', 'paper_id': 'p1',
             'venue': 'FSE', 'year': 2023, 'paper_citations': 55},
        ],
    }


@pytest.fixture
def full_html(full_result):
    return build_html_report(full_result)


# ------------------------------------------------------------------ structure

def test_report_is_single_html_document(full_html):
    assert full_html.startswith('<!DOCTYPE html>')
    assert full_html.count('<html') == 1
    assert full_html.rstrip().endswith('</html>')


def test_header_has_title_and_counts(full_html):
    assert 'Deep Learning for Program Repair' in full_html
    assert 'Citation Impact Report' in full_html
    assert '250' in full_html  # total citations
    assert '100 analyzed' in full_html


def test_stat_tiles(full_html):
    assert 'Total citations' in full_html
    assert 'FWCI' in full_html
    assert '4.31' in full_html
    assert 'High-profile scholars' in full_html
    assert 'Independent citations' in full_html
    assert '84%' in full_html
    assert 'Countries' in full_html


def test_impact_statements_listed(full_html):
    assert 'Impact Statements' in full_html
    assert 'Cited by 12 papers with 100+ citations.' in full_html


def test_timeline_bars_and_tooltips(full_html):
    # One rounded-top column path per year with a nonzero count
    assert full_html.count('<path class="mark"') == 3
    assert 'data-tip="2023 — 60 citations"' in full_html
    # Keyboard-focusable hit targets
    assert 'tabindex="0"' in full_html


def test_world_map_dot_for_known_country(full_html):
    assert 'data-iso="US"' in full_html
    assert 'data-iso="CN"' in full_html
    assert 'United States — 30 citing authors' in full_html


def test_world_map_unknown_code_noted_not_crashing(full_html):
    # 'XX' has no centroid: it goes to the note and the table, never the map
    assert 'data-iso="XX"' not in full_html
    assert 'Other/unknown' in full_html
    assert 'XX (2)' in full_html


def test_country_table_is_sorted_fallback(full_html):
    # The accessible table lists countries by descending count
    us = full_html.index('<td>United States</td>')
    cn = full_html.index('<td>China</td>')
    de = full_html.index('<td>Germany</td>')
    assert us < cn < de
    # The 'unknown' bucket is shown too
    assert '>Unknown</td>' in full_html


def test_intents_and_context_quotes(full_html):
    assert 'How This Work Is Used' in full_html
    assert 'Methodology' in full_html
    assert 'hbar-fill' in full_html
    assert '<blockquote' in full_html
    assert 'We adopt the repair pipeline of &lt;this work&gt;.' in full_html
    assert 'Repair Transformers (2023)' in full_html


def test_institution_breakdown_with_percentages(full_html):
    assert 'Institution Breakdown' in full_html
    # 50 of 70 = 71%
    assert '50 (71%)' in full_html
    assert 'Industry' in full_html


def test_scholars_table_links_and_match_chips(full_html):
    assert 'https://scholar.google.com/citations?user=gh123' in full_html
    assert 'ID-matched' in full_html
    assert 'name-only' in full_html
    assert 'QS #18' in full_html
    # Scholar names are escaped
    assert 'Ada &lt;Lovelace&gt;' in full_html
    assert 'Cambridge &amp; Co' in full_html


def test_venues_table_with_rank_chips(full_html):
    assert 'Top Citing Venues' in full_html
    assert 'CORE A*' in full_html
    assert 'CCF A' in full_html
    assert '30 unique venues' in full_html


def test_tree_section_contains_citing_paper(full_html):
    assert 'Citation Tree' in full_html
    assert '<details' in full_html
    assert 'Repair Transformers' in full_html
    assert 'https://example.com/c' in full_html


def test_footer_mentions_generator(full_html):
    assert 'Generated by CitationImpact v' in full_html


# ------------------------------------------------------------------ escaping

def test_title_with_script_tag_is_escaped():
    html = build_html_report(
        {'paper_title': 'Attack <script>alert("pwn")</script> & Defense'})
    assert '<script>alert(' not in html
    assert '&lt;script&gt;alert(&quot;pwn&quot;)&lt;/script&gt;' in html
    assert 'Attack' in html and '&amp; Defense' in html


def test_javascript_url_scheme_never_becomes_link():
    # A poisoned citing-paper URL (external API / cache JSON) must not
    # yield a clickable javascript: anchor in the citation tree.
    html = build_html_report({
        'paper_title': 'X',
        'influential_citations': [
            {'citing_paper_title': 'Poisoned Paper',
             'url': 'javascript:alert(1)', 'year': 2024},
        ],
    })
    assert 'Poisoned Paper' in html
    assert 'javascript:' not in html.lower()


def test_unsafe_url_falls_back_to_semantic_scholar_link():
    # Scheme check is case/whitespace-insensitive; with a paper_id the
    # link degrades to the fixed https semanticscholar.org URL.
    html = build_html_report({
        'paper_title': 'X',
        'influential_citations': [
            {'citing_paper_title': 'Poisoned Paper', 'paper_id': 'abc123',
             'url': '  JaVaScRiPt:alert(1)', 'year': 2024},
        ],
    })
    assert 'javascript' not in html.lower()
    assert 'href="https://www.semanticscholar.org/paper/abc123"' in html


def test_data_url_scheme_not_linked():
    html = build_html_report({
        'paper_title': 'X',
        'influential_citations': [
            {'citing_paper_title': 'Poisoned Paper',
             'url': 'data:text/html,<script>alert(1)</script>', 'year': 2024},
        ],
    })
    assert 'href="data:' not in html
    assert '<script>alert(' not in html


def test_http_and_https_urls_still_linked():
    html = build_html_report({
        'paper_title': 'X',
        'influential_citations': [
            {'citing_paper_title': 'Plain HTTP Paper',
             'url': 'http://example.com/a', 'year': 2024},
            {'citing_paper_title': 'HTTPS Paper',
             'url': 'https://example.com/b', 'year': 2023},
        ],
    })
    assert 'href="http://example.com/a"' in html
    assert 'href="https://example.com/b"' in html


# ------------------------------------------------------------ self-contained

def test_no_external_resources(full_html):
    # No stylesheet links, no script src, no CSS url() fetches
    assert '<link' not in full_html
    assert re.search(r'<script[^>]*\bsrc\s*=', full_html) is None
    assert 'url(' not in full_html
    # Only anchors may point at http(s) (paper / scholar profile links)
    for match in re.finditer(r'https?://', full_html):
        preceding = full_html[max(0, match.start() - 60):match.start()]
        assert 'href="' in preceding, f'non-anchor external URL at {match.start()}'


def test_dark_mode_and_system_fonts(full_html):
    assert '@media (prefers-color-scheme: dark)' in full_html
    assert 'system-ui' in full_html
    assert '@font-face' not in full_html


# --------------------------------------------------------------- degradation

def test_minimal_result_does_not_crash():
    html = build_html_report({'paper_title': 'X'})
    assert '<!DOCTYPE html>' in html
    assert 'X' in html
    assert 'No country data available (country detection requires OpenAlex data)' in html
    assert 'No yearly citation data available.' in html
    assert 'No venue data available.' in html
    assert 'No citing papers available.' in html


def test_empty_result_dict_does_not_crash():
    html = build_html_report({})
    assert 'Unknown Paper' in html


def test_fwci_tile_absent_without_field_normalized():
    html = build_html_report({'paper_title': 'X'})
    assert 'FWCI' not in html


# ------------------------------------------------------------ reference data

def test_country_reference_data_coverage():
    assert len(COUNTRY_CENTROIDS) >= 120
    assert set(COUNTRY_CENTROIDS) == set(COUNTRY_NAMES)
    for code in ('US', 'GB', 'CN', 'DE', 'JP', 'KR', 'FR', 'IN', 'BR', 'AU'):
        assert code in COUNTRY_CENTROIDS
    for lat, lon in COUNTRY_CENTROIDS.values():
        assert -90 <= lat <= 90 and -180 <= lon <= 180


# ------------------------------------------------------------------ dispatch

def test_build_report_dispatches_html(full_result):
    html = build_report(full_result, 'html')
    assert html.startswith('<!DOCTYPE html>')
    assert 'Deep Learning for Program Repair' in html


def test_html_registered_as_export_format(full_result):
    assert 'html' in EXPORT_FORMATS
    assert default_export_filename(full_result, 'html').endswith('.html')


def test_export_report_writes_html_file(full_result, tmp_path):
    target = export_report(full_result, 'html', str(tmp_path / 'report.html'))
    assert target.exists()
    content = target.read_text(encoding='utf-8')
    assert content.startswith('<!DOCTYPE html>')
