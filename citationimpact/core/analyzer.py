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

        # Step 5: Analyze years
        year_data = self._analyze_years(citations)

        # Step 6: Calculate grant-friendly impact statistics
        impact_stats = self._analyze_impact_stats(citations, authors_data)

        # Compile results
        result = {
            'paper_title': paper['title'],
            'total_citations': paper.get('citationCount', 0),
            'influential_citations_count': paper.get('influentialCitationCount', 0),
            'analyzed_citations': len(citations),
            'error': None,
            **authors_data,
            **venue_data,
            **influence_data,
            **year_data,
            'impact_stats': impact_stats  # Grant-friendly summary statistics
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
            'methodological_citations': [],
            'yearly_stats': [],
            'impact_stats': {
                'highly_cited_citing_papers': [],
                'citation_thresholds': {'over_1000': 0, 'over_500': 0, 'over_100': 0, 'over_50': 0},
                'author_stats': {'total_unique_authors': 0, 'high_profile_count': 0, 'max_h_index': 0, 'avg_h_index': 0, 'h_over_50': 0, 'h_over_30': 0, 'h_over_20': 0},
                'institution_stats': {'university_percentage': 0, 'industry_percentage': 0, 'from_qs_top_50': 0, 'from_qs_top_100': 0, 'from_qs_top_200': 0},
                'recent_citations_count': 0,
                'summary_statements': []
            }
        }

    def _analyze_years(self, citations: List[Citation]) -> Dict:
        """Analyze citations over years"""
        years = [c.year for c in citations if c.year]
        year_counts = Counter(years)
        # Filter out future years or unreasonable past years if necessary, but for now keep all
        sorted_years = sorted(year_counts.items())
        return {'yearly_stats': sorted_years}

    def _analyze_impact_stats(self, citations: List[Citation], authors_data: Dict) -> Dict:
        """
        Calculate grant-friendly impact statistics.
        
        These metrics are designed to be used in grant proposals, tenure files,
        and funding applications to demonstrate research impact.
        """
        # Highly-cited papers that cite you (e.g., papers with 100+ citations)
        highly_cited_citing = []
        for c in citations:
            if hasattr(c, 'citation_count') and c.citation_count >= 50:
                highly_cited_citing.append({
                    'title': c.citing_paper_title,
                    'citations': c.citation_count,
                    'year': c.year,
                    'venue': c.venue,
                    'url': c.url or f"https://www.semanticscholar.org/paper/{c.paper_id}" if c.paper_id else ""
                })
        
        # Sort by citation count descending
        highly_cited_citing.sort(key=lambda x: x['citations'], reverse=True)
        
        # Count papers at different citation thresholds
        citation_thresholds = {
            'over_1000': len([c for c in citations if hasattr(c, 'citation_count') and c.citation_count >= 1000]),
            'over_500': len([c for c in citations if hasattr(c, 'citation_count') and c.citation_count >= 500]),
            'over_100': len([c for c in citations if hasattr(c, 'citation_count') and c.citation_count >= 100]),
            'over_50': len([c for c in citations if hasattr(c, 'citation_count') and c.citation_count >= 50]),
        }
        
        # High-profile author stats
        all_authors = authors_data.get('all_authors', [])
        high_profile = authors_data.get('high_profile_scholars', [])
        
        author_h_indices = [a.get('h_index', 0) for a in all_authors if isinstance(a.get('h_index'), int)]
        
        author_stats = {
            'total_unique_authors': len(all_authors),
            'high_profile_count': len(high_profile),
            'max_h_index': max(author_h_indices) if author_h_indices else 0,
            'avg_h_index': sum(author_h_indices) / len(author_h_indices) if author_h_indices else 0,
            'h_over_50': len([h for h in author_h_indices if h >= 50]),
            'h_over_30': len([h for h in author_h_indices if h >= 30]),
            'h_over_20': len([h for h in author_h_indices if h >= 20]),
        }
        
        # Institution prestige stats
        institutions = authors_data.get('institutions', {})
        university_count = institutions.get('University', 0)
        industry_count = institutions.get('Industry', 0)
        total_inst = university_count + industry_count + institutions.get('Government', 0) + institutions.get('Other', 0)
        
        # Count authors from ranked universities
        details = institutions.get('details', {})
        qs_top_50 = 0
        qs_top_100 = 0
        qs_top_200 = 0
        
        for author in details.get('University', []):
            rank = author.get('university_rank')
            if rank:
                if rank <= 50:
                    qs_top_50 += 1
                if rank <= 100:
                    qs_top_100 += 1
                if rank <= 200:
                    qs_top_200 += 1
        
        institution_stats = {
            'university_percentage': (university_count / total_inst * 100) if total_inst > 0 else 0,
            'industry_percentage': (industry_count / total_inst * 100) if total_inst > 0 else 0,
            'from_qs_top_50': qs_top_50,
            'from_qs_top_100': qs_top_100,
            'from_qs_top_200': qs_top_200,
        }
        
        # Recent impact (last 2 years)
        from datetime import datetime
        current_year = datetime.now().year
        recent_citations = [c for c in citations if c.year and c.year >= current_year - 2]
        
        return {
            'highly_cited_citing_papers': highly_cited_citing[:20],  # Top 20
            'citation_thresholds': citation_thresholds,
            'author_stats': author_stats,
            'institution_stats': institution_stats,
            'recent_citations_count': len(recent_citations),
            'summary_statements': self._generate_impact_statements(
                citation_thresholds, author_stats, institution_stats, len(citations)
            )
        }
    
    def _generate_impact_statements(self, citation_thresholds: Dict, author_stats: Dict, 
                                    institution_stats: Dict, total_analyzed: int) -> List[str]:
        """Generate ready-to-use impact statements for grants/proposals."""
        statements = []
        
        # Highly-cited paper statement
        if citation_thresholds['over_100'] > 0:
            statements.append(
                f"Cited by {citation_thresholds['over_100']} papers with 100+ citations, "
                f"demonstrating adoption by high-impact research."
            )
        
        # High-profile scholars statement
        if author_stats['high_profile_count'] > 0:
            statements.append(
                f"Recognized by {author_stats['high_profile_count']} high-profile researchers "
                f"(h-index ≥ 20), including scholars with h-index up to {author_stats['max_h_index']}."
            )
        
        # Prestigious universities statement
        if institution_stats['from_qs_top_100'] > 0:
            statements.append(
                f"Adopted by researchers from {institution_stats['from_qs_top_100']} "
                f"QS Top 100 universities worldwide."
            )
        
        # Cross-sector impact
        if institution_stats['industry_percentage'] > 5:
            statements.append(
                f"Demonstrates industry relevance with {institution_stats['industry_percentage']:.0f}% "
                f"of citations from industry researchers."
            )
        
        # Academic adoption
        if institution_stats['university_percentage'] > 70:
            statements.append(
                f"Strong academic adoption with {institution_stats['university_percentage']:.0f}% "
                f"of citations from university researchers."
            )
        
        return statements

    def _analyze_authors(self, citations: List[Citation], h_index_threshold: int) -> Dict:
        """Analyze citing authors with proper deduplication"""
        all_authors = []
        high_profile = []
        institutions = defaultdict(list)

        # Simpler progress message
        print(f"Processing {len(citations)} citations for author information...")
        
        # Track processed authors - store best version of each author
        # Key: normalized name + affiliation, Value: author_dict with best h-index
        author_registry = {}  # {(normalized_name, affiliation): author_dict}
        processed_author_ids = set()
        
        def _normalize_for_dedup(name: str) -> str:
            """Normalize name for deduplication - handles 'C. Tantithamthavorn' vs 'Chakkrit Tantithamthavorn'"""
            if not name:
                return ""
            import re
            # Remove periods and extra spaces
            normalized = re.sub(r'\.', '', name.lower().strip())
            normalized = ' '.join(normalized.split())
            # Extract last name for comparison (helps with abbreviated first names)
            parts = normalized.split()
            return parts[-1] if parts else ""  # Use last name as primary key
        
        # OPTIMIZATION: Batch fetch all GS author profiles FIRST
        # This is much faster than fetching one by one!
        all_gs_ids = set()
        for citation in citations:
            if hasattr(citation, 'authors_with_ids') and citation.authors_with_ids:
                for author_info in citation.authors_with_ids:
                    author_id = author_info.author_id
                    if author_id:
                        # Handle combined IDs like "gs:XXX|s2:YYY"
                        if '|' in author_id:
                            for part in author_id.split('|'):
                                if part.startswith('gs:'):
                                    all_gs_ids.add(part[3:])
                        elif author_id.startswith('gs:'):
                            all_gs_ids.add(author_id[3:])
        
        # Batch fetch all GS profiles (from cache or GS)
        gs_profiles_cache = {}
        if all_gs_ids and hasattr(self.api, 'batch_fetch_gs_authors'):
            print(f"[Analyzer] Pre-fetching {len(all_gs_ids)} Google Scholar profiles...")
            gs_profiles_cache = self.api.batch_fetch_gs_authors(list(all_gs_ids))
        
        for citation in citations:
            # FIX: Check if author list is not empty before processing
            if not citation.citing_authors:
                continue

            # Prefer authors_with_ids if available (contains S2 author IDs for disambiguation)
            authors_to_process = []
            if hasattr(citation, 'authors_with_ids') and citation.authors_with_ids:
                # Use AuthorInfo objects with unique IDs
                for author_info in citation.authors_with_ids[:3]:  # First 3 authors
                    authors_to_process.append({
                        'name': author_info.name,
                        'author_id': author_info.author_id
                    })
            else:
                # Fallback to name-only list (backward compatibility)
                for author_name in citation.citing_authors[:3]:
                    authors_to_process.append({
                        'name': author_name,
                        'author_id': ''
                    })
            
            for author_data in authors_to_process:
                author_name = author_data['name']
                author_id = author_data['author_id']
                
                # Skip if author name is Unknown or empty
                if not author_name or author_name == 'Unknown':
                    continue
                
                # Skip if we've already processed this exact author ID
                if author_id and author_id in processed_author_ids:
                    continue
                if author_id:
                    processed_author_ids.add(author_id)

                # COMPREHENSIVE MODE: Google Scholar is PRIMARY!
                # Priority:
                # 1. GS ID from citation page (direct profile link)
                # 2. GS ID from cache (found via publication matching)
                # 3. S2 data (only if GS not available)
                
                author = None
                gs_id_part = None
                s2_id_part = None
                
                # Parse IDs from author_id
                if author_id:
                    if '|' in author_id:
                        for part in author_id.split('|'):
                            if part.startswith('gs:'):
                                gs_id_part = part[3:]
                            elif part.startswith('s2:'):
                                s2_id_part = part[3:]
                            else:
                                s2_id_part = part
                    elif author_id.startswith('gs:'):
                        gs_id_part = author_id[3:]
                    elif author_id.startswith('s2:'):
                        s2_id_part = author_id[3:]
                    else:
                        s2_id_part = author_id
                
                # PRIORITY 1: Direct GS ID from citation page
                if gs_id_part:
                    if gs_id_part in gs_profiles_cache:
                        author = gs_profiles_cache[gs_id_part]
                    elif hasattr(self.api, 'get_author_by_gs_id'):
                        author = self.api.get_author_by_gs_id(gs_id_part, author_name)
                
                # PRIORITY 2: Find GS ID from cache (via publication or name matching)
                if not author:
                    from citationimpact.cache import get_author_cache
                    author_cache = get_author_cache()
                    
                    # Try to find cached GS profile by name or S2 ID
                    cached_info = author_cache.get_by_any_id(
                        name=author_name,
                        semantic_scholar_id=s2_id_part
                    )
                    
                    if cached_info and cached_info.get('google_scholar_id'):
                        # Found GS ID in cache! Use GS profile
                        gs_id_from_cache = cached_info['google_scholar_id']
                        if gs_id_from_cache in gs_profiles_cache:
                            author = gs_profiles_cache[gs_id_from_cache]
                        elif hasattr(self.api, 'get_author_by_gs_id'):
                            author = self.api.get_author_by_gs_id(gs_id_from_cache, author_name)
                    
                    # Also try publication matching for the citing paper
                    if not author:
                        citing_paper_title = citation.citing_paper_title if hasattr(citation, 'citing_paper_title') else ''
                        if citing_paper_title:
                            pub_match = author_cache.find_by_publications(
                                [{'title': citing_paper_title}], 
                                min_overlap=1
                            )
                            if pub_match and pub_match.get('google_scholar_id'):
                                gs_id_from_pub = pub_match['google_scholar_id']
                                if gs_id_from_pub in gs_profiles_cache:
                                    author = gs_profiles_cache[gs_id_from_pub]
                                elif hasattr(self.api, 'get_author_by_gs_id'):
                                    author = self.api.get_author_by_gs_id(gs_id_from_pub, author_name)
                
                # PRIORITY 3: Use S2 to find author (may still get GS via hybrid client)
                if not author and s2_id_part and hasattr(self.api, 'get_author_by_s2_id'):
                    author = self.api.get_author_by_s2_id(s2_id_part, author_name)
                
                # PRIORITY 4: Search by paper title to find author
                if not author:
                    citing_paper_title = citation.citing_paper_title if hasattr(citation, 'citing_paper_title') else ''
                    if hasattr(self.api, 'get_author_by_paper') and citing_paper_title:
                        author = self.api.get_author_by_paper(author_name, citing_paper_title)
                
                # PRIORITY 5: Final fallback to name-based lookup
                if not author:
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

                # Create author dict with h-index display (add GS marker if from Google Scholar)
                h_index_display = author.h_index
                h_index_source = getattr(author, 'h_index_source', '')
                if h_index_source == 'google_scholar':
                    h_index_display = f"{author.h_index} (GS)"
                
                author_dict = {
                    'name': author.name,
                    'h_index': author.h_index,
                    'h_index_display': h_index_display,  # For display with source marker
                    'affiliation': author.affiliation,
                    'institution_type': author.institution_type,
                    'university_rank': university_rank,
                    'university_tier': university_tier,
                    'usnews_rank': usnews_rank,
                    'usnews_tier': usnews_tier,
                    'university_rankings': university_rankings,
                    'primary_university_source': primary_university_source,
                    'citing_paper': citation.citing_paper_title,
                    'citing_papers': [citation.citing_paper_title],  # Track all citing papers
                    'paper_url': getattr(citation, 'url', ''),
                    'paper_id': getattr(citation, 'paper_id', ''),
                    'paper_citations': getattr(citation, 'citation_count', 0),  # Citing paper's citation count
                    'year': getattr(citation, 'year', 0),  # Citing paper's year
                    'venue': getattr(citation, 'venue', 'Unknown'),  # Citing paper's venue
                    'google_scholar_id': getattr(author, 'google_scholar_id', ''),
                    'semantic_scholar_id': getattr(author, 'semantic_scholar_id', ''),
                    'orcid_id': getattr(author, 'orcid_id', ''),
                    'homepage': getattr(author, 'homepage', ''),
                    'h_index_source': h_index_source,
                    'total_citations': getattr(author, 'citation_count', 0),  # Author's total citations from profile
                    'works_count': getattr(author, 'works_count', 0)  # Author's total works
                }
                
                # Deduplication: Check if we already have this author (by last name + affiliation)
                dedup_key = (_normalize_for_dedup(author.name), author.affiliation or 'Unknown')
                
                if dedup_key in author_registry:
                    # Existing author - merge and keep best h-index
                    existing = author_registry[dedup_key]
                    existing['citing_papers'].append(citation.citing_paper_title)
                    
                    # Prefer Google Scholar h-index (more accurate)
                    # or keep higher h-index if both from same source
                    existing_is_gs = existing.get('h_index_source') == 'google_scholar'
                    new_is_gs = h_index_source == 'google_scholar'
                    
                    if new_is_gs and not existing_is_gs:
                        # New one has GS h-index, use it
                        existing['h_index'] = author.h_index
                        existing['h_index_display'] = h_index_display
                        existing['h_index_source'] = h_index_source
                    elif new_is_gs == existing_is_gs and author.h_index > existing['h_index']:
                        # Same source, keep higher
                        existing['h_index'] = author.h_index
                        existing['h_index_display'] = h_index_display
                    
                    # Use longer/better name (prefer full name over abbreviated)
                    if len(author.name) > len(existing['name']):
                        existing['name'] = author.name
                    
                    # Update IDs if we have better ones
                    if not existing.get('google_scholar_id') and author_dict.get('google_scholar_id'):
                        existing['google_scholar_id'] = author_dict['google_scholar_id']
                    if not existing.get('semantic_scholar_id') and author_dict.get('semantic_scholar_id'):
                        existing['semantic_scholar_id'] = author_dict['semantic_scholar_id']
                else:
                    # New author - add to registry
                    author_registry[dedup_key] = author_dict
                    
                    # Categorize institution
                    category = self.api.categorize_institution(author.institution_type, author.affiliation)
                    institutions[category].append(author_dict)

        # Build final lists from deduplicated registry
        all_authors = list(author_registry.values())
        high_profile = [a for a in all_authors if a['h_index'] >= h_index_threshold]
        
        # Sort by h-index
        high_profile.sort(key=lambda x: x['h_index'], reverse=True)
        all_authors.sort(key=lambda x: x['h_index'], reverse=True)

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
    use_cache: bool = True,
    scraper_api_key: str = None,
    gs_cites_id: list = None,  # For direct GS citation access (from My Papers)
    existing_client = None  # Pass existing API client to reuse browser session
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
            - 'comprehensive': Use BOTH S2 and GS for maximum coverage (slower but most complete)
        semantic_scholar_key: Optional S2 API key (free from semanticscholar.org)
        email: Optional email for OpenAlex polite pool
        timeout: Request timeout in seconds (default: 15)
        max_retries: Max retry attempts for failed requests (default: 3)
        use_proxy: Use free proxy for Google Scholar (unreliable)
        gs_cites_id: List of Google Scholar citation IDs for direct access (from My Papers)
        use_cache: Use cached results if available (default: True)
        scraper_api_key: ScraperAPI key for reliable Google Scholar access (recommended for 'comprehensive' mode)
                        Get key at: https://www.scraperapi.com/

    Returns:
        Complete analysis with:
        - High-profile scholars (with real h-indices!)
        - Institution breakdown (University/Industry/Government)
        - Venue rankings (based on h-index, works for ANY field!)
        - Influential citations (AI-detected, with 'api' or 'comprehensive' source)

    Example (Recommended - API-based):
        >>> result = analyze_paper_impact(
        ...     "Large language models for software engineering",
        ...     h_index_threshold=20,
        ...     max_citations=50,
        ...     data_source='api'
        ... )
        >>> print(f"High-profile scholars: {len(result['high_profile_scholars'])}")

    Example (Comprehensive - combines both sources):
        >>> result = analyze_paper_impact(
        ...     "Your Paper Title",
        ...     h_index_threshold=20,
        ...     max_citations=50,
        ...     data_source='comprehensive'
        ... )
        
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

    valid_sources = ['api', 'google_scholar', 'comprehensive']
    if data_source not in valid_sources:
        raise ValueError(f"Invalid data_source: {data_source}. Must be one of {valid_sources}")

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

    # Use existing client if provided (reuses browser session!)
    api = existing_client
    
    # No cache hit, perform analysis
    if not api:
        if data_source == 'api':
            from ..clients import get_api_client
            api = get_api_client(semantic_scholar_key, email, timeout, max_retries)
        elif data_source == 'comprehensive':
            from ..clients import get_hybrid_client
            api = get_hybrid_client(
                semantic_scholar_key=semantic_scholar_key,
                email=email,
                use_gs_proxy=use_proxy,
                scraper_api_key=scraper_api_key,
                timeout=timeout,
                max_retries=max_retries,
                gs_cites_id=gs_cites_id  # Pass for direct citation access (no GS search!)
            )
            print("\n🔄 Using Comprehensive Mode (Semantic Scholar + Google Scholar)")
            print("   - S2 API for paper search (no CAPTCHA)")
            print("   - Uses S2 author IDs for accurate disambiguation")
            if gs_cites_id:
                print("   - ✓ Using DIRECT GS citation URLs (no search needed!)")
            else:
                print("   - Supplements with GS citations if available")
            print()
        elif data_source == 'google_scholar':
            from ..clients import get_google_scholar_client
            api = get_google_scholar_client(use_proxy=use_proxy, scraper_api_key=scraper_api_key)
            print("\n⚠️  Using Google Scholar (web scraping)")
            print("   - This is SLOWER than API-based approach")
            print("   - May encounter CAPTCHAs")
            print("   - No influential citations or citation contexts")
            print("   - Use 'api' data source when possible\n")
        else:
            raise ValueError(f"Invalid data_source: {data_source}. Must be 'api', 'google_scholar', or 'comprehensive'")

    # Pass data_source to analyzer so it can provide accurate error messages
    analyzer = CitationImpactAnalyzer(api, data_source=data_source)
    
    result = analyzer.analyze_paper(paper_title, h_index_threshold, max_citations)

    # Save to cache
    if use_cache and not result.get('error'):
        cache.set(paper_title, params, result)

    # Store client reference in result so caller can reuse it
    # (browser stays open for entire session to avoid CAPTCHAs)
    result['_client'] = api
    
    return result
    # NOTE: DO NOT close the client here!
    # The browser should stay open for the entire session to avoid CAPTCHAs.
    # The client will be closed when the main app exits.
