1
"""
Hybrid API Client - Combines Semantic Scholar and Google Scholar for comprehensive analysis

Strategy:
1. Paper Search: Try S2 first (fast, has paper IDs), fall back to GS if not found
2. Citations: Get from both sources, deduplicate and merge
3. Authors: Use S2 IDs for disambiguation, enhance with GS h-index if higher
4. Venues: Combine data from both sources

Benefits:
- Best coverage (GS has more papers)
- Accurate author disambiguation (S2 unique IDs)
- AI-powered influential citation detection (S2)
- Higher h-indices from GS user profiles
"""

import time
import hashlib
from typing import Dict, List, Optional, Set, Tuple
from difflib import SequenceMatcher

from ..models import Author, Venue, Citation, AuthorInfo
from ..cache import get_author_cache
from .unified import UnifiedAPIClient, get_api_client

# Try to import Google Scholar client
try:
    from .google_scholar import GoogleScholarClient, get_google_scholar_client
    GS_AVAILABLE = True
except (ImportError, TypeError):
    GS_AVAILABLE = False
    GoogleScholarClient = None


def _normalize_title(title: str) -> str:
    """Normalize a paper title for comparison"""
    if not title:
        return ""
    # Lowercase, remove punctuation, normalize whitespace
    import re
    normalized = title.lower()
    normalized = re.sub(r'[^\w\s]', '', normalized)
    normalized = ' '.join(normalized.split())
    return normalized


def _titles_match(title1: str, title2: str, threshold: float = 0.85) -> bool:
    """Check if two titles are similar enough to be the same paper"""
    norm1 = _normalize_title(title1)
    norm2 = _normalize_title(title2)
    
    if not norm1 or not norm2:
        return False
    
    # Quick exact match
    if norm1 == norm2:
        return True
    
    # Fuzzy match
    ratio = SequenceMatcher(None, norm1, norm2).ratio()
    return ratio >= threshold


def _normalize_name(name: str) -> str:
    """Normalize author name for cache lookup"""
    if not name:
        return ""
    # Lowercase, remove punctuation except hyphens, normalize whitespace
    import re
    normalized = name.lower().strip()
    normalized = re.sub(r'[^\w\s\-]', '', normalized)
    normalized = ' '.join(normalized.split())
    return normalized


def _extract_last_name(name: str) -> str:
    """Extract last name for search (helps find authors with abbreviated first names)"""
    if not name:
        return ""
    parts = name.strip().split()
    return parts[-1] if parts else ""


class HybridAPIClient:
    """
    Hybrid client that combines Semantic Scholar and Google Scholar
    
    This provides the most comprehensive analysis by:
    - Using S2 for fast initial search and author IDs
    - Supplementing with GS for missing citations
    - Cross-referencing author data for best h-indices
    - Combining venue information
    
    Google Scholar options (in order of reliability):
    1. ScraperAPI (paid, most reliable): Pass scraper_api_key
    2. Visible browser (free): Allows manual CAPTCHA solving
    3. Free proxies (free but unreliable): Pass use_gs_proxy=True
    """
    
    def __init__(
        self,
        semantic_scholar_api_key: Optional[str] = None,
        email: Optional[str] = None,
        use_gs_proxy: bool = False,
        scraper_api_key: Optional[str] = None,
        timeout: int = 15,
        max_retries: int = 3,
        gs_cites_id: Optional[List[str]] = None  # Direct GS citation access (no search!)
    ):
        """
        Initialize hybrid client with both S2 and GS backends
        
        Args:
            semantic_scholar_api_key: Optional S2 API key for higher rate limits
            email: Email for OpenAlex polite pool
            use_gs_proxy: Use free proxy for Google Scholar (unreliable)
            scraper_api_key: ScraperAPI key for Google Scholar (most reliable)
                            Get key at: https://www.scraperapi.com/
            timeout: Request timeout
            max_retries: Max retries for failed requests
            gs_cites_id: List of Google Scholar citation IDs for DIRECT access
                        When provided, we can skip GS search entirely!
        """
        # Store direct citation IDs for later use
        self.gs_cites_id = gs_cites_id
        # Primary: Semantic Scholar + OpenAlex
        self.s2_client = get_api_client(
            semantic_scholar_key=semantic_scholar_api_key,
            email=email,
            timeout=timeout,
            max_retries=max_retries
        )
        
        # Secondary: Google Scholar (if available)
        self.gs_client = None
        self.gs_available = GS_AVAILABLE
        
        if GS_AVAILABLE:
            try:
                self.gs_client = get_google_scholar_client(
                    use_proxy=use_gs_proxy,
                    use_selenium=True,
                    headless=False,  # Use visible browser for CAPTCHA solving
                    scraper_api_key=scraper_api_key
                )
            except Exception as e:
                print(f"[Hybrid] Warning: Could not initialize Google Scholar client: {e}")
                self.gs_available = False
        
        # Caches
        self._paper_cache: Dict[str, Dict] = {}  # title -> paper data
        self._author_cache: Dict[str, Author] = {}  # author_id/name -> Author
        self._venue_cache: Dict[str, Venue] = {}  # venue_name -> Venue
        self._paper_id_to_title: Dict[str, str] = {}  # S2 paper ID -> title (for GS lookup)
        
        # Track sources for transparency
        self.last_sources_used: Dict[str, str] = {}
    
    def search_paper(self, title: str) -> Optional[Dict]:
        """
        Search for a paper using both sources
        
        Strategy:
        1. Try Semantic Scholar first (fast, has paper ID)
        2. If S2 finds it with good citation count, use that
        3. If S2 doesn't find it or has low citations, try GS
        4. Return the better result
        """
        print(f"[Hybrid] Searching for paper: {title[:50]}...")
        self.last_sources_used['paper_search'] = []
        
        # Try Semantic Scholar first
        s2_paper = self.s2_client.search_paper(title)
        
        if s2_paper:
            s2_citations = s2_paper.get('citationCount', 0)
            print(f"[Hybrid] S2 found paper with {s2_citations} citations")
            self.last_sources_used['paper_search'].append('semantic_scholar')
            
            # Store mapping from S2 paper ID to title (for later GS lookup)
            paper_id = s2_paper.get('paperId', '')
            paper_title = s2_paper.get('title', title)
            if paper_id:
                self._paper_id_to_title[paper_id] = paper_title
            
            # If S2 has reasonable citations, use it
            if s2_citations >= 10:
                return s2_paper
        
        # Try Google Scholar if available and S2 didn't find enough
        # Only try GS if S2 found nothing - avoid blocking when we have S2 results
        if self.gs_available and self.gs_client and not s2_paper:
            print(f"[Hybrid] S2 found nothing, trying Google Scholar...")
            try:
                gs_paper = self.gs_client.search_paper(title)
                
                if gs_paper:
                    gs_citations = gs_paper.get('citationCount', 0)
                    print(f"[Hybrid] GS found paper with {gs_citations} citations")
                    self.last_sources_used['paper_search'].append('google_scholar')
                    return gs_paper
            except Exception as e:
                print(f"[Hybrid] Google Scholar search failed: {e}")
        
        # Return S2 result (use what we have!)
        if s2_paper:
            print(f"[Hybrid] Using Semantic Scholar result")
        return s2_paper
    
    def get_citations(self, paper_id: str, limit: int = 100) -> List[Citation]:
        """
        Get citations from both sources and merge
        
        Strategy:
        1. ALWAYS get citations from Semantic Scholar first (reliable, has author IDs)
        2. If we have gs_cites_id, use DIRECT GS citation access (no search!)
        3. Otherwise try Google Scholar search as fallback
        4. Deduplicate by title matching
        """
        print(f"[Hybrid] Getting citations for paper ID: {paper_id}")
        self.last_sources_used['citations'] = []
        
        all_citations: List[Citation] = []
        seen_titles: Set[str] = set()
        
        # Check if we have direct GS citation access (from My Papers)
        has_direct_gs_access = self.gs_cites_id and len(self.gs_cites_id) > 0
        if has_direct_gs_access:
            print(f"[Hybrid] ✓ Have direct GS citation IDs: {self.gs_cites_id[:2]}...")
        
        # Get Semantic Scholar citations (primary - has author IDs and influential flags)
        try:
            s2_citations = self.s2_client.get_citations(paper_id, limit=limit)
            
            if s2_citations:
                print(f"[Hybrid] Got {len(s2_citations)} citations from Semantic Scholar")
                self.last_sources_used['citations'].append(f'semantic_scholar:{len(s2_citations)}')
                
                for citation in s2_citations:
                    all_citations.append(citation)
                    seen_titles.add(_normalize_title(citation.citing_paper_title))
            else:
                print(f"[Hybrid] S2 returned 0 citations")
        except Exception as e:
            print(f"[Hybrid] ⚠️ S2 citations failed: {str(e)[:50]}")
        
        # Get Google Scholar citations
        # Priority: Direct access via cites_id > Search by title (may trigger CAPTCHA)
        if self.gs_available and self.gs_client:
            s2_count = len(all_citations)
            
            try:
                gs_citations = []
                
                if has_direct_gs_access:
                    # DIRECT ACCESS - use cites_id URL (no search = no CAPTCHA!)
                    print(f"[Hybrid] Using DIRECT GS citation access (no search needed)...")
                    gs_citations = self.gs_client.get_citations_by_cites_id(
                        self.gs_cites_id, limit=limit
                    )
                else:
                    # Fallback: Search by paper title (may trigger CAPTCHA)
                    paper_title = self._paper_id_to_title.get(paper_id, '')
                    if paper_title:
                        if s2_count == 0:
                            print(f"[Hybrid] S2 found 0 citations, trying GS search...")
                        else:
                            print(f"[Hybrid] S2 found {s2_count}, checking GS for more...")
                        gs_citations = self.gs_client.get_citations(paper_title, limit=limit)
                
                if gs_citations:
                    new_from_gs = 0
                    for gs_citation in gs_citations:
                        gs_title_norm = _normalize_title(gs_citation.citing_paper_title)
                        
                        # Check if this is a duplicate
                        is_duplicate = False
                        for seen_title in seen_titles:
                            if _titles_match(gs_title_norm, seen_title):
                                is_duplicate = True
                                break
                        
                        if not is_duplicate and len(all_citations) < limit:
                            all_citations.append(gs_citation)
                            seen_titles.add(gs_title_norm)
                            new_from_gs += 1
                    
                    if new_from_gs > 0:
                        print(f"[Hybrid] ✓ Added {new_from_gs} NEW citations from Google Scholar")
                        self.last_sources_used['citations'].append(f'google_scholar:{new_from_gs}')
                    else:
                        print(f"[Hybrid] GS found {len(gs_citations)} citations (all duplicates of S2)")
                else:
                    print(f"[Hybrid] GS returned no citations")
                        
            except Exception as e:
                print(f"[Hybrid] ⚠️ GS unavailable: {str(e)[:50]}")
                if s2_count > 0:
                    print(f"[Hybrid] Using {s2_count} S2 citations only")
        
        # ENHANCEMENT: Use S2 to fill in missing data for GS-only citations
        # This adds: author IDs, DOI, citation count, influential flag
        all_citations = self._enhance_citations_with_s2(all_citations)
        
        print(f"[Hybrid] Total: {len(all_citations)} unique citations")
        return all_citations
    
    def _enhance_citations_with_s2(self, citations: List[Citation]) -> List[Citation]:
        """
        Enhance citations (especially from GS) with data from ALL available APIs.
        
        This fills in missing information using (in priority order):
        1. Semantic Scholar API - Author IDs, DOI, citation counts, influential flag
        2. Crossref API - DOI, venue, year
        3. DBLP API - Venue info for CS papers
        
        Key benefit: All these are APIs = NO CAPTCHA!
        """
        enhanced = []
        s2_enhanced_count = 0
        crossref_enhanced_count = 0
        
        # Initialize Crossref client once (avoid repeated init messages)
        crossref_client = None
        try:
            from .crossref import CrossrefClient
            crossref_client = CrossrefClient()
        except Exception:
            pass
        
        print(f"[Hybrid] Enhancing {len(citations)} citations with API data...")
        
        for citation in citations:
            # Track what we have and what's missing
            has_s2_data = citation.paper_id and citation.authors_with_ids
            has_venue = citation.venue and citation.venue != 'Unknown'
            has_year = citation.year and citation.year > 0
            has_doi = citation.doi and len(citation.doi) > 0
            
            # Skip if already complete
            if has_s2_data and has_venue and has_year:
                enhanced.append(citation)
                continue
            
            # Start with current data
            enhanced_citation = citation
            
            # 1. Try Semantic Scholar (best for author IDs and citation counts)
            if not has_s2_data:
                try:
                    s2_paper = self.s2_client.search_paper(citation.citing_paper_title)
                    
                    if s2_paper and _titles_match(s2_paper.get('title', ''), citation.citing_paper_title):
                        s2_paper_id = s2_paper.get('paperId', '')
                        
                        if s2_paper_id:
                            detailed = self.s2_client.get_paper_by_id(s2_paper_id)
                            if detailed:
                                # Extract author IDs (crucial for disambiguation!)
                                authors_with_ids = []
                                for author in detailed.get('authors', []):
                                    name = author.get('name', 'Unknown')
                                    author_id = author.get('authorId', '')
                                    if name and name != 'Unknown':
                                        authors_with_ids.append(AuthorInfo(name=name, author_id=author_id or ''))
                                
                                # Get external IDs
                                external_ids = detailed.get('externalIds', {})
                                doi = external_ids.get('DOI', '') if external_ids else ''
                                
                                # Merge S2 data with existing
                                enhanced_citation = Citation(
                                    citing_paper_title=citation.citing_paper_title,
                                    citing_authors=citation.citing_authors,
                                    venue=detailed.get('venue', '') or citation.venue or 'Unknown',
                                    year=detailed.get('year', 0) or citation.year or 0,
                                    is_influential=citation.is_influential or detailed.get('influentialCitationCount', 0) > 5,
                                    contexts=citation.contexts,
                                    intents=citation.intents,
                                    paper_id=s2_paper_id,
                                    doi=doi or citation.doi,
                                    url=f"https://www.semanticscholar.org/paper/{s2_paper_id}" if s2_paper_id else citation.url,
                                    # IMPORTANT: Merge author info - keep GS IDs if available
                                    authors_with_ids=self._merge_author_ids(citation.authors_with_ids, authors_with_ids),
                                    citation_count=detailed.get('citationCount', 0) or citation.citation_count,
                                    influential_citation_count=detailed.get('influentialCitationCount', 0) or citation.influential_citation_count
                                )
                                s2_enhanced_count += 1
                except Exception:
                    pass
            
            # 2. Try Crossref for missing DOI/venue/year (fallback)
            if crossref_client and (not enhanced_citation.doi or not enhanced_citation.venue or enhanced_citation.venue == 'Unknown'):
                try:
                    cr_paper = crossref_client.search_paper(citation.citing_paper_title)
                    
                    if cr_paper and _titles_match(cr_paper.get('title', ''), citation.citing_paper_title):
                        # Fill in missing data
                        if not enhanced_citation.doi and cr_paper.get('doi'):
                            enhanced_citation = Citation(
                                citing_paper_title=enhanced_citation.citing_paper_title,
                                citing_authors=enhanced_citation.citing_authors,
                                venue=cr_paper.get('venue', '') or enhanced_citation.venue,
                                year=cr_paper.get('year', 0) or enhanced_citation.year,
                                is_influential=enhanced_citation.is_influential,
                                contexts=enhanced_citation.contexts,
                                intents=enhanced_citation.intents,
                                paper_id=enhanced_citation.paper_id,
                                doi=cr_paper.get('doi', ''),
                                url=enhanced_citation.url or f"https://doi.org/{cr_paper.get('doi', '')}",
                                authors_with_ids=enhanced_citation.authors_with_ids,
                                citation_count=cr_paper.get('citation_count', 0) or enhanced_citation.citation_count,
                                influential_citation_count=enhanced_citation.influential_citation_count
                            )
                            crossref_enhanced_count += 1
                except Exception:
                    pass
            
            enhanced.append(enhanced_citation)
        
        # Print summary
        if s2_enhanced_count > 0 or crossref_enhanced_count > 0:
            print(f"[Hybrid] ✓ Enhanced citations: {s2_enhanced_count} via S2, {crossref_enhanced_count} via Crossref")
        
        return enhanced
    
    def _merge_author_ids(self, gs_authors: List[AuthorInfo], s2_authors: List[AuthorInfo]) -> List[AuthorInfo]:
        """
        Merge author info from GS and S2, keeping BOTH IDs when available.
        
        GS gives us: gs:XXXX IDs (profile links from citation page)
        S2 gives us: S2 author IDs (for API lookup, author disambiguation)
        
        Strategy:
        1. Match by last name
        2. Keep GS ID (has profile link) + S2 ID (has API access)
        3. Use fuller name (e.g., "Chakkrit Tantithamthavorn" over "C. Tantithamthavorn")
        4. Check author cache for publication-based matching
        """
        if not gs_authors and not s2_authors:
            return []
        
        if not gs_authors:
            return s2_authors
        
        if not s2_authors:
            return gs_authors
        
        # Try to enhance with cache (publication-based matching)
        from citationimpact.cache import get_author_cache
        author_cache = get_author_cache()
        
        # Merge by matching names
        merged = []
        used_s2 = set()
        
        for gs_author in gs_authors:
            gs_last = _extract_last_name(gs_author.name).lower()
            matched_s2 = None
            
            for i, s2_author in enumerate(s2_authors):
                if i in used_s2:
                    continue
                s2_last = _extract_last_name(s2_author.name).lower()
                if gs_last == s2_last:
                    matched_s2 = s2_author
                    used_s2.add(i)
                    break
            
            if matched_s2:
                # Combine: prefer GS ID (has profile), but also keep S2 ID
                # Use fuller name (prefer longer, non-abbreviated)
                gs_name = gs_author.name
                s2_name = matched_s2.name
                # Check if GS name is abbreviated (e.g., "C. Tantithamthavorn")
                gs_is_abbreviated = len(gs_name.split()[0]) <= 2 if gs_name else True
                s2_is_abbreviated = len(s2_name.split()[0]) <= 2 if s2_name else True
                
                if gs_is_abbreviated and not s2_is_abbreviated:
                    best_name = s2_name  # Use S2's full name
                elif not gs_is_abbreviated and s2_is_abbreviated:
                    best_name = gs_name  # Use GS's full name
                else:
                    best_name = gs_name if len(gs_name) >= len(s2_name) else s2_name
                
                # Combine IDs: prefer GS ID (has profile link), fallback to S2 ID
                gs_id = gs_author.author_id if gs_author.author_id and gs_author.author_id.startswith('gs:') else ''
                s2_id = matched_s2.author_id if matched_s2.author_id and not matched_s2.author_id.startswith('gs:') else ''
                
                # Store combined ID: "gs:XXX|s2:YYY" if both available
                if gs_id and s2_id:
                    combined_id = f"{gs_id}|s2:{s2_id}"
                else:
                    combined_id = gs_id or (f"s2:{s2_id}" if s2_id else matched_s2.author_id) or gs_author.author_id
                
                merged.append(AuthorInfo(name=best_name, author_id=combined_id))
            else:
                # No S2 match - try to find cached profile by publication
                # (This helps match "C. Tantithamthavorn" to existing "Chakkrit Tantithamthavorn" cache entry)
                merged.append(gs_author)
        
        # Add any S2 authors not matched (these might be authors without GS profiles)
        for i, s2_author in enumerate(s2_authors):
            if i not in used_s2:
                # Check cache for this author by name
                cached = author_cache.get_by_any_id(name=s2_author.name)
                if cached and cached.get('google_scholar_id'):
                    # Found in cache with GS ID! Use that info
                    gs_id = f"gs:{cached['google_scholar_id']}"
                    s2_id = s2_author.author_id or cached.get('semantic_scholar_id', '')
                    combined_id = f"{gs_id}|s2:{s2_id}" if s2_id else gs_id
                    merged.append(AuthorInfo(
                        name=cached.get('name', s2_author.name),  # Use cached full name
                        author_id=combined_id
                    ))
                else:
                    merged.append(s2_author)
        
        return merged[:5]  # Limit to first 5
    
    def get_author(self, author_name: str) -> Optional[Author]:
        """
        Get author info from best available source
        
        Strategy:
        1. Check persistent cache - only use if has Google Scholar h-index
        2. Try S2/OpenAlex (has institution type)
        3. ALWAYS call GS for h-index (much more accurate than S2!)
        4. Merge best data from both sources
        5. Save to persistent cache with all profile IDs
        """
        # Check in-memory cache first
        name_cache_key = f"name:{_normalize_name(author_name)}"
        if name_cache_key in self._author_cache:
            return self._author_cache[name_cache_key]
        
        # Check persistent cache - only use if we have GS h-index (accurate)
        persistent_cache = get_author_cache()
        cached_info = persistent_cache.get_by_any_id(name=author_name)
        if cached_info and cached_info.get('h_index_source') == 'google_scholar':
            # We have accurate GS h-index, use cached data
            try:
                author = Author(
                    name=cached_info.get('name', author_name),
                    h_index=cached_info.get('h_index', 0),
                    affiliation=cached_info.get('affiliation', 'Unknown'),
                    institution_type=cached_info.get('institution_type', 'other'),
                    works_count=cached_info.get('works_count', 0),
                    citation_count=cached_info.get('citation_count', 0),
                    semantic_scholar_id=cached_info.get('semantic_scholar_id', ''),
                    google_scholar_id=cached_info.get('google_scholar_id', ''),
                    orcid_id=cached_info.get('orcid_id', ''),
                    homepage=cached_info.get('homepage', ''),
                    h_index_source=cached_info.get('h_index_source', '')
                )
                self._author_cache[name_cache_key] = author
                return author
            except (ValueError, TypeError):
                pass  # Invalid cache entry, fetch fresh
        
        # Try S2/OpenAlex first (has better institution data)
        s2_author = self.s2_client.get_author(author_name)
        
        best_author = s2_author
        
        # Try to get GS h-index ONLY if we have the author's GS ID
        # DO NOT search by name - it triggers CAPTCHA!
        # GS IDs come from the citation page (author links) or from cache
        gs_author = None
        if self.gs_available and self.gs_client:
            # Check if we have a cached GS ID for this author
            gs_id = cached_info.get('google_scholar_id') if cached_info else None
            if gs_id:
                try:
                    gs_author = self.gs_client.get_author_by_gs_id(gs_id)
                except Exception:
                    pass
            
            if gs_author:
                gs_h_index = gs_author.h_index or 0
                gs_affiliation = gs_author.affiliation or 'Unknown'
                s2_h_index = s2_author.h_index if s2_author else 0
                
                # ALWAYS prefer GS h-index (much more accurate!)
                final_h_index = gs_h_index if gs_h_index > 0 else s2_h_index
                h_index_source = 'google_scholar' if gs_h_index > 0 else 'semantic_scholar'
                
                if s2_author:
                    # Use S2 affiliation if available (more structured), else GS
                    final_affiliation = s2_author.affiliation
                    if final_affiliation == 'Unknown' and gs_affiliation != 'Unknown':
                        final_affiliation = gs_affiliation
                    
                    best_author = Author(
                        name=s2_author.name,
                        h_index=final_h_index,
                        affiliation=final_affiliation,
                        institution_type=gs_author.institution_type if gs_author.institution_type != 'other' else s2_author.institution_type,
                        works_count=max(s2_author.works_count, gs_author.works_count),
                        citation_count=max(s2_author.citation_count, gs_author.citation_count),
                        # Profile IDs for linking
                        semantic_scholar_id=getattr(s2_author, 'semantic_scholar_id', ''),
                        google_scholar_id=getattr(gs_author, 'google_scholar_id', ''),
                        homepage=getattr(gs_author, 'homepage', ''),
                        h_index_source=h_index_source
                    )
                else:
                    best_author = gs_author
        
        if best_author:
            # Cache in memory
            self._author_cache[name_cache_key] = best_author
            
            # Fetch publications for disambiguation (use S2 ID if available)
            publications = []
            s2_id = getattr(best_author, 'semantic_scholar_id', '')
            if s2_id:
                try:
                    publications = self.s2_client.get_author_publications(s2_id, limit=10)
                except Exception:
                    pass  # Publications are optional
            
            # Save to persistent cache WITH publications (enables author matching by papers!)
            author_dict = {
                'name': best_author.name,
                'h_index': best_author.h_index,
                'affiliation': best_author.affiliation,
                'institution_type': best_author.institution_type,
                'works_count': best_author.works_count,
                'citation_count': best_author.citation_count,
                'semantic_scholar_id': s2_id,
                'google_scholar_id': getattr(best_author, 'google_scholar_id', ''),
                'orcid_id': getattr(best_author, 'orcid_id', ''),
                'homepage': getattr(best_author, 'homepage', ''),
                'h_index_source': getattr(best_author, 'h_index_source', '')
            }
            persistent_cache.update_profile(author_dict, publications=publications)
        
        return best_author
    
    def get_author_by_s2_id(self, author_id: str, author_name: str = None) -> Optional[Author]:
        """
        Get author by Semantic Scholar ID with GS enhancement
        
        Strategy:
        1. Check persistent cache first (by S2 ID or name) - no API call if found
        2. Use S2 ID for accurate author identification
        3. Only call GS if affiliation is Unknown (optimization)
        4. PREFER Google Scholar h-index (more accurate)
        5. Save to persistent cache with all profile IDs
        """
        cache_key = f"s2:{author_id}"
        if cache_key in self._author_cache:
            return self._author_cache[cache_key]
        
        # Also check normalized name cache (avoid duplicate GS calls)
        name_cache_key = f"name:{_normalize_name(author_name)}" if author_name else None
        if name_cache_key and name_cache_key in self._author_cache:
            return self._author_cache[name_cache_key]
        
        # Check persistent cache by S2 ID or name
        persistent_cache = get_author_cache()
        cached_info = persistent_cache.get_by_any_id(
            semantic_scholar_id=author_id,
            name=author_name
        )
        
        # Only use cache if we already have Google Scholar h-index (more accurate)
        # If cached with S2 h-index only, we should try to update with GS
        if cached_info and cached_info.get('h_index_source') == 'google_scholar':
            # We have accurate GS h-index, use cached data
            try:
                author = Author(
                    name=cached_info.get('name', author_name or 'Unknown'),
                    h_index=cached_info.get('h_index', 0),
                    affiliation=cached_info.get('affiliation', 'Unknown'),
                    institution_type=cached_info.get('institution_type', 'other'),
                    works_count=cached_info.get('works_count', 0),
                    citation_count=cached_info.get('citation_count', 0),
                    semantic_scholar_id=cached_info.get('semantic_scholar_id', author_id),
                    google_scholar_id=cached_info.get('google_scholar_id', ''),
                    orcid_id=cached_info.get('orcid_id', ''),
                    homepage=cached_info.get('homepage', ''),
                    h_index_source=cached_info.get('h_index_source', '')
                )
                # Cache in memory
                self._author_cache[cache_key] = author
                if name_cache_key:
                    self._author_cache[name_cache_key] = author
                return author
            except (ValueError, TypeError):
                pass  # Invalid cache entry, fetch fresh
        
        # Get from S2 first (to get author's full name and publications for matching)
        s2_author = self.s2_client.get_author_by_s2_id(author_id, author_name)
        
        if not s2_author:
            return None
        
        # Get S2 author's publications (for GS profile matching via paper overlap)
        s2_publications = []
        try:
            s2_publications = self.s2_client.get_author_publications(author_id, limit=10)
        except Exception:
            pass
        
        # COMPREHENSIVE MODE: Prioritize Google Scholar!
        # Strategy:
        # 1. Check cache for GS ID (by name or by publication overlap)
        # 2. If found, fetch from GS profile directly
        # 3. Fall back to S2 data only if GS not available
        
        persistent_cache = get_author_cache()
        gs_author = None
        gs_id = None
        
        if self.gs_available and self.gs_client:
            # Try to find GS ID from cache (by name, S2 ID, or publication overlap!)
            cached_profile = persistent_cache.get_by_any_id(
                name=s2_author.name,
                semantic_scholar_id=author_id,
                publications=s2_publications  # Match by shared papers!
            )
            
            if cached_profile and cached_profile.get('google_scholar_id'):
                gs_id = cached_profile.get('google_scholar_id')
                print(f"[Hybrid] Found GS ID {gs_id[:8]}... for {s2_author.name} (from cache)")
            
            # Also try publication-based matching if no direct cache hit
            if not gs_id and s2_publications:
                pub_matched = persistent_cache.find_by_publications(s2_publications, min_overlap=2)
                if pub_matched and pub_matched.get('google_scholar_id'):
                    gs_id = pub_matched.get('google_scholar_id')
                    print(f"[Hybrid] Found GS ID {gs_id[:8]}... for {s2_author.name} (via publication match)")
            
            # If we have a GS ID, fetch fresh profile data from GS!
            if gs_id:
                try:
                    gs_author = self.gs_client.get_author_by_gs_id(gs_id)
                except Exception:
                    pass
        
        # If we got GS author data, USE IT (GS is more accurate!)
        if gs_author:
            gs_h_index = gs_author.h_index or 0
            s2_h_index = s2_author.h_index or 0
            
            # ALWAYS prefer GS h-index (much more accurate!)
            final_h_index = gs_h_index if gs_h_index > 0 else s2_h_index
            h_index_source = 'google_scholar' if gs_h_index > 0 else 'semantic_scholar'
            
            # Prefer GS affiliation too (more complete)
            final_affiliation = gs_author.affiliation if gs_author.affiliation and gs_author.affiliation != 'Unknown' else s2_author.affiliation
            
            # Create merged author with GS as primary
            best_author = Author(
                name=gs_author.name if gs_author.name else s2_author.name,  # GS name is often fuller
                h_index=final_h_index,
                affiliation=final_affiliation,
                institution_type=gs_author.institution_type if gs_author.institution_type != 'other' else s2_author.institution_type,
                works_count=max(s2_author.works_count, gs_author.works_count),
                citation_count=max(s2_author.citation_count, gs_author.citation_count),
                # Profile IDs for linking
                semantic_scholar_id=author_id,
                google_scholar_id=gs_id or getattr(gs_author, 'google_scholar_id', ''),
                homepage=getattr(gs_author, 'homepage', ''),
                h_index_source=h_index_source
            )
        else:
            # No GS data, use S2 (with proper object)
            best_author = Author(
                name=s2_author.name,
                h_index=s2_author.h_index,
                affiliation=s2_author.affiliation,
                institution_type=s2_author.institution_type,
                works_count=s2_author.works_count,
                citation_count=s2_author.citation_count,
                semantic_scholar_id=author_id,
                h_index_source='semantic_scholar'
            )
        
        # Cache in memory under ID, name, and resolved name
        resolved_name_key = f"name:{_normalize_name(best_author.name)}"
        self._author_cache[cache_key] = best_author
        self._author_cache[resolved_name_key] = best_author
        if name_cache_key:
            self._author_cache[name_cache_key] = best_author
        
        # Use S2 publications for cache (already fetched above)
        
        # Save to persistent cache WITH publications (enables author matching by papers!)
        author_dict = {
            'name': best_author.name,
            'h_index': best_author.h_index,
            'affiliation': best_author.affiliation,
            'institution_type': best_author.institution_type,
            'works_count': best_author.works_count,
            'citation_count': best_author.citation_count,
            'semantic_scholar_id': getattr(best_author, 'semantic_scholar_id', author_id),
            'google_scholar_id': getattr(best_author, 'google_scholar_id', gs_id or ''),
            'orcid_id': getattr(best_author, 'orcid_id', ''),
            'homepage': getattr(best_author, 'homepage', ''),
            'h_index_source': getattr(best_author, 'h_index_source', '')
        }
        persistent_cache.update_profile(author_dict, publications=s2_publications)
        
        return best_author
    
    def get_venue(self, venue_name: str) -> Optional[Venue]:
        """Get venue info (delegates to S2/OpenAlex)"""
        if venue_name in self._venue_cache:
            return self._venue_cache[venue_name]
        
        venue = self.s2_client.get_venue(venue_name)
        
        if venue:
            self._venue_cache[venue_name] = venue
        
        return venue
    
    def categorize_institution(self, institution_type: str, affiliation: str = None) -> str:
        """Categorize institution (delegates to S2 client)"""
        return self.s2_client.categorize_institution(institution_type, affiliation)
    
    def get_author_by_id(self, author_id: str) -> Optional[Dict]:
        """Get raw author data by S2 ID"""
        return self.s2_client.get_author_by_id(author_id)
    
    def batch_fetch_gs_authors(self, gs_ids: List[str]) -> Dict[str, Author]:
        """
        Batch fetch multiple Google Scholar author profiles efficiently.
        
        This is MUCH faster than individual calls because:
        - Browser stays open
        - Only uncached profiles are fetched
        - Saves to persistent cache for future use
        
        Args:
            gs_ids: List of Google Scholar author IDs
            
        Returns:
            Dict mapping gs_id -> Author
        """
        if not gs_ids:
            return {}
        
        results = {}
        uncached_ids = []
        persistent_cache = get_author_cache()
        
        # First, check what's already cached
        for gs_id in gs_ids:
            cache_key = f"gs:{gs_id}"
            
            # Check in-memory cache
            if cache_key in self._author_cache:
                results[gs_id] = self._author_cache[cache_key]
                continue
            
            # Check persistent cache
            cached_info = persistent_cache.get_by_any_id(google_scholar_id=gs_id)
            if cached_info and cached_info.get('h_index_source') == 'google_scholar':
                try:
                    author = Author(
                        name=cached_info.get('name', 'Unknown'),
                        h_index=cached_info.get('h_index', 0),
                        affiliation=cached_info.get('affiliation', 'Unknown'),
                        institution_type=cached_info.get('institution_type', 'other'),
                        works_count=cached_info.get('works_count', 0),
                        citation_count=cached_info.get('citation_count', 0),
                        google_scholar_id=gs_id,
                        semantic_scholar_id=cached_info.get('semantic_scholar_id', ''),
                        homepage=cached_info.get('homepage', ''),
                        h_index_source='google_scholar'
                    )
                    results[gs_id] = author
                    self._author_cache[cache_key] = author
                    continue
                except (ValueError, TypeError):
                    pass
            
            # Not cached, need to fetch
            uncached_ids.append(gs_id)
        
        cached_count = len(results)
        if cached_count > 0:
            print(f"[Hybrid] ✓ {cached_count} authors loaded from cache")
        
        # Batch fetch uncached profiles
        if uncached_ids and self.gs_available and self.gs_client:
            print(f"[Hybrid] Fetching {len(uncached_ids)} uncached author profiles from GS...")
            
            fetched = self.gs_client.get_authors_by_gs_ids_batch(uncached_ids)
            
            # Save fetched authors to cache
            for gs_id, author in fetched.items():
                results[gs_id] = author
                cache_key = f"gs:{gs_id}"
                self._author_cache[cache_key] = author
                
                # Save to persistent cache
                author_dict = {
                    'name': author.name,
                    'h_index': author.h_index,
                    'affiliation': author.affiliation,
                    'institution_type': author.institution_type,
                    'works_count': author.works_count,
                    'citation_count': author.citation_count,
                    'google_scholar_id': gs_id,
                    'homepage': getattr(author, 'homepage', ''),
                    'h_index_source': 'google_scholar'
                }
                persistent_cache.update_profile(author_dict)
        
        return results

    def get_author_by_gs_id(self, gs_id: str, author_name: str = None) -> Optional[Author]:
        """
        Get author info directly from their Google Scholar profile.
        
        This is the SMART approach - instead of searching by name (triggers CAPTCHA),
        we go directly to the author's profile page using the GS ID extracted from
        the citation page.
        
        Args:
            gs_id: Google Scholar author ID (e.g., 'waVL0PgAAAAJ')
            author_name: Optional author name for caching
            
        Returns:
            Author object with h-index, affiliation, etc.
        """
        cache_key = f"gs:{gs_id}"
        if cache_key in self._author_cache:
            return self._author_cache[cache_key]
        
        # Check persistent cache
        persistent_cache = get_author_cache()
        cached_info = persistent_cache.get_by_any_id(google_scholar_id=gs_id)
        
        if cached_info and cached_info.get('h_index_source') == 'google_scholar':
            try:
                author = Author(
                    name=cached_info.get('name', author_name or 'Unknown'),
                    h_index=cached_info.get('h_index', 0),
                    affiliation=cached_info.get('affiliation', 'Unknown'),
                    institution_type=cached_info.get('institution_type', 'other'),
                    works_count=cached_info.get('works_count', 0),
                    citation_count=cached_info.get('citation_count', 0),
                    google_scholar_id=gs_id,
                    semantic_scholar_id=cached_info.get('semantic_scholar_id', ''),
                    homepage=cached_info.get('homepage', ''),
                    h_index_source='google_scholar'
                )
                self._author_cache[cache_key] = author
                return author
            except (ValueError, TypeError):
                pass
        
        # Directly access GS profile page - no search needed!
        if self.gs_available and self.gs_client:
            try:
                gs_author = self.gs_client.get_author_by_gs_id(gs_id)
                if gs_author:
                    # Cache and save
                    self._author_cache[cache_key] = gs_author
                    if author_name:
                        name_key = f"name:{_normalize_name(author_name)}"
                        self._author_cache[name_key] = gs_author
                    
                    # Save to persistent cache
                    author_dict = {
                        'name': gs_author.name,
                        'h_index': gs_author.h_index,
                        'affiliation': gs_author.affiliation,
                        'institution_type': gs_author.institution_type,
                        'works_count': gs_author.works_count,
                        'citation_count': gs_author.citation_count,
                        'google_scholar_id': gs_id,
                        'homepage': getattr(gs_author, 'homepage', ''),
                        'h_index_source': 'google_scholar'
                    }
                    persistent_cache.update_profile(author_dict)
                    
                    return gs_author
            except Exception as e:
                print(f"[Hybrid] Error fetching GS profile: {e}")
        
        return None
    
    def get_author_by_paper(self, author_name: str, paper_title: str) -> Optional[Author]:
        """
        Find author info using a paper they wrote.
        
        This is the KEY method for comprehensive mode when author has no GS profile!
        
        Strategy (all APIs, no CAPTCHA):
        1. Check cache by name
        2. Check cache by publication (finds "C. Tantithamthavorn" via shared papers!)
        3. Search for the paper on S2 → find author → get S2 author ID
        4. If S2 fails, try ORCID for affiliation
        5. Return best available data
        """
        if not author_name or not paper_title:
            return None
        
        # First check cache by name
        cached = self.get_author(author_name)
        if cached and cached.h_index > 0:
            return cached
        
        # Check cache using publication matching (KEY for disambiguation!)
        # This finds "C. Tantithamthavorn" when we have "Chakkrit Tantithamthavorn" cached
        from citationimpact.cache import get_author_cache
        author_cache = get_author_cache()
        cached_by_pub = author_cache.find_by_publications(
            [{'title': paper_title}], 
            min_overlap=1  # Just one matching paper is enough
        )
        if cached_by_pub and cached_by_pub.get('h_index', 0) > 0:
            # Found via publication matching!
            try:
                return Author(
                    name=cached_by_pub.get('name', author_name),
                    h_index=cached_by_pub.get('h_index', 0),
                    affiliation=cached_by_pub.get('affiliation', 'Unknown'),
                    institution_type=cached_by_pub.get('institution_type', 'other'),
                    works_count=cached_by_pub.get('works_count', 0),
                    citation_count=cached_by_pub.get('citation_count', 0),
                    semantic_scholar_id=cached_by_pub.get('semantic_scholar_id', ''),
                    google_scholar_id=cached_by_pub.get('google_scholar_id', ''),
                    orcid_id=cached_by_pub.get('orcid_id', ''),
                    h_index_source=cached_by_pub.get('h_index_source', '')
                )
            except (ValueError, TypeError):
                pass
        
        author_last_name = _extract_last_name(author_name).lower()
        
        # Strategy 1: Try Semantic Scholar (best for author disambiguation)
        try:
            paper = self.s2_client.search_paper(paper_title)
            if paper:
                paper_id = paper.get('paperId')
                if paper_id:
                    detailed = self.s2_client.get_paper_by_id(paper_id)
                    if detailed:
                        authors = detailed.get('authors', [])
                        
                        # Find matching author by last name
                        for author in authors:
                            s2_name = author.get('name', '')
                            s2_id = author.get('authorId', '')
                            
                            if not s2_name or not s2_id:
                                continue
                            
                            s2_last_name = _extract_last_name(s2_name).lower()
                            if s2_last_name == author_last_name:
                                result = self.get_author_by_s2_id(s2_id, s2_name)
                                if result:
                                    return result
                        
                        # Try fuzzy match
                        for author in authors:
                            s2_name = author.get('name', '')
                            s2_id = author.get('authorId', '')
                            if s2_name and s2_id:
                                if SequenceMatcher(None, author_name.lower(), s2_name.lower()).ratio() > 0.7:
                                    result = self.get_author_by_s2_id(s2_id, s2_name)
                                    if result:
                                        return result
        except Exception:
            pass
        
        # Strategy 2: Try ORCID (free API, has affiliation data)
        try:
            from .orcid import OrcidClient
            orcid_client = OrcidClient()
            orcid_author = orcid_client.search_author(author_name)
            
            if orcid_author:
                # Found on ORCID!
                return Author(
                    name=orcid_author.get('name', author_name),
                    h_index=0,  # ORCID doesn't have h-index
                    affiliation=orcid_author.get('affiliation', 'Unknown'),
                    institution_type=orcid_author.get('institution_type', 'other'),
                    works_count=orcid_author.get('works_count', 0),
                    citation_count=0,
                    orcid_id=orcid_author.get('orcid_id', ''),
                    h_index_source='orcid'
                )
        except Exception:
            pass
        
        # Strategy 3: Return basic info from S2 even without h-index
        try:
            s2_author = self.s2_client.get_author(author_name)
            if s2_author:
                return s2_author
        except Exception:
            pass
        
        return None
    
    def _get_author_by_paper_s2(self, author_name: str, paper_title: str) -> Optional[Author]:
        """
        Helper: Find author via S2 paper search.
        This is called from _enhance_citations_with_s2 for authors without profiles.
        """
        author_last_name = _extract_last_name(author_name).lower()
        
        try:
            paper = self.s2_client.search_paper(paper_title)
            if not paper:
                return None
            
            paper_id = paper.get('paperId')
            if not paper_id:
                return None
            
            detailed = self.s2_client.get_paper_by_id(paper_id)
            if not detailed:
                return None
            
            authors = detailed.get('authors', [])
            
            for author in authors:
                s2_name = author.get('name', '')
                s2_id = author.get('authorId', '')
                
                if not s2_name or not s2_id:
                    continue
                
                # Check if names are similar
                if SequenceMatcher(None, author_name.lower(), s2_name.lower()).ratio() > 0.7:
                    return self.get_author_by_s2_id(s2_id, s2_name)
                    
        except Exception as e:
            print(f"[Hybrid] Error finding author by paper: {e}")
        
        return None
    
    def close(self):
        """Close all clients and clean up resources (especially browser)"""
        if self.gs_client:
            try:
                self.gs_client.close()
                print("[Hybrid] Browser closed successfully")
            except Exception:
                pass
    
    def __del__(self):
        """Cleanup when object is deleted"""
        self.close()
    
    def __enter__(self):
        """Support context manager pattern"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close on context exit"""
        self.close()
        return False
    
    def get_author_publications(self, author_id: str, limit: int = 100) -> List[Dict]:
        """
        Get author publications from best source
        
        For comprehensive mode, try both and merge
        """
        publications = []
        seen_titles = set()
        
        # Try Semantic Scholar first
        s2_pubs = self.s2_client.get_author_publications(author_id, limit=limit)
        
        if s2_pubs:
            for pub in s2_pubs:
                title_norm = _normalize_title(pub.get('title', ''))
                if title_norm and title_norm not in seen_titles:
                    publications.append(pub)
                    seen_titles.add(title_norm)
        
        return publications
    
    def get_sources_summary(self) -> str:
        """Get a summary of which sources were used in the last analysis"""
        parts = []
        for operation, sources in self.last_sources_used.items():
            if sources:
                if isinstance(sources, list):
                    parts.append(f"{operation}: {', '.join(sources)}")
                else:
                    parts.append(f"{operation}: {sources}")
        return " | ".join(parts) if parts else "No sources tracked"


def get_hybrid_client(
    semantic_scholar_key: Optional[str] = None,
    email: Optional[str] = None,
    use_gs_proxy: bool = False,
    scraper_api_key: Optional[str] = None,
    timeout: int = 15,
    max_retries: int = 3,
    gs_cites_id: Optional[List[str]] = None
) -> HybridAPIClient:
    """
    Get a configured hybrid client
    
    Args:
        semantic_scholar_key: Optional S2 API key
        email: Email for OpenAlex polite pool
        use_gs_proxy: Use free proxy for Google Scholar (unreliable)
        scraper_api_key: ScraperAPI key for Google Scholar (most reliable)
                        Get key at: https://www.scraperapi.com/
        timeout: Request timeout
        max_retries: Max retries
        gs_cites_id: Direct GS citation IDs for DIRECT access (no search!)
        
    Returns:
        Configured HybridAPIClient
        
    Example:
        # Option 1: Visible browser for GS (free, may need CAPTCHA solving)
        client = get_hybrid_client(semantic_scholar_key="your_s2_key")
        
        # Option 2: ScraperAPI for GS (paid, most reliable)
        client = get_hybrid_client(
            semantic_scholar_key="your_s2_key",
            scraper_api_key="your_scraper_key"
        )
    """
    return HybridAPIClient(
        semantic_scholar_api_key=semantic_scholar_key,
        email=email,
        use_gs_proxy=use_gs_proxy,
        scraper_api_key=scraper_api_key,
        timeout=timeout,
        max_retries=max_retries,
        gs_cites_id=gs_cites_id
    )

