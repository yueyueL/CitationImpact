"""
ORCID API Client for CitationImpact

ORCID provides FREE persistent identifiers for researchers.
It's excellent for:
- Author disambiguation (ORCID ID is unique)
- Getting author publications
- Affiliation history

API Documentation: https://info.orcid.org/documentation/features/public-api/
No API key required for public data
"""

import requests
from typing import Optional, Dict, List


class ORCIDClient:
    """
    Client for ORCID public API - FREE researcher identifier service
    
    ORCID provides:
    - Unique researcher identifiers (solves name disambiguation!)
    - Publication lists
    - Affiliation history
    - Employment records
    """
    
    BASE_URL = "https://pub.orcid.org/v3.0"
    
    def __init__(self, timeout: int = 15):
        """
        Initialize ORCID client
        
        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
            'User-Agent': 'CitationImpact/1.0 (Academic citation analysis tool)'
        })
        print("[ORCID] Initialized public API client")
    
    def get_author_by_orcid(self, orcid_id: str) -> Optional[Dict]:
        """
        Get author information by ORCID ID
        
        Args:
            orcid_id: ORCID identifier (e.g., "0000-0001-2345-6789")
            
        Returns:
            Author information or None
        """
        try:
            # Clean ORCID ID
            orcid_id = orcid_id.strip().replace('https://orcid.org/', '')
            
            url = f"{self.BASE_URL}/{orcid_id}/record"
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            return self._parse_author_record(data, orcid_id)
            
        except Exception as e:
            print(f"[ORCID] Error getting author {orcid_id}: {e}")
            return None
    
    def search_author(self, name: str, affiliation: str = None) -> List[Dict]:
        """
        Search for authors by name
        
        Args:
            name: Author name to search
            affiliation: Optional affiliation to filter by
            
        Returns:
            List of matching authors
        """
        try:
            # Build search query
            query_parts = [f'family-name:{name.split()[-1]}']
            if len(name.split()) > 1:
                query_parts.append(f'given-names:{name.split()[0]}')
            if affiliation:
                query_parts.append(f'affiliation-org-name:{affiliation}')
            
            query = ' AND '.join(query_parts)
            
            url = f"{self.BASE_URL}/search"
            params = {
                'q': query,
                'rows': 10
            }
            
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            for result in data.get('result', []):
                orcid_id = result.get('orcid-identifier', {}).get('path')
                if orcid_id:
                    # Get full record for each result
                    author = self.get_author_by_orcid(orcid_id)
                    if author:
                        results.append(author)
            
            return results
            
        except Exception as e:
            print(f"[ORCID] Error searching for {name}: {e}")
            return []
    
    def get_author_works(self, orcid_id: str) -> List[Dict]:
        """
        Get publications for an ORCID ID
        
        Args:
            orcid_id: ORCID identifier
            
        Returns:
            List of publications
        """
        try:
            orcid_id = orcid_id.strip().replace('https://orcid.org/', '')
            
            url = f"{self.BASE_URL}/{orcid_id}/works"
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            data = response.json()
            works = []
            
            for group in data.get('group', []):
                work_summaries = group.get('work-summary', [])
                if work_summaries:
                    work = work_summaries[0]  # Take first (usually most complete)
                    works.append(self._parse_work(work))
            
            return works
            
        except Exception as e:
            print(f"[ORCID] Error getting works for {orcid_id}: {e}")
            return []
    
    def _parse_author_record(self, data: Dict, orcid_id: str) -> Dict:
        """Parse ORCID author record into common format"""
        person = data.get('person', {})
        activities = data.get('activities-summary', {})
        
        # Get name
        name_data = person.get('name', {})
        given_name = name_data.get('given-names', {}).get('value', '')
        family_name = name_data.get('family-name', {}).get('value', '')
        full_name = f"{given_name} {family_name}".strip()
        
        # Get current affiliation
        employments = activities.get('employments', {}).get('affiliation-group', [])
        current_affiliation = ''
        affiliation_type = 'Other'
        
        for emp_group in employments:
            summaries = emp_group.get('summaries', [])
            for summary in summaries:
                emp = summary.get('employment-summary', {})
                org = emp.get('organization', {})
                org_name = org.get('name', '')
                
                # Check if current (no end date)
                end_date = emp.get('end-date')
                if not end_date and org_name:
                    current_affiliation = org_name
                    # Determine type
                    org_name_lower = org_name.lower()
                    if 'university' in org_name_lower or 'college' in org_name_lower:
                        affiliation_type = 'University'
                    elif any(kw in org_name_lower for kw in ['google', 'microsoft', 'meta', 'amazon', 'apple', 'ibm']):
                        affiliation_type = 'Industry'
                    break
            if current_affiliation:
                break
        
        # Count works for approximate h-index indicator
        works_count = 0
        works_summary = activities.get('works', {})
        if works_summary:
            works_count = works_summary.get('group', [])
            works_count = len(works_count) if isinstance(works_count, list) else 0
        
        return {
            'name': full_name,
            'orcid_id': orcid_id,
            'affiliation': current_affiliation or 'Unknown',
            'affiliation_type': affiliation_type,
            'works_count': works_count,
            'profile_url': f"https://orcid.org/{orcid_id}",
            '_source': 'orcid'
        }
    
    def _parse_work(self, work: Dict) -> Dict:
        """Parse ORCID work into common format"""
        title = work.get('title', {}).get('title', {}).get('value', '')
        
        # Get year
        year = 0
        pub_date = work.get('publication-date')
        if pub_date and pub_date.get('year'):
            year = int(pub_date['year'].get('value', 0))
        
        # Get venue
        venue = work.get('journal-title', {}).get('value', '') if work.get('journal-title') else ''
        
        # Get DOI
        doi = None
        for ext_id in work.get('external-ids', {}).get('external-id', []):
            if ext_id.get('external-id-type') == 'doi':
                doi = ext_id.get('external-id-value')
                break
        
        return {
            'title': title,
            'year': year,
            'venue': venue,
            'doi': doi,
            'type': work.get('type', 'unknown'),
            '_source': 'orcid'
        }


def get_orcid_client(timeout: int = 15) -> ORCIDClient:
    """Get a configured ORCID client"""
    return ORCIDClient(timeout=timeout)

