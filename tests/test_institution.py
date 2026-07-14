"""Tests for institution categorization."""

from citationimpact.utils import categorize_institution


class TestCategorizeByAffiliation:
    def test_known_university(self):
        assert categorize_institution('', 'Massachusetts Institute of Technology') == 'University'

    def test_known_industry(self):
        assert categorize_institution('', 'Google Research') == 'Industry'

    def test_known_government(self):
        assert categorize_institution('', 'National Institute of Standards and Technology') == 'Government'


class TestCategorizeByType:
    def test_education_type(self):
        assert categorize_institution('education') == 'University'

    def test_company_type(self):
        assert categorize_institution('company') == 'Industry'

    def test_government_type(self):
        assert categorize_institution('government') == 'Government'

    def test_facility_type_maps_to_government(self):
        assert categorize_institution('facility') == 'Government'

    def test_empty_type_is_other(self):
        assert categorize_institution('') == 'Other'
        assert categorize_institution(None) == 'Other'

    def test_unknown_affiliation_falls_back_to_type(self):
        assert categorize_institution('education', 'Unknown') == 'University'
