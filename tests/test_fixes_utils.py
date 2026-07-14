"""Regression tests for utils bug fixes (institution categorization + rankings)."""

import pytest

from citationimpact.utils import rankings as rankings_module
from citationimpact.utils.institution import categorize_institution
from citationimpact.utils.known_institutions import (
    is_government_institution,
    is_industry_institution,
)
from citationimpact.utils.rankings import (
    _find_university_entry,
    _find_venue_entry,
    _store_university_entry,
    _store_venue_rank,
    get_core_rank,
    get_rankings_statistics,
    get_university_rank,
    get_venue_rankings,
    parse_rank_value,
)


class TestIndustryIndicatorWordBoundaries:
    """'inc'/'corp' etc. must not match inside ordinary words."""

    def test_princeton_is_not_industry(self):
        assert categorize_institution('education', 'Princeton University') == 'University'

    def test_cincinnati_is_not_industry(self):
        assert categorize_institution('education', 'University of Cincinnati') == 'University'

    def test_corpus_christi_is_not_industry(self):
        assert categorize_institution('education', 'Corpus Christi College') == 'University'

    def test_real_company_indicators_still_match(self):
        assert is_industry_institution('Apple Inc.')
        assert is_industry_institution('Samsung Electronics Co., Ltd.')
        assert is_industry_institution('XYZ Corporation')
        assert is_industry_institution('Siemens GmbH')
        assert categorize_institution(None, 'Acme Robotics LLC') == 'Industry'

    def test_education_type_not_overridden_by_name_heuristics(self):
        # An explicit OpenAlex 'education' type wins over name heuristics
        assert not is_industry_institution('Something Inc-like University', 'education')
        assert categorize_institution('education', 'Franklin W. Olin College') == 'University'


class TestGovernmentKeywordWordBoundaries:
    """Short government acronyms must not match substrings of common words."""

    def test_department_does_not_match_epa(self):
        assert categorize_institution(
            None, 'Department of Computer Science, Stanford University'
        ) == 'University'

    def test_newcastle_does_not_match_cas(self):
        assert categorize_institution(None, 'Newcastle University') == 'University'

    def test_administration_does_not_match_nist(self):
        assert categorize_institution(
            None, 'School of Business Administration, XYZ University'
        ) == 'University'

    def test_real_government_names_still_match(self):
        assert is_government_institution('National Institute of Standards and Technology')
        assert is_government_institution('NIST')
        assert is_government_institution('NASA Jet Propulsion Laboratory')
        assert is_government_institution('Chinese Academy of Sciences')
        assert is_government_institution('Oak Ridge National Laboratory')
        assert categorize_institution(None, 'US Environmental Protection Agency') == 'Government'


class TestVenueMatcherNoSubstringFallback:
    """Bidirectional substring matching returned arbitrary wrong venues."""

    def _storage_with(self, entries):
        storage = {}
        for keys, rank, source in entries:
            _store_venue_rank(storage, keys, rank, source=source)
        return storage

    def test_query_is_not_matched_to_superstring_venue(self):
        storage = self._storage_with(
            [(['AIAI', 'Artificial Intelligence Applications and Innovations'], 'C', 'icore')]
        )
        assert _find_venue_entry(storage, 'Artificial Intelligence') is None

    def test_normalized_match_ignores_parenthetical_acronym(self):
        storage = self._storage_with(
            [
                (['AIAI', 'Artificial Intelligence Applications and Innovations'], 'C', 'icore'),
                (['AI', 'Artificial Intelligence (AI)'], 'A', 'ccf'),
            ]
        )
        entry = _find_venue_entry(storage, 'Artificial Intelligence')
        assert entry is not None
        assert entry['sources'] == {'ccf': 'A'}

    def test_flagship_ai_journal_resolves_correctly_in_shipped_data(self):
        info = get_venue_rankings('Artificial Intelligence')
        assert info.get('ccf') == 'A'
        assert info.get('canonical') != 'Artificial Intelligence Applications and Innovations'

    def test_exact_acronym_still_matches(self):
        info = get_venue_rankings('ICSE')
        assert info.get('icore') == 'A*'


class TestUniversityMatcherNoSubstringFallback:
    """Substring matching misattributed rankings to unrelated universities."""

    def _storage_with_nus(self):
        storage = {}
        _store_university_entry(
            storage, 'National University of Singapore (NUS)', 8, source_key='qs'
        )
        return storage

    def test_substring_query_does_not_inherit_nus_rank(self):
        storage = self._storage_with_nus()
        assert _find_university_entry(storage, 'National University') is None

    def test_full_name_and_alias_still_match(self):
        storage = self._storage_with_nus()
        assert _find_university_entry(storage, 'National University of Singapore (NUS)') is not None
        assert _find_university_entry(storage, 'NUS') is not None
        # Normalized match without the parenthetical acronym
        assert _find_university_entry(storage, 'National University of Singapore') is not None

    def test_shipped_data_no_misattribution(self):
        assert get_university_rank('National University') is None
        assert get_university_rank('University of California') is None
        assert get_university_rank('National University of Singapore') == (8, 'Top 10')


class TestIcoreJunkRanksNotStored:
    """Non-tier Rank values ('Unranked', 'National: USA', ...) must be skipped."""

    def test_unranked_venue_has_no_core_rank(self):
        assert get_core_rank('INFOCOMP') is None

    def test_ranked_venue_keeps_rank(self):
        assert get_core_rank('HCOMP') == 'B'

    def test_statistics_do_not_count_unranked_venue(self):
        stats = get_rankings_statistics(['INFOCOMP'], [])
        assert stats['venues']['with_core_rank'] == 0


class TestParseRankValueRanges:
    """QS range displays ('601-610', '1401+') must parse to the lower bound."""

    def test_range(self):
        assert parse_rank_value('601-610') == 601

    def test_open_ended(self):
        assert parse_rank_value('1401+') == 1401

    def test_equals_prefix(self):
        assert parse_rank_value('=12') == 12

    def test_plain_and_invalid(self):
        assert parse_rank_value('42') == 42
        assert parse_rank_value('abc') is None
        assert parse_rank_value('') is None
        assert parse_rank_value(None) is None

    def test_universities_beyond_600_are_loaded(self):
        # Drexel University is QS 601-610 in the shipped 24_qs.csv
        assert get_university_rank('Drexel University') == (601, 'Ranked')


class TestStoreUniversityEntryRangeStrings:
    """String range ranks previously raised ValueError."""

    def test_range_string_does_not_crash(self):
        storage = {}
        _store_university_entry(storage, 'Test University', '601-650')
        entry = storage['Test University']
        assert entry['rank'] == 601
        assert entry['tier'] == 'Ranked'

    def test_unparseable_string_is_skipped(self):
        storage = {}
        _store_university_entry(storage, 'Test University', 'not a rank')
        assert storage == {}


class TestSameSourceRankRefresh:
    """Re-storing a newer rank for the same source must refresh rank/tier."""

    def test_entry_rank_updates_for_same_source(self):
        storage = {}
        _store_university_entry(storage, 'Example University', 5, source_key='qs')
        _store_university_entry(storage, 'Example University', 1, source_key='qs')
        entry = storage['Example University']
        assert entry['rank'] == 1
        assert entry['tier'] == 'Top 10'
        assert entry['sources']['qs']['rank'] == 1
        assert entry['primary_source'] == 'qs'

    def test_lower_priority_source_still_does_not_override(self):
        storage = {}
        _store_university_entry(storage, 'Example University', 5, source_key='qs')
        _store_university_entry(storage, 'Example University', 50, source_key='usnews')
        entry = storage['Example University']
        assert entry['rank'] == 5
        assert entry['primary_source'] == 'qs'
        assert entry['sources']['usnews']['rank'] == 50


class TestNanKeysNotStored:
    """str(NaN) acronym cells must not merge unrelated venues under 'nan'."""

    def test_nan_keys_are_filtered(self):
        storage = {}
        _store_venue_rank(storage, ['nan', 'Venue Alpha Conference'], 'A*', source='core')
        _store_venue_rank(storage, ['nan', 'Venue Beta Conference'], 'C', source='core')
        assert 'nan' not in storage
        assert 'NAN' not in storage
        alpha = storage['Venue Alpha Conference']
        beta = storage['Venue Beta Conference']
        assert alpha is not beta
        assert alpha['sources']['core'] == 'A*'
        assert beta['sources']['core'] == 'C'
        assert alpha['canonical'] == 'Venue Alpha Conference'

    def test_all_nan_keys_stores_nothing(self):
        storage = {}
        _store_venue_rank(storage, ['nan', 'NaN'], 'A', source='core')
        assert storage == {}

    def test_loader_with_blank_acronyms(self, tmp_path, monkeypatch):
        core_dir = tmp_path / 'core_rankings'
        core_dir.mkdir()
        (core_dir / 'test.csv').write_text(
            'Title,Acronym,Rank\n'
            'Venue Alpha Conference,,A*\n'
            'Venue Beta Conference,,C\n'
        )
        monkeypatch.setattr(rankings_module, 'CORE_DIR', core_dir)
        monkeypatch.setattr(rankings_module, 'VENUE_DIR', tmp_path / 'missing')
        monkeypatch.setattr(rankings_module, '_core_rankings_cache', None)
        rankings = rankings_module.load_core_rankings()
        assert 'nan' not in rankings
        assert rankings['Venue Alpha Conference']['sources']['core'] == 'A*'
        assert rankings['Venue Beta Conference']['sources']['core'] == 'C'
