"""Regression tests for bug fixes in the DBLP, ORCID and Crossref clients.

All tests are offline: HTTP is stubbed by replacing the client's session.
"""

from citationimpact.clients.crossref import CrossrefClient
from citationimpact.clients.dblp import DBLPClient
from citationimpact.clients.orcid import ORCIDClient


class FakeResponse:
    def __init__(self, json_data=None, content=b''):
        self._json = json_data
        self.content = content

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class FakeSession:
    """Stub session that records calls and returns a canned response."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class TestDBLPSearchPaper:
    def test_no_good_match_returns_none_instead_of_first_hit(self):
        # Hits share zero title words with the query (matched via author fields)
        data = {'result': {'hits': {'hit': [
            {'info': {'title': 'Deep learning for AI.',
                      'authors': {'author': [{'text': 'Yoshua Bengio'}]}}},
        ]}}}
        client = DBLPClient()
        client.session = FakeSession(FakeResponse(json_data=data))

        assert client.search_paper('Bengio Hinton LeCun') is None

    def test_trailing_period_no_longer_deflates_two_word_titles(self):
        # Old scorer: 'Deep Learning' vs 'Deep learning.' scored 0.5 (not > 0.5)
        # and the code fell back to the unrelated hits[0].
        data = {'result': {'hits': {'hit': [
            {'info': {'title': 'Completely Unrelated Paper.',
                      'authors': {'author': [{'text': 'Someone Else'}]}}},
            {'info': {'title': 'Deep Learning.',
                      'authors': {'author': [{'text': 'Ian Goodfellow'}]}}},
        ]}}}
        client = DBLPClient()
        client.session = FakeSession(FakeResponse(json_data=data))

        result = client.search_paper('Deep Learning')
        assert result is not None
        assert result['title'] == 'Deep Learning.'


class TestDBLPAuthorNormalization:
    def test_normalize_paper_single_author_dict(self):
        hit = {'info': {
            'title': 'A Theory of Type Polymorphism in Programming.',
            'authors': {'author': {'@pid': 'm/RobinMilner', 'text': 'Robin Milner'}},
            'year': '1978',
        }}
        paper = DBLPClient()._normalize_paper(hit)
        assert paper['authors'] == ['Robin Milner']

    def test_normalize_publication_single_author_dict(self):
        pub = DBLPClient()._normalize_publication(
            {'title': 'T', 'author': {'@pid': 'x/Y', 'text': 'Robin Milner'},
             'year': '1980'},
            'article')
        assert pub['authors'] == ['Robin Milner']

    def test_normalize_publication_unexpected_author_value_gives_empty_list(self):
        pub = DBLPClient()._normalize_publication(
            {'title': 'T', 'author': None, 'year': '1980'}, 'article')
        assert pub['authors'] == []


class TestDBLPAuthorPublications:
    XML = b'''<?xml version="1.0" encoding="UTF-8"?>
<dblpperson name="Jane Doe" pid="12/345">
<r><article key="journals/x/Doe20">
<author pid="12/345">Jane Doe</author>
<author pid="12/346">John Smith</author>
<title>A Journal Paper.</title>
<year>2020</year>
<journal>J. Xyz</journal>
<ee>https://doi.org/10.1000/x</ee>
</article></r>
<r><inproceedings key="conf/y/Doe19">
<author pid="12/345">Jane Doe</author>
<title>A Conference Paper.</title>
<year>2019</year>
<booktitle>CONF</booktitle>
</inproceedings></r>
</dblpperson>'''

    def test_fetches_xml_endpoint_and_parses_publications(self):
        client = DBLPClient()
        client.session = FakeSession(FakeResponse(content=self.XML))

        pubs = client.get_author_publications('https://dblp.org/pid/12/345')

        url, _ = client.session.calls[0]
        assert url == 'https://dblp.org/pid/12/345.xml'

        assert len(pubs) == 2
        assert pubs[0]['title'] == 'A Journal Paper.'
        assert pubs[0]['authors'] == ['Jane Doe', 'John Smith']
        assert pubs[0]['year'] == 2020
        assert pubs[0]['venue'] == 'J. Xyz'
        assert pubs[0]['type'] == 'article'
        assert pubs[1]['type'] == 'inproceedings'
        assert pubs[1]['venue'] == 'CONF'
        assert pubs[1]['authors'] == ['Jane Doe']

    def test_does_not_double_append_xml_suffix(self):
        client = DBLPClient()
        client.session = FakeSession(FakeResponse(content=self.XML))
        client.get_author_publications('https://dblp.org/pid/12/345.xml')
        url, _ = client.session.calls[0]
        assert url == 'https://dblp.org/pid/12/345.xml'


class TestORCIDNullFields:
    def test_parse_author_record_with_null_name(self):
        data = {'person': {'name': None}, 'activities-summary': {}}
        record = ORCIDClient()._parse_author_record(data, '0000-0001-2345-6789')
        assert record['name'] == ''
        assert record['orcid_id'] == '0000-0001-2345-6789'

    def test_parse_author_record_mononym_null_family_name(self):
        data = {
            'person': {'name': {
                'given-names': {'value': 'Madonna'},
                'family-name': None,
                'credit-name': None,
            }},
            'activities-summary': {},
        }
        record = ORCIDClient()._parse_author_record(data, '0009-0009-9740-7221')
        assert record['name'] == 'Madonna'

    def test_parse_work_with_all_null_fields(self):
        work = {'title': None, 'publication-date': None, 'journal-title': None,
                'external-ids': None, 'type': None}
        parsed = ORCIDClient()._parse_work(work)
        assert parsed['title'] == ''
        assert parsed['year'] == 0
        assert parsed['venue'] == ''
        assert parsed['doi'] is None
        assert parsed['type'] == 'unknown'

    def test_parse_work_with_null_year_value(self):
        work = {'title': {'title': {'value': 'T'}},
                'publication-date': {'year': {'value': None}}}
        parsed = ORCIDClient()._parse_work(work)
        assert parsed['year'] == 0

    def test_get_author_works_skips_malformed_work_keeps_rest(self):
        data = {'group': [
            {'work-summary': [{'title': {'title': {'value': 'Good 1'}},
                               'external-ids': None}]},
            {'work-summary': [{'title': {'title': {'value': 'Bad'}},
                               'publication-date': {'year': {'value': 'not-a-year'}}}]},
            {'work-summary': [{'title': {'title': {'value': 'Good 2'}}}]},
        ]}
        client = ORCIDClient()
        client.session = FakeSession(FakeResponse(json_data=data))

        works = client.get_author_works('0000-0001-2345-6789')
        assert [w['title'] for w in works] == ['Good 1', 'Good 2']


class TestCrossrefAuthorWorks:
    def test_select_includes_year_fallback_and_metadata_fields(self):
        data = {'message': {'items': [{
            'DOI': '10.1000/x',
            'title': ['Online Only Paper'],
            'published-online': {'date-parts': [[2024, 5, 1]]},
            'is-referenced-by-count': 3,
            'reference-count': 10,
            'type': 'journal-article',
        }]}}
        client = CrossrefClient()
        client.session = FakeSession(FakeResponse(json_data=data))

        works = client.get_author_works('Jane Doe')

        _, kwargs = client.session.calls[0]
        selected = kwargs['params']['select'].split(',')
        for field in ('published-print', 'published-online', 'created',
                      'reference-count', 'type'):
            assert field in selected

        assert works[0]['year'] == 2024
        assert works[0]['referenceCount'] == 10
        assert works[0]['type'] == 'journal-article'
