# Copyright (c) 2024 CitationImpact
# All rights reserved.

"""
CitationImpact - Academic Impact Analysis Tool

Clean, API-based citation analysis for grant applications and performance reviews.
Works for ANY academic field!

Organized package structure:
  - models/: Data models (Author, Venue, Citation)
  - clients/: API clients (Semantic Scholar, OpenAlex, Google Scholar)
  - core/: Main analysis logic
  - utils/: Helper functions (institution categorization, rate limiting)

Data Sources:
  - 'api': Semantic Scholar + OpenAlex APIs (RECOMMENDED - fast, reliable)
  - 'google_scholar': Google Scholar web scraping (slow, for papers not in APIs)
"""

# Main API - simple one-function interface
from .core import analyze_paper_impact, CitationImpactAnalyzer

# API clients
from .clients import UnifiedAPIClient, get_api_client
try:
    from .clients import GoogleScholarClient, get_google_scholar_client
except (ImportError, TypeError):
    # Google Scholar client requires scholarly library (optional dependency)
    GoogleScholarClient = None
    get_google_scholar_client = None

# Data models
from .models import Author, Venue, Citation

# Utils
from .utils import categorize_institution

# Cache
from .cache import ResultCache, get_result_cache, AuthorProfileCache, get_author_cache

# Config
from .config import ConfigManager, get_config_manager

__version__ = '1.2.0'
__all__ = [
    # Main API
    'analyze_paper_impact',
    'CitationImpactAnalyzer',
    # Clients
    'UnifiedAPIClient',
    'get_api_client',
    'GoogleScholarClient',
    'get_google_scholar_client',
    # Models
    'Author',
    'Venue',
    'Citation',
    # Utils
    'categorize_institution',
    # Cache
    'ResultCache',
    'get_result_cache',
    'AuthorProfileCache',
    'get_author_cache',
    # Config
    'ConfigManager',
    'get_config_manager',
]
