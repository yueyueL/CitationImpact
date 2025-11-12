"""
Unified API Client for Citation Analysis - FIXED VERSION

Improvements:
- ✅ Retry logic with exponential backoff
- ✅ LRU caching to reduce API calls
- ✅ Proper rate limit initialization
- ✅ Response validation
- ✅ Configurable timeouts
- ✅ Better error handling
"""

import requests
import time
from typing import Dict, List, Optional

from ..models import Author, Venue, Citation
from ..utils import categorize_institution


class UnifiedAPIClient:
    """
    Single client for all citation analysis APIs with robust error handling
    """

    def __init__(
        self,
        semantic_scholar_api_key: Optional[str] = None,
        email: Optional[str] = None,
        timeout: int = 15,
        max_retries: int = 3
    ):
        """
        Args:
            semantic_scholar_api_key: Optional S2 API key
            email: Optional email for OpenAlex polite pool
            timeout: Request timeout in seconds (default: 15)
            max_retries: Max retry attempts for failed requests (default: 3)
        """
        self.session = requests.Session()
        self.email = email
        self.s2_api_key = semantic_scholar_api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.last_error: Optional[str] = None

        # Set headers
        user_agent = f'CitationImpact/1.0 (mailto:{email})' if email else 'CitationImpact/1.0'
        self.session.headers.update({'User-Agent': user_agent})

        if semantic_scholar_api_key:
            self.session.headers.update({'x-api-key': semantic_scholar_api_key})

        # Rate limiting - properly initialized
        self.last_request_time = {
            'openalex': 0,
            'semantic_scholar': 0
        }
        self.min_intervals = {
            'openalex': 0.11,  # ~9 req/sec (safe margin)
            'semantic_scholar': 1.1 if not semantic_scholar_api_key else 0.025,
        }

        # Instance-based caching (FIX: lru_cache doesn't work on instance methods)
        self._author_cache: Dict[str, Optional[Author]] = {}
        self._venue_cache: Dict[str, Optional[Venue]] = {}

    def _rate_limit(self, api: str):
        """Ensure rate limits are respected"""
        if api not in self.last_request_time:
            self.last_request_time[api] = 0

        elapsed = time.time() - self.last_request_time[api]
        min_interval = self.min_intervals.get(api, 0.1)

        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

        self.last_request_time[api] = time.time()

    def _make_request(self, url: str, params: dict, api: str) -> Optional[dict]:
        """
        Make API request with retry logic and exponential backoff

        Returns:
            Response JSON or None if all retries failed
        """
        self._rate_limit(api)
        self.last_error = None

        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                return response.json()

            except requests.exceptions.Timeout:
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    print(f"[WARNING] Timeout on attempt {attempt + 1}/{self.max_retries}, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    print(f"[ERROR] Request timed out after {self.max_retries} attempts")
                    self.last_error = f"Semantic Scholar request timed out after {self.max_retries} attempts."
                    return None

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:  # Rate limit
                    if attempt < self.max_retries - 1:
                        wait_time = 5 * (2 ** attempt)  # Longer backoff for rate limits
                        print(f"[WARNING] Rate limited, waiting {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        print(f"[ERROR] Rate limited after {self.max_retries} attempts")
                        self.last_error = "Semantic Scholar rate limit exceeded."
                        return None
                elif e.response.status_code >= 500:  # Server error
                    if attempt < self.max_retries - 1:
                        wait_time = 2 ** attempt
                        print(f"[WARNING] Server error, retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        print(f"[ERROR] Server error after {self.max_retries} attempts: {e}")
                        self.last_error = f"Semantic Scholar server error: {e}"
                        return None
                else:
                    error_body = ""
                    if e.response is not None:
                        try:
                            error_body = e.response.json()
                        except ValueError:
                            error_body = e.response.text
                    print(f"[ERROR] HTTP error: {e}")
                    if error_body:
                        print(f"[ERROR] Response body: {error_body}")
                    self.last_error = f"Semantic Scholar HTTP {e.response.status_code}: {error_body or str(e)}"
                    return None

            except Exception as e:
                print(f"[ERROR] Request failed: {e}")
                self.last_error = str(e)
                return None

        return None

    def get_author(self, author_name: str) -> Optional[Author]:
        """
        Get author with h-index and affiliation from OpenAlex (cached)
        """
        # Check cache first
        if author_name in self._author_cache:
            return self._author_cache[author_name]

        url = "https://api.openalex.org/authors"
        params = {'search': author_name, 'per-page': 1}

        data = self._make_request(url, params, 'openalex')
        if not data:
            self._author_cache[author_name] = None
            return None

        results = data.get('results', [])
        if not results:
            self._author_cache[author_name] = None
            return None

        author_data = results[0]

        # Get affiliation - last_known_institutions is a LIST!
        institutions = author_data.get('last_known_institutions', [])
        affiliation = institutions[0] if institutions else None

        author = Author(
            name=author_data.get('display_name', author_name),
            h_index=author_data.get('summary_stats', {}).get('h_index', 0),
            affiliation=affiliation.get('display_name', 'Unknown') if affiliation else 'Unknown',
            institution_type=affiliation.get('type', 'other') if affiliation else 'other',
            works_count=author_data.get('works_count', 0),
            citation_count=author_data.get('cited_by_count', 0)
        )

        # Cache the result
        self._author_cache[author_name] = author
        return author

    def get_venue(self, venue_name: str) -> Optional[Venue]:
        """
        Get venue with h-index from OpenAlex (cached)
        """
        # Check cache first
        if venue_name in self._venue_cache:
            return self._venue_cache[venue_name]

        url = "https://api.openalex.org/sources"
        params = {'search': venue_name, 'per-page': 1}

        data = self._make_request(url, params, 'openalex')
        if not data:
            self._venue_cache[venue_name] = None
            return None

        results = data.get('results', [])
        if not results:
            self._venue_cache[venue_name] = None
            return None

        venue_data = results[0]
        h_index = venue_data.get('summary_stats', {}).get('h_index', 0)
        rank_tier = self._calculate_venue_rank(h_index)

        venue = Venue(
            name=venue_data.get('display_name', venue_name),
            h_index=h_index,
            type=venue_data.get('type', 'unknown'),
            works_count=venue_data.get('works_count', 0),
            cited_by_count=venue_data.get('cited_by_count', 0),
            rank_tier=rank_tier
        )

        # Cache the result
        self._venue_cache[venue_name] = venue
        return venue

    def _calculate_venue_rank(self, h_index: int) -> str:
        """Calculate venue rank tier based on h-index"""
        if h_index > 100:
            return 'Tier 1 (Top 5%)'
        elif h_index >= 50:
            return 'Tier 2 (Top 20%)'
        elif h_index >= 20:
            return 'Tier 3 (Top 50%)'
        else:
            return 'Tier 4'

    def search_paper(self, title: str) -> Optional[Dict]:
        """Search for a paper on Semantic Scholar"""
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            'query': title,
            'limit': 1,
            'fields': 'paperId,title,year,citationCount,influentialCitationCount,authors,venue'
        }

        data = self._make_request(url, params, 'semantic_scholar')
        if not data:
            return None

        results = data.get('data', [])
        return results[0] if results else None

    def get_citations(self, paper_id: str, limit: int = 100) -> List[Citation]:
        """Get citations with contexts and influence from Semantic Scholar"""
        url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations"
        params = {
            'limit': limit,
            'fields': 'contexts,intents,isInfluential,citingPaper.title,citingPaper.authors,citingPaper.venue,citingPaper.year,citingPaper.paperId,citingPaper.externalIds'
        }

        data = self._make_request(url, params, 'semantic_scholar')
        if not data:
            return []

        citations = []
        for item in data.get('data', []):
            citing_paper = item.get('citingPaper', {})
            if not citing_paper:
                continue

            # FIX: Handle missing authors gracefully
            authors = citing_paper.get('authors', [])
            author_names = [a.get('name', 'Unknown') for a in authors] if authors else ['Unknown']

            # Extract paper ID, DOI, and construct URL
            paper_id_str = citing_paper.get('paperId', '')
            external_ids = citing_paper.get('externalIds', {})
            doi = external_ids.get('DOI', '') if external_ids else ''

            # Construct URL (prefer Semantic Scholar, fallback to DOI)
            paper_url = ''
            if paper_id_str:
                paper_url = f"https://www.semanticscholar.org/paper/{paper_id_str}"
            elif doi:
                paper_url = f"https://doi.org/{doi}"

            year_value = citing_paper.get('year', 0)
            if isinstance(year_value, str):
                try:
                    year_value = int(year_value)
                except ValueError:
                    year_value = 0
            elif not isinstance(year_value, int):
                year_value = 0

            contexts = item.get('contexts') or []
            intents = item.get('intents') or []

            if venue := citing_paper.get('venue'):
                venue_name = venue
            elif citing_paper.get('journal'):
                venue_name = citing_paper['journal'].get('name', 'Unknown')
            elif citing_paper.get('conference'):
                venue_name = citing_paper['conference'].get('name', 'Unknown')
            else:
                venue_name = 'Unknown'

            citations.append(Citation(
                citing_paper_title=citing_paper.get('title', 'Unknown'),
                citing_authors=author_names,
                venue=venue_name,
                year=year_value,
                is_influential=item.get('isInfluential', False),
                contexts=contexts,
                intents=intents,
                paper_id=paper_id_str,
                doi=doi,
                url=paper_url
            ))

        return citations

    def categorize_institution(self, institution_type: str, affiliation: str = None) -> str:
        """
        Categorize institution based on OpenAlex type and affiliation name

        Args:
            institution_type: Institution type from OpenAlex
            affiliation: Affiliation name (for better accuracy)

        Returns:
            Category: 'University', 'Industry', 'Government', or 'Other'
        """
        return categorize_institution(institution_type, affiliation)

    def get_author_by_id(self, author_id: str) -> Optional[Dict]:
        """
        Get author information by Semantic Scholar author ID

        Args:
            author_id: Semantic Scholar author ID

        Returns:
            Dictionary with author info
        """
        url = f"https://api.semanticscholar.org/graph/v1/author/{author_id}"
        params = {
            'fields': 'authorId,name,affiliations,paperCount,citationCount,hIndex'
        }

        data = self._make_request(url, params, 'semantic_scholar')
        return data

    def get_author_publications(self, author_id: str, limit: int = 100) -> List[Dict]:
        """
        Get publications for an author

        Args:
            author_id: Semantic Scholar author ID
            limit: Maximum number of publications to retrieve

        Returns:
            List of publication dictionaries
        """
        url = f"https://api.semanticscholar.org/graph/v1/author/{author_id}/papers"
        params = {
            'fields': 'paperId,title,year,venue,citationCount,influentialCitationCount',
            'limit': limit
        }

        data = self._make_request(url, params, 'semantic_scholar')
        if not data:
            return []

        papers = data.get('data', [])

        # Sort by citations (most cited first)
        papers.sort(key=lambda x: x.get('citationCount', 0), reverse=True)

        return papers

    def search_author(self, author_name: str) -> Optional[str]:
        """
        Search for an author by name and return their ID

        Args:
            author_name: Author name to search

        Returns:
            Author ID if found, None otherwise
        """
        url = "https://api.semanticscholar.org/graph/v1/author/search"
        params = {
            'query': author_name,
            'fields': 'authorId,name,affiliations,hIndex',
            'limit': 1
        }

        data = self._make_request(url, params, 'semantic_scholar')
        if not data:
            return None

        results = data.get('data', [])
        if not results:
            return None

        return results[0].get('authorId')


def get_api_client(
    semantic_scholar_key: Optional[str] = None,
    email: Optional[str] = None,
    timeout: int = 15,
    max_retries: int = 3
) -> UnifiedAPIClient:
    """
    Get a configured API client with retry logic

    Args:
        semantic_scholar_key: Free from https://www.semanticscholar.org/product/api
        email: Your email for OpenAlex polite pool
        timeout: Request timeout in seconds
        max_retries: Max retry attempts

    Returns:
        Configured UnifiedAPIClient
    """
    return UnifiedAPIClient(
        semantic_scholar_api_key=semantic_scholar_key,
        email=email,
        timeout=timeout,
        max_retries=max_retries
    )
