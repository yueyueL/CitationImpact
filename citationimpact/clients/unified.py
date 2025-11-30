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

from ..models import Author, Venue, Citation, AuthorInfo
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
        
        NOTE: This method searches by name which can be inaccurate for common names.
        When possible, use get_author_by_s2_id() with the Semantic Scholar author ID
        for accurate author identification.
        """
        # Validate input
        if not author_name or not author_name.strip():
            return None
        
        author_name = author_name.strip()
        
        # Check cache first
        if author_name in self._author_cache:
            return self._author_cache[author_name]
        
        # Generate name variations to try (handles abbreviated names like "C. Smith")
        name_variations = self._generate_name_variations(author_name)
        
        for search_name in name_variations:
            result = self._search_openalex_author(search_name, author_name)
            if result and result.affiliation != 'Unknown':
                return result
        
        # Return best result even if affiliation is Unknown
        for search_name in name_variations:
            result = self._search_openalex_author(search_name, author_name)
            if result:
                return result
        
        self._author_cache[author_name] = None
        return None
    
    def _generate_name_variations(self, author_name: str) -> list:
        """
        Generate variations of author name for searching.
        Handles cases like 'C. Tantithamthavorn' -> ['C. Tantithamthavorn', 'Tantithamthavorn']
        """
        import re
        variations = [author_name]
        
        # If name has initials (like "C. Smith" or "A. B. Johnson"), try last name only
        parts = author_name.split()
        if len(parts) >= 2:
            # Check if first parts are initials (single letter or letter with period)
            non_initial_parts = []
            for part in parts:
                # Remove periods and check if it's an initial
                clean = part.replace('.', '').strip()
                if len(clean) > 1:  # Not an initial
                    non_initial_parts.append(part)
            
            # If we found non-initial parts, add them as a variation
            if non_initial_parts and len(non_initial_parts) < len(parts):
                # Add last name only
                variations.append(non_initial_parts[-1])
                # Add all non-initial parts
                if len(non_initial_parts) > 1:
                    variations.append(' '.join(non_initial_parts))
        
        return variations
    
    def _search_openalex_author(self, search_name: str, original_name: str) -> Optional[Author]:
        """
        Search OpenAlex for an author by name.
        """
        url = "https://api.openalex.org/authors"
        # Request more results to allow for disambiguation
        params = {'search': search_name, 'per-page': 5}

        data = self._make_request(url, params, 'openalex')
        if not data:
            return None

        results = data.get('results', [])
        if not results:
            return None

        # Try to find the best match for the author name
        # Prefer exact name matches and authors with higher h-index as a tiebreaker
        best_match = None
        best_score = -1
        original_name_lower = original_name.lower().strip()
        search_name_lower = search_name.lower().strip()
        
        for candidate in results:
            display_name = candidate.get('display_name', '')
            display_name_lower = display_name.lower().strip()
            h_index = candidate.get('summary_stats', {}).get('h_index', 0) or 0
            has_institution = len(candidate.get('last_known_institutions', [])) > 0
            
            # Calculate match score
            score = 0
            
            # Check against both original and search name
            for check_name in [original_name_lower, search_name_lower]:
                # Exact match is best
                if display_name_lower == check_name:
                    score = max(score, 1000)
                # Name contains search query
                elif check_name in display_name_lower:
                    score = max(score, 500)
                # Display name is contained in search query
                elif display_name_lower in check_name:
                    score = max(score, 400)
                else:
                    # Partial match - check name parts
                    query_parts = set(check_name.split())
                    name_parts = set(display_name_lower.split())
                    # Remove initials from comparison
                    query_parts = {p for p in query_parts if len(p.replace('.', '')) > 1}
                    name_parts = {p for p in name_parts if len(p.replace('.', '')) > 1}
                    common_parts = query_parts.intersection(name_parts)
                    if len(common_parts) >= 2:
                        score = max(score, 300)
                    elif common_parts:
                        score = max(score, 100)
            
            # IMPORTANT: Prefer authors WITH institution data
            # This helps when same person appears with/without institution
            if has_institution:
                score += 200
            
            # Add h-index as a small tiebreaker (max 50 points)
            score += min(h_index, 50)
            
            if score > best_score:
                best_score = score
                best_match = candidate
        
        if not best_match:
            return None

        # Get affiliation - last_known_institutions is a LIST!
        institutions = best_match.get('last_known_institutions', [])
        affiliation = institutions[0] if institutions else None

        author = Author(
            name=best_match.get('display_name', original_name),
            h_index=best_match.get('summary_stats', {}).get('h_index', 0),
            affiliation=affiliation.get('display_name', 'Unknown') if affiliation else 'Unknown',
            institution_type=affiliation.get('type', 'other') if affiliation else 'other',
            works_count=best_match.get('works_count', 0),
            citation_count=best_match.get('cited_by_count', 0)
        )

        # Cache the result under original name
        self._author_cache[original_name] = author
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
        """
        Search for a paper on Semantic Scholar
        
        Args:
            title: Paper title OR Semantic Scholar paper ID (40-char hex string)
        """
        # Check if input is a Semantic Scholar paper ID (40-char hex string)
        if len(title) == 40 and all(c in '0123456789abcdef' for c in title.lower()):
            return self.get_paper_by_id(title)
        
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            'query': title,
            'limit': 5,  # Get top 5 to find best match
            'fields': 'paperId,title,year,citationCount,influentialCitationCount,authors,venue'
        }

        data = self._make_request(url, params, 'semantic_scholar')
        if not data:
            return None

        results = data.get('data', [])
        if not results:
            return None
        
        # Find best matching paper by title similarity
        import re
        
        def normalize(s):
            """Normalize string for comparison"""
            s = s.lower()
            s = re.sub(r'[^\w\s]', '', s)
            return ' '.join(s.split())
        
        query_normalized = normalize(title)
        
        best_match = None
        best_score = 0
        
        for paper in results:
            paper_title = paper.get('title', '')
            paper_normalized = normalize(paper_title)
            
            # Calculate word overlap
            query_words = set(query_normalized.split())
            paper_words = set(paper_normalized.split())
            
            if not query_words or not paper_words:
                continue
            
            # Jaccard similarity
            intersection = len(query_words & paper_words)
            union = len(query_words | paper_words)
            score = intersection / union if union > 0 else 0
            
            # Bonus for exact substring match
            if query_normalized in paper_normalized or paper_normalized in query_normalized:
                score += 0.3
            
            if score > best_score:
                best_score = score
                best_match = paper
        
        # Require minimum similarity score (0.5 = at least 50% word overlap)
        if best_score < 0.5:
            print(f"[WARNING] No good title match found. Best match '{best_match.get('title', '')}' has only {best_score:.0%} similarity")
            # Still return best match but warn user
        
        return best_match
    
    def get_paper_by_id(self, paper_id: str) -> Optional[Dict]:
        """Get paper directly by Semantic Scholar paper ID"""
        url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}"
        params = {
            'fields': 'paperId,title,year,citationCount,influentialCitationCount,authors,venue'
        }
        
        data = self._make_request(url, params, 'semantic_scholar')
        return data if data else None

    def get_citations(self, paper_id: str, limit: int = 100) -> List[Citation]:
        """Get citations with contexts and influence from Semantic Scholar"""
        url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations"
        params = {
            'limit': limit,
            # Include citationCount & influentialCitationCount for impact analysis
            # (helps identify "highly-cited papers that cite you")
            'fields': 'contexts,intents,isInfluential,citingPaper.title,citingPaper.authors,citingPaper.venue,citingPaper.year,citingPaper.paperId,citingPaper.externalIds,citingPaper.citationCount,citingPaper.influentialCitationCount'
        }

        data = self._make_request(url, params, 'semantic_scholar')
        if not data:
            return []

        citations = []
        for item in data.get('data', []):
            citing_paper = item.get('citingPaper', {})
            if not citing_paper:
                continue

            # FIX: Handle missing authors gracefully and extract author IDs
            authors = citing_paper.get('authors', [])
            author_names = [a.get('name', 'Unknown') for a in authors] if authors else ['Unknown']
            
            # NEW: Extract author IDs for accurate author disambiguation
            authors_with_ids = []
            for a in (authors or []):
                author_name = a.get('name', 'Unknown')
                author_id = a.get('authorId', '')  # Semantic Scholar unique author ID
                if author_name and author_name != 'Unknown':
                    authors_with_ids.append(AuthorInfo(name=author_name, author_id=author_id or ''))

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

            # Get citation counts for the CITING paper (for impact analysis)
            citing_paper_citations = citing_paper.get('citationCount', 0) or 0
            citing_paper_influential = citing_paper.get('influentialCitationCount', 0) or 0
            
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
                url=paper_url,
                authors_with_ids=authors_with_ids,
                # Impact metrics: how cited is the paper that cites you
                citation_count=citing_paper_citations,
                influential_citation_count=citing_paper_influential
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

    def get_author_by_s2_id(self, author_id: str, author_name: str = None) -> Optional[Author]:
        """
        Get Author object by Semantic Scholar author ID (preferred method for accuracy)
        
        This method uses the unique S2 author ID to get accurate author information,
        avoiding the name disambiguation problem that occurs with common names.
        
        Args:
            author_id: Semantic Scholar author ID (unique identifier)
            author_name: Optional author name (used for cache key and fallback)
            
        Returns:
            Author object with h-index and affiliation, or None if not found
        """
        if not author_id:
            # Fall back to name-based search if no ID provided
            if author_name:
                return self.get_author(author_name)
            return None
        
        # Create cache key using S2 author ID for accurate caching
        cache_key = f"s2:{author_id}"
        if cache_key in self._author_cache:
            return self._author_cache[cache_key]
        
        # Fetch from Semantic Scholar API
        url = f"https://api.semanticscholar.org/graph/v1/author/{author_id}"
        params = {
            'fields': 'authorId,name,affiliations,paperCount,citationCount,hIndex'
        }
        
        data = self._make_request(url, params, 'semantic_scholar')
        
        if not data:
            # Try fallback to name-based search if S2 lookup fails
            if author_name:
                return self.get_author(author_name)
            self._author_cache[cache_key] = None
            return None
        
        # Extract author information from S2 response
        name = data.get('name', author_name or 'Unknown')
        h_index = data.get('hIndex') or 0
        affiliations = data.get('affiliations', [])
        s2_affiliation = affiliations[0] if affiliations else None
        
        # S2 doesn't provide institution type, default to 'other'
        institution_type = 'other'
        affiliation = s2_affiliation or 'Unknown'
        
        # ALWAYS try OpenAlex to get institution type and fill missing affiliation
        # S2 often has incomplete affiliation data
        if s2_affiliation:
            # S2 has affiliation - use it to help disambiguate OpenAlex search
            openalex_author = self._get_openalex_author_by_affiliation(name, s2_affiliation)
        else:
            # S2 has no affiliation - try direct OpenAlex name search
            openalex_author = self.get_author(name)
        
        if openalex_author:
            # Use OpenAlex data to fill gaps
            if h_index == 0:
                h_index = openalex_author.h_index
            if affiliation == 'Unknown':
                affiliation = openalex_author.affiliation
            institution_type = openalex_author.institution_type
        
        author = Author(
            name=name,
            h_index=h_index,
            affiliation=affiliation,
            institution_type=institution_type,
            works_count=data.get('paperCount', 0),
            citation_count=data.get('citationCount', 0)
        )
        
        # Cache by S2 author ID
        self._author_cache[cache_key] = author
        # Also cache by name for backward compatibility
        if name:
            self._author_cache[name] = author
        
        return author
    
    def _get_openalex_author_by_affiliation(self, author_name: str, affiliation: str) -> Optional[Author]:
        """
        Get author from OpenAlex with affiliation filter for better disambiguation
        
        Args:
            author_name: Author's name
            affiliation: Known affiliation to help disambiguate
            
        Returns:
            Author object or None
        """
        url = "https://api.openalex.org/authors"
        # Include affiliation in search for better results
        search_query = f"{author_name}"
        params = {
            'search': search_query,
            'per-page': 5,  # Get multiple results to find best match
        }
        
        data = self._make_request(url, params, 'openalex')
        if not data:
            return None
        
        results = data.get('results', [])
        if not results:
            return None
        
        # Try to find the best matching author based on affiliation
        best_match = None
        best_score = 0
        affiliation_lower = affiliation.lower()
        
        for author_data in results:
            institutions = author_data.get('last_known_institutions', [])
            if not institutions:
                continue
            
            # Check if any institution matches the known affiliation
            for inst in institutions:
                inst_name = inst.get('display_name', '').lower()
                if affiliation_lower in inst_name or inst_name in affiliation_lower:
                    # Found a match!
                    score = 2  # High score for affiliation match
                else:
                    score = 1  # Base score
                
                if score > best_score:
                    best_score = score
                    best_match = author_data
                    break
        
        # If no affiliation match, use first result
        if not best_match and results:
            best_match = results[0]
        
        if not best_match:
            return None
        
        institutions = best_match.get('last_known_institutions', [])
        inst = institutions[0] if institutions else None
        
        return Author(
            name=best_match.get('display_name', author_name),
            h_index=best_match.get('summary_stats', {}).get('h_index', 0),
            affiliation=inst.get('display_name', 'Unknown') if inst else 'Unknown',
            institution_type=inst.get('type', 'other') if inst else 'other',
            works_count=best_match.get('works_count', 0),
            citation_count=best_match.get('cited_by_count', 0)
        )

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
