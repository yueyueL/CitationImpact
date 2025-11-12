"""API clients for citation data"""

from .unified import UnifiedAPIClient, get_api_client

# Optional Google Scholar support (requires scholarly library)
try:
    from .google_scholar import GoogleScholarClient, get_google_scholar_client
    _GOOGLE_SCHOLAR_AVAILABLE = True
except ImportError:
    GoogleScholarClient = None
    get_google_scholar_client = None
    _GOOGLE_SCHOLAR_AVAILABLE = False

__all__ = [
    'UnifiedAPIClient',
    'get_api_client',
    'GoogleScholarClient',
    'get_google_scholar_client',
]
