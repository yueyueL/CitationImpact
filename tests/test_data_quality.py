"""Regression tests for the data-quality / reliability layer.

Real-world failure being pinned: a run where 149 Semantic Scholar requests
died on rate limits produced a report full of 'Unknown' affiliations with no
countries or FWCI, presented as complete, and then cached for 7 days. Root
cause of the 429 storm: with an API key the client used a 0.025s min interval
(40 req/s) while Semantic Scholar's standard allowance is ~1 req/s.

Covers:
1. Rate-limit intervals: >= 1s for Semantic Scholar with AND without a key.
2. _make_request honors a numeric Retry-After header on 429 (capped at 60s).
3. Every permanent request failure increments the per-API failure counter,
   and reset/get helpers behave (get returns a copy).
4. HybridAPIClient delegates the failure-count API to its S2 client.
5. The analyzer computes result['data_quality'] and flags degraded runs.
6. Degraded results are NOT written to the result cache.
7. Every surface (terminal UI, Markdown, LaTeX, HTML) shows a warning for
   degraded results and tolerates legacy results without data_quality.
"""

import pytest
import requests
from rich.console import Console

import citationimpact.core.analyzer as analyzer_module
from citationimpact.clients.hybrid import HybridAPIClient
from citationimpact.clients.unified import UnifiedAPIClient
from citationimpact.core.analyzer import CitationImpactAnalyzer, analyze_paper_impact
from citationimpact.export import build_latex_report, build_markdown_report
from citationimpact.html_report import build_html_report
from citationimpact.ui.analysis_view import AnalysisView


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeResponse:
    """Minimal requests.Response stand-in that fails raise_for_status."""

    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = 'error body'

    def json(self):
        return {}

    def raise_for_status(self):
        raise requests.exceptions.HTTPError(
            f'{self.status_code} error', response=self)


@pytest.fixture
def no_sleep(monkeypatch):
    """Record every time.sleep() call instead of actually sleeping."""
    sleeps = []
    monkeypatch.setattr('time.sleep', lambda s: sleeps.append(s))
    return sleeps


class FakeAPI:
    """Analyzer-facing client stub with failure-count tracking."""

    def __init__(self, failures=None):
        self.failures = dict(failures or {'semantic_scholar': 0, 'openalex': 0})
        self.reset_called = False
        self.last_error = None

    def get_failure_counts(self):
        return dict(self.failures)

    def reset_failure_counts(self):
        self.reset_called = True

    def search_paper(self, title):
        return None


def _authors(n_unknown, n_known):
    authors = [{'name': f'U{i}', 'affiliation': 'Unknown'} for i in range(n_unknown)]
    authors += [{'name': f'K{i}', 'affiliation': 'MIT'} for i in range(n_known)]
    return authors


def _degraded_result():
    """A minimal analysis result flagged as degraded."""
    return {
        'paper_title': 'Reliability Paper',
        'total_citations': 100,
        'influential_citations_count': 1,
        'analyzed_citations': 50,
        'h_index_threshold': 20,
        'error': None,
        'all_authors': [],
        'high_profile_scholars': [],
        'institutions': {},
        'countries': {'counts': {}, 'unknown': 0},
        'venues': {},
        'influential_citations': [],
        'methodological_citations': [],
        'citation_insights': {},
        'yearly_stats': [],
        'self_citation_stats': None,
        'field_normalized': None,
        'impact_stats': {},
        'data_quality': {
            'failed_requests': {'semantic_scholar': 9, 'openalex': 0},
            'total_failed': 9,
            'unknown_affiliation_count': 30,
            'unknown_affiliation_percentage': 75.0,
            'degraded': True,
            'warnings': [
                '9 API request(s) failed during this analysis (semantic_scholar: 9), '
                'so affiliations, countries, and field-normalized metrics may be '
                'missing (30 of 40 citing authors have an unknown affiliation). '
                'Re-run the analysis later to fetch complete data.'
            ],
        },
    }


def _note_only_result():
    """A result with only the non-degraded cross-source note."""
    result = _degraded_result()
    result['data_quality'] = {
        'failed_requests': {'semantic_scholar': 0, 'openalex': 0},
        'total_failed': 0,
        'unknown_affiliation_count': 0,
        'unknown_affiliation_percentage': 0.0,
        'degraded': False,
        'warnings': ['Citation counts differ across sources: Semantic Scholar 100 '
                     'vs OpenAlex 130 (databases index different venues).'],
    }
    return result


def _legacy_result():
    """A result without data_quality, as served from an older cache."""
    result = _degraded_result()
    del result['data_quality']
    return result


# ---------------------------------------------------------------------------
# 1. Rate-limit interval choice
# ---------------------------------------------------------------------------

class TestRateLimitIntervals:
    def test_with_api_key_uses_1_05(self):
        client = UnifiedAPIClient(semantic_scholar_api_key='key')
        assert client.min_intervals['semantic_scholar'] == pytest.approx(1.05)

    def test_without_api_key_keeps_1_1(self):
        client = UnifiedAPIClient()
        assert client.min_intervals['semantic_scholar'] == pytest.approx(1.1)

    def test_no_sub_second_interval_for_semantic_scholar(self):
        # The 0.025s interval (40 req/s) caused the 429 storm - S2's standard
        # allowance is ~1 req/s even with an API key
        for key in ('key', None):
            client = UnifiedAPIClient(semantic_scholar_api_key=key)
            assert client.min_intervals['semantic_scholar'] >= 1.0


# ---------------------------------------------------------------------------
# 2. Retry-After honoring on 429
# ---------------------------------------------------------------------------

class TestRetryAfter:
    def _run_429(self, headers, no_sleep):
        client = UnifiedAPIClient(max_retries=2)
        client.session.get = lambda *a, **k: FakeResponse(429, headers)
        assert client._make_request('https://x', {}, 'semantic_scholar') is None
        return no_sleep

    def test_numeric_retry_after_is_honored(self, no_sleep):
        sleeps = self._run_429({'Retry-After': '7'}, no_sleep)
        assert 7.0 in sleeps

    def test_retry_after_capped_at_60_seconds(self, no_sleep):
        sleeps = self._run_429({'Retry-After': '600'}, no_sleep)
        assert 60 in sleeps
        assert 600.0 not in sleeps

    def test_non_numeric_retry_after_keeps_exponential_backoff(self, no_sleep):
        sleeps = self._run_429({'Retry-After': 'Wed, 21 Oct 2026 07:28:00 GMT'},
                               no_sleep)
        assert 5 in sleeps  # 5 * 2**0

    def test_missing_retry_after_keeps_exponential_backoff(self, no_sleep):
        sleeps = self._run_429({}, no_sleep)
        assert 5 in sleeps

    def test_negative_retry_after_falls_back_to_backoff(self, no_sleep):
        # 'Retry-After: -1' parses as float but time.sleep(-1) raises
        # ValueError - must fall back to exponential backoff instead
        sleeps = self._run_429({'Retry-After': '-1'}, no_sleep)
        assert 5 in sleeps
        assert all(s >= 0 for s in sleeps)

    def test_nan_retry_after_falls_back_to_backoff(self, no_sleep):
        # 'nan' parses as float('nan') but time.sleep(nan) raises ValueError
        import math
        sleeps = self._run_429({'Retry-After': 'nan'}, no_sleep)
        assert 5 in sleeps
        assert not any(math.isnan(s) for s in sleeps)

    def test_negative_infinity_retry_after_falls_back_to_backoff(self, no_sleep):
        sleeps = self._run_429({'Retry-After': '-inf'}, no_sleep)
        assert 5 in sleeps
        assert all(s >= 0 for s in sleeps)

    def test_positive_infinity_retry_after_is_capped_at_60(self, no_sleep):
        # +inf passes the >= 0 guard and is capped like any large value
        sleeps = self._run_429({'Retry-After': 'inf'}, no_sleep)
        assert 60 in sleeps
        assert not any(s == float('inf') for s in sleeps)


# ---------------------------------------------------------------------------
# 3. Failure counting in _make_request
# ---------------------------------------------------------------------------

class TestFailureCounting:
    def _final_failure(self, failure, api='semantic_scholar'):
        client = UnifiedAPIClient(max_retries=2)
        if isinstance(failure, FakeResponse):
            client.session.get = lambda *a, **k: failure
        else:
            def _raise(*a, **k):
                raise failure
            client.session.get = _raise
        assert client._make_request('https://x', {}, api) is None
        return client

    def test_timeout_final_counts(self, no_sleep):
        client = self._final_failure(requests.exceptions.Timeout())
        assert client.get_failure_counts()['semantic_scholar'] == 1

    def test_429_final_counts(self, no_sleep):
        client = self._final_failure(FakeResponse(429))
        assert client.get_failure_counts()['semantic_scholar'] == 1

    def test_5xx_final_counts(self, no_sleep):
        client = self._final_failure(FakeResponse(503))
        assert client.get_failure_counts()['semantic_scholar'] == 1

    def test_other_http_error_counts(self, no_sleep):
        client = self._final_failure(FakeResponse(404))
        assert client.get_failure_counts()['semantic_scholar'] == 1

    def test_connection_error_final_counts(self, no_sleep):
        client = self._final_failure(requests.exceptions.ConnectionError())
        assert client.get_failure_counts()['semantic_scholar'] == 1

    def test_generic_exception_counts(self, no_sleep):
        client = self._final_failure(ValueError('boom'))
        assert client.get_failure_counts()['semantic_scholar'] == 1

    def test_openalex_failures_counted_under_openalex(self, no_sleep):
        client = self._final_failure(requests.exceptions.Timeout(), api='openalex')
        counts = client.get_failure_counts()
        assert counts['openalex'] == 1
        assert counts['semantic_scholar'] == 0

    def test_success_does_not_count(self):
        client = UnifiedAPIClient()

        class OKResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {'ok': True}

        client.session.get = lambda *a, **k: OKResponse()
        assert client._make_request('https://x', {}, 'openalex') == {'ok': True}
        assert client.get_failure_counts() == {'semantic_scholar': 0, 'openalex': 0}

    def test_counters_initialized_in_init(self):
        client = UnifiedAPIClient()
        assert client.request_failures == {'semantic_scholar': 0, 'openalex': 0}

    def test_get_failure_counts_returns_a_copy(self):
        client = UnifiedAPIClient()
        client._record_failure('semantic_scholar')
        counts = client.get_failure_counts()
        counts['semantic_scholar'] = 99  # mutating the copy must not leak back
        assert client.get_failure_counts()['semantic_scholar'] == 1

    def test_reset_failure_counts(self):
        client = UnifiedAPIClient()
        client._record_failure('semantic_scholar')
        client._record_failure('openalex')
        client.reset_failure_counts()
        assert client.get_failure_counts() == {'semantic_scholar': 0, 'openalex': 0}


# ---------------------------------------------------------------------------
# 4. Hybrid client passthroughs
# ---------------------------------------------------------------------------

def test_hybrid_failure_counts_delegate_to_s2_client():
    client = HybridAPIClient.__new__(HybridAPIClient)  # no network/browser init
    client.gs_client = None  # keep __del__/close quiet
    client.s2_client = UnifiedAPIClient()
    client.s2_client._record_failure('semantic_scholar')
    assert client.get_failure_counts()['semantic_scholar'] == 1
    client.reset_failure_counts()
    assert client.get_failure_counts() == {'semantic_scholar': 0, 'openalex': 0}


# ---------------------------------------------------------------------------
# 5. Degraded computation in the analyzer
# ---------------------------------------------------------------------------

class TestAssessDataQuality:
    def test_few_failures_without_data_impact_warn_but_not_degraded(self):
        # 5 failures but every author resolved: substantially complete
        analyzer = CitationImpactAnalyzer(FakeAPI({'semantic_scholar': 5, 'openalex': 0}))
        dq = analyzer._assess_data_quality(_authors(0, 4))
        assert dq['degraded'] is False
        assert dq['total_failed'] == 5
        assert dq['failed_requests'] == {'semantic_scholar': 5, 'openalex': 0}
        assert any('substantially complete' in w for w in dq['warnings'])

    def test_mass_failures_degrade(self):
        analyzer = CitationImpactAnalyzer(FakeAPI({'semantic_scholar': 20, 'openalex': 0}))
        dq = analyzer._assess_data_quality(_authors(0, 4))
        assert dq['degraded'] is True
        # Warning names the cause, the consequence, and advises re-running
        assert any('failed' in w and 'Re-run' in w for w in dq['warnings'])

    def test_moderate_failures_with_data_impact_degrade(self):
        # 5 failures AND >=20% unknown affiliations: visible data impact
        analyzer = CitationImpactAnalyzer(FakeAPI({'semantic_scholar': 5, 'openalex': 0}))
        dq = analyzer._assess_data_quality(_authors(2, 8))
        assert dq['degraded'] is True

    def test_failures_summed_across_apis(self):
        analyzer = CitationImpactAnalyzer(FakeAPI({'semantic_scholar': 3, 'openalex': 2}))
        dq = analyzer._assess_data_quality([])
        assert dq['total_failed'] == 5
        # No authors resolved at all -> no data-impact evidence -> not degraded
        assert dq['degraded'] is False

    def test_unknown_majority_with_a_failure_degrades(self):
        analyzer = CitationImpactAnalyzer(FakeAPI({'semantic_scholar': 1, 'openalex': 0}))
        dq = analyzer._assess_data_quality(_authors(6, 4))
        assert dq['degraded'] is True
        assert dq['unknown_affiliation_count'] == 6
        assert dq['unknown_affiliation_percentage'] == pytest.approx(60.0)

    def test_unknowns_without_failures_not_degraded(self):
        analyzer = CitationImpactAnalyzer(FakeAPI())
        dq = analyzer._assess_data_quality(_authors(10, 0))
        assert dq['degraded'] is False
        assert dq['warnings'] == []

    def test_small_author_set_not_degraded(self):
        analyzer = CitationImpactAnalyzer(FakeAPI({'semantic_scholar': 1, 'openalex': 0}))
        dq = analyzer._assess_data_quality(_authors(4, 1))  # 5 authors < 10
        assert dq['degraded'] is False

    def test_few_failures_with_known_affiliations_not_degraded(self):
        analyzer = CitationImpactAnalyzer(FakeAPI({'semantic_scholar': 4, 'openalex': 0}))
        dq = analyzer._assess_data_quality(_authors(0, 20))
        assert dq['degraded'] is False

    def test_empty_affiliation_counts_as_unknown(self):
        analyzer = CitationImpactAnalyzer(FakeAPI())
        dq = analyzer._assess_data_quality(
            [{'affiliation': ''}, {'affiliation': None}, {'affiliation': 'MIT'}])
        assert dq['unknown_affiliation_count'] == 2

    def test_client_without_failure_tracking_tolerated(self):
        class BareClient:
            pass

        analyzer = CitationImpactAnalyzer(BareClient())
        dq = analyzer._assess_data_quality(_authors(2, 2))
        assert dq['degraded'] is False
        assert dq['failed_requests'] == {}
        assert dq['total_failed'] == 0

    def test_cross_source_note_added_but_not_degraded(self):
        analyzer = CitationImpactAnalyzer(FakeAPI())
        dq = analyzer._assess_data_quality(
            [], field_normalized={'openalex_cited_by_count': 200},
            total_citations=100)
        assert dq['degraded'] is False
        assert dq['warnings'] == [
            'Citation counts differ across sources: Semantic Scholar 100 '
            'vs OpenAlex 200 (databases index different venues).']

    def test_close_cross_source_counts_produce_no_note(self):
        analyzer = CitationImpactAnalyzer(FakeAPI())
        dq = analyzer._assess_data_quality(
            [], field_normalized={'openalex_cited_by_count': 105},
            total_citations=100)
        assert dq['warnings'] == []

    def test_missing_openalex_count_tolerated(self):
        analyzer = CitationImpactAnalyzer(FakeAPI())
        dq = analyzer._assess_data_quality(
            [], field_normalized={'fwci': 2.0}, total_citations=100)
        assert dq['warnings'] == []

    def test_analyze_paper_resets_counters_and_empty_result_has_skeleton(self):
        api = FakeAPI()
        analyzer = CitationImpactAnalyzer(api)
        result = analyzer.analyze_paper('Some Unfindable Paper')
        assert api.reset_called is True
        dq = result['data_quality']
        assert dq == {
            'failed_requests': {},
            'total_failed': 0,
            'unknown_affiliation_count': 0,
            'unknown_affiliation_percentage': 0.0,
            'degraded': False,
            'warnings': [],
        }


# ---------------------------------------------------------------------------
# 6. Degraded results must not be cached
# ---------------------------------------------------------------------------

_CACHE_PARAMS = {'h_index_threshold': 20, 'max_citations': 100, 'data_source': 'api'}


def _run_analysis(monkeypatch, result):
    monkeypatch.setattr(analyzer_module.CitationImpactAnalyzer, 'analyze_paper',
                        lambda self, *a, **k: dict(result))
    return analyze_paper_impact(result['paper_title'], use_cache=True,
                                data_source='api')


class TestCacheSkip:
    def test_degraded_result_not_cached(self, monkeypatch, capsys):
        canned = _degraded_result()
        returned = _run_analysis(monkeypatch, canned)
        assert returned['data_quality']['degraded'] is True

        out = capsys.readouterr().out
        assert ('[Cache] Result may be incomplete (API failures) - not caching '
                'so a later run can fetch complete data') in out

        from citationimpact.cache import get_result_cache
        assert get_result_cache().get(canned['paper_title'], _CACHE_PARAMS) is None

    def test_healthy_result_is_cached(self, monkeypatch):
        canned = _note_only_result()  # non-degraded warnings still cache
        _run_analysis(monkeypatch, canned)

        from citationimpact.cache import get_result_cache
        cached = get_result_cache().get(canned['paper_title'], _CACHE_PARAMS)
        assert cached is not None

    def test_legacy_result_without_data_quality_still_cached(self, monkeypatch):
        canned = _legacy_result()
        _run_analysis(monkeypatch, canned)

        from citationimpact.cache import get_result_cache
        cached = get_result_cache().get(canned['paper_title'], _CACHE_PARAMS)
        assert cached is not None


# ---------------------------------------------------------------------------
# 7. Surfaces
# ---------------------------------------------------------------------------

def _render_ui(result):
    console = Console(record=True, width=120, force_terminal=False)
    AnalysisView(console)._render_summary(result)
    return console.export_text()


class TestUISurface:
    def test_degraded_banner_at_top(self):
        text = _render_ui(_degraded_result())
        assert 'Data May Be Incomplete' in text
        # Wrap-safe fragment: the Panel word-wraps the full warning sentence
        assert 'Re-run' in text
        # Banner renders BEFORE the header panel
        assert text.index('Data May Be Incomplete') < \
            text.index('Impact Analysis Results')

    def test_non_degraded_warning_is_a_note(self):
        text = _render_ui(_note_only_result())
        assert 'Data May Be Incomplete' not in text
        assert 'Citation counts differ across sources' in text

    def test_legacy_result_renders_without_banner(self):
        text = _render_ui(_legacy_result())
        assert 'Data May Be Incomplete' not in text
        assert 'Impact Analysis Results' in text


class TestMarkdownSurface:
    def test_degraded_blockquote_after_header(self):
        md = build_markdown_report(_degraded_result())
        assert '> ⚠' in md
        assert md.index('# Citation Impact Report') < md.index('> ⚠') < \
            md.index('## Overview')
        assert 'Re-run the analysis later' in md

    def test_non_degraded_warning_is_plain_note(self):
        md = build_markdown_report(_note_only_result())
        assert '> ⚠' not in md
        assert '*Note: Citation counts differ across sources' in md

    def test_legacy_result_has_no_banner(self):
        md = build_markdown_report(_legacy_result())
        assert '> ⚠' not in md
        assert '*Note:' not in md


class TestLatexSurface:
    def test_degraded_emphasized_paragraph(self):
        tex = build_latex_report(_degraded_result())
        assert '\\emph{Warning:' in tex
        assert tex.index('\\section*') < tex.index('\\emph{Warning:') < \
            tex.index('\\begin{itemize}')

    def test_non_degraded_warning_is_note(self):
        tex = build_latex_report(_note_only_result())
        assert '\\emph{Warning:' not in tex
        assert '\\emph{Note: Citation counts differ across sources' in tex

    def test_legacy_result_has_no_banner(self):
        tex = build_latex_report(_legacy_result())
        assert '\\emph{Warning:' not in tex
        assert '\\emph{Note:' not in tex


class TestHtmlSurface:
    def test_degraded_amber_banner_under_header(self):
        page = build_html_report(_degraded_result())
        assert 'quality-banner' in page
        # Text label, never color alone
        assert 'Data may be incomplete' in page
        # Directly under the header, before the stat tiles
        assert page.index('report-header') < page.index('quality-banner') < \
            page.index('class="tiles"')
        # Styled via the existing --status-warn token
        assert 'var(--status-warn)' in page

    def test_non_degraded_warning_is_note(self):
        page = build_html_report(_note_only_result())
        assert '<section class="card quality-banner"' not in page
        assert 'Citation counts differ across sources' in page

    def test_legacy_result_has_no_banner(self):
        page = build_html_report(_legacy_result())
        assert '<section class="card quality-banner"' not in page
        assert 'Data may be incomplete' not in page
