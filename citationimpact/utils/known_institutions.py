"""
Well-known institutions database for better categorization

This helps identify government agencies, top companies, and universities
that might not be properly categorized by API responses.
"""

# Well-known government institutions and research labs
KNOWN_GOVERNMENT_INSTITUTIONS = {
    # United States
    'nasa', 'national aeronautics and space administration',
    'nih', 'national institutes of health',
    'nsf', 'national science foundation',
    'darpa', 'defense advanced research projects agency',
    'doe', 'department of energy',
    'nist', 'national institute of standards',
    'noaa', 'national oceanic and atmospheric',
    'usgs', 'geological survey',
    'cdc', 'centers for disease control',
    'fda', 'food and drug administration',
    'epa', 'environmental protection agency',
    'sandia national laboratories', 'sandia',
    'los alamos national laboratory', 'lanl',
    'lawrence livermore national laboratory', 'llnl',
    'oak ridge national laboratory', 'ornl',
    'argonne national laboratory',
    'brookhaven national laboratory',
    'fermilab', 'fermi national accelerator',
    'pacific northwest national laboratory', 'pnnl',
    'national renewable energy laboratory', 'nrel',

    # United Kingdom
    'government digital service', 'gds',
    'uk research and innovation', 'ukri',
    'medical research council', 'mrc',
    'engineering and physical sciences research council', 'epsrc',
    'natural environment research council', 'nerc',

    # European Union
    'european commission',
    'joint research centre', 'jrc',
    'european space agency', 'esa',

    # China
    'chinese academy of sciences', 'cas',
    'ministry of science and technology',

    # Japan
    'riken',
    'japan aerospace exploration agency', 'jaxa',

    # India
    'indian space research organisation', 'isro',
    'defence research and development organisation', 'drdo',
    'council of scientific and industrial research', 'csir',

    # Australia
    'csiro', 'commonwealth scientific',

    # Canada
    'national research council canada', 'nrc',

    # International
    'cern', 'european organization for nuclear research',
    'iter', 'international thermonuclear',

    # Keywords
    'national laboratory', 'national lab',
    'government research', 'federal research',
    'ministry of', 'department of defense',
    'air force research', 'naval research',
    'army research', 'military research',
}

# Well-known industry research labs
KNOWN_INDUSTRY_INSTITUTIONS = {
    # Tech Giants
    'google', 'google research', 'google ai', 'google brain', 'deepmind',
    'microsoft', 'microsoft research',
    'meta', 'facebook', 'facebook ai research', 'fair',
    'apple', 'apple inc',
    'amazon', 'amazon web services', 'aws',
    'ibm', 'ibm research', 'ibm watson',
    'intel', 'intel labs',
    'nvidia',
    'openai',
    'anthropic',

    # Other Tech
    'adobe', 'adobe research',
    'salesforce', 'salesforce research',
    'spotify',
    'uber', 'uber technologies',
    'airbnb',
    'netflix',

    # Telecom
    'bell labs', 'nokia bell labs',
    'huawei',
    'qualcomm',
    'ericsson',

    # Automotive
    'tesla',
    'toyota research',
    'ford',
    'general motors',

    # Pharma/Biotech
    'pfizer',
    'moderna',
    'novartis',
    'roche',
    'genentech',

    # Other
    'siemens',
    'bosch',
    'philips research',
}

def is_government_institution(affiliation: str, institution_type: str = None) -> bool:
    """
    Check if an affiliation is a government institution

    Args:
        affiliation: Affiliation string
        institution_type: Institution type from OpenAlex (optional)

    Returns:
        True if government institution
    """
    if not affiliation or affiliation == 'Unknown':
        return False

    affiliation_lower = affiliation.lower()

    # Check OpenAlex institution type first
    if institution_type and institution_type.lower() in ['government', 'facility']:
        return True

    # Check against known government institutions
    for gov_keyword in KNOWN_GOVERNMENT_INSTITUTIONS:
        if gov_keyword in affiliation_lower:
            return True

    return False

def is_industry_institution(affiliation: str, institution_type: str = None) -> bool:
    """
    Check if an affiliation is an industry/company research lab

    Args:
        affiliation: Affiliation string
        institution_type: Institution type from OpenAlex (optional)

    Returns:
        True if industry institution
    """
    import re

    if not affiliation or affiliation == 'Unknown':
        return False

    affiliation_lower = affiliation.lower()

    # Check OpenAlex institution type first
    if institution_type and institution_type.lower() == 'company':
        return True

    # Check against known industry institutions
    # Use word boundaries to avoid false positives (e.g., "Stanford" shouldn't match "ford")
    for company_keyword in KNOWN_INDUSTRY_INSTITUTIONS:
        # For multi-word keywords, do simple substring match
        if ' ' in company_keyword:
            if company_keyword in affiliation_lower:
                return True
        else:
            # For single-word keywords, use word boundary
            pattern = r'\b' + re.escape(company_keyword) + r'\b'
            if re.search(pattern, affiliation_lower):
                return True

    # Check for common company indicators
    if any(indicator in affiliation_lower for indicator in ['inc.', 'inc', 'corp', 'ltd', 'llc', 'gmbh']):
        return True

    return False

def is_university_institution(affiliation: str, institution_type: str = None) -> bool:
    """
    Check if an affiliation is a university

    Args:
        affiliation: Affiliation string
        institution_type: Institution type from OpenAlex (optional)

    Returns:
        True if university
    """
    if not affiliation or affiliation == 'Unknown':
        return False

    affiliation_lower = affiliation.lower()

    # Check OpenAlex institution type first
    if institution_type and institution_type.lower() == 'education':
        return True

    # Check for university keywords
    university_keywords = [
        'university', 'college', 'institute of technology',
        'école', 'universität', 'universidad', 'università',
        'polytechnic', 'academy', 'school of'
    ]

    for keyword in university_keywords:
        if keyword in affiliation_lower:
            return True

    return False
