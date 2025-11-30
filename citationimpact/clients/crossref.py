"""
Crossref API Client for CitationImpact

Crossref is a major DOI registration agency that provides FREE API access to:
- Paper metadata (title, authors, venue, year)
- Citation counts
- Reference lists

API Documentation: https://api.crossref.org/
No API key required (but polite pool with email recommended)
"""

import time
import requests
from typing import Optional, Dict, List, Any
from urllib.parse import quote_plus


class CrossrefClient:
    """
    Client for Crossref API - FREE citation and metadata service
    
    Crossref provides reliable, structured data for papers with DOIs.
    It's particularly good for:
    - Getting citation counts
    - Finding paper metadata by title
    - Getting reference lists
    """
    
    BASE_URL = "https://api.crossref.org"
    
    def __init__(self, email: Optional[str] = None, timeout: int = 15):
        """
        Initialize Crossref client
        
        Args:
            email: Optional email for polite pool (faster responses)
            timeout: Request timeout in seconds
        """
        self.email = email
        self.timeout = timeout
        self.session = requests.Session()
        
        # Set up headers
        headers = {
            'User-Agent': 'CitationImpact/1.0 (Academic citation analysis tool)'
        }
        if email:
            headers['User-Agent'] += f' (mailto:{email})'
        
        self.session.headers.update(headers)
        print(f"[Crossref] Initialized (email: {'set' if email else 'not set - consider adding for faster responses'})")
    
    def search_paper(self, title: str, limit: int = 5) -> Optional[Dict]:
        """
        Search for a paper by title
        
        Args:
            title: Paper title to search
            limit: Max results to return
            
        Returns:
            Best matching paper or None
        """
        try:
            url = f"{self.BASE_URL}/works"
            params = {
                'query': title,  # Use general query instead of query.title
                'rows': limit
            }
            
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            items = data.get('message', {}).get('items', [])
            
            if not items:
                return None
            
            # Find best match (highest citation count among close matches)
            best_match = items[0]
            search_title_lower = title.lower()
            
            for item in items:
                item_title = item.get('title', [''])[0].lower() if item.get('title') else ''
                if search_title_lower in item_title or item_title in search_title_lower:
                    # Good title match, prefer higher citations
                    if item.get('is-referenced-by-count', 0) > best_match.get('is-referenced-by-count', 0):
                        best_match = item
            
            return self._normalize_paper(best_match)
            
        except Exception as e:
            print(f"[Crossref] Error searching paper: {e}")
            return None
    
    def get_paper_by_doi(self, doi: str) -> Optional[Dict]:
        """
        Get paper metadata by DOI
        
        Args:
            doi: Paper DOI (e.g., "10.1145/3551349.3556964")
            
        Returns:
            Paper metadata or None
        """
        try:
            url = f"{self.BASE_URL}/works/{quote_plus(doi)}"
            
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            work = data.get('message', {})
            
            return self._normalize_paper(work)
            
        except Exception as e:
            print(f"[Crossref] Error getting paper by DOI: {e}")
            return None
    
    def get_citations(self, doi: str, limit: int = 100) -> List[Dict]:
        """
        Get papers that cite a given DOI
        
        Note: Crossref doesn't directly provide citing papers,
        but we can search for papers that reference this DOI.
        This is less complete than Semantic Scholar.
        
        Args:
            doi: Paper DOI
            limit: Max citations to return
            
        Returns:
            List of citing papers (may be incomplete)
        """
        try:
            # First get the paper to verify it exists
            paper = self.get_paper_by_doi(doi)
            if not paper:
                return []
            
            citation_count = paper.get('citationCount', 0)
            print(f"[Crossref] Paper has {citation_count} citations (Crossref count)")
            
            # Crossref doesn't have a direct "cited-by" API
            # We would need to use their event data or other sources
            # For now, return empty and let other sources handle citations
            print(f"[Crossref] Note: Use Semantic Scholar for citation details")
            
            return []
            
        except Exception as e:
            print(f"[Crossref] Error getting citations: {e}")
            return []
    
    def get_author_works(self, author_name: str, limit: int = 50) -> List[Dict]:
        """
        Get papers by an author name
        
        Args:
            author_name: Author name to search
            limit: Max results
            
        Returns:
            List of papers by this author
        """
        try:
            url = f"{self.BASE_URL}/works"
            params = {
                'query.author': author_name,
                'rows': limit,
                'select': 'DOI,title,author,container-title,published-print,is-referenced-by-count'
            }
            
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            items = data.get('message', {}).get('items', [])
            
            return [self._normalize_paper(item) for item in items]
            
        except Exception as e:
            print(f"[Crossref] Error getting author works: {e}")
            return []
    
    def _normalize_paper(self, raw: Dict) -> Dict:
        """Normalize Crossref paper data to common format"""
        # Extract authors
        authors = []
        for author in raw.get('author', []):
            name_parts = []
            if author.get('given'):
                name_parts.append(author['given'])
            if author.get('family'):
                name_parts.append(author['family'])
            if name_parts:
                authors.append(' '.join(name_parts))
        
        # Extract year
        year = 0
        published = raw.get('published-print') or raw.get('published-online') or raw.get('created')
        if published and 'date-parts' in published:
            date_parts = published['date-parts'][0]
            if date_parts:
                year = date_parts[0]
        
        # Extract venue
        venue = ''
        if raw.get('container-title'):
            venue = raw['container-title'][0] if isinstance(raw['container-title'], list) else raw['container-title']
        
        return {
            'doi': raw.get('DOI'),
            'title': raw.get('title', [''])[0] if raw.get('title') else '',
            'authors': authors,
            'venue': venue,
            'year': year,
            'citationCount': raw.get('is-referenced-by-count', 0),
            'referenceCount': raw.get('reference-count', 0),
            'type': raw.get('type', 'unknown'),
            '_source': 'crossref'
        }


def get_crossref_client(email: Optional[str] = None, timeout: int = 15) -> CrossrefClient:
    """Get a configured Crossref client"""
    return CrossrefClient(email=email, timeout=timeout)

