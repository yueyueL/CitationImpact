"""
Google Scholar API Client using scholarly library

NOTE: This is slower than API-based clients and may encounter CAPTCHAs.
Use only when Semantic Scholar/OpenAlex don't have your paper.
"""

import time
import random
import signal
import threading
from typing import Optional, List, Dict
from urllib.parse import urlparse, parse_qs
from scholarly import scholarly, ProxyGenerator

from ..models import Author, Venue, Citation, AuthorInfo
from ..utils import categorize_institution

# ANSI color codes for terminal output
class Colors:
    RED = '\033[91m'
    YELLOW = '\033[93m'
    GREEN = '\033[92m'
    BOLD = '\033[1m'
    RESET = '\033[0m'
    BG_RED = '\033[41m'
    WHITE = '\033[97m'


def _timeout_call(func, args=(), kwargs=None, timeout=30, default=None):
    """
    Call a function with a timeout. Returns default if timeout occurs.
    
    Uses threading to avoid issues with signal on non-main threads.
    """
    if kwargs is None:
        kwargs = {}
    
    result = [default]
    exception = [None]
    
    def target():
        try:
            result[0] = func(*args, **kwargs)
        except Exception as e:
            exception[0] = e
    
    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout)
    
    if thread.is_alive():
        print(f"[Google Scholar] ⚠️ Operation timed out after {timeout}s")
        return default
    
    if exception[0]:
        raise exception[0]
    
    return result[0]

# Import BeautifulSoup for HTML parsing (for citation scraping)
try:
    from bs4 import BeautifulSoup
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("[Warning] Selenium and BeautifulSoup not available. Citation fetching will be limited.")

# Try to import undetected-chromedriver for better anti-detection
try:
    import undetected_chromedriver as uc
    UC_AVAILABLE = True
except ImportError:
    UC_AVAILABLE = False


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
    
    Anti-blocking options:
    - ScraperAPI (recommended): Paid service that handles anti-bot detection
    - FreeProxies: Free but unreliable rotating proxies
    - Tor: Uses Tor network for anonymity
    - Visible browser: Allows manual CAPTCHA solving
    """

    def __init__(
        self, 
        use_proxy: bool = False, 
        use_selenium: bool = True, 
        headless: bool = False,
        scraper_api_key: str = None
    ):
        """
        Initialize Google Scholar client

        Args:
            use_proxy: If True, use free proxies (slower but helps avoid blocks)
            use_selenium: If True, use Selenium for citation scraping (required for accurate citation counts)
            headless: If True, run browser in headless mode (faster but more likely to be blocked)
                     If False (default), run visible browser so user can solve CAPTCHAs
            scraper_api_key: If provided, use ScraperAPI service (most reliable, requires paid API key)
                            Get key at: https://www.scraperapi.com/
        """
        self.use_proxy = use_proxy
        self.use_selenium = use_selenium and SELENIUM_AVAILABLE
        self.headless = headless
        self.scraper_api_key = scraper_api_key
        self.driver = None
        self._paper_cache = {}  # Cache paperId -> (title, paper_data)
        
        # Set up proxy/scraper
        if scraper_api_key:
            print("[Google Scholar] 🔧 Setting up ScraperAPI (recommended for reliability)...")
            pg = ProxyGenerator()
            success = pg.ScraperAPI(scraper_api_key)
            if success:
                scholarly.use_proxy(pg)
                print("[Google Scholar] ✅ ScraperAPI configured successfully")
            else:
                print("[Google Scholar] ⚠️ ScraperAPI setup failed, falling back to direct access")
        elif use_proxy:
            print("[Google Scholar] 🔧 Setting up free proxies (may be slow/unreliable)...")
            pg = ProxyGenerator()
            pg.FreeProxies()
            scholarly.use_proxy(pg)
            print("[Google Scholar] ✅ Free proxies enabled")

        if use_proxy:
            print("[INFO] Setting up Google Scholar with proxy...")
            pg = ProxyGenerator()
            pg.FreeProxies()
            scholarly.use_proxy(pg)
            print("[INFO] Proxy enabled. This will be slower but may avoid blocks.")

    def _search_paper_selenium(self, title: str) -> Optional[Dict]:
        """
        Fallback paper search using Selenium with undetected-chromedriver.
        Used when scholarly library fails.
        """
        driver = self._get_driver()
        if not driver:
            return None
            
        try:
            # Search Google Scholar directly
            search_url = f"https://scholar.google.com/scholar?q={title.replace(' ', '+')}"
            driver.get(search_url)
            time.sleep(random.uniform(2, 4))
            
            # Wait for CAPTCHA if needed (may restart browser in visible mode)
            new_driver = self._wait_for_captcha(driver)
            if new_driver:
                driver = new_driver
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Find first result
            result = soup.find('div', class_='gs_ri')
            if not result:
                return None
                
            title_tag = result.find('h3', class_='gs_rt')
            if not title_tag:
                return None
                
            found_title = title_tag.get_text().replace('[HTML]', '').replace('[PDF]', '').strip()
            
            # Get citation info
            cite_link = result.find('a', href=lambda x: x and 'cites=' in x)
            cites_id = None
            num_citations = 0
            
            if cite_link:
                href = cite_link.get('href', '')
                if 'cites=' in href:
                    cites_id = href.split('cites=')[1].split('&')[0]
                cite_text = cite_link.get_text()
                import re
                match = re.search(r'Cited by (\d+)', cite_text)
                if match:
                    num_citations = int(match.group(1))
            
            # Get author/venue info
            author_div = result.find('div', class_='gs_a')
            venue = 'Unknown'
            year = 0
            
            if author_div:
                author_text = author_div.get_text()
                parts = author_text.split(' - ')
                if len(parts) > 1:
                    venue_year = parts[1].strip()
                    year_match = re.search(r'\b(19|20)\d{2}\b', venue_year)
                    if year_match:
                        year = int(year_match.group())
                        venue = venue_year[:year_match.start()].strip().rstrip(',')
                    else:
                        venue = venue_year
            
            return {
                'title': found_title,
                'citationCount': num_citations,
                'cites_id': [cites_id] if cites_id else None,
                'venue': venue,
                'year': year,
                'paperId': f"gs_{hash(found_title) % 10000000}",
                '_source': 'selenium'
            }
            
        except Exception as e:
            print(f"[Google Scholar] Selenium search failed: {e}")
            return None

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
                print("[Google Scholar] ⚠️ scholarly library failed, trying Selenium fallback...")
                # Try Selenium-based search as fallback
                selenium_result = self._search_paper_selenium(title)
                if selenium_result:
                    print(f"[Google Scholar] ✓ Found via Selenium: {selenium_result['title'][:50]}...")
                    # Cache and return
                    paper_id = selenium_result['paperId']
                    self._paper_cache[paper_id] = (selenium_result['title'], selenium_result)
                    return selenium_result
                
                print("[Google Scholar] ❌ No results found for this paper title")
                print("[Google Scholar] Tips:")
                print("[Google Scholar]   - Verify the exact title on Google Scholar website")
                print("[Google Scholar]   - Try a shorter version of the title")
                print("[Google Scholar]   - Check for special characters or formatting")
                return None

            print(f"[Google Scholar] ✓ Found paper, fetching details (timeout: 30s)...")
            # Fill complete paper data with timeout to avoid hanging
            paper = _timeout_call(scholarly.fill, args=(paper,), timeout=30, default=paper)
            if paper:
                print(f"[Google Scholar] ✓ Paper details retrieved successfully")
            else:
                print(f"[Google Scholar] ⚠️ Could not fill paper details, using basic info")

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
            
            # Paper data retrieved successfully
            
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
                'url_scholarbib': paper.get('url_scholarbib'),
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
        """Get or create Selenium WebDriver
        
        Uses undetected-chromedriver if available to bypass bot detection.
        Falls back to regular Selenium if not available.
        """
        if self.driver is None:
            print("[Google Scholar] " + "="*50)
            print("[Google Scholar] Opening browser for Google Scholar...")
            
            # Try undetected-chromedriver first (best for avoiding detection)
            if UC_AVAILABLE:
                print("[Google Scholar] Using undetected-chromedriver (anti-detection)")
                try:
                    options = uc.ChromeOptions()
                    options.add_argument('--no-sandbox')
                    options.add_argument('--disable-dev-shm-usage')
                    
                    if self.headless:
                        options.add_argument('--headless=new')
                        print("[Google Scholar] Running in headless mode")
                    else:
                        print(f"{Colors.YELLOW}{Colors.BOLD}[Google Scholar] ⚠️  KEEP THE BROWSER WINDOW OPEN!{Colors.RESET}")
                        print(f"{Colors.YELLOW}[Google Scholar] You may need to solve CAPTCHAs if prompted.{Colors.RESET}")
                    
                    # undetected_chromedriver handles anti-detection automatically
                    self.driver = uc.Chrome(options=options, use_subprocess=True)
                    
                    if not self.headless:
                        self.driver.maximize_window()
                    
                    print("[Google Scholar] ✅ Browser ready (anti-detection enabled)")
                    print("[Google Scholar] " + "="*50)
                    return self.driver
                    
                except Exception as e:
                    print(f"[Google Scholar] ⚠️ undetected-chromedriver failed: {e}")
                    print("[Google Scholar] Falling back to regular Selenium...")
            
            # Fallback to regular Selenium
            print("[Google Scholar] Using regular Selenium WebDriver")
            options = Options()
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
            
            if self.headless:
                options.add_argument('--headless=new')
                print("[Google Scholar] Running in headless mode (faster but may be blocked)")
            else:
                print(f"{Colors.YELLOW}{Colors.BOLD}[Google Scholar] ⚠️  KEEP THE BROWSER WINDOW OPEN!{Colors.RESET}")
                print(f"{Colors.YELLOW}[Google Scholar] You may need to solve CAPTCHAs if prompted.{Colors.RESET}")
            
            try:
                self.driver = webdriver.Chrome(options=options)
                if not self.headless:
                    self.driver.maximize_window()
            except Exception as e:
                print(f"[Google Scholar] ❌ Could not start Chrome: {e}")
                print("[Google Scholar] Make sure Chrome and ChromeDriver are installed")
                return None
            
            print("[Google Scholar] " + "="*50)
                
        return self.driver

    def _wait_for_captcha(self, driver):
        """Check for CAPTCHA/blocking and wait for user to resolve
        
        Detects various forms of Google's anti-bot protection:
        - CAPTCHA challenges
        - "unusual traffic" blocks
        - reCAPTCHA
        
        In headless mode, if CAPTCHA is detected, we restart in visible mode.
        """
        page_source = driver.page_source.lower()
        
        # Check for various blocking indicators
        blocking_indicators = [
            'captcha',
            'not a robot',
            'unusual traffic',
            'solve this puzzle',
            'verify you are human',
            'recaptcha',
            'please verify',
        ]
        
        is_blocked = any(indicator in page_source for indicator in blocking_indicators)
        
        if is_blocked:
            if self.headless:
                # In headless mode, we can't solve CAPTCHA
                # Restart in visible mode
                print(f"\n{Colors.BG_RED}{Colors.WHITE}{Colors.BOLD}" + "="*60 + f"{Colors.RESET}")
                print(f"{Colors.RED}{Colors.BOLD}🚨 CAPTCHA DETECTED in headless mode!{Colors.RESET}")
                print(f"{Colors.YELLOW}Restarting browser in visible mode for CAPTCHA solving...{Colors.RESET}")
                print(f"{Colors.BG_RED}{Colors.WHITE}{Colors.BOLD}" + "="*60 + f"{Colors.RESET}")
                
                # Close current driver and restart in visible mode
                current_url = driver.current_url
                driver.quit()
                self.driver = None
                self.headless = False  # Switch to visible mode
                
                # Get new visible driver
                new_driver = self._get_driver()
                if new_driver:
                    new_driver.get(current_url)
                    time.sleep(2)
                    # Now wait for user to solve CAPTCHA
                    self._wait_for_captcha(new_driver)
                    return new_driver
                return None
            else:
                print(f"\n{Colors.BG_RED}{Colors.WHITE}{Colors.BOLD}" + "="*60 + f"{Colors.RESET}")
                print(f"{Colors.RED}{Colors.BOLD}🚨 CAPTCHA or VERIFICATION REQUIRED!{Colors.RESET}")
                print("")
                print(f"{Colors.YELLOW}{Colors.BOLD}👉 Please solve the challenge in the browser window{Colors.RESET}")
                print(f"{Colors.YELLOW}{Colors.BOLD}👉 Then press Enter here to continue...{Colors.RESET}")
                print(f"{Colors.BG_RED}{Colors.WHITE}{Colors.BOLD}" + "="*60 + f"{Colors.RESET}")
                try:
                    input()  # Wait for user to press Enter
                    time.sleep(2)  # Give page time to reload after solving
                except EOFError:
                    # Non-interactive mode, can't get user input
                    print(f"{Colors.RED}[Google Scholar] ⚠️  Non-interactive mode, cannot solve CAPTCHA{Colors.RESET}")
                    time.sleep(5)  # Just wait and hope page loads
        
        return None  # No restart needed

    def _parse_citations_from_page(self, soup) -> List[Dict]:
        """Parse citing papers from a Google Scholar search results page"""
        citing_papers = []
        import re

        # Try multiple CSS selectors (Google Scholar changes their structure)
        result_selectors = [
            ('div', {'class_': 'gs_ri'}),  # Standard result item
            ('div', {'class_': 'gs_r'}),   # Alternative result wrapper
            ('div', {'data-rp': True}),    # Data-attribute based
        ]
        
        results = []
        for tag, attrs in result_selectors:
            results = soup.find_all(tag, attrs)
            if results:
                break
        
        # Check for blocking or empty results
        if not results:
            page_text = soup.get_text()
            if 'unusual traffic' in page_text.lower() or 'captcha' in page_text.lower():
                print(f"{Colors.RED}{Colors.BOLD}[Google Scholar] ⚠️  Detected CAPTCHA or rate limiting!{Colors.RESET}")
            elif 'did not match any articles' in page_text.lower():
                print("[Google Scholar] ⚠️  No articles found for this citation query")
                        
        for result in results:
            try:
                # Try multiple title selectors
                title_tag = result.find('h3', class_='gs_rt') or result.find('h3') or result.find('a')
                if not title_tag:
                    continue

                title_text = title_tag.get_text()
                title = title_text.replace('[HTML]', '').replace('[PDF]', '').replace('[CITATION]', '').strip()
                
                if not title or len(title) < 5:
                    continue

                # Extract paper ID for BibTeX fetching (from data-cid or link)
                paper_id = None
                parent_div = result.find_parent('div', {'data-cid': True})
                if parent_div:
                    paper_id = parent_div.get('data-cid')
                if not paper_id:
                    # Try to extract from "Cite" link
                    cite_link = result.find('a', {'class': 'gs_or_cit'}) or result.find('a', string=re.compile(r'Cite', re.I))
                    if cite_link and cite_link.get('href'):
                        cid_match = re.search(r'info:([^:]+):', cite_link.get('href', ''))
                        if cid_match:
                            paper_id = cid_match.group(1)

                # Extract author info from the author line
                author_div = result.find('div', class_='gs_a') or result.find('div', class_='gs_gray')
                authors = []
                all_authors = []  # Complete author list (will try to get from BibTeX)
                venue = 'Unknown'
                year = 0

                # Extract author info AND their profile links from the author line
                author_profiles = []  # List of {name, gs_id, profile_url}
                
                if author_div:
                    author_text = author_div.get_text()
                    # Format: "Author1, Author2, ... - Venue, Year - Publisher"
                    parts = author_text.split(' - ')
                    if len(parts) > 0:
                        author_str = parts[0].strip()
                        # Handle "..." which indicates truncated author list
                        if '…' in author_str or '...' in author_str:
                            # Truncated! We should get full list from BibTeX later
                            authors = [a.strip() for a in author_str.replace('…', '').replace('...', '').split(',') if a.strip()]
                        else:
                            authors = [a.strip() for a in author_str.split(',') if a.strip()]
                    if len(parts) > 1:
                        venue_year = parts[1].strip()
                        # Try to extract year
                        year_match = re.search(r'\b(19|20)\d{2}\b', venue_year)
                        if year_match:
                            year = int(year_match.group())
                        # Venue is everything before the year
                        if year_match:
                            venue = venue_year[:year_match.start()].strip().rstrip(',')
                        else:
                            venue = venue_year
                    
                    # Extract author profile links (key improvement!)
                    # Authors with GS profiles have links like /citations?user=AUTHOR_ID
                    for link in author_div.find_all('a', href=True):
                        href = link.get('href', '')
                        author_name = link.get_text(strip=True)
                        if '/citations?user=' in href:
                            # Extract Google Scholar author ID
                            gs_id_match = re.search(r'user=([^&]+)', href)
                            if gs_id_match:
                                gs_id = gs_id_match.group(1)
                                profile_url = f"https://scholar.google.com{href}" if href.startswith('/') else href
                                author_profiles.append({
                                    'name': author_name,
                                    'google_scholar_id': gs_id,
                                    'profile_url': profile_url
                                })
                
                # Extract "Cited by X" count from the result
                # This shows how many times THIS citing paper has been cited
                citation_count = 0
                cited_by_link = result.find('a', href=lambda h: h and 'cites=' in h)
                if cited_by_link:
                    cited_by_text = cited_by_link.get_text(strip=True)
                    # Format: "Cited by 175" or just "175"
                    cite_match = re.search(r'(\d+)', cited_by_text)
                    if cite_match:
                        citation_count = int(cite_match.group(1))
                
                # Extract paper URL (for linking)
                paper_url = ''
                title_link = title_tag.find('a', href=True) if title_tag else None
                if title_link:
                    paper_url = title_link.get('href', '')
                    if paper_url.startswith('/'):
                        paper_url = f"https://scholar.google.com{paper_url}"

                citing_papers.append({
                    'title': title,
                    'authors': authors if authors else ['Unknown'],
                    'author_profiles': author_profiles,  # Direct profile links from page
                    'paper_id': paper_id,  # For BibTeX fetching if needed
                    'venue': venue,
                    'year': year,
                    'citation_count': citation_count,  # How many times this paper is cited
                    'url': paper_url
                })

            except Exception as e:
                print(f"[Google Scholar] Warning: Error parsing citation: {e}")
                continue

        return citing_papers

    def _fetch_bibtex_authors(self, paper_id: str, driver) -> List[str]:
        """
        Fetch complete author list from BibTeX citation export.
        
        Google Scholar shows truncated author lists on the page (e.g., "A, B, C..."),
        but the BibTeX export has the COMPLETE list!
        
        Args:
            paper_id: Google Scholar paper ID (from data-cid)
            driver: Selenium WebDriver instance
            
        Returns:
            List of all author names
        """
        if not paper_id:
            return []
        
        try:
            import re
            # BibTeX URL format
            bibtex_url = f"https://scholar.googleusercontent.com/scholar.bib?q=info:{paper_id}:scholar.google.com/&output=citation&scisdr=&scisig=&scisf=4&ct=citation&cd=0"
            
            # Fetch BibTeX (quick request)
            driver.get(bibtex_url)
            time.sleep(0.5)  # Brief pause
            
            bibtex_content = driver.page_source
            
            # Parse author field from BibTeX
            # Format: author={LastName1, FirstName1 and LastName2, FirstName2 and ...}
            author_match = re.search(r'author\s*=\s*\{([^}]+)\}', bibtex_content, re.IGNORECASE)
            if author_match:
                author_str = author_match.group(1)
                # Split by " and " (BibTeX author separator)
                authors_raw = author_str.split(' and ')
                authors = []
                for author in authors_raw:
                    author = author.strip()
                    # Convert "LastName, FirstName" to "FirstName LastName"
                    if ',' in author:
                        parts = author.split(',', 1)
                        author = f"{parts[1].strip()} {parts[0].strip()}"
                    authors.append(author)
                return authors
            
        except Exception as e:
            # Silent fail - BibTeX is optional enhancement
            pass
        
        return []

    def get_citations_by_cites_id(self, cites_ids: List[str], limit: int = 100) -> List[Citation]:
        """
        Get citations using DIRECT cites_id access with PAGINATION - NO SEARCH NEEDED!
        
        This is the PREFERRED method when coming from "My Papers" because:
        - We already have the cites_id from the user's GS profile
        - No search = No CAPTCHA risk!
        - Much faster and more reliable
        - Supports pagination (10 results per page)
        
        Args:
            cites_ids: List of Google Scholar cites IDs (e.g., ['10513421991346554310', '17090356534793247477'])
            limit: Maximum citations to retrieve
            
        Returns:
            List of Citation objects
        """
        if not cites_ids:
            print("[Google Scholar] No cites_ids provided")
            return []
        
        # Build base citation URL
        cites_str = ','.join(cites_ids) if isinstance(cites_ids, list) else str(cites_ids)
        base_url = f"https://scholar.google.com/scholar?cites={cites_str}&hl=en"
        
        print(f"[Google Scholar] DIRECT citation access with pagination")
        print(f"[Google Scholar] Base URL: {base_url[:80]}...")
        
        try:
            driver = self._get_driver()
            if not driver:
                print("[Google Scholar] ❌ Could not get browser driver")
                return []
            
            citations = []
            page = 0
            max_pages = (limit // 10) + 1  # Each page has ~10 results
            
            while len(citations) < limit and page < max_pages:
                # Build URL with pagination (start=0, 10, 20, ...)
                start = page * 10
                if page == 0:
                    page_url = base_url
                else:
                    page_url = f"{base_url}&start={start}"
                
                print(f"[Google Scholar] Fetching page {page + 1} (start={start})...")
                
                driver.get(page_url)
                time.sleep(2)
                
                # Check for CAPTCHA on first page
                if page == 0:
                    self._wait_for_captcha(driver)
                
                # Parse citations from page
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                
                # Get citing papers from this page
                citing_papers = self._parse_citations_from_page(soup)
                
                if not citing_papers:
                    print(f"[Google Scholar] No more citations found on page {page + 1}")
                    break
                
                for paper in citing_papers:
                    if len(citations) >= limit:
                        break
                        
                    try:
                        authors = paper.get('authors', [])
                        if not authors and paper.get('author'):
                            authors = [a.strip() for a in paper.get('author', '').split(',')]
                        
                        # Check if author list was truncated (has "..." on page)
                        # If truncated, try to get full list from BibTeX
                        paper_id = paper.get('paper_id')
                        if paper_id and any('…' in str(a) or '...' in str(a) for a in authors):
                            bibtex_authors = self._fetch_bibtex_authors(paper_id, driver)
                            if bibtex_authors:
                                print(f"[Google Scholar] Got {len(bibtex_authors)} authors from BibTeX (was truncated on page)")
                                authors = bibtex_authors
                        
                        # Extract author info with GS profile links
                        # KEY: Use 'author_profiles' (from _parse_citations_from_page)
                        authors_with_ids = []
                        author_profiles = paper.get('author_profiles', [])
                        
                        # Build map of author name -> GS ID
                        # Some authors have GS profile links, others don't
                        author_gs_ids = {}
                        for profile in author_profiles:
                            author_gs_ids[profile['name']] = profile['google_scholar_id']
                        
                        # Create AuthorInfo with GS IDs for ALL authors
                        # Authors WITHOUT GS links will have empty author_id
                        # → They'll be looked up via cache/S2/paper search in analyzer
                        for name in authors:
                            if name and name != 'Unknown':
                                gs_id = author_gs_ids.get(name, '')
                                author_id = f"gs:{gs_id}" if gs_id else ''
                                from ..models import AuthorInfo
                                authors_with_ids.append(AuthorInfo(name=name, author_id=author_id))
                        
                        # Summary logging
                        gs_count = sum(1 for a in authors_with_ids if a.author_id.startswith('gs:'))
                        no_gs_count = len(authors_with_ids) - gs_count
                        if gs_count > 0 or no_gs_count > 0:
                            status = f"{gs_count} with GS profiles"
                            if no_gs_count > 0:
                                status += f", {no_gs_count} without (will use fallback)"
                            print(f"[Google Scholar] '{paper.get('title', '')[:35]}...': {status}")
                        
                        citation = Citation(
                            citing_paper_title=paper.get('title', 'Unknown'),
                            citing_authors=authors,
                            venue=paper.get('venue', 'Unknown'),
                            year=int(paper.get('year', 0)) if paper.get('year') else 0,
                            is_influential=False,
                            contexts=[],
                            intents=[],
                            url=paper.get('url', ''),
                            authors_with_ids=authors_with_ids,
                            citation_count=paper.get('citation_count', 0)  # How many times this paper is cited
                        )
                        citations.append(citation)
                    except Exception as e:
                        print(f"[Google Scholar] Warning parsing citation: {e}")
                        continue
                
                page += 1
                
                # Small delay between pages to avoid rate limiting
                if page < max_pages and len(citations) < limit:
                    time.sleep(1)
            
            print(f"[Google Scholar] ✓ Got {len(citations)} citations via DIRECT access ({page} pages)")
            return citations
            
        except Exception as e:
            print(f"[Google Scholar] ❌ Direct citation access failed: {e}")
            return []

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
            
            # If cites_id is None, try to extract from citedby_url
            if not cites_id:
                citedby_url = paper_data.get('citedby_url', '')
                if citedby_url and 'cites=' in citedby_url:
                    import re
                    match = re.search(r'cites=(\d+)', citedby_url)
                    if match:
                        cites_id = match.group(1)
                        print(f"[Google Scholar] ✓ Extracted cites_id from URL: {cites_id}")
            
            print(f"[Google Scholar] cites_id: {cites_id}")
        else:
            # Not in cache - this shouldn't happen if search_paper was called first
            # But handle it gracefully by treating paper_id as a title
            print(f"[Google Scholar] ⚠️  Paper not in cache, treating as title and searching...")
            paper_title = paper_id.replace('gs_', '')  # Strip prefix if present
            print(f"[Google Scholar] Searching for: {paper_title}")

            cites_id = None
            try:
                print(f"[Google Scholar] Adding rate limit delay...")
                time.sleep(random.uniform(2, 5))
                
                search_query = scholarly.search_pubs(paper_title)
                paper_result = next(search_query, None)

                if not paper_result:
                    # Try Selenium fallback
                    print("[Google Scholar] ⚠️ scholarly failed, trying Selenium fallback...")
                    selenium_result = self._search_paper_selenium(paper_title)
                    if selenium_result:
                        cites_id = selenium_result.get('cites_id')
                        if isinstance(cites_id, list) and len(cites_id) > 0:
                            cites_id = cites_id[0]
                        print(f"[Google Scholar] ✓ Found via Selenium, cites_id: {cites_id}")
                    else:
                        print("[Google Scholar] ❌ Paper not found in search")
                        return []
                else:
                    print(f"[Google Scholar] ✓ Paper found, filling details (timeout: 30s)...")
                    # Fill to get cites_id with timeout
                    filled = _timeout_call(scholarly.fill, args=(paper_result,), timeout=30, default=None)
                    if filled:
                        paper_result = filled
                    cites_id = paper_result.get('cites_id') if paper_result else None
                    
                    # If cites_id is None, try to extract it from citedby_url
                    # The URL looks like: /scholar?cites=6811164040269105362&...
                    if not cites_id:
                        citedby_url = paper_result.get('citedby_url', '')
                        if citedby_url and 'cites=' in citedby_url:
                            import re
                            match = re.search(r'cites=(\d+)', citedby_url)
                            if match:
                                cites_id = match.group(1)
                                print(f"[Google Scholar] ✓ Extracted cites_id from URL: {cites_id}")
                    
                    print(f"[Google Scholar] cites_id: {cites_id}")
            except Exception as e:
                print(f"[Google Scholar] ⚠️ scholarly error: {e}, trying Selenium fallback...")
                # Try Selenium fallback on any exception
                selenium_result = self._search_paper_selenium(paper_title)
                if selenium_result:
                    cites_id = selenium_result.get('cites_id')
                    if isinstance(cites_id, list) and len(cites_id) > 0:
                        cites_id = cites_id[0]
                    print(f"[Google Scholar] ✓ Found via Selenium, cites_id: {cites_id}")
                else:
                    print(f"[Google Scholar] ❌ Both scholarly and Selenium failed")
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
            
            # Wait for CAPTCHA (may restart browser in visible mode)
            new_driver = self._wait_for_captcha(driver)
            if new_driver:
                driver = new_driver

            soup = BeautifulSoup(driver.page_source, 'html.parser')
            page_text = soup.get_text().lower()

            # Check for blocking after CAPTCHA handling
            blocking_indicators = [
                'access denied',
                'forbidden',
                'unusual traffic',
                'solve this puzzle',
                'not a robot',
                'captcha',
                'verify you are human',
            ]
            
            if any(indicator in page_text for indicator in blocking_indicators):
                # Still blocked after CAPTCHA handling
                print(f'{Colors.RED}{Colors.BOLD}[Google Scholar] ❌ Still blocked after CAPTCHA handling.{Colors.RESET}')
                print(f'{Colors.YELLOW}[Google Scholar] Try running again - the tool will open a visible browser.{Colors.RESET}')
                return []

            # Parse citations from first page
            citing_papers = self._parse_citations_from_page(soup)
            print(f"[Google Scholar] Found {len(citing_papers)} citations on page 1")
            
            # Check if no citations found
            if len(citing_papers) == 0:
                # Check if page loaded correctly
                result_stats = soup.find('div', id='gs_ab_md')
                if result_stats:
                    stats_text = result_stats.get_text()
                    if 'About' in stats_text:
                        print(f"[Google Scholar] Page says: {stats_text[:80]}...")

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
                        new_driver = self._wait_for_captcha(driver)
                        if new_driver:
                            driver = new_driver

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
                    # Create AuthorInfo objects - NOW with GS IDs from profile links!
                    # Build a map of author name -> GS ID from extracted profiles
                    author_gs_ids = {}
                    author_profiles_data = paper.get('author_profiles', [])
                    for profile in author_profiles_data:
                        author_gs_ids[profile['name']] = profile['google_scholar_id']
                    
                    authors_with_ids = []
                    for name in paper['authors']:
                        if name and name != 'Unknown':
                            # Use GS ID if we extracted a profile link for this author
                            gs_id = author_gs_ids.get(name, '')
                            # Store GS ID with 'gs:' prefix to distinguish from S2 IDs
                            author_id = f"gs:{gs_id}" if gs_id else ''
                            authors_with_ids.append(AuthorInfo(name=name, author_id=author_id))
                    
                    citation = Citation(
                        citing_paper_title=paper['title'],
                        citing_authors=paper['authors'],
                        venue=paper['venue'],
                        year=paper['year'],
                        is_influential=False,  # Google Scholar doesn't provide this
                        contexts=[],  # Google Scholar doesn't provide citation contexts
                        intents=[],  # Google Scholar doesn't provide intents
                        authors_with_ids=authors_with_ids  # GS has no unique author IDs
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
            Author object with Google Scholar ID and profile data
        """
        print(f"[Google Scholar] Getting author: {author_name}")

        # Try browser-based scraping first (more reliable than scholarly)
        if self.use_selenium and SELENIUM_AVAILABLE:
            result = self._get_author_via_browser(author_name)
            if result:
                return result
        
        # Fallback to scholarly (often rate-limited)
        print(f"[Google Scholar] Trying scholarly library...")
        time.sleep(random.uniform(1, 2))

        try:
            search_query = scholarly.search_author(author_name)
            author = next(search_query, None)

            if not author:
                print(f"[Google Scholar] ⚠️ Author not found")
                return None

            # Fill complete author data with timeout
            filled_author = _timeout_call(scholarly.fill, args=(author,), timeout=30, default=None)
            
            # Check if fill worked (unfilled authors don't have hindex)
            if filled_author and filled_author.get('hindex') is not None:
                author = filled_author
                h_index = author.get('hindex', 0)
            else:
                print(f"[Google Scholar] ⚠️ Could not fill profile (rate limited?)")
                return None

            affiliation = author.get('affiliation', 'Unknown')
            gs_author_id = author.get('scholar_id', '')
            homepage = author.get('homepage', '')

            institution_type = self._get_institution_type(affiliation)

            print(f"[Google Scholar] ✓ Found: {author.get('name')} (h={h_index})")
            
            return Author(
                name=author.get('name', author_name),
                h_index=h_index,
                affiliation=affiliation,
                institution_type=institution_type,
                works_count=author.get('citedby', 0),
                citation_count=author.get('citedby', 0),
                google_scholar_id=gs_author_id,
                homepage=homepage,
                h_index_source='google_scholar'
            )

        except Exception as e:
            print(f"[Google Scholar] ⚠️ Error: {str(e)[:50]}")
            return None
    
    def _get_author_via_browser(self, author_name: str) -> Optional[Author]:
        """
        Get author info by directly visiting Google Scholar in browser.
        
        More reliable than scholarly.fill() because:
        - Single page load instead of multiple API calls
        - User can solve CAPTCHAs if needed
        - Less likely to be rate-limited
        
        NOTE: Google now requires login for /citations?view_op=search_authors
        So we use regular search and look for author links instead.
        """
        try:
            driver = self._get_driver()
            if not driver:
                return None
            
            # Use regular search (doesn't require login) and look for author
            # Format: search for author's papers and find their profile link
            search_url = f"https://scholar.google.com/scholar?q=author:{author_name.replace(' ', '+')}"
            driver.get(search_url)
            time.sleep(2)
            
            # Check for CAPTCHA or login redirect
            current_url = driver.current_url
            if 'accounts.google.com' in current_url or 'signin' in current_url:
                print(f"[Google Scholar] ⚠️ Login required, skipping browser lookup")
                return None
            
            if self._check_for_captcha(driver):
                return None
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Look for author profile link in search results
            # Author links look like: /citations?user=XXXXX
            import re
            gs_author_id = None
            profile_url = None
            
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                if '/citations?user=' in href:
                    match = re.search(r'user=([^&]+)', href)
                    if match:
                        gs_author_id = match.group(1)
                        if href.startswith('/'):
                            profile_url = f"https://scholar.google.com{href}"
                        else:
                            profile_url = href
                        break
            
            if not profile_url:
                print(f"[Google Scholar] ⚠️ No author profile found in search results")
                return None
            
            # Visit author profile directly
            driver.get(profile_url)
            time.sleep(2)
            
            # Check for login redirect again
            current_url = driver.current_url
            if 'accounts.google.com' in current_url or 'signin' in current_url:
                print(f"[Google Scholar] ⚠️ Profile requires login, skipping")
                return None
            
            if self._check_for_captcha(driver):
                return None
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Extract author name
            name_elem = soup.find('div', id='gsc_prf_in')
            name = name_elem.get_text(strip=True) if name_elem else author_name
            
            # Extract affiliation
            affiliation_elem = soup.find('div', class_='gsc_prf_il')
            affiliation = affiliation_elem.get_text(strip=True) if affiliation_elem else 'Unknown'
            
            # Extract h-index from the stats table
            h_index = 0
            stats_table = soup.find('table', id='gsc_rsb_st')
            if stats_table:
                rows = stats_table.find_all('tr')
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 2:
                        label = cells[0].get_text(strip=True).lower()
                        if 'h-index' in label:
                            try:
                                h_index = int(cells[1].get_text(strip=True))
                            except ValueError:
                                pass
                            break
            
            # Extract citation count
            citation_count = 0
            if stats_table:
                rows = stats_table.find_all('tr')
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 2:
                        label = cells[0].get_text(strip=True).lower()
                        if 'citations' in label:
                            try:
                                citation_count = int(cells[1].get_text(strip=True))
                            except ValueError:
                                pass
                            break
            
            # Extract homepage
            homepage = ''
            homepage_elem = soup.find('a', id='gsc_prf_ivh')
            if homepage_elem:
                homepage = homepage_elem.get('href', '')
            
            institution_type = self._get_institution_type(affiliation)
            
            print(f"[Google Scholar] ✓ Browser found: {name} (h={h_index}, {affiliation[:30]}...)")
            
            return Author(
                name=name,
                h_index=h_index,
                affiliation=affiliation,
                institution_type=institution_type,
                works_count=0,
                citation_count=citation_count,
                google_scholar_id=gs_author_id,
                homepage=homepage,
                h_index_source='google_scholar'
            )
            
        except Exception as e:
            print(f"[Google Scholar] ⚠️ Browser error: {str(e)[:50]}")
            return None
    
    def _check_for_captcha(self, driver, check_data_presence: bool = False) -> bool:
        """
        Check if page has CAPTCHA or login redirect and handle it.
        
        Args:
            driver: Selenium WebDriver
            check_data_presence: If True, first check if useful data is already on page.
                                 If data exists, skip CAPTCHA check (false positive).
        
        Returns:
            True if blocked (can't proceed), False if OK to proceed
        """
        # Check for login redirect first
        current_url = driver.current_url
        if 'accounts.google.com' in current_url or 'signin' in current_url:
            print("[Google Scholar] ⚠️ Login required - Google Scholar now requires sign-in for some features")
            return True
        
        # If check_data_presence is True, check if we already have useful data
        # This avoids false positives (page might have 'robot' in footer scripts)
        if check_data_presence:
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            # Check if author profile data exists
            name_elem = soup.find('div', id='gsc_prf_in')
            stats_table = soup.find('table', id='gsc_rsb_st')
            # Check if citation results exist
            results = soup.find_all('div', class_='gs_ri')
            
            if name_elem or stats_table or results:
                # We have data! No real CAPTCHA block
                return False
        
        page_text = driver.page_source.lower()
        
        # More specific CAPTCHA indicators (avoid false positives from script tags)
        captcha_indicators = [
            'unusual traffic from your computer',
            'please show you\'re not a robot',
            'complete the captcha',
            'verify you are a human',
            'sorry, we can\'t verify that you\'re not a robot'
        ]
        
        is_captcha = any(indicator in page_text for indicator in captcha_indicators)
        
        if is_captcha:
            print("\n" + "="*60)
            print("⚠️  CAPTCHA DETECTED!")
            print("Please solve it in the browser window...")
            print("="*60)
            
            # In non-interactive mode, just fail
            import sys
            if not sys.stdin.isatty():
                print(f"{Colors.RED}[Google Scholar] ⚠️ Non-interactive mode, cannot solve CAPTCHA{Colors.RESET}")
                return True
            
            input("Press Enter after solving the CAPTCHA...")
            time.sleep(2)
            return False
        return False
    
    def _get_institution_type(self, affiliation: str) -> str:
        """Determine institution type from affiliation string"""
        if not affiliation or affiliation == 'Unknown':
            return 'other'
        
        aff_lower = affiliation.lower()
        if any(word in aff_lower for word in ['university', 'college', 'institute', 'school']):
            return 'education'
        elif any(word in aff_lower for word in ['google', 'microsoft', 'meta', 'amazon', 'ibm', 'apple', 'nvidia']):
            return 'company'
        elif any(word in aff_lower for word in ['government', 'national', 'ministry', 'federal']):
            return 'government'
        return 'other'

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

    def get_authors_by_gs_ids_batch(self, gs_ids: List[str]) -> Dict[str, Author]:
        """
        Batch fetch multiple author profiles efficiently.
        
        Instead of opening/closing browser for each author, this method
        keeps the browser open and fetches all profiles in sequence.
        Much faster than individual calls!
        
        Args:
            gs_ids: List of Google Scholar author IDs
            
        Returns:
            Dict mapping gs_id -> Author object
        """
        if not gs_ids:
            return {}
        
        results = {}
        unique_ids = list(set(gs_ids))  # Deduplicate
        
        print(f"[Google Scholar] Batch fetching {len(unique_ids)} author profiles...")
        
        try:
            driver = self._get_driver()
            if not driver:
                return {}
            
            for i, gs_id in enumerate(unique_ids):
                try:
                    # Progress indicator
                    if len(unique_ids) > 3:
                        print(f"[Google Scholar] Fetching profile {i+1}/{len(unique_ids)}: {gs_id[:8]}...")
                    
                    # Go directly to author profile page
                    profile_url = f"https://scholar.google.com/citations?user={gs_id}"
                    driver.get(profile_url)
                    time.sleep(1.5)  # Brief pause between profiles
                    
                    # Check for login/CAPTCHA
                    current_url = driver.current_url
                    if 'accounts.google.com' in current_url or 'signin' in current_url:
                        continue
                    
                    if self._check_for_captcha(driver, check_data_presence=True):
                        continue
                    
                    soup = BeautifulSoup(driver.page_source, 'html.parser')
                    
                    # Extract author info (same as get_author_by_gs_id)
                    name_elem = soup.find('div', id='gsc_prf_in')
                    name = name_elem.get_text(strip=True) if name_elem else 'Unknown'
                    
                    affiliation_elem = soup.find('div', class_='gsc_prf_il')
                    affiliation = affiliation_elem.get_text(strip=True) if affiliation_elem else 'Unknown'
                    
                    h_index = 0
                    citation_count = 0  # Total citations for this author
                    stats_table = soup.find('table', id='gsc_rsb_st')
                    if stats_table:
                        for row in stats_table.find_all('tr'):
                            cells = row.find_all('td')
                            if len(cells) >= 2:
                                label = cells[0].get_text(strip=True).lower()
                                if 'h-index' in label:
                                    try:
                                        h_index = int(cells[1].get_text(strip=True))
                                    except ValueError:
                                        pass
                                elif 'citations' in label:
                                    try:
                                        citation_count = int(cells[1].get_text(strip=True))
                                    except ValueError:
                                        pass
                    
                    homepage = None
                    homepage_link = soup.find('a', class_='gsc_prf_ila')
                    if homepage_link:
                        homepage = homepage_link.get('href', '')
                    
                    institution_type = self._get_institution_type(affiliation)
                    
                    results[gs_id] = Author(
                        name=name,
                        h_index=h_index,
                        affiliation=affiliation,
                        institution_type=institution_type,
                        works_count=0,
                        citation_count=citation_count,  # Now properly extracted!
                        google_scholar_id=gs_id,
                        homepage=homepage or '',
                        h_index_source='google_scholar'
                    )
                    
                except Exception as e:
                    print(f"[Google Scholar] Warning: Error fetching {gs_id}: {e}")
                    continue
            
            print(f"[Google Scholar] ✓ Batch fetched {len(results)}/{len(unique_ids)} profiles")
            
        except Exception as e:
            print(f"[Google Scholar] Error in batch fetch: {e}")
        
        return results

    def get_author_by_gs_id(self, gs_id: str) -> Optional[Author]:
        """
        Get author info directly from their Google Scholar profile page.
        
        This is more reliable than scholarly.fill() because:
        - Single page load (no multiple hidden requests)
        - User can solve CAPTCHAs if needed
        - Less likely to timeout
        
        Args:
            gs_id: Google Scholar author ID (e.g., 'waVL0PgAAAAJ')
            
        Returns:
            Author object with h-index, affiliation, etc.
        """
        print(f"[Google Scholar] Getting author profile: {gs_id}")
        
        try:
            driver = self._get_driver()
            if not driver:
                return None
            
            # Go directly to author profile page - no search needed!
            profile_url = f"https://scholar.google.com/citations?user={gs_id}"
            driver.get(profile_url)
            time.sleep(2)
            
            # Check for login redirect
            current_url = driver.current_url
            if 'accounts.google.com' in current_url or 'signin' in current_url:
                print(f"[Google Scholar] ⚠️ Profile requires login")
                return None
            
            # Use check_data_presence=True to avoid false CAPTCHA prompts
            # when profile data is already visible
            if self._check_for_captcha(driver, check_data_presence=True):
                return None
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Extract author name
            name_elem = soup.find('div', id='gsc_prf_in')
            name = name_elem.get_text(strip=True) if name_elem else 'Unknown'
            
            # Extract affiliation
            affiliation_elem = soup.find('div', class_='gsc_prf_il')
            affiliation = affiliation_elem.get_text(strip=True) if affiliation_elem else 'Unknown'
            
            # Extract h-index from stats table
            h_index = 0
            stats_table = soup.find('table', id='gsc_rsb_st')
            if stats_table:
                rows = stats_table.find_all('tr')
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 2:
                        label = cells[0].get_text(strip=True).lower()
                        if 'h-index' in label:
                            try:
                                h_index = int(cells[1].get_text(strip=True))
                            except ValueError:
                                pass
                            break
            
            # Extract homepage if available
            homepage = None
            homepage_link = soup.find('a', class_='gsc_prf_ila')
            if homepage_link:
                homepage = homepage_link.get('href', '')
            
            institution_type = self._get_institution_type(affiliation)
            
            print(f"[Google Scholar] ✓ Got profile: {name} (h={h_index}, {affiliation[:30]}...)")
            
            return Author(
                name=name,
                h_index=h_index,
                affiliation=affiliation,
                institution_type=institution_type,
                works_count=0,
                citation_count=0,
                google_scholar_id=gs_id,
                homepage=homepage,
                h_index_source='google_scholar'
            )
            
        except Exception as e:
            print(f"[Google Scholar] ⚠️ Error getting author profile: {str(e)[:50]}")
            return None

    def get_author_by_id(self, author_id: str) -> Optional[Dict]:
        """
        Get author information by Google Scholar ID (legacy method)

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

            # Fill complete author data with timeout
            filled = _timeout_call(
                scholarly.fill, 
                args=(author,), 
                kwargs={'sections': ['basics', 'publications']},
                timeout=60,  # Longer timeout for full author data
                default=author
            )
            return filled if filled else author

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
                
                # Fill the publication to get complete data including cites_id (with timeout)
                try:
                    filled_pub = _timeout_call(scholarly.fill, args=(pub,), timeout=20, default=pub)
                    if not filled_pub:
                        filled_pub = pub
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
            except Exception:
                pass  # Ignore errors during cleanup
            self.driver = None

    def __del__(self):
        """Cleanup when object is deleted"""
        self.close()


def get_google_scholar_client(
    use_proxy: bool = False, 
    use_selenium: bool = True,
    headless: bool = False,
    scraper_api_key: str = None
) -> GoogleScholarClient:
    """
    Get a configured Google Scholar client

    Args:
        use_proxy: Use free proxies (slower but helps avoid blocks)
        use_selenium: Use Selenium for citation scraping (required for accurate results)
        headless: Run browser in headless mode (faster but more likely to be blocked)
                 Default is False - visible browser allows user to solve CAPTCHAs
        scraper_api_key: ScraperAPI key for reliable scraping (recommended)
                        Get key at: https://www.scraperapi.com/

    Returns:
        Configured GoogleScholarClient
        
    Example:
        # Option 1: Visible browser (free, may need CAPTCHA solving)
        client = get_google_scholar_client()
        
        # Option 2: ScraperAPI (paid, most reliable)
        client = get_google_scholar_client(scraper_api_key="your_key")
        
        # Option 3: Free proxies (free but unreliable)
        client = get_google_scholar_client(use_proxy=True)
    """
    return GoogleScholarClient(
        use_proxy=use_proxy, 
        use_selenium=use_selenium, 
        headless=headless,
        scraper_api_key=scraper_api_key
    )
