"""
Google Scholar API Client using scholarly library

NOTE: This is slower than API-based clients and may encounter CAPTCHAs.
Use only when Semantic Scholar/OpenAlex don't have your paper.
"""

import time
import random
from typing import Optional, List, Dict
from urllib.parse import urlparse, parse_qs
from scholarly import scholarly, ProxyGenerator

from ..models import Author, Venue, Citation
from ..utils import categorize_institution

# Import BeautifulSoup for HTML parsing (for citation scraping)
try:
    from bs4 import BeautifulSoup
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("[Warning] Selenium and BeautifulSoup not available. Citation fetching will be limited.")


def _extract_cites_id_from_url(url: Optional[str]) -> Optional[List[str]]:
    """Extract Google Scholar citation cluster ID from a URL."""
    if not url:
        return None

    try:
        # Ensure absolute URL for parsing
        if url.startswith('/'):
            url = f'https://scholar.google.com{url}'

        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        cites_values = query.get('cites')
        if cites_values:
            return [cites_values[0]]
    except Exception as exc:
        print(f"[Google Scholar] Warning: Could not extract cites_id from URL '{url}': {exc}")

    return None


class GoogleScholarClient:
    """
    Client for Google Scholar using scholarly library

    WARNING: This uses web scraping and may be slow or blocked.
    Prefer using UnifiedAPIClient (Semantic Scholar + OpenAlex) when possible.
    """

    def __init__(self, use_proxy: bool = False, use_selenium: bool = True):
        """
        Initialize Google Scholar client

        Args:
            use_proxy: If True, use free proxies (slower but helps avoid blocks)
            use_selenium: If True, use Selenium for citation scraping (required for accurate citation counts)
        """
        self.use_proxy = use_proxy
        self.use_selenium = use_selenium and SELENIUM_AVAILABLE
        self.driver = None
        self._paper_cache = {}  # Cache paperId -> (title, paper_data)

        if use_proxy:
            print("[INFO] Setting up Google Scholar with proxy...")
            pg = ProxyGenerator()
            pg.FreeProxies()
            scholarly.use_proxy(pg)
            print("[INFO] Proxy enabled. This will be slower but may avoid blocks.")

    def search_paper(self, title: str) -> Optional[Dict]:
        """
        Search for a paper on Google Scholar

        Args:
            title: Paper title

        Returns:
            Dictionary with paper info or None if not found
        """
        print(f"\n[Google Scholar] ========================================")
        print(f"[Google Scholar] SEARCH_PAPER called")
        print(f"[Google Scholar] Title: '{title}'")
        print(f"[Google Scholar] ========================================")
        print(f"[Google Scholar] Adding delay to avoid rate limits...")
        time.sleep(random.uniform(2, 5))  # Random delay

        try:
            print(f"[Google Scholar] Querying Google Scholar API...")
            search_query = scholarly.search_pubs(title)
            paper = next(search_query, None)

            if not paper:
                print("[Google Scholar] ❌ No results found for this paper title")
                print("[Google Scholar] Tips:")
                print("[Google Scholar]   - Verify the exact title on Google Scholar website")
                print("[Google Scholar]   - Try a shorter version of the title")
                print("[Google Scholar]   - Check for special characters or formatting")
                return None

            print(f"[Google Scholar] ✓ Found paper, fetching details...")
            # Fill complete paper data
            paper = scholarly.fill(paper)
            print(f"[Google Scholar] ✓ Paper details retrieved successfully")

            # Generate a unique paperId from scholar_id or title hash
            # This is needed for compatibility with analyzer code
            scholar_id = paper.get('url_scholarbib', '').split('?')[0] if paper.get('url_scholarbib') else None
            if scholar_id:
                paper_id = f"gs_{scholar_id.split('/')[-1]}"  # Use last part of URL
            else:
                # Use hash of title as fallback
                import hashlib
                paper_id = f"gs_{hashlib.md5(title.encode()).hexdigest()[:12]}"

            # Get cites_id - this is CRITICAL for fetching citations
            cites_id = paper.get('cites_id')
            
            # DEBUG: Show what we got
            print(f"[Google Scholar] DEBUG: Paper data keys: {list(paper.keys())}")
            print(f"[Google Scholar] DEBUG: cites_id value: {cites_id}")
            print(f"[Google Scholar] DEBUG: gsrank value: {paper.get('gsrank')}")
            
            # If no cites_id, try to extract from citedby_url or scholarbib URL
            if not cites_id:
                cites_id = _extract_cites_id_from_url(paper.get('citedby_url'))
                if cites_id:
                    print(f"[Google Scholar] ✓ Extracted cites_id from citedby_url: {cites_id}")
                else:
                    print(f"[Google Scholar] ⚠️  No cites_id found in citedby_url. Trying scholarbib URL...")
                    cites_id = _extract_cites_id_from_url(paper.get('url_scholarbib'))
                    if cites_id:
                        print(f"[Google Scholar] ✓ Extracted cites_id from scholarbib URL: {cites_id}")
                    else:
                        print(f"[Google Scholar] ⚠️  Unable to extract cites_id for this paper.")
            
            paper_dict = {
                'title': paper['bib'].get('title', title),
                'paperId': paper_id,  # Add paperId for compatibility
                'citationCount': paper.get('num_citations', 0),
                'year': paper['bib'].get('pub_year', 'Unknown'),
                'venue': paper['bib'].get('venue', 'Unknown'),
                'scholar_id': scholar_id,
                'cites_id': cites_id,  # Store for citations
                'url_scholarbib': paper.get('url_scholarbib'),  # Keep for debugging
                'gsrank': paper.get('gsrank')  # Might be useful
            }

            # Cache the paper for later citation fetching
            self._paper_cache[paper_id] = (paper_dict['title'], paper_dict)

            print(f"[Google Scholar] ✓ Paper cached with ID: {paper_id}")
            print(f"[Google Scholar] ✓ Final cites_id: {cites_id if cites_id else 'NONE - Citations cannot be fetched!'}")
            return paper_dict

        except StopIteration:
            print("[Google Scholar] ❌ No results found (StopIteration)")
            return None
        except Exception as e:
            print(f"[Google Scholar] ❌ Error searching paper: {e}")
            print(f"[Google Scholar] Error type: {type(e).__name__}")
            import traceback
            print(f"[Google Scholar] Traceback:")
            traceback.print_exc()
            return None

    def _get_driver(self):
        """Get or create Selenium WebDriver"""
        if self.driver is None:
            print("[Google Scholar] Opening browser for citation scraping...")
            print("[Google Scholar] IMPORTANT: Keep the browser window open!")
            options = Options()
            options.add_argument('--headless=new')  # Run headless
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            try:
                self.driver = webdriver.Chrome(options=options)
            except Exception as e:
                print(f"[Google Scholar] Warning: Could not start Chrome in headless mode: {e}")
                print("[Google Scholar] Trying without headless mode...")
                options = Options()
                self.driver = webdriver.Chrome(options=options)
                print("[Google Scholar] Browser opened. You can solve CAPTCHAs if prompted.")
        return self.driver

    def _wait_for_captcha(self, driver):
        """Check for CAPTCHA and wait if needed"""
        page_source = driver.page_source
        if 'CAPTCHA' in page_source or 'not a robot' in page_source.lower():
            print("\n" + "="*60)
            print("⚠️  CAPTCHA DETECTED!")
            print("Please solve it in the browser window, then press Enter...")
            print("="*60)
            input()
            time.sleep(1)

    def _parse_citations_from_page(self, soup) -> List[Dict]:
        """Parse citing papers from a Google Scholar search results page"""
        citing_papers = []

        for result in soup.find_all('div', class_='gs_ri'):
            try:
                title_tag = result.find('h3', class_='gs_rt')
                if not title_tag:
                    continue

                title_text = title_tag.get_text()
                title = title_text.replace('[HTML]', '').replace('[PDF]', '').strip()

                # Extract author info from the author line
                author_div = result.find('div', class_='gs_a')
                authors = []
                venue = 'Unknown'
                year = 0

                if author_div:
                    author_text = author_div.get_text()
                    # Format: "Author1, Author2, ... - Venue, Year - Publisher"
                    parts = author_text.split(' - ')
                    if len(parts) > 0:
                        author_str = parts[0].strip()
                        authors = [a.strip() for a in author_str.split(',')[:3]]  # First 3 authors
                    if len(parts) > 1:
                        venue_year = parts[1].strip()
                        # Try to extract year
                        import re
                        year_match = re.search(r'\b(19|20)\d{2}\b', venue_year)
                        if year_match:
                            year = int(year_match.group())
                        # Venue is everything before the year
                        if year_match:
                            venue = venue_year[:year_match.start()].strip().rstrip(',')
                        else:
                            venue = venue_year

                citing_papers.append({
                    'title': title,
                    'authors': authors if authors else ['Unknown'],
                    'venue': venue,
                    'year': year
                })

            except Exception as e:
                print(f"[Google Scholar] Warning: Error parsing citation: {e}")
                continue

        return citing_papers

    def get_citations(self, paper_id: str, limit: int = 100) -> List[Citation]:
        """
        Get citations for a paper using Selenium scraping

        Args:
            paper_id: Paper ID (gs_* format from search_paper)
            limit: Maximum number of citations to retrieve

        Returns:
            List of Citation objects
        """
        print(f"[Google Scholar] Getting citations for paper ID: {paper_id}")
        print(f"[Google Scholar] Cache contains {len(self._paper_cache)} papers")

        # Look up paper from cache
        if paper_id in self._paper_cache:
            paper_title, paper_data = self._paper_cache[paper_id]
            print(f"[Google Scholar] ✓ Found in cache: {paper_title}")
            cites_id = paper_data.get('cites_id')
            print(f"[Google Scholar] cites_id from cache: {cites_id}")
        else:
            # Not in cache - this shouldn't happen if search_paper was called first
            # But handle it gracefully by treating paper_id as a title
            print(f"[Google Scholar] ⚠️  Paper not in cache, treating as title and searching...")
            paper_title = paper_id.replace('gs_', '')  # Strip prefix if present
            print(f"[Google Scholar] Searching for: {paper_title}")

            try:
                print(f"[Google Scholar] Adding rate limit delay...")
                time.sleep(random.uniform(2, 5))
                
                search_query = scholarly.search_pubs(paper_title)
                paper_result = next(search_query, None)

                if not paper_result:
                    print("[Google Scholar] ❌ Paper not found in search")
                    return []

                print(f"[Google Scholar] ✓ Paper found, filling details...")
                # Fill to get cites_id
                paper_result = scholarly.fill(paper_result)
                cites_id = paper_result.get('cites_id')
                print(f"[Google Scholar] cites_id from search: {cites_id}")
            except Exception as e:
                print(f"[Google Scholar] ❌ Error finding paper: {e}")
                import traceback
                traceback.print_exc()
                return []

        # Check if we have a cites_id (handle empty list case)
        if not cites_id or (isinstance(cites_id, list) and len(cites_id) == 0):
            print(f"[Google Scholar] ❌ No cites_id found - paper may have no citations or isn't indexed")
            print(f"[Google Scholar] This can happen if:")
            print(f"[Google Scholar]   - Paper is very new")
            print(f"[Google Scholar]   - Paper has 0 citations")
            print(f"[Google Scholar]   - Google Scholar hasn't indexed citations yet")
            return []

        # Get the cites_id (can be a list)
        if isinstance(cites_id, list):
            if len(cites_id) > 0:
                cites_id = cites_id[0]
            else:
                print(f"[Google Scholar] ❌ cites_id list is empty")
                return []

        print(f"[Google Scholar] ✓ Using cites_id: {cites_id}")

        if not self.use_selenium:
            print("[Google Scholar] Selenium not available, cannot fetch citations")
            return []

        citations = []

        try:
            driver = self._get_driver()

            # Construct the cited-by URL
            base_url = f"https://scholar.google.com/scholar?hl=en&cites={cites_id}"

            # Fetch first page
            time.sleep(random.uniform(2, 4))
            driver.get(base_url)
            self._wait_for_captcha(driver)

            soup = BeautifulSoup(driver.page_source, 'html.parser')

            # Check for access denied
            if 'Access Denied' in soup.text or 'Forbidden' in soup.text:
                print('[Google Scholar] Access denied when fetching citations')
                return []

            # Parse citations from first page
            citing_papers = self._parse_citations_from_page(soup)
            print(f"[Google Scholar] Found {len(citing_papers)} citations on page 1")

            # Handle pagination
            current_page = 1
            while len(citing_papers) < limit:
                # Find next page button
                navigation_buttons = soup.find_all('a', class_='gs_nma')
                next_page_found = False

                for nav_button in navigation_buttons:
                    page_text = nav_button.text
                    if page_text and page_text.isnumeric() and int(page_text) == current_page + 1:
                        # Found next page
                        next_url = 'https://scholar.google.com' + nav_button['href']
                        current_page += 1

                        time.sleep(random.uniform(2, 4))
                        driver.get(next_url)
                        self._wait_for_captcha(driver)

                        soup = BeautifulSoup(driver.page_source, 'html.parser')
                        page_citations = self._parse_citations_from_page(soup)
                        citing_papers.extend(page_citations)
                        print(f"[Google Scholar] Found {len(page_citations)} citations on page {current_page} (total: {len(citing_papers)})")
                        next_page_found = True
                        break

                if not next_page_found:
                    break  # No more pages

            # Convert to Citation objects (limit to requested amount)
            for paper in citing_papers[:limit]:
                try:
                    citation = Citation(
                        citing_paper_title=paper['title'],
                        citing_authors=paper['authors'],
                        venue=paper['venue'],
                        year=paper['year'],
                        is_influential=False,  # Google Scholar doesn't provide this
                        contexts=[],  # Google Scholar doesn't provide citation contexts
                        intents=[]  # Google Scholar doesn't provide intents
                    )
                    citations.append(citation)
                except Exception as e:
                    print(f"[Google Scholar] Warning: Error creating Citation object: {e}")
                    continue

            print(f"[Google Scholar] Retrieved {len(citations)} citations total")
            return citations

        except Exception as e:
            print(f"[Google Scholar] Error getting citations: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_author(self, author_name: str) -> Optional[Author]:
        """
        Get author information from Google Scholar

        Args:
            author_name: Author name

        Returns:
            Author object or None if not found
        """
        print(f"[Google Scholar] Getting author info: {author_name}")
        time.sleep(random.uniform(2, 5))

        try:
            search_query = scholarly.search_author(author_name)
            author = next(search_query, None)

            if not author:
                return None

            # Fill complete author data
            author = scholarly.fill(author)

            # Get affiliation
            affiliation = author.get('affiliation', 'Unknown')
            organization = author.get('organization', 0)

            # Try to determine institution type (basic heuristics)
            institution_type = 'other'
            if affiliation and affiliation != 'Unknown':
                affiliation_lower = affiliation.lower()
                if any(word in affiliation_lower for word in ['university', 'college', 'institute']):
                    institution_type = 'education'
                elif any(word in affiliation_lower for word in ['google', 'microsoft', 'meta', 'amazon', 'ibm']):
                    institution_type = 'company'
                elif any(word in affiliation_lower for word in ['government', 'national', 'ministry']):
                    institution_type = 'government'

            return Author(
                name=author.get('name', author_name),
                h_index=author.get('hindex', 0),
                affiliation=affiliation,
                institution_type=institution_type,
                works_count=author.get('citedby', 0),  # Total citations as proxy
                citation_count=author.get('citedby', 0)
            )

        except Exception as e:
            print(f"[Google Scholar] Error getting author: {e}")
            return None

    def get_venue(self, venue_name: str) -> Optional[Venue]:
        """
        Get venue information

        NOTE: Google Scholar doesn't provide venue h-indices.
        This returns a basic Venue object.

        Args:
            venue_name: Venue name

        Returns:
            Basic Venue object
        """
        # Google Scholar doesn't have venue h-index data
        # Return a basic venue object
        return Venue(
            name=venue_name,
            h_index=0,
            type='unknown',
            works_count=0,
            cited_by_count=0,
            rank_tier='Unknown (Google Scholar has no venue rankings)'
        )

    def categorize_institution(self, institution_type: str) -> str:
        """Categorize institution type"""
        return categorize_institution(institution_type)

    def get_author_by_id(self, author_id: str) -> Optional[Dict]:
        """
        Get author information by Google Scholar ID

        Args:
            author_id: Google Scholar author ID

        Returns:
            Dictionary with author info and publications
        """
        print(f"[Google Scholar] Getting author by ID: {author_id}")
        time.sleep(random.uniform(2, 5))

        try:
            author = scholarly.search_author_id(author_id)
            if not author:
                return None

            # Fill complete author data
            author = scholarly.fill(author, sections=['basics', 'publications'])

            return author

        except Exception as e:
            print(f"[Google Scholar] Error getting author by ID: {e}")
            return None

    def get_author_publications(self, author_id: str, limit: int = 100) -> List[Dict]:
        """
        Get all publications for an author
        
        NOTE: Following CitationMap approach - fills each publication to get cites_id
        https://github.com/ChenLiu-1996/CitationMap

        Args:
            author_id: Google Scholar author ID
            limit: Maximum number of publications to retrieve (default: 100)

        Returns:
            List of publication dictionaries with cites_id for citation fetching
        """
        author = self.get_author_by_id(author_id)
        if not author:
            return []

        print(f"[Google Scholar] Filling publication metadata for {len(author.get('publications', []))} papers...")
        print(f"[Google Scholar] This may take a while due to rate limiting...")
        
        publications = []
        raw_pubs = author.get('publications', [])[:limit]  # Limit early to avoid excessive fills
        
        for idx, pub in enumerate(raw_pubs, 1):
            try:
                # Get basic info
                title = pub['bib'].get('title', 'Unknown')
                
                # CRITICAL: Fill each publication to get cites_id
                # This is what CitationMap does: scholarly.fill(pub)
                print(f"[Google Scholar] ({idx}/{len(raw_pubs)}) Filling: {title[:60]}...")
                
                # Add delay to avoid rate limiting
                time.sleep(random.uniform(1, 3))
                
                # Fill the publication to get complete data including cites_id
                try:
                    filled_pub = scholarly.fill(pub)
                except Exception as fill_error:
                    print(f"[Google Scholar] Warning: Could not fill publication: {fill_error}")
                    filled_pub = pub  # Use unfilled version as fallback
                
                # Generate paper ID for caching
                import hashlib
                paper_id = f"gs_{hashlib.md5(title.encode()).hexdigest()[:12]}"
                
                # Get cites_id from filled publication
                cites_id = filled_pub.get('cites_id', [])
                if not cites_id:
                    cites_id = _extract_cites_id_from_url(filled_pub.get('citedby_url'))
                    if cites_id:
                        print(f"[Google Scholar]   ✓ Extracted cites_id from citedby_url: {cites_id}")
                
                pub_info = {
                    'title': title,
                    'year': filled_pub['bib'].get('pub_year', 'Unknown'),
                    'venue': filled_pub['bib'].get('venue', 'Unknown'),
                    'citations': filled_pub.get('num_citations', 0),
                    'author': filled_pub['bib'].get('author', 'Unknown'),
                    'paperId': paper_id,
                    'cites_id': cites_id  # This should now have data!
                }
                
                # Cache the publication with its cites_id
                self._paper_cache[paper_id] = (title, pub_info)
                
                print(f"[Google Scholar]   ✓ cites_id: {cites_id if cites_id else 'None (no citations)'}")
                
                publications.append(pub_info)
                
            except Exception as e:
                print(f"[Google Scholar] Warning: Error processing publication: {e}")
                continue

        print(f"[Google Scholar] ✓ Successfully processed {len(publications)} publications")
        
        # Sort by citations (most cited first)
        publications.sort(key=lambda x: x['citations'], reverse=True)

        return publications


    def close(self):
        """Close the Selenium driver if open"""
        if self.driver is not None:
            try:
                self.driver.quit()
                print("[Google Scholar] Browser closed")
            except:
                pass
            self.driver = None

    def __del__(self):
        """Cleanup when object is deleted"""
        self.close()


def get_google_scholar_client(use_proxy: bool = False, use_selenium: bool = True) -> GoogleScholarClient:
    """
    Get a configured Google Scholar client

    Args:
        use_proxy: Use free proxies (slower but helps avoid blocks)
        use_selenium: Use Selenium for citation scraping (required for accurate results)

    Returns:
        Configured GoogleScholarClient
    """
    return GoogleScholarClient(use_proxy=use_proxy, use_selenium=use_selenium)
