"""
Institution categorization utilities with enhanced government/industry detection
"""

from .known_institutions import (
    is_government_institution,
    is_industry_institution,
    is_university_institution
)


def categorize_institution(institution_type: str, affiliation: str = None) -> str:
    """
    Categorize institution into University, Industry, Government, or Other

    Uses both OpenAlex institution type AND affiliation name for better accuracy.

    Args:
        institution_type: Institution type from OpenAlex
        affiliation: Affiliation name (optional, but recommended for better accuracy)

    Returns:
        Category string: 'University', 'Industry', 'Government', or 'Other'
    """
    # If we have affiliation name, use enhanced detection
    if affiliation and affiliation != 'Unknown':
        # Check government first (most specific)
        if is_government_institution(affiliation, institution_type):
            return 'Government'

        # Check industry
        if is_industry_institution(affiliation, institution_type):
            return 'Industry'

        # Check university
        if is_university_institution(affiliation, institution_type):
            return 'University'

    # Fallback to basic type-based categorization
    if not institution_type:
        return 'Other'

    inst_type_lower = institution_type.lower()

    # University/Education
    if any(keyword in inst_type_lower for keyword in [
        'education', 'university', 'college', 'institute', 'school', 'academy'
    ]):
        return 'University'

    # Industry/Company
    if any(keyword in inst_type_lower for keyword in [
        'company', 'corporation', 'corporate', 'lab', 'research', 'private'
    ]):
        return 'Industry'

    # Government
    if any(keyword in inst_type_lower for keyword in [
        'government', 'gov', 'federal', 'national', 'public', 'ministry'
    ]):
        return 'Government'

    # Nonprofit (usually research orgs)
    if 'nonprofit' in inst_type_lower or 'non-profit' in inst_type_lower:
        return 'Other'

    # Healthcare
    if any(keyword in inst_type_lower for keyword in ['healthcare', 'hospital', 'medical']):
        return 'Other'

    # Archive
    if 'archive' in inst_type_lower:
        return 'Other'

    # Facility (labs, observatories, etc.)
    if 'facility' in inst_type_lower:
        return 'Government'  # Often national labs

    return 'Other'
