"""Regression tests for verified bug fixes in the Google Scholar / SerpAPI clients."""

import threading
import time

import pytest

import citationimpact.clients.google_scholar as gs_module
import citationimpact.clients.serpapi_scholar as serp_module
from citationimpact.clients.google_scholar import GoogleScholarClient, _timeout_call

bs4 = pytest.importorskip('bs4')
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeDriver:
    """Minimal stand-in for a Selenium WebDriver."""

    def __init__(self, pages=None, default_page='<html><body></body></html>'):
        self.pages = pages or {}  # substring of URL -> page_source
        self.default_page = default_page
        self.page_source = default_page
        self.current_url = 'about:blank'
        self.visited = []

    def get(self, url):
        self.visited.append(url)
        self.current_url = url
        for key, html in self.pages.items():
            if key in url:
                self.page_source = html
                return
        self.page_source = self.default_page

    def quit(self):
        pass


def _no_sleep(monkeypatch):
    monkeypatch.setattr(gs_module.time, 'sleep', lambda *a, **k: None)


# A realistic Google Scholar citations page: outer gs_r wrapper carries
# data-cid/data-rp, the inner gs_ri div holds the content. The author list is
# truncated with an ellipsis and one author has a profile link.
CITATIONS_PAGE = """
<html><body><div id="gs_res_ccl_mid">
  <div class="gs_r gs_or gs_scl" data-cid="CID123" data-rp="0">
    <div class="gs_ri">
      <h3 class="gs_rt"><a href="https://example.org/paper1">A Great Citing Paper About Things</a></h3>
      <div class="gs_a"><a href="/citations?user=AF00BAR&amp;hl=en">A Foo</a>, B Bar, C Baz… - Journal of Examples, 2021 - example.com</div>
      <div class="gs_fl"><a href="/scholar?cites=999">Cited by 17</a></div>
    </div>
  </div>
</div></body></html>
"""

# Layout variant without gs_ri/gs_r classes: only data-rp/data-cid on the div.
WRAPPER_ONLY_PAGE = """
<html><body><div id="gs_res_ccl_mid">
  <div class="gs_scl" data-cid="CID999" data-rp="0">
    <h3 class="gs_rt"><a href="/paper2">Another Paper Entirely Different Title</a></h3>
    <div class="gs_a">D Qux, E Quux - Proc. of Testing, 2020</div>
  </div>
</div></body></html>
"""

# Search result with an author line but NO "Cited by" link (0-citation paper).
NO_CITE_LINK_PAGE = """
<html><body>
  <div class="gs_r gs_or gs_scl" data-cid="X1" data-rp="0">
    <div class="gs_ri">
      <h3 class="gs_rt"><a href="/x">Some Paper Without Citations Yet</a></h3>
      <div class="gs_a">J Smith - Journal of Testing, 2021 - publisher.com</div>
    </div>
  </div>
</body></html>
"""

AUTHOR_SEARCH_PAGE = """
<html><body>
  <div class="gs_r gs_or gs_scl" data-rp="0">
    <div class="gs_ri">
      <h3 class="gs_rt"><a href="/p1">Paper By The Coauthor</a></h3>
      <div class="gs_a"><a href="/citations?user=WRONGID&amp;hl=en">John Smith</a>, J Roe - Venue A, 2019</div>
    </div>
  </div>
  <div class="gs_r gs_or gs_scl" data-rp="1">
    <div class="gs_ri">
      <h3 class="gs_rt"><a href="/p2">Paper By Jane Roe Herself</a></h3>
      <div class="gs_a">A Person, <a href="/citations?user=RIGHTID&amp;hl=en">J Roe</a> - Venue B, 2020</div>
    </div>
  </div>
</body></html>
"""

PROFILE_PAGE = """
<html><body>
  <div id="gsc_prf_in">Jane Roe</div>
  <div class="gsc_prf_il">Test University</div>
  <table id="gsc_rsb_st">
    <tr><td>Citations</td><td>12345</td><td>6789</td></tr>
    <tr><td>h-index</td><td>42</td><td>30</td></tr>
  </table>
</body></html>
"""


# ---------------------------------------------------------------------------
# _timeout_call: abandoned worker must not mutate the returned default
# ---------------------------------------------------------------------------

def test_timeout_call_timeout_does_not_leak_mutations():
    done = threading.Event()

    def slow_fill(d):
        time.sleep(0.3)
        d['filled'] = True
        done.set()
        return d

    paper = {'title': 'x'}
    result = _timeout_call(slow_fill, args=(paper,), timeout=0.05, default=paper)

    assert result is paper  # default returned on timeout
    assert done.wait(5)  # let the abandoned worker finish
    # The worker filled a private copy - the caller's dict stays untouched
    assert 'filled' not in paper


def test_timeout_call_success_returns_filled_result():
    def fill(d):
        d['filled'] = True
        return d

    paper = {'title': 'x'}
    result = _timeout_call(fill, args=(paper,), timeout=5, default=paper)
    assert result['filled'] is True
    assert result['title'] == 'x'


# ---------------------------------------------------------------------------
# _parse_citations_from_page: selectors, data-cid, truncated-author flag
# ---------------------------------------------------------------------------

def test_parse_citations_standard_layout():
    client = GoogleScholarClient(use_selenium=False)
    soup = BeautifulSoup(CITATIONS_PAGE, 'html.parser')
    papers = client._parse_citations_from_page(soup)

    assert len(papers) == 1
    paper = papers[0]
    assert paper['title'] == 'A Great Citing Paper About Things'
    # data-cid sits on the outer gs_r wrapper (an ancestor of the gs_ri match)
    assert paper['paper_id'] == 'CID123'
    # Ellipsis stripped from names, but the truncation is flagged
    assert paper['authors'] == ['A Foo', 'B Bar', 'C Baz']
    assert paper['authors_truncated'] is True
    assert paper['venue'] == 'Journal of Examples'
    assert paper['year'] == 2021
    assert paper['citation_count'] == 17
    assert paper['author_profiles'][0]['google_scholar_id'] == 'AF00BAR'


def test_parse_citations_data_rp_layout_reads_data_cid_from_self():
    client = GoogleScholarClient(use_selenium=False)
    soup = BeautifulSoup(WRAPPER_ONLY_PAGE, 'html.parser')
    papers = client._parse_citations_from_page(soup)

    assert len(papers) == 1
    paper = papers[0]
    # The matched result IS the div carrying data-cid
    assert paper['paper_id'] == 'CID999'
    assert paper['authors'] == ['D Qux', 'E Quux']
    assert paper['authors_truncated'] is False


def test_truncated_authors_trigger_bibtex_completion(monkeypatch):
    _no_sleep(monkeypatch)
    client = GoogleScholarClient()
    driver = FakeDriver(default_page=CITATIONS_PAGE)
    monkeypatch.setattr(client, '_get_driver', lambda: driver)

    full_authors = ['A Foo', 'B Bar', 'C Baz', 'D Qux', 'E Quux']
    fetch_calls = []

    def fake_fetch(paper_id, drv):
        fetch_calls.append(paper_id)
        return full_authors

    monkeypatch.setattr(client, '_fetch_bibtex_authors', fake_fetch)

    citations = client.get_citations_by_cites_id(['12345'], limit=5)

    assert fetch_calls == ['CID123']
    assert len(citations) == 1
    assert citations[0].citing_authors == full_authors


# ---------------------------------------------------------------------------
# get_citations_by_cites_id: use the driver returned by _wait_for_captcha
# ---------------------------------------------------------------------------

def test_get_citations_by_cites_id_uses_restarted_driver(monkeypatch):
    _no_sleep(monkeypatch)
    client = GoogleScholarClient()

    old_driver = FakeDriver(default_page='<html><body>empty</body></html>')
    new_driver = FakeDriver(default_page=WRAPPER_ONLY_PAGE)

    monkeypatch.setattr(client, '_get_driver', lambda: old_driver)
    # Simulate a headless CAPTCHA restart: a NEW driver is returned
    monkeypatch.setattr(client, '_wait_for_captcha', lambda drv: new_driver)

    citations = client.get_citations_by_cites_id(['12345'], limit=5)

    assert len(citations) == 1
    assert citations[0].citing_paper_title == 'Another Paper Entirely Different Title'


# ---------------------------------------------------------------------------
# _search_paper_selenium: no NameError without a "Cited by" link, URL encoding
# ---------------------------------------------------------------------------

def test_search_paper_selenium_result_without_cite_link(monkeypatch):
    _no_sleep(monkeypatch)
    client = GoogleScholarClient()
    driver = FakeDriver(default_page=NO_CITE_LINK_PAGE)
    monkeypatch.setattr(client, '_get_driver', lambda: driver)
    monkeypatch.setattr(client, '_wait_for_captcha', lambda drv: None)

    result = client._search_paper_selenium('Some Paper Without Citations Yet')

    # Previously raised UnboundLocalError on 're' and returned None
    assert result is not None
    assert result['title'] == 'Some Paper Without Citations Yet'
    assert result['citationCount'] == 0
    assert result['year'] == 2021
    assert result['venue'] == 'Journal of Testing'


def test_search_paper_selenium_url_encodes_title(monkeypatch):
    _no_sleep(monkeypatch)
    client = GoogleScholarClient()
    driver = FakeDriver(default_page=NO_CITE_LINK_PAGE)
    monkeypatch.setattr(client, '_get_driver', lambda: driver)
    monkeypatch.setattr(client, '_wait_for_captcha', lambda drv: None)

    client._search_paper_selenium('Privacy & Security in Machine Learning')

    assert driver.visited
    assert 'q=Privacy+%26+Security+in+Machine+Learning' in driver.visited[0]


# ---------------------------------------------------------------------------
# __init__: no duplicate proxy setup
# ---------------------------------------------------------------------------

class _FakeProxyGenerator:
    instances = []

    def __init__(self):
        self.scraperapi_keys = []
        self.freeproxies_calls = 0
        _FakeProxyGenerator.instances.append(self)

    def ScraperAPI(self, key):
        self.scraperapi_keys.append(key)
        return True

    def FreeProxies(self):
        self.freeproxies_calls += 1
        return True


class _FakeScholarly:
    def __init__(self):
        self.use_proxy_calls = []

    def use_proxy(self, pg):
        self.use_proxy_calls.append(pg)


@pytest.fixture
def fake_proxy_env(monkeypatch):
    _FakeProxyGenerator.instances = []
    fake_scholarly = _FakeScholarly()
    monkeypatch.setattr(gs_module, 'ProxyGenerator', _FakeProxyGenerator)
    monkeypatch.setattr(gs_module, 'scholarly', fake_scholarly)
    return fake_scholarly


def test_scraper_api_not_overridden_by_free_proxies(fake_proxy_env):
    GoogleScholarClient(use_proxy=True, scraper_api_key='KEY', use_selenium=False)

    # Exactly one proxy configured: the ScraperAPI one
    assert len(fake_proxy_env.use_proxy_calls) == 1
    pg = fake_proxy_env.use_proxy_calls[0]
    assert pg.scraperapi_keys == ['KEY']
    assert sum(p.freeproxies_calls for p in _FakeProxyGenerator.instances) == 0


def test_free_proxies_initialized_once(fake_proxy_env):
    GoogleScholarClient(use_proxy=True, use_selenium=False)

    assert len(fake_proxy_env.use_proxy_calls) == 1
    assert sum(p.freeproxies_calls for p in _FakeProxyGenerator.instances) == 1


# ---------------------------------------------------------------------------
# Author profile lookup: name matching, citation_count, homepage, signatures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('link_text,query,expected', [
    ('J Smith', 'Jane Smith', True),      # abbreviated first name
    ('JA Smith', 'Jane Smith', True),     # double-initial abbreviation
    ('Smith', 'Jane Smith', True),        # last name only
    ('j smith', 'Jane SMITH', True),      # case-insensitive
    ('John Smith', 'Jane Roe', False),    # different person entirely
    ('J Doe', 'Jane Smith', False),       # last name mismatch
    ('B Smith', 'Jane Smith', False),     # first initial mismatch
    ('', 'Jane Smith', False),            # empty link text
])
def test_profile_link_matches_author(link_text, query, expected):
    assert GoogleScholarClient._profile_link_matches_author(link_text, query) is expected


def test_get_author_via_browser_skips_coauthor_profiles(monkeypatch):
    _no_sleep(monkeypatch)
    client = GoogleScholarClient()
    driver = FakeDriver(pages={
        'scholar?q=author:': AUTHOR_SEARCH_PAGE,
        'citations?user=RIGHTID': PROFILE_PAGE,
    })
    monkeypatch.setattr(client, '_get_driver', lambda: driver)

    author = client._get_author_via_browser('Jane Roe')

    assert author is not None
    # The co-author's profile (WRONGID, first link on the page) must be skipped
    assert author.google_scholar_id == 'RIGHTID'
    assert author.name == 'Jane Roe'
    assert author.h_index == 42
    assert author.citation_count == 12345
    assert not any('WRONGID' in url for url in driver.visited)


def test_get_author_via_browser_returns_none_without_name_match(monkeypatch):
    _no_sleep(monkeypatch)
    client = GoogleScholarClient()
    only_coauthor = AUTHOR_SEARCH_PAGE.replace('RIGHTID', 'WRONGID2').replace('J Roe', 'Q Other')
    driver = FakeDriver(pages={'scholar?q=author:': only_coauthor})
    monkeypatch.setattr(client, '_get_driver', lambda: driver)

    author = client._get_author_via_browser('Jane Roe')

    assert author is None
    # Only the search page was visited - no profile was opened
    assert len(driver.visited) == 1


def test_get_author_by_gs_id_extracts_citations_and_accepts_author_name(monkeypatch):
    _no_sleep(monkeypatch)
    client = GoogleScholarClient()
    driver = FakeDriver(default_page=PROFILE_PAGE)
    monkeypatch.setattr(client, '_get_driver', lambda: driver)

    # Two positional args, exactly as core/analyzer.py calls it
    author = client.get_author_by_gs_id('RIGHTID', 'Jane Roe')

    assert author is not None
    assert author.h_index == 42
    assert author.citation_count == 12345  # was hardcoded to 0
    assert author.homepage == ''           # was None when no homepage link
    assert author.google_scholar_id == 'RIGHTID'


def test_categorize_institution_accepts_affiliation():
    client = GoogleScholarClient(use_selenium=False)
    # Two positional args, exactly as core/analyzer.py calls it
    assert client.categorize_institution('education', 'Test University') == 'University'
    # Old 1-arg call keeps working
    assert client.categorize_institution('education') == 'University'


def test_get_author_scholarly_fallback_works_count(monkeypatch):
    _no_sleep(monkeypatch)

    filled_fields = {
        'hindex': 30,
        'affiliation': 'Test University',
        'homepage': '',
        'citedby': 12000,
        'publications': [{'n': 1}, {'n': 2}, {'n': 3}],
    }

    class FakeScholarly:
        def search_author(self, name):
            return iter([{'name': 'Jane Roe', 'scholar_id': 'XYZ'}])

        def fill(self, author, **kwargs):
            author.update(filled_fields)
            return author

    monkeypatch.setattr(gs_module, 'scholarly', FakeScholarly())
    client = GoogleScholarClient(use_selenium=False)

    author = client.get_author('Jane Roe')

    assert author is not None
    assert author.works_count == 3          # publication count, not citedby
    assert author.citation_count == 12000
    assert author.h_index == 30


# ---------------------------------------------------------------------------
# SerpAPI client: clean venue extraction
# ---------------------------------------------------------------------------

def _make_serpapi_client(monkeypatch, canned):
    class FakeSearch:
        def __init__(self, params):
            self.params = params

        def get_dict(self):
            return canned

    monkeypatch.setattr(serp_module, 'GoogleSearch', FakeSearch)
    client = object.__new__(serp_module.SerpAPIScholarClient)
    client.api_key = 'test-key'
    return client


def test_serpapi_search_paper_extracts_clean_venue(monkeypatch):
    canned = {
        'organic_results': [{
            'title': 'AlphaFold: highly accurate protein structure prediction',
            'inline_links': {'cited_by': {'total': 100, 'cites_id': '123'}},
            'publication_info': {
                'summary': 'J Jumper, R Evans - Nature, 2021 - nature.com',
                'authors': [{'name': 'J Jumper'}, {'name': 'R Evans'}],
            },
            'link': 'https://nature.com/x',
        }]
    }
    client = _make_serpapi_client(monkeypatch, canned)

    result = client.search_paper('AlphaFold')

    assert result['venue'] == 'Nature'  # not the whole byline summary
    assert result['year'] == 2021
    assert result['citationCount'] == 100


def test_serpapi_extract_venue_formats():
    client = object.__new__(serp_module.SerpAPIScholarClient)
    # 3-part summary: venue is the middle segment, not the trailing domain
    assert client._extract_venue('J Smith, A Jones - Nature, 2020 - nature.com') == 'Nature'
    # 2-part summary without domain
    assert client._extract_venue('J Smith - Science, 2019') == 'Science'
    assert client._extract_venue('no separator here') == 'Unknown'
