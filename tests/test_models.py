"""Tests for citationimpact.models data models."""

import pytest

from citationimpact.models import Author, Citation, Venue
from citationimpact.models.data_models import AuthorInfo


class TestAuthor:
    def test_valid_author(self):
        a = Author(name='Ada Lovelace', h_index=10, affiliation='Cambridge',
                   institution_type='education')
        assert a.works_count == 0
        assert a.citation_count == 0

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError):
            Author(name='  ', h_index=1, affiliation='X', institution_type='t')

    def test_negative_h_index_rejected(self):
        with pytest.raises(ValueError):
            Author(name='A', h_index=-1, affiliation='X', institution_type='t')

    def test_profile_url_priority(self):
        a = Author(name='A', h_index=1, affiliation='X', institution_type='t',
                   google_scholar_id='gs1', semantic_scholar_id='s21',
                   orcid_id='0000', homepage='https://a.io')
        assert 'scholar.google.com' in a.get_profile_url()
        a.google_scholar_id = ''
        assert 'semanticscholar.org' in a.get_profile_url()
        a.semantic_scholar_id = ''
        assert 'orcid.org' in a.get_profile_url()
        a.orcid_id = ''
        assert a.get_profile_url() == 'https://a.io'
        a.homepage = ''
        assert a.get_profile_url() == ''


class TestCitation:
    def _make(self, **overrides):
        base = dict(
            citing_paper_title='T', citing_authors=['A'], venue='V',
            year=2024, is_influential=False, contexts=[], intents=[],
        )
        base.update(overrides)
        return Citation(**base)

    def test_authors_with_ids_defaults_to_empty_list(self):
        c = self._make()
        assert c.authors_with_ids == []

    def test_negative_citation_count_coerced_to_zero(self):
        c = self._make(citation_count=-5)
        assert c.citation_count == 0

    def test_non_int_year_rejected(self):
        with pytest.raises(ValueError):
            self._make(year='2024')

    def test_authors_with_ids_instances_are_independent(self):
        c1 = self._make()
        c2 = self._make()
        c1.authors_with_ids.append(AuthorInfo(name='X'))
        assert c2.authors_with_ids == []


class TestVenue:
    def test_defaults(self):
        v = Venue(name='ICSE', h_index=100, type='conference')
        assert v.rank_tier == 'Unranked'

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError):
            Venue(name='', h_index=1, type='conference')
