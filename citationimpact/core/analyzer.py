"""
Clean, Simple Citation Impact Analyzer - FIXED VERSION

Improvements:
- ✅ Fixed error handling to return complete structure
- ✅ Added empty author list check
- ✅ Fixed inconsistent result keys (len() for counts)
- ✅ Added progress bar for venue analysis
- ✅ Better error messages
"""

from typing import Dict, List
from collections import Counter, defaultdict

from ..models import Author, Venue, Citation
from ..clients import UnifiedAPIClient
from ..utils.rankings import get_core_rank, get_university_rankings, get_venue_rankings


class CitationImpactAnalyzer:
    """
    Analyze citation impact using real API data

    Simple 3-step process:
    1. Find paper → get citations
    2. Analyze authors → get h-indices
    3. Analyze venues → get rankings

    No hardcoded lists! Works for any field!
    """

    def __init__(self, api_client: UnifiedAPIClient, data_source: str = 'api'):
        self.api = api_client
        self.data_source = data_source  # Track which data source we're using

    def analyze_paper(
        self,
        paper_title: str,
        h_index_threshold: int = 20,
        max_citations: int = 100
    ) -> Dict:
        """
        Analyze a paper's citation impact

        Args:
            paper_title: Title of your paper
            h_index_threshold: Minimum h-index for "high-profile" (default: 20)
            max_citations: How many citations to analyze (default: 100)

        Returns:
            Complete analysis dictionary with all fields populated
        """
        # Input validation
        if not paper_title or not isinstance(paper_title, str) or not paper_title.strip():
            raise ValueError("paper_title must be a non-empty string")

        if not isinstance(h_index_threshold, int) or h_index_threshold < 0:
            raise ValueError("h_index_threshold must be a non-negative integer")

        if not isinstance(max_citations, int) or max_citations <= 0:
            raise ValueError("max_citations must be a positive integer")

        if max_citations > 1000:
            print(f"[WARNING] max_citations={max_citations} is very large and may take a long time")

        print(f"\n{'='*80}")
        print(f"Analyzing: {paper_title}")
        print(f"{'='*80}\n")

        # Step 1: Find paper and get citations
        # For Google Scholar, check if paper is already cached from author browsing
        paper = None
        if self.data_source == 'google_scholar' and hasattr(self.api, '_paper_cache'):
            # Check cache first (paper might be from author browsing)
            cache_size = len(self.api._paper_cache)
            print(f"[INFO] Checking cache ({cache_size} papers) for: '{paper_title}'")
            
            for cached_id, (cached_title, cached_data) in self.api._paper_cache.items():
                # Try exact match first
                if cached_title == paper_title:
                    print(f"[INFO] ✓ Found exact match in cache")
                    paper = cached_data
                    break
                # Try case-insensitive match
                elif cached_title.lower() == paper_title.lower():
                    print(f"[INFO] ✓ Found case-insensitive match in cache")
                    print(f"[INFO]   Cached: '{cached_title}'")
                    print(f"[INFO]   Requested: '{paper_title}'")
                    paper = cached_data
                    break
            
            if not paper:
                print(f"[INFO] Paper not found in cache, will search Google Scholar")
        
        # If not in cache, search for it
        if not paper:
            paper = self.api.search_paper(paper_title)
            
        if not paper:
            # Make error message reflect actual data source
            if self.data_source == 'google_scholar':
                source_name = 'Google Scholar'
                error_message = 'Paper not found on Google Scholar'
            else:
                source_name = 'Semantic Scholar'
                error_details = getattr(self.api, 'last_error', None)
                error_message = error_details or 'Paper not found on Semantic Scholar'
            return self._empty_result(paper_title, error_message)

        print(f"✅ Found: {paper['title']}")
        print(f"   Citations: {paper.get('citationCount', 0)}")
        print(f"   Influential: {paper.get('influentialCitationCount', 0)}")

        citations = self.api.get_citations(paper['paperId'], limit=max_citations)
        print(f"✅ Retrieved {len(citations)} citations\n")

        # FIX: Return complete structure with zeros instead of error dict
        if not citations:
            return self._empty_result(
                paper['title'],
                f"No citations found. Paper may be too new or not indexed.",
                paper.get('citationCount', 0),
                paper.get('influentialCitationCount', 0)
            )

        # Step 2: Analyze citing authors
        print("Analyzing authors...")
        authors_data = self._analyze_authors(citations, h_index_threshold)

        # Step 3: Analyze venues
        print("Analyzing venues...")
        venue_data = self._analyze_venues(citations)

        # Step 4: Analyze citation influence
        print("Analyzing citation contexts...")
        influence_data = self._analyze_influence(citations)

        # Compile results
        result = {
            'paper_title': paper['title'],
            'total_citations': paper.get('citationCount', 0),
            'influential_citations_count': paper.get('influentialCitationCount', 0),
            'analyzed_citations': len(citations),
            'error': None,
            **authors_data,
            **venue_data,
            **influence_data
        }

        self._print_summary(result, h_index_threshold)
        return result

    def _empty_result(self, title: str, error_msg: str, total_cites: int = 0, influential_cites: int = 0) -> Dict:
        """
        Return complete structure with zeros when no data available

        FIX: Previously returned {'error': 'message'} which crashed later code
        """
        return {
            'paper_title': title,
            'total_citations': total_cites,
            'influential_citations_count': influential_cites,
            'analyzed_citations': 0,
            'error': error_msg,
            'all_authors': [],
            'high_profile_scholars': [],
            'institutions': {
                'University': 0,
                'Industry': 0,
                'Government': 0,
                'Other': 0,
                'details': {}
            },
            'venues': {
                'total': 0,
                'unique': 0,
                'top_tier_count': 0,
                'top_tier_percentage': 0.0,
                'most_common': [],
                'rankings': {}
            },
            'influential_citations': [],
            'methodological_citations': []
        }

    def _analyze_authors(self, citations: List[Citation], h_index_threshold: int) -> Dict:
        """Analyze citing authors"""
        all_authors = []
        high_profile = []
        institutions = defaultdict(list)

        # Simpler progress message
        print(f"Processing {len(citations)} citations for author information...")
        
        for citation in citations:
            # FIX: Check if author list is not empty before processing
            if not citation.citing_authors:
                continue

            for author_name in citation.citing_authors[:3]:  # First 3 authors
                # Skip if author name is Unknown or empty
                if not author_name or author_name == 'Unknown':
                    continue

                author = self.api.get_author(author_name)
                if not author:
                    continue

                # Get university ranking if available
                university_rank = None
                university_tier = None
                usnews_rank = None
                usnews_tier = None
                university_rankings = {}
                primary_university_source = None

                if author.affiliation and author.affiliation != 'Unknown':
                    rank_data = get_university_rankings(author.affiliation)
                    if rank_data:
                        university_rankings = rank_data
                        primary_university_source = rank_data.get('primary_source')

                        qs_info = rank_data.get('qs')
                        if qs_info:
                            university_rank = qs_info.get('rank')
                            university_tier = qs_info.get('tier')

                        us_info = rank_data.get('usnews')
                        if us_info:
                            usnews_rank = us_info.get('rank')
                            usnews_tier = us_info.get('tier')

                        if university_rank is None and primary_university_source:
                            primary_data = rank_data.get('sources', {}).get(primary_university_source)
                            if primary_data:
                                university_rank = primary_data.get('rank')
                                university_tier = primary_data.get('tier')

                author_dict = {
                    'name': author.name,
                    'h_index': author.h_index,
                    'affiliation': author.affiliation,
                    'university_rank': university_rank,  # Add QS ranking
                    'university_tier': university_tier,  # Add QS tier
                    'usnews_rank': usnews_rank,
                    'usnews_tier': usnews_tier,
                    'university_rankings': university_rankings,
                    'primary_university_source': primary_university_source,
                    'citing_paper': citation.citing_paper_title,
                    'paper_url': getattr(citation, 'url', ''),  # Add URL for clickable links
                    'paper_id': getattr(citation, 'paper_id', '')  # Add paper ID for link construction
                }
                all_authors.append(author_dict)

                # High-profile?
                if author.h_index >= h_index_threshold:
                    high_profile.append(author_dict)

                # Categorize institution (use both type and affiliation name for better accuracy)
                category = self.api.categorize_institution(author.institution_type, author.affiliation)
                institutions[category].append(author_dict)

        # Sort by h-index
        high_profile.sort(key=lambda x: x['h_index'], reverse=True)

        return {
            'all_authors': all_authors,
            'high_profile_scholars': high_profile,
            'institutions': {
                'University': len(institutions.get('University', [])),
                'Industry': len(institutions.get('Industry', [])),
                'Government': len(institutions.get('Government', [])),
                'Other': len(institutions.get('Other', [])),
                'details': dict(institutions)
            }
        }

    def _analyze_venues(self, citations: List[Citation]) -> Dict:
        """Analyze publication venues"""
        venue_names = [c.venue for c in citations if c.venue and c.venue != 'Unknown']
        venue_counter = Counter(venue_names)

        # Get h-index for each unique venue with progress bar
        venue_rankings = {}
        top_tier_count = 0
        citations_by_venue = defaultdict(list)

        for citation in citations:
            if citation.venue and citation.venue != 'Unknown':
                citations_by_venue[citation.venue].append(citation)

        unique_venues = set(venue_names)
        print(f"Processing {len(unique_venues)} unique venues...")
        
        for venue_name in unique_venues:
            venue = self.api.get_venue(venue_name)

            rank_sources = get_venue_rankings(venue_name)
            core_rank = rank_sources.get('core')
            ccf_rank = rank_sources.get('ccf')
            icore_rank = rank_sources.get('icore')
            citation_records = []
            for citing in citations_by_venue.get(venue_name, []):
                citation_records.append({
                    'title': citing.citing_paper_title,
                    'year': getattr(citing, 'year', None),
                    'authors': getattr(citing, 'citing_authors', []),
                    'url': getattr(citing, 'url', ''),
                    'paper_id': getattr(citing, 'paper_id', ''),
                    'doi': getattr(citing, 'doi', ''),
                })

            rank_tier = venue.rank_tier if venue else 'Unknown'
            venue_rankings[venue_name] = {
                'h_index': venue.h_index if venue else 'N/A',
                'rank_tier': rank_tier,
                'type': venue.type if venue else 'Unknown',
                'core_rank': core_rank,
                'ccf_rank': ccf_rank,
                'icore_rank': icore_rank,
                'rank_sources': rank_sources,
                'citations': citation_records,
            }
            if venue and ('Tier 1' in rank_tier or 'Tier 2' in rank_tier):
                top_tier_count += venue_counter[venue_name]

        total = len(venue_names)
        top_tier_pct = (top_tier_count / total * 100) if total > 0 else 0

        return {
            'venues': {
                'total': total,
                'unique': len(venue_counter),
                'top_tier_count': top_tier_count,
                'top_tier_percentage': top_tier_pct,
                'most_common': venue_counter.most_common(10),
                'rankings': venue_rankings
            }
        }

    def _analyze_influence(self, citations: List[Citation]) -> Dict:
        """Analyze citation influence"""
        influential = []
        methodological = []

        for citation in citations:
            # FIX: Check if authors list is not empty
            authors_to_show = citation.citing_authors[:3] if citation.citing_authors else ['Unknown']

            if citation.is_influential:
                # Return the full Citation object, not just a dict
                influential.append(citation)

            if 'Methodology' in citation.intents or 'Uses' in citation.intents:
                # Return the full Citation object, not just a dict
                methodological.append(citation)

        return {
            'influential_citations': influential,
            'methodological_citations': methodological
        }

    def _print_summary(self, result: Dict, h_threshold: int):
        """Print analysis summary"""
        print(f"\n{'='*80}")
        print("ANALYSIS COMPLETE")
        print(f"{'='*80}\n")

        # Show error if present
        if result.get('error'):
            print(f"⚠️  {result['error']}\n")

        print(f"📄 Paper: {result['paper_title']}")
        print(f"📊 Total Citations: {result['total_citations']}")
        # FIX: Use len() for list counts
        print(f"⭐ Influential: {result['influential_citations_count']}")
        print(f"🔍 Analyzed: {result['analyzed_citations']}")

        print(f"\n👥 HIGH-PROFILE SCHOLARS (h-index >= {h_threshold}): {len(result['high_profile_scholars'])}")
        for i, scholar in enumerate(result['high_profile_scholars'][:5], 1):
            affiliation_str = scholar['affiliation']
            rank_parts = []
            if scholar.get('university_rank'):
                part = f"QS #{scholar['university_rank']}"
                if scholar.get('university_tier'):
                    part += f" ({scholar['university_tier']})"
                rank_parts.append(part)
            if scholar.get('usnews_rank'):
                part = f"US News #{scholar['usnews_rank']}"
                if scholar.get('usnews_tier'):
                    part += f" ({scholar['usnews_tier']})"
                rank_parts.append(part)
            if rank_parts:
                affiliation_str += " [" + " | ".join(rank_parts) + "]"
            print(f"  {i}. {scholar['name']} (h={scholar['h_index']}) - {affiliation_str}")

        inst = result['institutions']
        print(f"\n🏛️  INSTITUTIONS:")
        print(f"  University: {inst['University']}")
        print(f"  Industry: {inst['Industry']}")
        print(f"  Government: {inst['Government']}")

        venues = result['venues']
        print(f"\n📚 VENUES:")
        print(f"  Total: {venues['total']}")
        print(f"  Top-Tier: {venues['top_tier_count']} ({venues['top_tier_percentage']:.1f}%)")

        if venues['most_common']:
            print(f"\n  Most Common:")
            for venue, count in venues['most_common'][:5]:
                rank_info = venues['rankings'].get(venue, {})
                h = rank_info.get('h_index', '?')
                tier = rank_info.get('rank_tier', '?')
                core_rank = rank_info.get('core_rank')
                ccf_rank = rank_info.get('ccf_rank')
                icore_rank = rank_info.get('icore_rank')

                # Build venue info string
                detail_parts = [f"h={h}", tier]
                if core_rank:
                    detail_parts.append(f"CORE: {core_rank}")
                if ccf_rank:
                    detail_parts.append(f"CCF: {ccf_rank}")
                if icore_rank:
                    detail_parts.append(f"iCORE: {icore_rank}")
                venue_info = ", ".join(part for part in detail_parts if part)

                print(f"    - {venue}: {count} ({venue_info})")

        # FIX: Use len() for list counts
        print(f"\n🎯 INFLUENTIAL CITATIONS: {len(result['influential_citations'])}")
        print(f"🔬 METHODOLOGICAL CITATIONS: {len(result['methodological_citations'])}")

        # University rankings statistics
        qs_authors = []
        usnews_authors = []
        for author in result['all_authors']:
            rankings_info = author.get('university_rankings') or {}
            qs_info = rankings_info.get('qs')
            if qs_info and qs_info.get('rank'):
                qs_authors.append(qs_info)
            us_info = rankings_info.get('usnews')
            if us_info and us_info.get('rank'):
                usnews_authors.append(us_info)

        if qs_authors:
            top10_count = sum(1 for info in qs_authors if info.get('rank') and info['rank'] <= 10)
            top25_count = sum(1 for info in qs_authors if info.get('rank') and info['rank'] <= 25)
            top50_count = sum(1 for info in qs_authors if info.get('rank') and info['rank'] <= 50)
            print(f"\n🎓 UNIVERSITY RANKINGS (QS):")
            print(f"  Top 10: {top10_count} authors")
            print(f"  Top 25: {top25_count} authors")
            print(f"  Top 50: {top50_count} authors")

        if usnews_authors:
            top10_us = sum(1 for info in usnews_authors if info.get('rank') and info['rank'] <= 10)
            top25_us = sum(1 for info in usnews_authors if info.get('rank') and info['rank'] <= 25)
            top50_us = sum(1 for info in usnews_authors if info.get('rank') and info['rank'] <= 50)
            print(f"\n🎓 UNIVERSITY RANKINGS (US News):")
            print(f"  Top 10: {top10_us} authors")
            print(f"  Top 25: {top25_us} authors")
            print(f"  Top 50: {top50_us} authors")

        print(f"\n{'='*80}\n")


# ============================================================================
# SIMPLE PUBLIC API
# ============================================================================

def analyze_paper_impact(
    paper_title: str,
    h_index_threshold: int = 20,
    max_citations: int = 100,
    data_source: str = 'api',
    semantic_scholar_key: str = None,
    email: str = None,
    timeout: int = 15,
    max_retries: int = 3,
    use_proxy: bool = False,
    use_cache: bool = True
) -> Dict:
    """
    Analyze citation impact for a paper

    Simple one-function interface with automatic caching!

    Args:
        paper_title: Your paper title
        h_index_threshold: Minimum h-index for "high-profile" (default: 20)
        max_citations: Number of citations to analyze (default: 100)
        data_source: Data source to use (default: 'api')
            - 'api': Use Semantic Scholar + OpenAlex APIs (RECOMMENDED - fast, reliable)
            - 'google_scholar': Use Google Scholar scraping (slow, may encounter CAPTCHAs)
        semantic_scholar_key: Optional S2 API key (free from semanticscholar.org)
        email: Optional email for OpenAlex polite pool
        timeout: Request timeout in seconds (default: 15)
        max_retries: Max retry attempts for failed requests (default: 3)
        use_proxy: Use proxy for Google Scholar (only applies if data_source='google_scholar')
        use_cache: Use cached results if available (default: True)

    Returns:
        Complete analysis with:
        - High-profile scholars (with real h-indices!)
        - Institution breakdown (University/Industry/Government)
        - Venue rankings (based on h-index, works for ANY field!)
        - Influential citations (AI-detected, only with 'api' source)

    Example (Recommended - API-based):
        >>> result = analyze_paper_impact(
        ...     "Large language models for software engineering",
        ...     h_index_threshold=20,
        ...     max_citations=50,
        ...     data_source='api'
        ... )
        >>> print(f"High-profile scholars: {len(result['high_profile_scholars'])}")

    Example (Google Scholar - for papers not in Semantic Scholar):
        >>> result = analyze_paper_impact(
        ...     "Your Paper Title",
        ...     h_index_threshold=20,
        ...     max_citations=50,
        ...     data_source='google_scholar',
        ...     use_proxy=False
        ... )
    """
    # Input validation
    if not isinstance(timeout, int) or timeout <= 0:
        raise ValueError("timeout must be a positive integer")

    if not isinstance(max_retries, int) or max_retries < 1:
        raise ValueError("max_retries must be at least 1")

    if data_source not in ['api', 'google_scholar']:
        raise ValueError(f"Invalid data_source: {data_source}. Must be 'api' or 'google_scholar'")

    # Check cache first
    if use_cache:
        from ..cache import get_result_cache
        cache = get_result_cache()

        params = {
            'h_index_threshold': h_index_threshold,
            'max_citations': max_citations,
            'data_source': data_source
        }

        cached_result = cache.get(paper_title, params)
        if cached_result:
            return cached_result

    # No cache hit, perform analysis
    if data_source == 'api':
        from ..clients import get_api_client
        api = get_api_client(semantic_scholar_key, email, timeout, max_retries)
    elif data_source == 'google_scholar':
        from ..clients import get_google_scholar_client
        api = get_google_scholar_client(use_proxy=use_proxy)
        print("\n⚠️  Using Google Scholar (web scraping)")
        print("   - This is SLOWER than API-based approach")
        print("   - May encounter CAPTCHAs")
        print("   - No influential citations or citation contexts")
        print("   - Use 'api' data source when possible\n")
    else:
        raise ValueError(f"Invalid data_source: {data_source}. Must be 'api' or 'google_scholar'")

    # Pass data_source to analyzer so it can provide accurate error messages
    analyzer = CitationImpactAnalyzer(api, data_source=data_source)
    result = analyzer.analyze_paper(paper_title, h_index_threshold, max_citations)

    # Save to cache
    if use_cache and not result.get('error'):
        cache.set(paper_title, params, result)

    return result
