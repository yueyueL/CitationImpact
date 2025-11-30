"""
SerpAPI Google Scholar Client - Most reliable way to access Google Scholar

SerpAPI is a paid service that provides a clean API for Google Scholar.
No CAPTCHAs, no blocking, no rate limits (within your plan).

Get your API key at: https://serpapi.com/
Free tier: 100 searches/month

Pricing: https://serpapi.com/pricing
- Free: 100 searches/month
- Developer: $50/month for 5,000 searches
- Production: $130/month for 15,000 searches
"""

import time
from typing import Optional, List, Dict

from ..models import Author, Citation, AuthorInfo


# Try to import serpapi
try:
    from serpapi import GoogleSearch
    SERPAPI_AVAILABLE = True
except ImportError:
    SERPAPI_AVAILABLE = False
    GoogleSearch = None


class SerpAPIScholarClient:
    """
    Google Scholar client using SerpAPI (most reliable)
    
    Benefits over web scraping:
    - No CAPTCHAs ever
    - No rate limiting
    - Structured JSON responses
    - Fast and reliable
    
    Requires: pip install google-search-results
    """
    
    def __init__(self, api_key: str):
        """
        Initialize SerpAPI client
        
        Args:
            api_key: SerpAPI key from https://serpapi.com/
        """
        if not SERPAPI_AVAILABLE:
            raise ImportError(
                "SerpAPI not installed. Run: pip install google-search-results"
            )
        
        self.api_key = api_key
        print(f"[SerpAPI] Initialized Google Scholar client")
    
    def search_paper(self, title: str) -> Optional[Dict]:
        """
        Search for a paper on Google Scholar via SerpAPI
        
        Args:
            title: Paper title
            
        Returns:
            Paper dict with citationCount, title, etc.
        """
        print(f"[SerpAPI] Searching for: {title[:50]}...")
        
        params = {
            "engine": "google_scholar",
            "q": title,
            "api_key": self.api_key
        }
        
        search = GoogleSearch(params)
        results = search.get_dict()
        
        if "error" in results:
            print(f"[SerpAPI] Error: {results['error']}")
            return None
        
        organic_results = results.get("organic_results", [])
        
        if not organic_results:
            print(f"[SerpAPI] No results found")
            return None
        
        # Find best match
        paper = organic_results[0]
        
        # Extract citation count
        cited_by = paper.get("inline_links", {}).get("cited_by", {})
        citation_count = cited_by.get("total", 0)
        cites_id = cited_by.get("cites_id", "")
        
        print(f"[SerpAPI] Found: {paper.get('title', '')[:50]}... ({citation_count} citations)")
        
        return {
            'title': paper.get('title', ''),
            'citationCount': citation_count,
            'paperId': f"serpapi_{cites_id}" if cites_id else f"serpapi_{hash(title)}",
            'cites_id': cites_id,
            'authors': [a.get('name', '') for a in paper.get('publication_info', {}).get('authors', [])],
            'venue': paper.get('publication_info', {}).get('summary', ''),
            'year': self._extract_year(paper.get('publication_info', {}).get('summary', '')),
            'url': paper.get('link', ''),
            'snippet': paper.get('snippet', '')
        }
    
    def get_citations(self, cites_id: str, limit: int = 100) -> List[Citation]:
        """
        Get citations for a paper using its cites_id
        
        Args:
            cites_id: Google Scholar cites ID (from search_paper result)
            limit: Maximum citations to retrieve
            
        Returns:
            List of Citation objects
        """
        # If cites_id looks like a title, search for the paper first
        if not cites_id.isdigit() and len(cites_id) > 20:
            print(f"[SerpAPI] Got title instead of cites_id, searching first...")
            paper = self.search_paper(cites_id)
            if paper and paper.get('cites_id'):
                cites_id = paper['cites_id']
            else:
                print(f"[SerpAPI] Could not find cites_id for paper")
                return []
        
        print(f"[SerpAPI] Getting citations for cites_id: {cites_id}")
        
        citations = []
        start = 0
        
        while len(citations) < limit:
            params = {
                "engine": "google_scholar",
                "cites": cites_id,
                "start": start,
                "num": min(20, limit - len(citations)),
                "api_key": self.api_key
            }
            
            search = GoogleSearch(params)
            results = search.get_dict()
            
            if "error" in results:
                print(f"[SerpAPI] Error: {results['error']}")
                break
            
            organic_results = results.get("organic_results", [])
            
            if not organic_results:
                break
            
            for paper in organic_results:
                # Extract authors
                authors = []
                author_infos = []
                for author in paper.get('publication_info', {}).get('authors', []):
                    name = author.get('name', '')
                    authors.append(name)
                    author_infos.append(AuthorInfo(name=name, author_id=''))
                
                # Extract venue/year from summary
                summary = paper.get('publication_info', {}).get('summary', '')
                year = self._extract_year(summary)
                venue = self._extract_venue(summary)
                
                citation = Citation(
                    citing_paper_title=paper.get('title', 'Unknown'),
                    citing_authors=authors,
                    venue=venue,
                    year=year,
                    is_influential=False,  # SerpAPI doesn't provide this
                    contexts=[paper.get('snippet', '')],
                    intents=[],
                    paper_id=f"serpapi_{paper.get('result_id', '')}",
                    url=paper.get('link', ''),
                    authors_with_ids=author_infos
                )
                citations.append(citation)
                
                if len(citations) >= limit:
                    break
            
            start += 20
            time.sleep(0.5)  # Small delay between pages
        
        print(f"[SerpAPI] Retrieved {len(citations)} citations")
        return citations
    
    def get_author(self, author_name: str) -> Optional[Author]:
        """
        Search for author info on Google Scholar
        
        Args:
            author_name: Author name
            
        Returns:
            Author object or None
        """
        print(f"[SerpAPI] Searching for author: {author_name}")
        
        params = {
            "engine": "google_scholar_profiles",
            "mauthors": author_name,
            "api_key": self.api_key
        }
        
        search = GoogleSearch(params)
        results = search.get_dict()
        
        if "error" in results:
            print(f"[SerpAPI] Error: {results['error']}")
            return None
        
        profiles = results.get("profiles", [])
        
        if not profiles:
            print(f"[SerpAPI] No author profile found")
            return None
        
        profile = profiles[0]
        
        # Get detailed author info
        author_id = profile.get("author_id", "")
        if author_id:
            return self._get_author_details(author_id, profile)
        
        return Author(
            name=profile.get("name", author_name),
            h_index=0,
            affiliation=profile.get("affiliations", "Unknown"),
            institution_type="other",
            works_count=0,
            citation_count=profile.get("cited_by", 0),
            google_scholar_id=author_id,
            h_index_source="serpapi"
        )
    
    def _get_author_details(self, author_id: str, profile: Dict) -> Author:
        """Get detailed author info including h-index"""
        params = {
            "engine": "google_scholar_author",
            "author_id": author_id,
            "api_key": self.api_key
        }
        
        search = GoogleSearch(params)
        results = search.get_dict()
        
        if "error" in results:
            # Fall back to basic profile
            return Author(
                name=profile.get("name", "Unknown"),
                h_index=0,
                affiliation=profile.get("affiliations", "Unknown"),
                institution_type="other",
                works_count=0,
                citation_count=profile.get("cited_by", 0),
                google_scholar_id=author_id,
                h_index_source="serpapi"
            )
        
        author_data = results.get("author", {})
        cited_by = results.get("cited_by", {})
        
        # Get h-index from table
        h_index = 0
        for row in cited_by.get("table", []):
            if row.get("h_index"):
                h_index = row["h_index"].get("all", 0)
                break
        
        affiliation = author_data.get("affiliations", "Unknown")
        
        # Determine institution type
        inst_type = "other"
        if affiliation and affiliation != "Unknown":
            aff_lower = affiliation.lower()
            if any(w in aff_lower for w in ['university', 'college', 'institute']):
                inst_type = "education"
            elif any(w in aff_lower for w in ['google', 'microsoft', 'meta', 'amazon']):
                inst_type = "company"
        
        return Author(
            name=author_data.get("name", profile.get("name", "Unknown")),
            h_index=h_index,
            affiliation=affiliation,
            institution_type=inst_type,
            works_count=len(results.get("articles", [])),
            citation_count=cited_by.get("table", [{}])[0].get("citations", {}).get("all", 0),
            google_scholar_id=author_id,
            homepage=author_data.get("website", ""),
            h_index_source="serpapi"
        )
    
    def _extract_year(self, summary: str) -> int:
        """Extract year from publication summary"""
        import re
        match = re.search(r'\b(19|20)\d{2}\b', summary)
        return int(match.group()) if match else 0
    
    def _extract_venue(self, summary: str) -> str:
        """Extract venue from publication summary"""
        # Summary format: "Author1, Author2 - Journal/Conference, Year"
        if ' - ' in summary:
            parts = summary.split(' - ')
            if len(parts) >= 2:
                venue_part = parts[-1]
                # Remove year
                import re
                venue = re.sub(r',?\s*(19|20)\d{2}$', '', venue_part).strip()
                return venue
        return "Unknown"


def get_serpapi_client(api_key: str) -> Optional[SerpAPIScholarClient]:
    """
    Get a SerpAPI Google Scholar client
    
    Args:
        api_key: SerpAPI key from https://serpapi.com/
        
    Returns:
        SerpAPIScholarClient or None if not available
    """
    if not SERPAPI_AVAILABLE:
        print("[SerpAPI] Not installed. Run: pip install google-search-results")
        return None
    
    if not api_key:
        print("[SerpAPI] No API key provided")
        return None
    
    return SerpAPIScholarClient(api_key)

