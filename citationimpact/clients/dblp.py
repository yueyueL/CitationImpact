"""
DBLP API Client for CitationImpact

DBLP is a comprehensive FREE database for Computer Science publications.
It's particularly excellent for:
- CS conference papers (ICSE, FSE, ASE, etc.)
- CS journal papers
- Author disambiguation
- Complete publication lists

API Documentation: https://dblp.org/faq/13501473.html
No API key required
"""

import requests
import time
from typing import Optional, Dict, List


class DBLPClient:
    """
    Client for DBLP API - FREE Computer Science bibliography
    
    DBLP is extremely complete for CS publications and provides:
    - Paper search by title
    - Author profiles with all publications
    - Venue information
    - Co-author networks
    """
    
    BASE_URL = "https://dblp.org"
    
    def __init__(self, timeout: int = 15):
        """
        Initialize DBLP client
        
        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'CitationImpact/1.0 (Academic citation analysis tool)'
        })
        print("[DBLP] Initialized client (specialized for Computer Science)")
    
    def search_paper(self, title: str, limit: int = 10) -> Optional[Dict]:
        """
        Search for a paper by title
        
        Args:
            title: Paper title to search
            limit: Max results to return
            
        Returns:
            Best matching paper or None
        """
        try:
            url = f"{self.BASE_URL}/search/publ/api"
            params = {
                'q': title,
                'format': 'json',
                'h': limit
            }
            
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            hits = data.get('result', {}).get('hits', {}).get('hit', [])
            
            if not hits:
                return None
            
            # Find best match by title similarity
            search_title_lower = title.lower()
            best_match = None
            best_score = 0
            
            for hit in hits:
                info = hit.get('info', {})
                paper_title = info.get('title', '').lower()
                
                # Simple similarity: count matching words
                search_words = set(search_title_lower.split())
                paper_words = set(paper_title.split())
                overlap = len(search_words & paper_words)
                score = overlap / max(len(search_words), 1)
                
                if score > best_score:
                    best_score = score
                    best_match = hit
            
            if best_match and best_score > 0.5:
                return self._normalize_paper(best_match)
            
            return self._normalize_paper(hits[0])
            
        except Exception as e:
            print(f"[DBLP] Error searching paper: {e}")
            return None
    
    def search_author(self, name: str, limit: int = 10) -> List[Dict]:
        """
        Search for authors by name
        
        Args:
            name: Author name to search
            limit: Max results
            
        Returns:
            List of matching authors
        """
        try:
            url = f"{self.BASE_URL}/search/author/api"
            params = {
                'q': name,
                'format': 'json',
                'h': limit
            }
            
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            hits = data.get('result', {}).get('hits', {}).get('hit', [])
            
            authors = []
            for hit in hits:
                info = hit.get('info', {})
                authors.append({
                    'name': info.get('author', ''),
                    'dblp_url': info.get('url', ''),
                    'notes': info.get('notes', {}).get('note', []),
                    '_source': 'dblp'
                })
            
            return authors
            
        except Exception as e:
            print(f"[DBLP] Error searching author: {e}")
            return []
    
    def get_author_publications(self, author_url: str) -> List[Dict]:
        """
        Get all publications for a DBLP author
        
        Args:
            author_url: DBLP author page URL (e.g., "https://dblp.org/pid/123/4567")
            
        Returns:
            List of publications
        """
        try:
            # Convert URL to API endpoint
            if '/pid/' in author_url:
                api_url = author_url.replace('https://dblp.org/', f'{self.BASE_URL}/') + '.json'
            else:
                api_url = author_url + '.json' if not author_url.endswith('.json') else author_url
            
            response = self.session.get(api_url, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract publications
            publications = []
            for pub in data.get('dblpPerson', {}).get('r', []):
                # Each 'r' entry can be article, inproceedings, etc.
                for pub_type, pub_data in pub.items():
                    if isinstance(pub_data, dict):
                        publications.append(self._normalize_publication(pub_data, pub_type))
            
            return publications
            
        except Exception as e:
            print(f"[DBLP] Error getting author publications: {e}")
            return []
    
    def get_venue_info(self, venue_name: str) -> Optional[Dict]:
        """
        Get information about a venue (conference/journal)
        
        Args:
            venue_name: Venue name (e.g., "ICSE", "TSE")
            
        Returns:
            Venue information or None
        """
        try:
            url = f"{self.BASE_URL}/search/venue/api"
            params = {
                'q': venue_name,
                'format': 'json',
                'h': 5
            }
            
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            hits = data.get('result', {}).get('hits', {}).get('hit', [])
            
            if not hits:
                return None
            
            # Return first match
            info = hits[0].get('info', {})
            return {
                'name': info.get('venue', ''),
                'acronym': info.get('acronym', ''),
                'type': info.get('type', ''),
                'url': info.get('url', ''),
                '_source': 'dblp'
            }
            
        except Exception as e:
            print(f"[DBLP] Error getting venue info: {e}")
            return None
    
    def _normalize_paper(self, hit: Dict) -> Dict:
        """Normalize DBLP paper data to common format"""
        info = hit.get('info', {})
        
        # Get authors
        authors_data = info.get('authors', {}).get('author', [])
        if isinstance(authors_data, str):
            authors = [authors_data]
        elif isinstance(authors_data, list):
            authors = [a if isinstance(a, str) else a.get('text', '') for a in authors_data]
        else:
            authors = []
        
        # Get venue
        venue = info.get('venue', '')
        if isinstance(venue, list):
            venue = venue[0] if venue else ''
        
        return {
            'title': info.get('title', ''),
            'authors': authors,
            'venue': venue,
            'year': int(info.get('year', 0)) if info.get('year') else 0,
            'type': info.get('type', ''),
            'doi': info.get('doi', ''),
            'dblp_url': info.get('url', ''),
            'ee': info.get('ee', ''),  # Electronic edition URL
            '_source': 'dblp'
        }
    
    def _normalize_publication(self, pub_data: Dict, pub_type: str) -> Dict:
        """Normalize a publication from author page"""
        # Handle authors which can be string or list
        authors = pub_data.get('author', [])
        if isinstance(authors, str):
            authors = [authors]
        elif isinstance(authors, list):
            authors = [a if isinstance(a, str) else a.get('text', '') for a in authors]
        
        return {
            'title': pub_data.get('title', ''),
            'authors': authors,
            'venue': pub_data.get('journal', '') or pub_data.get('booktitle', ''),
            'year': int(pub_data.get('year', 0)) if pub_data.get('year') else 0,
            'type': pub_type,
            'doi': pub_data.get('doi', ''),
            'ee': pub_data.get('ee', ''),
            '_source': 'dblp'
        }


def get_dblp_client(timeout: int = 15) -> DBLPClient:
    """Get a configured DBLP client"""
    return DBLPClient(timeout=timeout)

