"""
Clean, Simple Citation Impact Analyzer - FIXED VERSION

Improvements:
- ✅ Fixed error handling to return complete structure
- ✅ Added empty author list check
- ✅ Fixed inconsistent result keys (len() for counts)
- ✅ Added progress bar for venue analysis
- ✅ Better error messages
"""

from typing import Dict, List, Optional
from collections import Counter, defaultdict

from ..models import Author, Venue, Citation
from ..clients import UnifiedAPIClient
from ..utils.rankings import get_core_rank, get_university_rankings, get_venue_rankings


def _names_compatible(candidate_name: str, target_name: str) -> bool:
    """
    Check that two author names could plausibly refer to the same person.

    Requires a matching last name and, when both names carry a first name,
    a matching first initial. Used to guard cache matches based on a single
    shared publication, which would otherwise attribute a co-author's
    profile to this author.
    """
    if not candidate_name or not target_name:
        return False
    import re

    def _parts(name: str) -> List[str]:
        normalized = re.sub(r'\.', ' ', name.lower().strip())
        return [p for p in normalized.split() if p]

    candidate = _parts(candidate_name)
    target = _parts(target_name)
    if not candidate or not target:
        return False
    if candidate[-1] != target[-1]:
        return False
    if len(candidate) > 1 and len(target) > 1 and candidate[0][0] != target[0][0]:
        return False
    return True


# Ordering for Author.match_confidence values: 'id' > 'verified' > 'name' > ''
_CONFIDENCE_ORDER = {'': 0, 'name': 1, 'verified': 2, 'id': 3}


def _confidence_rank(level) -> int:
    """Rank a match_confidence level; unknown values rank lowest (as '')."""
    return _CONFIDENCE_ORDER.get(level, 0)


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
            if self.data_source == 'google_scholar':
                print(f"[WARNING] max_citations={max_citations} is very large and may take a long time")
            else:
                # Semantic Scholar's citations endpoint rejects limit > 1000 (HTTP 400)
                print(f"[WARNING] max_citations={max_citations} exceeds the Semantic Scholar maximum of 1000, using 1000")
                max_citations = 1000

        # Fresh failure counters so data_quality reflects only THIS analysis
        if hasattr(self.api, 'reset_failure_counts'):
            try:
                self.api.reset_failure_counts()
            except Exception:
                pass

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
            # An empty list can also mean the citations request itself failed
            # (rate limit, timeout, HTTP error) - report the real cause if known
            api_error = getattr(self.api, 'last_error', None)
            if api_error:
                error_message = f"Failed to retrieve citations: {api_error}"
            else:
                error_message = "No citations found. Paper may be too new or not indexed."
            return self._empty_result(
                paper['title'],
                error_message,
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

        # Step 6: Self-citation analysis (independent vs own-team citations)
        self_citation_stats = self._analyze_self_citations(paper, citations)

        # Step 7: Field-normalized impact from OpenAlex (FWCI + percentile)
        field_normalized = None
        metrics_fn = getattr(self.api, 'get_field_normalized_metrics', None)
        if metrics_fn:
            try:
                doi = (paper.get('externalIds') or {}).get('DOI') if isinstance(paper.get('externalIds'), dict) else None
                field_normalized = metrics_fn(paper['title'], doi=doi)
            except Exception as e:
                print(f"[INFO] Field-normalized metrics unavailable: {e}")

        # Step 8: Calculate grant-friendly impact statistics
        impact_stats = self._analyze_impact_stats(
            citations, authors_data,
            self_citation_stats=self_citation_stats,
            field_normalized=field_normalized,
            h_index_threshold=h_index_threshold,
        )

        # Step 9: Data-quality assessment (API failures, unknown affiliations,
        # cross-source citation-count transparency)
        data_quality = self._assess_data_quality(
            authors_data.get('all_authors', []),
            field_normalized=field_normalized,
            total_citations=paper.get('citationCount', 0),
        )

        # Compile results
        result = {
            'paper_title': paper['title'],
            'total_citations': paper.get('citationCount', 0),
            'influential_citations_count': paper.get('influentialCitationCount', 0),
            'analyzed_citations': len(citations),
            'h_index_threshold': h_index_threshold,
            'error': None,
            **authors_data,
            **venue_data,
            **influence_data,
            **year_data,
            'self_citation_stats': self_citation_stats,
            'field_normalized': field_normalized,
            'impact_stats': impact_stats,  # Grant-friendly summary statistics
            'data_quality': data_quality  # Completeness flags (degraded runs are not cached)
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
            'h_index_threshold': 20,
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
            'countries': {'counts': {}, 'unknown': 0},
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
            'citation_insights': {'intent_counts': {}, 'context_samples': []},
            'yearly_stats': [],
            'self_citation_stats': None,
            'field_normalized': None,
            'impact_stats': {
                'highly_cited_citing_papers': [],
                'citation_thresholds': {'over_1000': 0, 'over_500': 0, 'over_100': 0, 'over_50': 0},
                'author_stats': {'total_unique_authors': 0, 'high_profile_count': 0, 'max_h_index': 0, 'avg_h_index': 0, 'h_over_50': 0, 'h_over_30': 0, 'h_over_20': 0, 'id_matched_count': 0, 'verified_count': 0, 'name_only_count': 0},
                'institution_stats': {'university_percentage': 0, 'industry_percentage': 0, 'from_qs_top_50': 0, 'from_qs_top_100': 0, 'from_qs_top_200': 0, 'countries_count': 0},
                'recent_citations_count': 0,
                'summary_statements': []
            },
            'data_quality': {
                'failed_requests': {},
                'total_failed': 0,
                'unknown_affiliation_count': 0,
                'unknown_affiliation_percentage': 0.0,
                'degraded': False,
                'warnings': []
            }
        }

    def _assess_data_quality(self, all_authors: List[Dict],
                             field_normalized: Optional[Dict] = None,
                             total_citations: int = 0) -> Dict:
        """
        Summarize how complete this analysis is.

        Combines the client's per-API permanent-failure counts (when the
        client tracks them) with the share of deduplicated citing authors
        whose affiliation is unknown. Degraded results are NOT cached (see
        analyze_paper_impact) so a later run can fetch complete data.
        """
        failed_requests: Dict[str, int] = {}
        if hasattr(self.api, 'get_failure_counts'):
            try:
                failed_requests = dict(self.api.get_failure_counts() or {})
            except Exception:
                failed_requests = {}
        total_failed = int(sum(v for v in failed_requests.values()
                               if isinstance(v, (int, float))))

        authors = [a for a in (all_authors or []) if isinstance(a, dict)]
        unknown_count = sum(
            1 for a in authors
            if (a.get('affiliation') or '').strip() in ('', 'Unknown')
        )
        unknown_pct = (unknown_count / len(authors) * 100) if authors else 0.0

        # Degraded: only when failures plausibly harmed the RESULT, not for a
        # handful of transient misses in an otherwise-complete analysis.
        # Alarm tiers: mass failure (>=20 requests), moderate failure with
        # visible data impact (>=5 requests AND >=20% unknown affiliations),
        # or a mostly-unknown author list with any failure at all.
        degraded = (
            total_failed >= 20
            or (total_failed >= 5 and unknown_pct >= 20)
            or (unknown_pct >= 50 and len(authors) >= 10 and total_failed >= 1)
        )

        warnings: List[str] = []
        if total_failed > 0:
            api_parts = ', '.join(
                f"{api}: {count}" for api, count in sorted(failed_requests.items()) if count)
            detail = f" ({api_parts})" if api_parts else ""
            if degraded:
                warnings.append(
                    f"{total_failed} API request(s) failed during this analysis{detail}, "
                    f"so affiliations, countries, and field-normalized metrics may be "
                    f"missing ({unknown_count} of {len(authors)} citing authors have an "
                    f"unknown affiliation). Re-run the analysis later to fetch complete data."
                )
            else:
                warnings.append(
                    f"{total_failed} API request(s) failed during this analysis{detail}; "
                    f"a few author details may be missing, but the analysis is "
                    f"substantially complete."
                )

        # Cross-source transparency: S2 and OpenAlex index different venues,
        # so their citation counts can legitimately differ. Informational
        # only - this note never marks the run as degraded.
        oa_count = field_normalized.get('openalex_cited_by_count') \
            if isinstance(field_normalized, dict) else None
        try:
            oa_count = int(oa_count)
            s2_count = int(total_citations)
        except (TypeError, ValueError):
            oa_count = None
            s2_count = 0
        if oa_count is not None and s2_count > 0 and \
                abs(oa_count - s2_count) / s2_count > 0.10:
            warnings.append(
                f"Citation counts differ across sources: Semantic Scholar {s2_count} "
                f"vs OpenAlex {oa_count} (databases index different venues)."
            )

        return {
            'failed_requests': failed_requests,
            'total_failed': total_failed,
            'unknown_affiliation_count': unknown_count,
            'unknown_affiliation_percentage': unknown_pct,
            'degraded': degraded,
            'warnings': warnings,
        }

    def _analyze_years(self, citations: List[Citation]) -> Dict:
        """Analyze citations over years"""
        years = [c.year for c in citations if c.year]
        year_counts = Counter(years)
        # Filter out future years or unreasonable past years if necessary, but for now keep all
        sorted_years = sorted(year_counts.items())
        return {'yearly_stats': sorted_years}

    def _analyze_self_citations(self, paper: Dict, citations: List[Citation]) -> Optional[Dict]:
        """
        Split analyzed citations into self-citations (a citing paper sharing an
        author with the analyzed paper) and independent citations.

        Grant reviewers routinely ask what fraction of citations is independent
        of the original authors; this makes that number explicit.

        Returns None when the analyzed paper's own author list is unavailable
        (e.g. some Google Scholar results), so the UI can hide the section
        rather than report a misleading 0%.
        """
        own_authors = paper.get('authors') or []
        own_ids = {a.get('authorId') for a in own_authors
                   if isinstance(a, dict) and a.get('authorId')}
        own_names = [a.get('name', '') if isinstance(a, dict) else str(a)
                     for a in own_authors]
        own_names = [n for n in own_names if n]
        if not own_ids and not own_names:
            return None

        def _is_self(citation: Citation) -> bool:
            # Prefer ID comparison (exact), fall back to name compatibility
            for info in getattr(citation, 'authors_with_ids', None) or []:
                author_id = getattr(info, 'author_id', '') or ''
                # IDs may be combined like 'gs:XXX|s2:YYY'
                for part in author_id.split('|'):
                    plain = part[3:] if part.startswith('s2:') else part
                    if plain and plain in own_ids:
                        return True
            for citing_name in citation.citing_authors or []:
                for own_name in own_names:
                    if _names_compatible(citing_name, own_name):
                        return True
            return False

        self_count = sum(1 for c in citations if _is_self(c))
        total = len(citations)
        independent = total - self_count
        return {
            'self_count': self_count,
            'independent_count': independent,
            'independent_percentage': (independent / total * 100) if total else 0.0,
            'own_authors': own_names,
        }

    def _analyze_impact_stats(self, citations: List[Citation], authors_data: Dict,
                              self_citation_stats: Optional[Dict] = None,
                              field_normalized: Optional[Dict] = None,
                              h_index_threshold: int = 20) -> Dict:
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
                    'url': c.url or (f"https://www.semanticscholar.org/paper/{c.paper_id}" if c.paper_id else "")
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

        # Match-confidence breakdown: how each author profile was resolved.
        # Authors with an unknown/legacy confidence ('') count as name-only.
        confidences = [a.get('match_confidence', '') for a in all_authors]

        author_stats = {
            'total_unique_authors': len(all_authors),
            'high_profile_count': len(high_profile),
            'max_h_index': max(author_h_indices) if author_h_indices else 0,
            'avg_h_index': sum(author_h_indices) / len(author_h_indices) if author_h_indices else 0,
            'h_over_50': len([h for h in author_h_indices if h >= 50]),
            'h_over_30': len([h for h in author_h_indices if h >= 30]),
            'h_over_20': len([h for h in author_h_indices if h >= 20]),
            'id_matched_count': sum(1 for c in confidences if c == 'id'),
            'verified_count': sum(1 for c in confidences if c == 'verified'),
            'name_only_count': sum(1 for c in confidences if c not in ('id', 'verified')),
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
            # Distinct known countries among deduplicated citing authors
            # ('' = unknown, never counted)
            'countries_count': len({a.get('country') for a in all_authors if a.get('country')}),
        }
        
        # Recent impact (last 2 years)
        from datetime import datetime
        current_year = datetime.now().year
        # A two-year window means the current year and the previous one
        recent_citations = [c for c in citations if c.year and c.year >= current_year - 1]
        
        return {
            'highly_cited_citing_papers': highly_cited_citing[:20],  # Top 20
            'citation_thresholds': citation_thresholds,
            'author_stats': author_stats,
            'institution_stats': institution_stats,
            'recent_citations_count': len(recent_citations),
            'summary_statements': self._generate_impact_statements(
                citation_thresholds, author_stats, institution_stats, len(citations),
                self_citation_stats=self_citation_stats,
                field_normalized=field_normalized,
                h_index_threshold=h_index_threshold,
            )
        }

    def _generate_impact_statements(self, citation_thresholds: Dict, author_stats: Dict,
                                    institution_stats: Dict, total_analyzed: int,
                                    self_citation_stats: Optional[Dict] = None,
                                    field_normalized: Optional[Dict] = None,
                                    h_index_threshold: int = 20) -> List[str]:
        """Generate ready-to-use impact statements for grants/proposals."""
        statements = []

        # Field-normalized impact (FWCI) statement
        if field_normalized:
            fwci = field_normalized.get('fwci')
            if fwci and fwci > 1.0:
                statements.append(
                    f"Field-Weighted Citation Impact of {fwci:.1f} — cited {fwci:.1f}× more than "
                    f"the world average for papers in the same field and year (source: OpenAlex)."
                )
            percentile = field_normalized.get('citation_percentile')
            if percentile is not None:
                pct = percentile * 100 if percentile <= 1 else percentile
                if field_normalized.get('is_top_1_percent'):
                    statements.append("Ranks in the top 1% of papers by field-normalized citations.")
                elif field_normalized.get('is_top_10_percent'):
                    statements.append("Ranks in the top 10% of papers by field-normalized citations.")
                elif pct >= 75:
                    statements.append(
                        f"Ranks in the top {100 - pct:.0f}% of papers by field-normalized citations."
                    )

        # Independent-citation statement
        if self_citation_stats and total_analyzed > 0:
            independent_pct = self_citation_stats.get('independent_percentage', 0)
            if independent_pct >= 50:
                statements.append(
                    f"{independent_pct:.0f}% of analyzed citations are independent of the "
                    f"original authors, demonstrating broad external adoption."
                )
        
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
                f"(h-index ≥ {h_index_threshold}), including scholars with h-index up to {author_stats['max_h_index']}."
            )
        
        # Prestigious universities statement
        # NOTE: from_qs_top_100 counts AUTHORS at QS Top 100 universities,
        # not distinct universities, so the statement must quantify researchers
        if institution_stats['from_qs_top_100'] > 0:
            researcher_count = institution_stats['from_qs_top_100']
            statements.append(
                f"Adopted by {researcher_count} researcher{'s' if researcher_count != 1 else ''} "
                f"from QS Top 100 universities worldwide."
            )
        
        # International reach (counts absent on results from older caches)
        countries_count = institution_stats.get('countries_count', 0) or 0
        if countries_count >= 5:
            statements.append(
                f"Cited by researchers across {countries_count} countries, "
                f"demonstrating international reach."
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
        author_entries_by_id = {}  # {author_id: author_dict} - for repeat citers
        
        def _normalize_for_dedup(name: str) -> str:
            """Normalize name for deduplication - handles 'C. Tantithamthavorn' vs 'Chakkrit Tantithamthavorn'"""
            if not name:
                return ""
            import re
            # Remove periods and extra spaces
            normalized = re.sub(r'\.', '', name.lower().strip())
            normalized = ' '.join(normalized.split())
            # Key on last name + first initial: abbreviated names still merge
            # ('C. Tantithamthavorn' == 'Chakkrit Tantithamthavorn') but distinct
            # people sharing a surname ('Wei Zhang' vs 'Li Zhang') stay separate
            parts = normalized.split()
            if not parts:
                return ""
            last_name = parts[-1]
            first_initial = parts[0][0] if len(parts) > 1 else ''
            return f"{last_name}|{first_initial}"
        
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

        # OPTIMIZATION: Batch fetch all S2 author profiles too - one POST to
        # the S2 batch endpoint replaces dozens of per-author GET requests
        # (which trigger 429 storms under sustained load). The batch only
        # stages raw S2 bases inside the client; the per-author enrichment
        # (OpenAlex institution type/country, hybrid GS merge) still runs in
        # PRIORITY 3 below, just without the per-author S2 GET.
        all_s2_ids = set()
        for citation in citations:
            if hasattr(citation, 'authors_with_ids') and citation.authors_with_ids:
                for author_info in citation.authors_with_ids:
                    author_id = author_info.author_id
                    if author_id:
                        # Handle combined IDs like "gs:XXX|s2:YYY"
                        if '|' in author_id:
                            for part in author_id.split('|'):
                                if part.startswith('s2:'):
                                    all_s2_ids.add(part[3:])
                                elif not part.startswith('gs:'):
                                    all_s2_ids.add(part)  # plain ids are S2
                        elif author_id.startswith('s2:'):
                            all_s2_ids.add(author_id[3:])
                        elif not author_id.startswith('gs:'):
                            all_s2_ids.add(author_id)  # plain ids are S2

        s2_profiles_cache = {}
        if len(all_s2_ids) >= 3 and hasattr(self.api, 'get_authors_batch'):
            print(f"[Analyzer] Pre-fetching {len(all_s2_ids)} Semantic Scholar author profiles...")
            try:
                s2_profiles_cache = self.api.get_authors_batch(list(all_s2_ids)) or {}
            except Exception:
                # Batch failure: fall back to the per-id path silently
                s2_profiles_cache = {}

        # Some clients (hybrid) accept a context_title kwarg on get_author so a
        # name-only lookup can be corroborated against the citing paper.
        import inspect
        try:
            get_author_accepts_context = (
                'context_title' in inspect.signature(self.api.get_author).parameters
            )
        except (TypeError, ValueError):
            get_author_accepts_context = False

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
                
                # Skip if we've already processed this exact author ID,
                # but still record this citing paper for that author
                if author_id and author_id in processed_author_ids:
                    existing = author_entries_by_id.get(author_id)
                    if existing is not None and citation.citing_paper_title not in existing['citing_papers']:
                        existing['citing_papers'].append(citation.citing_paper_title)
                    continue
                if author_id:
                    processed_author_ids.add(author_id)

                # COMPREHENSIVE MODE: Google Scholar is PRIMARY!
                # Priority:
                # 1. GS ID from citation page (direct profile link)
                # 2. GS ID from cache (found via publication matching)
                # 3. S2 data (only if GS not available)
                
                author = None
                confidence = ''  # how confidently this profile was matched to the name
                gs_id_part = None
                s2_id_part = None
                citing_paper_title = getattr(citation, 'citing_paper_title', '') or ''

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
                    if author:
                        # GS profile ID came straight from the citation itself
                        confidence = 'id'

                # PRIORITY 2: Find GS ID from cache (via publication or name matching)
                if not author:
                    from citationimpact.cache import get_author_cache
                    author_cache = get_author_cache()

                    # Try to find cached GS profile by name or S2 ID.
                    # verify_titles guards the name-key path: a cached profile
                    # that merely shares this author's NAME is only trusted if
                    # its stored publications contain the citing paper - two
                    # different researchers can share the same name.
                    # A missing citing title means the name path CANNOT be
                    # verified - keep the gate active (empty list) so only
                    # real-ID matches get through, never an unverified name hit
                    cached_info = author_cache.get_by_any_id(
                        name=author_name,
                        semantic_scholar_id=s2_id_part,
                        verify_titles=[citing_paper_title] if citing_paper_title else []
                    )

                    if cached_info and cached_info.get('google_scholar_id'):
                        # Found GS ID in cache! Use GS profile
                        gs_id_from_cache = cached_info['google_scholar_id']
                        if gs_id_from_cache in gs_profiles_cache:
                            author = gs_profiles_cache[gs_id_from_cache]
                        elif hasattr(self.api, 'get_author_by_gs_id'):
                            author = self.api.get_author_by_gs_id(gs_id_from_cache, author_name)
                        if author:
                            if s2_id_part and cached_info.get('semantic_scholar_id') == s2_id_part:
                                # Cache entry matched the real S2 author ID
                                confidence = 'id'
                            else:
                                # Name-key hit corroborated by the citing paper
                                confidence = 'verified'

                    # Also try publication matching for the citing paper
                    if not author:
                        if citing_paper_title:
                            pub_match = author_cache.find_by_publications(
                                [{'title': citing_paper_title}],
                                min_overlap=1
                            )
                            # A single shared paper matches ANY co-author's cached
                            # profile, so only adopt it if the names are compatible
                            if (pub_match and pub_match.get('google_scholar_id')
                                    and _names_compatible(pub_match.get('name', ''), author_name)):
                                gs_id_from_pub = pub_match['google_scholar_id']
                                if gs_id_from_pub in gs_profiles_cache:
                                    author = gs_profiles_cache[gs_id_from_pub]
                                elif hasattr(self.api, 'get_author_by_gs_id'):
                                    author = self.api.get_author_by_gs_id(gs_id_from_pub, author_name)
                                if author:
                                    # Corroborated by publication overlap
                                    confidence = 'verified'

                # PRIORITY 3: Use S2 to find author (may still get GS via hybrid client).
                # The batch prefetch only staged a raw S2 base inside the
                # client - get_author_by_s2_id still runs so batch-resolved
                # authors keep the full enrichment (OpenAlex institution
                # type/country/affiliation fill, hybrid's GS merge and
                # persistent-cache save). The client skips its per-author S2
                # GET for batch-staged ids, so this stays cheap.
                if not author and s2_id_part and hasattr(self.api, 'get_author_by_s2_id'):
                    author = self.api.get_author_by_s2_id(s2_id_part, author_name)
                    if author:
                        # Resolved via the real S2 author ID -> 'id'. Keep the
                        # client's own stamp when it had to fall back to a name
                        # search (failed ID fetch or name-only cache rebuild).
                        confidence = getattr(author, 'match_confidence', '') or 'id'
                # Batch hit as a last resort (per-id path found nothing, or
                # the client has no per-id method): raw S2-only profile, but
                # still resolved via the real S2 author ID.
                if not author and s2_id_part and s2_id_part in s2_profiles_cache:
                    author = s2_profiles_cache[s2_id_part]
                    if author:
                        confidence = 'id'

                # PRIORITY 4: Search by paper title to find author
                if not author:
                    if hasattr(self.api, 'get_author_by_paper') and citing_paper_title:
                        author = self.api.get_author_by_paper(author_name, citing_paper_title)
                        if author:
                            # Client stamps 'verified' when the candidate's
                            # publication list contained the citing paper and
                            # 'name' when it fell back to a bare name search.
                            confidence = getattr(author, 'match_confidence', '') or 'verified'

                # PRIORITY 5: Final fallback to name-based lookup
                if not author:
                    if get_author_accepts_context and citing_paper_title:
                        author = self.api.get_author(author_name, context_title=citing_paper_title)
                    else:
                        author = self.api.get_author(author_name)
                    if author:
                        # Bare name search -> 'name', unless the client itself
                        # corroborated the match (publication overlap or an
                        # ID-resolved profile served from its cache).
                        stamped = getattr(author, 'match_confidence', '')
                        confidence = stamped if _confidence_rank(stamped) > _confidence_rank('name') else 'name'
                if not author:
                    continue

                # Normalize: fall back to the Author's own stamp, and never let
                # an unexpected value through ('' means unknown/legacy).
                if confidence not in ('id', 'verified', 'name'):
                    confidence = getattr(author, 'match_confidence', '')
                    if confidence not in ('id', 'verified', 'name'):
                        confidence = ''

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
                    'works_count': getattr(author, 'works_count', 0),  # Author's total works
                    'match_confidence': confidence,  # 'id' / 'verified' / 'name' / '' (unknown)
                    'country': getattr(author, 'country', '') or ''  # ISO 3166-1 alpha-2, '' when unknown
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
                    if not existing.get('country') and author_dict.get('country'):
                        existing['country'] = author_dict['country']

                    # Keep the strongest match confidence seen for this person
                    # ('id' > 'verified' > 'name' > '') and, when the new record
                    # was matched more confidently, trust its identity fields.
                    # Metrics must travel with the identity: the earlier
                    # lower-confidence profile may belong to a same-named
                    # different person, so its h-index/citations must not
                    # survive under the upgraded (ID-verified) identity.
                    if _confidence_rank(author_dict.get('match_confidence', '')) > \
                            _confidence_rank(existing.get('match_confidence', '')):
                        existing['match_confidence'] = author_dict['match_confidence']
                        for identity_field in ('google_scholar_id', 'semantic_scholar_id', 'affiliation'):
                            if author_dict.get(identity_field):
                                existing[identity_field] = author_dict[identity_field]
                        for metric_field in ('h_index', 'h_index_display', 'h_index_source',
                                             'total_citations', 'works_count'):
                            existing[metric_field] = author_dict[metric_field]
                else:
                    # New author - add to registry
                    author_registry[dedup_key] = author_dict

                    # Categorize institution
                    category = self.api.categorize_institution(author.institution_type, author.affiliation)
                    institutions[category].append(author_dict)

                # Remember the registry entry for this ID so repeat citers
                # accumulate all of their citing papers
                if author_id:
                    author_entries_by_id[author_id] = author_registry[dedup_key]

        # Build final lists from deduplicated registry
        all_authors = list(author_registry.values())
        high_profile = [a for a in all_authors if a['h_index'] >= h_index_threshold]
        
        # Sort by h-index
        high_profile.sort(key=lambda x: x['h_index'], reverse=True)
        all_authors.sort(key=lambda x: x['h_index'], reverse=True)

        # Country breakdown over the deduplicated registry; authors without a
        # known ISO code ('') are bucketed separately as 'unknown'
        country_counts = Counter()
        unknown_countries = 0
        for a in all_authors:
            code = a.get('country', '') or ''
            if code:
                country_counts[code] += 1
            else:
                unknown_countries += 1

        return {
            'all_authors': all_authors,
            'high_profile_scholars': high_profile,
            'institutions': {
                'University': len(institutions.get('University', [])),
                'Industry': len(institutions.get('Industry', [])),
                'Government': len(institutions.get('Government', [])),
                'Other': len(institutions.get('Other', [])),
                'details': dict(institutions)
            },
            'countries': {
                'counts': dict(country_counts),
                'unknown': unknown_countries
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
        """Analyze citation influence and how citing papers use the work"""
        influential = []
        methodological = []
        intent_counts = Counter()
        context_samples = []

        for citation in citations:
            # FIX: Check if authors list is not empty
            authors_to_show = citation.citing_authors[:3] if citation.citing_authors else ['Unknown']

            if citation.is_influential:
                # Return the full Citation object, not just a dict
                influential.append(citation)

            # Semantic Scholar returns intents in lowercase (e.g. 'methodology'),
            # so compare case-insensitively
            intents_lower = {i.lower() for i in citation.intents if isinstance(i, str)}
            if 'methodology' in intents_lower or 'uses' in intents_lower:
                # Return the full Citation object, not just a dict
                methodological.append(citation)

            for intent in intents_lower:
                intent_counts[intent] += 1

            # Keep a sample of context sentences showing HOW the work is cited
            if citation.contexts and len(context_samples) < 15:
                snippet = next((s.strip() for s in citation.contexts
                                if isinstance(s, str) and s.strip()), None)
                if snippet:
                    context_samples.append({
                        'context': snippet,
                        'title': citation.citing_paper_title,
                        'year': citation.year,
                        'venue': citation.venue,
                        'url': citation.url,
                        'is_influential': citation.is_influential,
                        'intents': sorted(intents_lower),
                    })

        return {
            'influential_citations': influential,
            'methodological_citations': methodological,
            'citation_insights': {
                'intent_counts': dict(intent_counts),
                'context_samples': context_samples,
            }
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
    # Only reuse it when its type matches the requested data_source; otherwise a
    # client left over from a previously-selected source would silently run this
    # analysis and its results would be cached under the wrong data_source key.
    # Compare by class NAME to avoid importing optional heavy client modules.
    expected_client_classes = {
        'api': 'UnifiedAPIClient',
        'google_scholar': 'GoogleScholarClient',
        'comprehensive': 'HybridAPIClient',
    }
    api = existing_client
    if api is not None and type(api).__name__ != expected_client_classes[data_source]:
        print(f"[WARNING] Ignoring existing {type(api).__name__} client: "
              f"data_source '{data_source}' requires {expected_client_classes[data_source]}")
        api = None

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

    # Save to cache - but never cache a degraded result: it would be served
    # for up to 7 days as if it were complete
    if use_cache and not result.get('error'):
        if (result.get('data_quality') or {}).get('degraded'):
            print("[Cache] Result may be incomplete (API failures) - not caching so a later run can fetch complete data")
        else:
            cache.set(paper_title, params, result)

    # Store client reference in result so caller can reuse it
    # (browser stays open for entire session to avoid CAPTCHAs)
    result['_client'] = api
    
    return result
    # NOTE: DO NOT close the client here!
    # The browser should stay open for the entire session to avoid CAPTCHAs.
    # The client will be closed when the main app exits.
