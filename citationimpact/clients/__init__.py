"""API clients for citation data

Available clients:
- UnifiedAPIClient: Semantic Scholar + OpenAlex (primary, most reliable)
- GoogleScholarClient: Google Scholar scraping (fallback, may have CAPTCHA issues)
- SerpAPIScholarClient: Google Scholar via SerpAPI (paid, most reliable for GS)
- HybridAPIClient: Combines S2 + GS for comprehensive coverage
- CrossrefClient: DOI metadata and citation counts (free)
- ORCIDClient: Author identification and profiles (free)
- DBLPClient: Computer Science publications (free, excellent for CS)
"""

from .unified import UnifiedAPIClient, get_api_client

# Optional Google Scholar support (requires scholarly library)
try:
    from .google_scholar import GoogleScholarClient, get_google_scholar_client
    _GOOGLE_SCHOLAR_AVAILABLE = True
except ImportError:
    GoogleScholarClient = None
    get_google_scholar_client = None
    _GOOGLE_SCHOLAR_AVAILABLE = False

# Hybrid client combining S2 + GS
try:
    from .hybrid import HybridAPIClient, get_hybrid_client
    _HYBRID_AVAILABLE = True
except ImportError:
    HybridAPIClient = None
    get_hybrid_client = None
    _HYBRID_AVAILABLE = False

# Crossref client (DOI metadata)
try:
    from .crossref import CrossrefClient, get_crossref_client
    _CROSSREF_AVAILABLE = True
except ImportError:
    CrossrefClient = None
    get_crossref_client = None
    _CROSSREF_AVAILABLE = False

# ORCID client (author identification)
try:
    from .orcid import ORCIDClient, get_orcid_client
    _ORCID_AVAILABLE = True
except ImportError:
    ORCIDClient = None
    get_orcid_client = None
    _ORCID_AVAILABLE = False

# DBLP client (Computer Science publications)
try:
    from .dblp import DBLPClient, get_dblp_client
    _DBLP_AVAILABLE = True
except ImportError:
    DBLPClient = None
    get_dblp_client = None
    _DBLP_AVAILABLE = False

# SerpAPI client (paid, most reliable for Google Scholar)
try:
    from .serpapi_scholar import SerpAPIScholarClient, get_serpapi_client
    _SERPAPI_AVAILABLE = True
except ImportError:
    SerpAPIScholarClient = None
    get_serpapi_client = None
    _SERPAPI_AVAILABLE = False

__all__ = [
    # Primary clients
    'UnifiedAPIClient',
    'get_api_client',
    # Google Scholar (scraping - may have CAPTCHA issues)
    'GoogleScholarClient',
    'get_google_scholar_client',
    # SerpAPI (paid, most reliable for Google Scholar)
    'SerpAPIScholarClient',
    'get_serpapi_client',
    # Hybrid (S2 + GS)
    'HybridAPIClient',
    'get_hybrid_client',
    # Additional data sources
    'CrossrefClient',
    'get_crossref_client',
    'ORCIDClient',
    'get_orcid_client',
    'DBLPClient',
    'get_dblp_client',
]
