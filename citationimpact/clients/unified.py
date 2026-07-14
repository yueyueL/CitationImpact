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


def _extract_openalex_country(author_data) -> str:
    """
    Extract the institution country code (ISO 3166-1 alpha-2, e.g. 'US')
    from OpenAlex author JSON, defensively.

    OpenAlex carries it in last_known_institutions[].country_code and/or
    affiliations[].institution.country_code depending on the record shape.
    Returns '' when unknown.
    """
    if not isinstance(author_data, dict):
        return ''
    # Primary: last_known_institutions (same list used for affiliation)
    for inst in (author_data.get('last_known_institutions') or []):
        if isinstance(inst, dict):
            code = inst.get('country_code')
            if isinstance(code, str) and code.strip():
                return code.strip().upper()
    # Fallback: affiliations[].institution.country_code
    for affiliation in (author_data.get('affiliations') or []):
        if not isinstance(affiliation, dict):
            continue
        inst = affiliation.get('institution')
        if isinstance(inst, dict):
            code = inst.get('country_code')
            if isinstance(code, str) and code.strip():
                return code.strip().upper()
    return ''


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
            # OpenAlex allows 10 req/s in the polite pool, but sustained runs at
            # that edge earn 429 penalties - run at ~4 req/s to stay well clear
            'openalex': 0.25,
            # Semantic Scholar's standard allowance is ~1 req/s even WITH an
            # API key - a faster interval triggers a 429 storm and the run
            # comes back full of holes ('Unknown' affiliations, no FWCI)
            'semantic_scholar': 1.05 if semantic_scholar_api_key else 1.1,
        }

        # Permanent failures per API (a request that gave up after all
        # retries). Read by the analyzer to flag incomplete results.
        self.request_failures = {'semantic_scholar': 0, 'openalex': 0}

        # Adaptive throttle: after repeated FINAL 429 failures the api's
        # min_interval doubles (capped at 8x base) and decays back toward
        # base on success. _base_min_intervals keeps the configured floor.
        self._base_min_intervals = dict(self.min_intervals)
        self._consecutive_429s = {'semantic_scholar': 0, 'openalex': 0}

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

    def _record_failure(self, api: str):
        """Count a request that permanently failed (all retries exhausted)."""
        self.request_failures[api] = self.request_failures.get(api, 0) + 1

    def reset_failure_counts(self):
        """Zero the per-API failure counters (call before a fresh analysis)."""
        for api in self.request_failures:
            self.request_failures[api] = 0

    def get_failure_counts(self) -> Dict[str, int]:
        """Return a copy of the per-API permanent-failure counts."""
        return dict(self.request_failures)

    def _note_request_success(self, api: str):
        """
        Reset the consecutive-429 streak and decay any adaptive throttle:
        halve the api's min_interval back toward its base (floor = base).
        """
        self._consecutive_429s[api] = 0
        base = self._base_min_intervals.get(api)
        if base is None:
            return
        current = self.min_intervals.get(api, base)
        if current > base:
            self.min_intervals[api] = max(base, current / 2)

    def _note_final_429(self, api: str):
        """
        Count a FINAL 429 (rate limit that exhausted all retries). After 2
        consecutive, double the api's min_interval (capped at 8x base).
        """
        self._consecutive_429s[api] = self._consecutive_429s.get(api, 0) + 1
        if self._consecutive_429s[api] < 2:
            return
        base = self._base_min_intervals.get(api)
        if base is None:
            return
        current = self.min_intervals.get(api, base)
        new_interval = min(current * 2, base * 8)
        if new_interval > current:
            self.min_intervals[api] = new_interval
            print(f"[Throttle] Slowing {api} requests to {new_interval:.2f}s")

    def _make_request(self, url: str, params: dict, api: str) -> Optional[dict]:
        """
        Make API GET request with retry logic and exponential backoff

        Returns:
            Response JSON or None if all retries failed
        """
        return self._request_with_retries(
            lambda: self.session.get(url, params=params, timeout=self.timeout),
            api
        )

    def _make_post_request(self, url: str, params: dict, json_body: dict, api: str) -> Optional[dict]:
        """
        Make API POST request (JSON body) with the same rate limiting,
        retry logic, and failure accounting as _make_request.

        Returns:
            Response JSON or None if all retries failed
        """
        return self._request_with_retries(
            lambda: self.session.post(url, params=params, json=json_body, timeout=self.timeout),
            api
        )

    def _request_with_retries(self, send, api: str) -> Optional[dict]:
        """
        Shared retry/backoff engine behind _make_request/_make_post_request.

        Args:
            send: Zero-arg callable performing one HTTP attempt and
                  returning the requests Response.
            api: API key for rate limiting / failure accounting.

        Returns:
            Response JSON or None if all retries failed
        """
        self._rate_limit(api)
        self.last_error = None
        api_label = 'OpenAlex' if api == 'openalex' else 'Semantic Scholar'

        for attempt in range(self.max_retries):
            try:
                response = send()
                response.raise_for_status()
                result = response.json()
                self._note_request_success(api)
                return result

            except requests.exceptions.Timeout:
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    print(f"[WARNING] Timeout on attempt {attempt + 1}/{self.max_retries}, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    print(f"[ERROR] Request timed out after {self.max_retries} attempts")
                    self.last_error = f"{api_label} request timed out after {self.max_retries} attempts."
                    self._record_failure(api)
                    return None

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:  # Rate limit
                    if attempt < self.max_retries - 1:
                        wait_time = 5 * (2 ** attempt)  # Longer backoff for rate limits
                        # Honor the server's Retry-After header when it is
                        # numeric (seconds), capped at 60s; HTTP-date values
                        # fall back to the exponential backoff above
                        retry_after = (getattr(e.response, 'headers', None) or {}).get('Retry-After')
                        if retry_after is not None:
                            try:
                                parsed = float(retry_after)
                                # NaN and negative values parse but crash
                                # time.sleep(); NaN also fails the >= 0
                                # comparison, so this guard covers both and
                                # falls back to the exponential backoff
                                if parsed >= 0:
                                    wait_time = min(parsed, 60)
                            except (TypeError, ValueError):
                                pass
                        print(f"[WARNING] Rate limited, waiting {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        print(f"[ERROR] Rate limited after {self.max_retries} attempts")
                        self.last_error = f"{api_label} rate limit exceeded."
                        self._record_failure(api)
                        self._note_final_429(api)
                        return None
                elif e.response.status_code >= 500:  # Server error
                    if attempt < self.max_retries - 1:
                        wait_time = 2 ** attempt
                        print(f"[WARNING] Server error, retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        print(f"[ERROR] Server error after {self.max_retries} attempts: {e}")
                        self.last_error = f"{api_label} server error: {e}"
                        self._record_failure(api)
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
                    self.last_error = f"{api_label} HTTP {e.response.status_code}: {error_body or str(e)}"
                    self._record_failure(api)
                    return None

            except requests.exceptions.ConnectionError as e:
                # Transient network failures (DNS, reset, refused) - retry with backoff
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt
                    print(f"[WARNING] Connection error on attempt {attempt + 1}/{self.max_retries}, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    print(f"[ERROR] Connection error after {self.max_retries} attempts: {e}")
                    self.last_error = f"{api_label} connection error after {self.max_retries} attempts: {e}"
                    self._record_failure(api)
                    return None

            except Exception as e:
                print(f"[ERROR] Request failed: {e}")
                self.last_error = str(e)
                self._record_failure(api)
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
            # OpenAlex returns explicit nulls for these keys on some authors
            h_index = (candidate.get('summary_stats') or {}).get('h_index') or 0
            has_institution = len(candidate.get('last_known_institutions') or []) > 0
            
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

        # Get affiliation - last_known_institutions is a LIST (or an explicit null)!
        institutions = best_match.get('last_known_institutions') or []
        affiliation = institutions[0] if institutions else None

        author = Author(
            name=best_match.get('display_name') or original_name,
            h_index=(best_match.get('summary_stats') or {}).get('h_index') or 0,
            affiliation=(affiliation.get('display_name') or 'Unknown') if affiliation else 'Unknown',
            institution_type=(affiliation.get('type') or 'other') if affiliation else 'other',
            works_count=best_match.get('works_count') or 0,
            citation_count=best_match.get('cited_by_count') or 0,
            match_confidence='name',  # Name-only search - may be a same-named person
            country=_extract_openalex_country(best_match)
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
        h_index = (venue_data.get('summary_stats') or {}).get('h_index') or 0
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
            # externalIds is needed for the FWCI DOI fast-path (analyzer passes
            # the paper's DOI to get_field_normalized_metrics)
            'fields': 'paperId,title,year,citationCount,influentialCitationCount,authors,venue,externalIds'
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
        
        # No candidate shared any words with the query - treat as not found
        if best_match is None:
            print(f"[WARNING] No matching paper found for '{title[:60]}'")
            return None

        # Require minimum similarity score (0.5 = at least 50% word overlap)
        if best_score < 0.5:
            print(f"[WARNING] No good title match found. Best match '{best_match.get('title', '')}' has only {best_score:.0%} similarity")
            # Still return best match but warn user

        return best_match

    def get_field_normalized_metrics(self, title: str, doi: str = None) -> Optional[Dict]:
        """
        Fetch field-normalized impact metrics for a paper from OpenAlex.

        Returns a dict with FWCI (Field-Weighted Citation Impact: 1.0 = world
        average for papers of the same field, year, and type) and the citation
        percentile within the field, or None if the paper isn't found or
        OpenAlex doesn't have the metrics.
        """
        work = None
        if doi:
            url = f"https://api.openalex.org/works/https://doi.org/{doi}"
            work = self._make_request(url, {}, 'openalex')

        if not work and title:
            url = "https://api.openalex.org/works"
            params = {
                # Commas separate filter clauses in the OpenAlex API - a comma
                # in the title would be parsed as a second (invalid) filter,
                # so replace them (OpenAlex's documented workaround); the
                # exact-title match below is normalization-based anyway
                'filter': f"title.search:{title.replace(',', ' ')}",
                'per-page': 5,
                'select': 'title,fwci,citation_normalized_percentile,cited_by_count',
            }
            data = self._make_request(url, params, 'openalex')
            results = (data or {}).get('results', [])

            def _normalize(s):
                import re
                return ' '.join(re.sub(r'[^\w\s]', '', (s or '').lower()).split())

            wanted = _normalize(title)
            for candidate in results:
                if _normalize(candidate.get('title', '')) == wanted:
                    work = candidate
                    break

        if not work:
            return None

        fwci = work.get('fwci')
        percentile_info = work.get('citation_normalized_percentile') or {}
        percentile = percentile_info.get('value')
        if fwci is None and percentile is None:
            return None

        return {
            'fwci': fwci,
            'citation_percentile': percentile,
            'is_top_1_percent': bool(percentile_info.get('is_in_top_1_percent')),
            'is_top_10_percent': bool(percentile_info.get('is_in_top_10_percent')),
            'openalex_cited_by_count': work.get('cited_by_count'),
            'source': 'openalex',
        }
    
    def get_paper_by_id(self, paper_id: str) -> Optional[Dict]:
        """Get paper directly by Semantic Scholar paper ID"""
        url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}"
        params = {
            # externalIds is needed for DOI enrichment (see hybrid._enhance_citations_with_s2)
            'fields': 'paperId,title,year,citationCount,influentialCitationCount,authors,venue,externalIds'
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

        # A batch prefetch (get_authors_batch) may have staged a raw S2-only
        # profile for this id. Reuse it as the S2 base - skipping the
        # per-author GET - but still run the OpenAlex enrichment below; the
        # enriched result then supersedes the raw entry under the s2: key.
        raw_author = self._author_cache.get(f"s2raw:{author_id}")
        if raw_author is not None:
            data = {
                'name': raw_author.name if raw_author.name != 'Unknown' else None,
                'hIndex': raw_author.h_index,
                'affiliations': ([raw_author.affiliation]
                                 if raw_author.affiliation and raw_author.affiliation != 'Unknown'
                                 else []),
                'paperCount': raw_author.works_count,
                'citationCount': raw_author.citation_count,
            }
        else:
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
        name = data.get('name') or author_name or 'Unknown'
        h_index = data.get('hIndex') or 0
        affiliations = data.get('affiliations') or []
        s2_affiliation = affiliations[0] if affiliations else None
        
        # S2 doesn't provide institution type or country, default to 'other'/''
        institution_type = 'other'
        affiliation = s2_affiliation or 'Unknown'
        country = ''

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
            country = getattr(openalex_author, 'country', '') or ''

        author = Author(
            name=name,
            h_index=h_index,
            affiliation=affiliation,
            institution_type=institution_type,
            works_count=data.get('paperCount', 0),
            citation_count=data.get('citationCount', 0),
            match_confidence='id',  # Resolved via unique S2 author ID
            country=country
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
        affiliation_matched = False  # True when the chosen candidate's affiliation corroborates
        affiliation_lower = affiliation.lower()
        
        for author_data in results:
            institutions = author_data.get('last_known_institutions', [])
            if not institutions:
                continue

            # Score the candidate by its best match across ALL institutions
            candidate_score = 0
            for inst in institutions:
                inst_name = (inst.get('display_name') or '').lower()
                if not inst_name:
                    # Skip unnamed institutions ('' would match any affiliation)
                    continue
                if affiliation_lower in inst_name or inst_name in affiliation_lower:
                    score = 2  # High score for affiliation match
                else:
                    score = 1  # Base score
                candidate_score = max(candidate_score, score)

            if candidate_score > best_score:
                best_score = candidate_score
                best_match = author_data

        # Score 2 means the candidate's institution actually matched the known affiliation
        affiliation_matched = best_score >= 2

        # If no affiliation match, use first result
        if not best_match and results:
            best_match = results[0]

        if not best_match:
            return None

        institutions = best_match.get('last_known_institutions', [])
        inst = institutions[0] if institutions else None

        return Author(
            name=best_match.get('display_name') or author_name,
            h_index=(best_match.get('summary_stats') or {}).get('h_index') or 0,
            affiliation=(inst.get('display_name') or 'Unknown') if inst else 'Unknown',
            institution_type=(inst.get('type') or 'other') if inst else 'other',
            works_count=best_match.get('works_count') or 0,
            citation_count=best_match.get('cited_by_count') or 0,
            # Affiliation-corroborated matches are 'verified'; fallback is name-only
            match_confidence='verified' if affiliation_matched else 'name',
            country=_extract_openalex_country(best_match)
        )

    def get_authors_batch(self, author_ids: List[str]) -> Dict[str, Author]:
        """
        Batch-resolve Semantic Scholar author IDs via the S2 batch endpoint.

        One POST resolves up to 500 authors, replacing dozens of per-author
        GET requests (which trigger 429 storms under sustained load). The
        endpoint returns a JSON array aligned with the input ids; entries
        can be null (unknown id) and every field can be null.

        The returned Authors are RAW S2 bases (no institution type/country -
        S2 doesn't carry them). They are staged in the in-memory cache so a
        subsequent get_author_by_s2_id call skips the per-author S2 GET and
        only performs the OpenAlex enrichment on top of this base.

        Args:
            author_ids: Semantic Scholar author IDs

        Returns:
            Dict mapping author_id -> Author for the ids that resolved
            (unknown/failed ids are simply absent; {} on total failure).
        """
        results: Dict[str, Author] = {}
        if not author_ids:
            return results

        # Serve in-memory cache hits and de-duplicate before POSTing
        # (enriched s2: entries first, then raw profiles staged earlier)
        to_fetch: List[str] = []
        seen = set()
        for author_id in author_ids:
            if not author_id or author_id in seen:
                continue
            seen.add(author_id)
            cache_key = f"s2:{author_id}"
            if cache_key in self._author_cache:
                cached = self._author_cache[cache_key]
                if cached is not None:
                    results[author_id] = cached
                continue
            raw_cached = self._author_cache.get(f"s2raw:{author_id}")
            if raw_cached is not None:
                results[author_id] = raw_cached
                continue
            to_fetch.append(author_id)

        url = "https://api.semanticscholar.org/graph/v1/author/batch"
        params = {'fields': 'name,hIndex,affiliations,paperCount,citationCount'}

        for start in range(0, len(to_fetch), 500):
            chunk = to_fetch[start:start + 500]
            data = self._make_post_request(url, params, {'ids': chunk}, 'semantic_scholar')
            if not isinstance(data, list):
                # Chunk failed - callers fall back to per-id lookups
                continue

            for author_id, entry in zip(chunk, data):
                if not isinstance(entry, dict):
                    continue  # null entry: S2 doesn't know this id

                # Same null-safe parsing as get_author_by_s2_id
                affiliations = entry.get('affiliations') or []
                s2_affiliation = affiliations[0] if affiliations else None
                try:
                    author = Author(
                        name=entry.get('name') or 'Unknown',
                        h_index=entry.get('hIndex') or 0,
                        affiliation=s2_affiliation or 'Unknown',
                        # S2 doesn't provide institution type or country
                        institution_type='other',
                        works_count=entry.get('paperCount') or 0,
                        citation_count=entry.get('citationCount') or 0,
                        semantic_scholar_id=author_id,
                        match_confidence='id',  # Resolved via unique S2 author ID
                        country=''
                    )
                except (ValueError, TypeError):
                    continue  # malformed entry - leave to the per-id fallback

                results[author_id] = author
                # Stage under a raw key, NOT the enriched s2: key that
                # get_author_by_s2_id checks first - the raw S2 profile has no
                # institution type/country and caching it there would silently
                # skip the documented OpenAlex enrichment for the whole
                # session. get_author_by_s2_id upgrades this entry instead:
                # it reuses the raw base (no second S2 GET), enriches it, and
                # caches the enriched author under the s2: key.
                self._author_cache[f"s2raw:{author_id}"] = author

        return results

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

        # Sort by citations (most cited first); S2 may return null citationCount
        papers.sort(key=lambda x: x.get('citationCount') or 0, reverse=True)

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

    def search_author_candidates(self, author_name: str, limit: int = 5) -> List[Dict]:
        """
        Search Semantic Scholar for author candidates matching a name.

        Unlike search_author() (which returns only the first hit's ID), this
        returns multiple candidates so callers can disambiguate same-named
        authors using affiliation / h-index / paper count.

        Args:
            author_name: Author name to search
            limit: Maximum number of candidates to return (default: 5)

        Returns:
            List of candidate dicts with keys:
            'author_id', 'name', 'affiliation', 'h_index', 'paper_count'.
            Empty list on failure or no results.
        """
        if not author_name or not author_name.strip():
            return []

        url = "https://api.semanticscholar.org/graph/v1/author/search"
        params = {
            'query': author_name.strip(),
            'fields': 'name,affiliations,hIndex,paperCount',
            'limit': limit
        }

        data = self._make_request(url, params, 'semantic_scholar')
        if not data:
            return []

        candidates = []
        for item in data.get('data', [])[:limit]:
            if not item:
                continue
            affiliations = item.get('affiliations') or []
            candidates.append({
                'author_id': str(item.get('authorId') or ''),
                'name': item.get('name') or '',
                'affiliation': affiliations[0] if affiliations else '',
                'h_index': item.get('hIndex') or 0,
                'paper_count': item.get('paperCount') or 0
            })

        return candidates


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
