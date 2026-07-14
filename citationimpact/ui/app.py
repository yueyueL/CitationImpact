"""
Main application entry point for CitationImpact Terminal UI.

This is the simplified TerminalUI that delegates to specialized modules.
"""
import sys
from typing import Dict, Any
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.markdown import Markdown
from rich.theme import Theme

from citationimpact import analyze_paper_impact
from citationimpact.config import ConfigManager

from .settings import SettingsManager
from .analysis_view import AnalysisView
from .components.prompts import looks_like_author_id


def _display_value(*values, default: str = 'N/A') -> str:
    """
    Return the first non-None value as a string, else the default.

    dict.get() returns None (not the fallback) for present-but-null keys
    (e.g. Semantic Scholar's "year": null), so chained .get() defaults
    would render the literal string 'None' in tables.
    """
    for value in values:
        if value is not None:
            return str(value)
    return default


class TerminalUI:
    """Interactive terminal UI for CitationImpact analysis."""
    
    def __init__(self):
        """Initialize the terminal UI."""
        custom_theme = Theme({
            "info": "cyan",
            "warning": "yellow",
            "error": "bold red",
            "success": "bold green",
            "highlight": "bold magenta",
            "title": "bold blue"
        })

        self.console = Console(theme=custom_theme)
        
        # Load configuration
        self.config_manager = ConfigManager()
        self.config = self.config_manager.get_all()
        self.config_dir = self.config_manager.get_config_path()
        
        # Initialize sub-modules
        self.settings_manager = SettingsManager(self.console, self.config_manager, self.config)
        self.analysis_view = AnalysisView(self.console, self.config)

        # Shared API client (browser stays open for entire session!)
        self._shared_client = None
        # Data source the shared client was created for (so a mid-session
        # data_source change doesn't silently reuse a client of the wrong type)
        self._shared_client_source = None

    def _cleanup(self):
        """Clean up resources (close browser) before exit."""
        if self._shared_client and hasattr(self._shared_client, 'close'):
            try:
                self._shared_client.close()
            except Exception:
                pass
        self._shared_client = None
        self._shared_client_source = None

    def _get_reusable_client(self):
        """
        Return the shared client if it matches the current data source.

        If the user changed data_source in Settings since the client was
        created, close and discard the stale client so the analyzer builds
        a fresh one of the right type.
        """
        if (self._shared_client is not None
                and self._shared_client_source != self.config.get('data_source')):
            self._cleanup()
        return self._shared_client

    def clear_screen(self):
        """Clear the terminal screen."""
        self.console.clear()

    def show_header(self):
        """Display the application header."""
        header = """
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║              📚 CITATION IMPACT ANALYZER 📚                   ║
║                                                               ║
║        Demonstrate the Significance of Your Research         ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
        """
        self.console.print(header, style="bold cyan", justify="center")

    def show_main_menu(self) -> str:
        """Display main menu and get user choice."""
        self.console.print("\n[title]MAIN MENU[/title]", justify="center")
        self.console.print("─" * 60, style="dim")
        
        # Check if user has set their profile IDs
        has_gs_id = bool(self.config.get('default_google_scholar_author_id'))
        has_s2_id = bool(self.config.get('default_semantic_scholar_author_id'))
        
        if has_gs_id or has_s2_id:
            profile_status = "[success]✓ Profile configured[/success]"
        else:
            profile_status = "[warning]⚠ Set your IDs in Settings for best experience[/warning]"
        
        self.console.print(f"  {profile_status}\n")

        menu_items = [
            ("1", "📚 My Papers", "Analyze YOUR papers (uses saved profile - fastest!)"),
            ("2", "🔍 Search Any Paper", "Search and analyze any paper by title"),
            ("3", "👤 Browse Other Authors", "Browse papers by another author"),
            ("4", "⚙️  Settings", "Configure your profile IDs and preferences"),
            ("5", "📖 Help", "Learn how to use the analyzer"),
            ("6", "❌ Exit", "Exit the application")
        ]

        for key, title, desc in menu_items:
            self.console.print(f"  [highlight]{key}.[/highlight] {title}")
            self.console.print(f"     [dim]{desc}[/dim]")
            self.console.print()

        choice = Prompt.ask(
            "[bold]Select an option[/bold]",
            choices=["1", "2", "3", "4", "5", "6"],
            default="1"
        )
        return choice

    def my_papers(self):
        """Browse YOUR papers using saved profile - no searching needed!"""
        self.clear_screen()
        self.console.print(Panel(
            "[title]📚 MY PAPERS[/title]",
            expand=False
        ))
        
        gs_id = self.config.get('default_google_scholar_author_id')
        s2_id = self.config.get('default_semantic_scholar_author_id')
        
        if not gs_id and not s2_id:
            self.console.print("\n[warning]⚠ No profile IDs configured![/warning]")
            self.console.print("\n[info]To use this feature, set your IDs in Settings:[/info]")
            self.console.print("  • Google Scholar ID (from your profile URL)")
            self.console.print("  • Semantic Scholar ID (from your profile URL)")
            self.console.print("\n[dim]Example: scholar.google.com/citations?user=[bold]waVL0PgAAAAJ[/bold][/dim]")
            
            if Confirm.ask("\n[bold]Go to Settings now?[/bold]", default=True):
                self.manage_settings()
            return
        
        # Show profile info
        self.console.print("\n[success]✓ Your Profile[/success]")
        if gs_id:
            gs_url = f"https://scholar.google.com/citations?user={gs_id}"
            self.console.print(f"  Google Scholar: [link={gs_url}]{gs_id}[/link]")
        if s2_id:
            s2_url = f"https://www.semanticscholar.org/author/{s2_id}"
            self.console.print(f"  Semantic Scholar: [link={s2_url}]{s2_id}[/link]")
        
        # Check cache first!
        from citationimpact.cache import get_my_publications_cache
        pub_cache = get_my_publications_cache()
        
        author_id = gs_id or s2_id
        data_source = 'google_scholar' if gs_id else 'api'
        
        publications = pub_cache.get(author_id, data_source)
        
        if publications:
            self.console.print("\n[success]✓ Loaded from cache (instant!)[/success]")
            self.console.print(f"[dim]Found {len(publications)} papers. Press 'r' to refresh from profile.[/dim]")
            self._display_my_publications(publications, gs_id, s2_id, from_cache=True)
            return
        
        # Not in cache - fetch from source
        self.console.print("\n[info]Fetching from profile (will be cached for future use)...[/info]")
        
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console
            ) as progress:
                task = progress.add_task("Fetching your publications...", total=None)
                
                publications = []
                author_info = {}
                
                # Prefer Google Scholar for comprehensive data
                if gs_id:
                    from citationimpact.clients.google_scholar import get_google_scholar_client
                    # Reuse the shared client when it is already a Google
                    # Scholar client; otherwise create a temporary one and
                    # close it once the fetch is done (don't leak it)
                    client = (
                        self._shared_client
                        if self._shared_client_source == 'google_scholar'
                        else None
                    )
                    local_client = None
                    if client is None:
                        client = local_client = get_google_scholar_client(
                            use_selenium=True,
                            headless=False,
                            scraper_api_key=self.config.get('scraper_api_key')
                        )
                    try:
                        publications = client.get_author_publications(gs_id, limit=50)
                    finally:
                        if local_client is not None:
                            local_client.close()
                    # Get author info for cache
                    author_info = {'scholar_id': gs_id}
                elif s2_id:
                    from citationimpact.clients import get_api_client
                    client = get_api_client(
                        email=self.config.get('email'),
                        semantic_scholar_key=self.config.get('api_key')
                    )
                    publications = client.get_author_publications(s2_id, limit=50)
                    author_info = {'semantic_scholar_id': s2_id}
                
                progress.remove_task(task)
            
            if not publications:
                self.console.print("[warning]No publications found[/warning]")
                Prompt.ask("\nPress Enter to continue")
                return
            
            # Save to cache
            author_info['publications'] = publications
            pub_cache.set(author_id, publications, data_source, author_info)
            
            # Display papers with direct links
            self._display_my_publications(publications, gs_id, s2_id)
            
        except Exception as e:
            self.console.print(f"\n[error]Error: {str(e)}[/error]")
            import traceback
            traceback.print_exc()
            Prompt.ask("\nPress Enter to continue")
    
    def _display_my_publications(self, publications: list, gs_id: str = None, s2_id: str = None, from_cache: bool = False):
        """Display YOUR publications with citation links."""
        from rich.table import Table
        from rich import box
        from citationimpact.cache import get_result_cache
        
        self.clear_screen()
        
        # Get result cache to check which papers are already analyzed
        result_cache = get_result_cache()
        
        cache_note = " [dim](cached)[/dim]" if from_cache else ""
        self.console.print(Panel(
            f"[title]📚 YOUR PUBLICATIONS[/title]{cache_note}\n[dim]Select a paper to analyze its citation impact[/dim]",
            expand=False
        ))
        
        table = Table(box=box.ROUNDED, header_style="bold cyan")
        table.add_column("#", style="bold magenta", width=4)
        table.add_column("", width=2)  # Status icon column
        table.add_column("Title", style="bold", max_width=48)
        table.add_column("Year", justify="center", style="yellow", width=6)
        table.add_column("Citations", justify="right", style="green", width=10)
        table.add_column("Venue", style="dim", max_width=25)
        
        analyzed_count = 0
        for idx, pub in enumerate(publications[:20], 1):
            if isinstance(pub, dict):
                # Handle nested bib structure from Google Scholar
                bib = pub.get('bib', {})
                full_title = bib.get('title', pub.get('title', 'Unknown'))
                title = full_title[:48]
                year = _display_value(bib.get('pub_year'), pub.get('year'))
                citations = _display_value(pub.get('num_citations'), pub.get('citations'), pub.get('citationCount'))
                venue_raw = bib.get('citation', pub.get('venue', ''))
                venue = venue_raw[:25] if venue_raw else 'N/A'
            else:
                full_title = getattr(pub, 'title', 'Unknown')
                title = full_title[:48]
                year = _display_value(getattr(pub, 'year', None))
                citations = _display_value(getattr(pub, 'citationCount', None))
                venue = (getattr(pub, 'venue', 'N/A') or 'N/A')[:25]

            # Check if this paper has cached analysis results (using the
            # user's actual settings, not hardcoded defaults)
            is_analyzed = result_cache.has_cached_result(
                full_title,
                params={
                    'h_index_threshold': self.config['h_index_threshold'],
                    'max_citations': self.config['max_citations'],
                    'data_source': self.config['data_source'],
                }
            )
            status_icon = "[green]✓[/green]" if is_analyzed else "[dim]○[/dim]"
            if is_analyzed:
                analyzed_count += 1
            
            table.add_row(str(idx), status_icon, title, year, citations, venue)
        
        self.console.print()
        self.console.print(table)
        
        # Show legend and stats
        self.console.print(f"\n[dim]Legend: [green]✓[/green] = Analysis cached  [dim]○[/dim] = Not analyzed yet[/dim]")
        if analyzed_count > 0:
            self.console.print(f"[dim]{analyzed_count}/{min(20, len(publications))} papers have cached analysis[/dim]")
        
        if len(publications) > 20:
            self.console.print(f"[dim]Showing 20 of {len(publications)} publications[/dim]")
        
        self.console.print("\n[info]Enter a number to analyze that paper's citations[/info]")
        self.console.print("[dim]  [r] = Refresh from source  |  [b] = Back to menu[/dim]")
        
        choice = Prompt.ask("[bold]Select paper[/bold]", default="b")
        
        if choice.lower() == 'b':
            return
        
        if choice.lower() == 'r':
            # Refresh - clear cache and reload from profile
            from citationimpact.cache import get_my_publications_cache
            pub_cache = get_my_publications_cache()
            author_id = gs_id or s2_id
            data_source = 'google_scholar' if gs_id else 'api'
            
            # Clear the cache first
            pub_cache.clear(author_id, data_source)
            self.console.print("\n[info]Refreshing from profile...[/info]")
            self.my_papers()  # Re-run - will fetch fresh
            return
        
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(publications):
                pub = publications[idx]
                if isinstance(pub, dict):
                    # Handle nested bib structure from Google Scholar
                    bib = pub.get('bib', {})
                    paper_title = bib.get('title', pub.get('title', ''))
                    # Only use S2 paper IDs, not GS internal IDs (which look like gs_xxx)
                    paper_id = pub.get('paperId', '')
                    if not paper_id or paper_id.startswith('gs_'):
                        paper_id = ''  # Clear invalid IDs
                    # For Google Scholar publications
                    author_pub_id = pub.get('author_pub_id', '')
                    cites_id = pub.get('cites_id', [])
                else:
                    paper_title = getattr(pub, 'title', '')
                    paper_id = getattr(pub, 'paperId', '')
                    author_pub_id = getattr(pub, 'author_pub_id', '')
                    cites_id = getattr(pub, 'cites_id', [])
                
                self._analyze_my_paper(paper_title, paper_id, gs_id, author_pub_id, cites_id)
            else:
                self.console.print("[error]Invalid selection[/error]")
                Prompt.ask("\nPress Enter to continue")
        except ValueError:
            self.console.print("[error]Invalid input[/error]")
            Prompt.ask("\nPress Enter to continue")
    
    def _analyze_my_paper(self, paper_title: str, paper_id: str, gs_id: str = None, 
                          author_pub_id: str = None, cites_id: list = None):
        """
        Analyze YOUR paper's citations using direct access.
        
        Strategy (NO Google Scholar search needed!):
        1. Use Semantic Scholar API to find paper (API = no CAPTCHA)
        2. Use direct GS citation URL (cites_id) to get citing papers
        3. Combine data from both sources
        """
        self.console.print(f"\n[info]Analyzing: {paper_title[:50]}...[/info]")
        
        # Show direct citation URL if available
        gs_citation_url = None
        if cites_id:
            cites_str = ','.join(cites_id) if isinstance(cites_id, list) else cites_id
            gs_citation_url = f"https://scholar.google.com/scholar?cites={cites_str}"
            self.console.print(f"[dim]GS Citations: {gs_citation_url}[/dim]")
        
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console
            ) as progress:
                task = progress.add_task("Analyzing paper...", total=None)
                
                # Use Semantic Scholar API to search by title
                # S2 API has no CAPTCHA issues - it's a proper API!
                result = analyze_paper_impact(
                    paper_title=paper_title,  # Always use title for S2 API search
                    h_index_threshold=self.config['h_index_threshold'],
                    max_citations=self.config['max_citations'],
                    data_source=self.config['data_source'],
                    email=self.config['email'],
                    semantic_scholar_key=self.config['api_key'],
                    scraper_api_key=self.config.get('scraper_api_key'),
                    # Pass GS cites_id for DIRECT citation access (no search!)
                    gs_cites_id=cites_id,
                    # Reuse existing client (browser stays open!)
                    existing_client=self._get_reusable_client()
                )

                # Store client for reuse (browser stays open for session)
                if result.get('_client'):
                    self._shared_client = result.pop('_client')
                    self._shared_client_source = self.config['data_source']
                
                progress.remove_task(task)
            
            self.analysis_view.display_results(result)
            
        except Exception as e:
            self.console.print(f"\n[error]Error: {str(e)}[/error]")
            import traceback
            traceback.print_exc()
        
        Prompt.ask("\nPress Enter to continue")

    def analyze_paper(self):
        """Search and analyze any paper by title."""
        self.clear_screen()
        self.console.print(Panel(
            "[title]🔍 SEARCH ANY PAPER[/title]",
            expand=False
        ))

        self.console.print("\n[info]Enter the paper title or Semantic Scholar ID:[/info]")
        self.console.print("[dim]Tip: For exact match, use the S2 paper ID from the URL[/dim]")
        self.console.print("[dim]     e.g., semanticscholar.org/paper/TITLE/[bold]7883f26b62d3043a40bc29b974c54c3e4163a239[/bold][/dim]\n")

        paper_title = Prompt.ask("[bold]Paper title or ID[/bold]")

        if not paper_title.strip():
            self.console.print("[error]Error: Paper title cannot be empty[/error]")
            Prompt.ask("\nPress Enter to continue")
            return

        # Confirm settings
        self.console.print("\n[info]Analysis Settings:[/info]")
        self.console.print(f"  • H-Index Threshold: [highlight]{self.config['h_index_threshold']}[/highlight]")
        self.console.print(f"  • Max Citations: [highlight]{self.config['max_citations']}[/highlight]")
        self.console.print(f"  • Data Source: [highlight]{self.config['data_source']}[/highlight]")

        if not Confirm.ask("\n[bold]Proceed with analysis?[/bold]", default=True):
            return

        self.console.print("\n[info]Starting analysis...[/info]")

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console
            ) as progress:
                task = progress.add_task(
                    f"Analyzing '{paper_title[:50]}...'",
                    total=None
                )

                result = analyze_paper_impact(
                    paper_title=paper_title,
                    h_index_threshold=self.config['h_index_threshold'],
                    max_citations=self.config['max_citations'],
                    data_source=self.config['data_source'],
                    email=self.config['email'],
                    semantic_scholar_key=self.config['api_key'],
                    scraper_api_key=self.config.get('scraper_api_key'),
                    existing_client=self._get_reusable_client()  # Reuse browser session
                )

                # Store client for reuse
                if result.get('_client'):
                    self._shared_client = result.pop('_client')
                    self._shared_client_source = self.config['data_source']

                progress.remove_task(task)

            self.analysis_view.display_results(result)

        except Exception as e:
            self.console.print(f"\n[error]Error during analysis: {str(e)}[/error]")

        Prompt.ask("\nPress Enter to continue")

    def browse_author_papers(self):
        """Browse papers by author and select one to analyze."""
        self.clear_screen()
        self.console.print(Panel(
            "[title]👤 BROWSE AUTHOR PAPERS[/title]",
            expand=False
        ))

        data_source = self.config.get('data_source', 'api')

        self.console.print("\n[info]Enter author information:[/info]")
        self.console.print("[dim]You can enter:[/dim]")

        if data_source == 'google_scholar':
            self.console.print("[dim]  • Author name (e.g., 'Geoffrey Hinton')[/dim]")
            self.console.print("[dim]  • Google Scholar ID (e.g., 'waVL0PgAAAAJ')[/dim]")
            self.console.print(f"\n[warning]Note: Using Google Scholar (slow, may encounter CAPTCHAs)[/warning]")
        else:
            self.console.print("[dim]  • Author name (e.g., 'Geoffrey Hinton')[/dim]")
            self.console.print("[dim]  • Semantic Scholar author ID (e.g., '1745629')[/dim]")

        self.console.print()
        default_author_id = (
            self.config.get('default_google_scholar_author_id')
            if data_source == 'google_scholar'
            else self.config.get('default_semantic_scholar_author_id')
        )
        prompt_kwargs = {}
        if default_author_id:
            self.console.print(f"[dim]Press Enter to use saved ID: {default_author_id}[/dim]")
            prompt_kwargs['default'] = default_author_id
        author_input = Prompt.ask("[bold]Author name or ID[/bold]", **prompt_kwargs).strip()

        if not author_input:
            if default_author_id:
                author_input = default_author_id
            else:
                self.console.print("[error]Error: Author name or ID cannot be empty[/error]")
                Prompt.ask("\nPress Enter to continue")
                return

        is_author_id = looks_like_author_id(author_input, data_source)

        # Name entered in API mode → disambiguate same-named authors up front
        # so we fetch the RIGHT person's publications by unique ID, not the
        # first name-search hit (which may be a different same-named author)
        selected_author_id = None
        if not is_author_id and data_source != 'google_scholar':
            selected_author_id = self._select_author_candidate(author_input)

        self.console.print(f"\n[info]Fetching papers for {'ID' if is_author_id else 'author'}: {author_input}...[/info]")

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console
            ) as progress:
                task = progress.add_task("Fetching author publications...", total=None)

                if data_source == 'google_scholar':
                    from citationimpact.clients.google_scholar import get_google_scholar_client
                    # Reuse the shared browser session when possible; otherwise
                    # create one and retain it so the follow-up analysis reuses
                    # the same browser instead of launching a second one
                    client = self._get_reusable_client()
                    if client is None:
                        client = get_google_scholar_client(
                            use_selenium=True,
                            headless=False,
                            scraper_api_key=self.config.get('scraper_api_key')
                        )
                        self._shared_client = client
                        self._shared_client_source = data_source

                    if is_author_id:
                        publications = client.get_author_publications(author_input, limit=50)
                    else:
                        author_data = client.get_author(author_input)
                        if author_data and hasattr(author_data, 'google_scholar_id'):
                            gs_id = author_data.google_scholar_id
                            if gs_id:
                                publications = client.get_author_publications(gs_id, limit=50)
                            else:
                                publications = []
                        else:
                            publications = []
                else:
                    from citationimpact.clients import get_api_client
                    client = get_api_client(
                        email=self.config.get('email'),
                        semantic_scholar_key=self.config.get('api_key')
                    )

                    if is_author_id:
                        publications = client.get_author_publications(author_input, limit=50)
                    elif selected_author_id:
                        # Unique ID chosen via the candidate picker above
                        publications = client.get_author_publications(selected_author_id, limit=50)
                    else:
                        # Resolve the name to a Semantic Scholar author ID
                        # (get_author() never populates semantic_scholar_id)
                        resolved_id = client.search_author(author_input)
                        if resolved_id:
                            publications = client.get_author_publications(resolved_id, limit=50)
                        else:
                            publications = []

                progress.remove_task(task)

            if not publications:
                self.console.print("[warning]No publications found for this author[/warning]")
                Prompt.ask("\nPress Enter to continue")
                return

            # Display publications
            self._display_publications(publications, author_input)

        except Exception as e:
            self.console.print(f"\n[error]Error fetching publications: {str(e)}[/error]")
            Prompt.ask("\nPress Enter to continue")

    def _select_author_candidate(self, author_name: str):
        """
        Disambiguate same-named authors before fetching publications.

        Searches Semantic Scholar for author candidates matching the name.
        If several candidates exist, shows a small picker table (affiliation,
        h-index, paper count) so the user selects the right person; a single
        candidate is used directly. Returns the chosen S2 author ID, or None
        (no candidates / client without candidate search / lookup error) so
        the caller falls back to the legacy name-search behavior.
        """
        from citationimpact.clients import get_api_client

        try:
            client = get_api_client(
                email=self.config.get('email'),
                semantic_scholar_key=self.config.get('api_key')
            )
            search_candidates = getattr(client, 'search_author_candidates', None)
            if not callable(search_candidates):
                return None
            candidates = search_candidates(author_name, limit=5) or []
        except Exception:
            return None

        candidates = [c for c in candidates if c.get('author_id')]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]['author_id']

        from rich.table import Table
        from rich.markup import escape
        from rich import box

        self.console.print(
            f"\n[info]Found {len(candidates)} authors matching "
            f"'{escape(author_name)}'. Select the right person:[/info]"
        )

        table = Table(box=box.ROUNDED, header_style="bold cyan")
        table.add_column("#", style="bold magenta", width=4)
        table.add_column("Name", style="bold", max_width=30)
        table.add_column("Affiliation", style="cyan", max_width=40)
        table.add_column("H-Index", justify="right", style="yellow", width=8)
        table.add_column("Papers", justify="right", style="green", width=8)

        for idx, cand in enumerate(candidates, 1):
            # API-supplied strings may contain [bracketed] tokens that Rich
            # would parse as markup (dropped text or MarkupError on print)
            table.add_row(
                str(idx),
                escape(cand.get('name') or 'Unknown'),
                escape(cand.get('affiliation') or 'Unknown'),
                str(cand.get('h_index', 0) or 0),
                str(cand.get('paper_count', 0) or 0),
            )

        self.console.print(table)

        choice = Prompt.ask(
            "[bold]Select author[/bold]",
            choices=[str(i) for i in range(1, len(candidates) + 1)],
            default="1"
        )
        try:
            return candidates[int(choice) - 1]['author_id']
        except (ValueError, IndexError):
            return candidates[0]['author_id']

    def _display_publications(self, publications: list, author_name: str):
        """Display author publications and allow selection."""
        from rich.table import Table
        from rich import box

        self.clear_screen()
        self.console.print(Panel(
            f"[title]📚 PUBLICATIONS BY {author_name.upper()}[/title]",
            expand=False
        ))

        table = Table(box=box.ROUNDED, header_style="bold cyan")
        table.add_column("#", style="bold magenta", width=4)
        table.add_column("Title", style="bold", max_width=50)
        table.add_column("Year", justify="center", style="yellow", width=6)
        table.add_column("Citations", justify="right", style="cyan", width=10)
        table.add_column("Venue", style="dim", max_width=25)

        for idx, pub in enumerate(publications[:20], 1):
            if isinstance(pub, dict):
                title = pub.get('title', 'Unknown')[:50]
                year = _display_value(pub.get('year'))
                citations = _display_value(pub.get('citations'), pub.get('citationCount'))
                venue = pub.get('venue', 'N/A')[:25] if pub.get('venue') else 'N/A'
            else:
                title = getattr(pub, 'title', 'Unknown')[:50]
                year = _display_value(getattr(pub, 'year', None))
                citations = _display_value(getattr(pub, 'citationCount', None))
                venue = (getattr(pub, 'venue', 'N/A') or 'N/A')[:25]

            table.add_row(str(idx), title, year, citations, venue)

        self.console.print()
        self.console.print(table)

        if len(publications) > 20:
            self.console.print(f"\n[dim]Showing 20 of {len(publications)} publications[/dim]")

        self.console.print("\n[info]Enter a number to analyze that paper, or 'b' to go back[/info]")
        choice = Prompt.ask("[bold]Select paper[/bold]", default="b")

        if choice.lower() == 'b':
            return

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(publications):
                pub = publications[idx]
                if isinstance(pub, dict):
                    paper_title = pub.get('title', '')
                    paper_id = pub.get('paperId', '')
                else:
                    paper_title = getattr(pub, 'title', '')
                    paper_id = getattr(pub, 'paperId', '')

                if paper_id:
                    self._analyze_selected_paper(paper_id, paper_title)
                elif paper_title:
                    self._analyze_selected_paper(paper_title, paper_title)
            else:
                self.console.print("[error]Invalid selection[/error]")
                Prompt.ask("\nPress Enter to continue")
        except ValueError:
            self.console.print("[error]Invalid input[/error]")
            Prompt.ask("\nPress Enter to continue")

    def _analyze_selected_paper(self, paper_id_or_title: str, display_title: str):
        """Analyze a selected paper."""
        self.console.print(f"\n[info]Analyzing: {display_title[:50]}...[/info]")

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console
            ) as progress:
                task = progress.add_task(f"Analyzing paper...", total=None)

                result = analyze_paper_impact(
                    paper_title=paper_id_or_title,
                    h_index_threshold=self.config['h_index_threshold'],
                    max_citations=self.config['max_citations'],
                    data_source=self.config['data_source'],
                    email=self.config['email'],
                    semantic_scholar_key=self.config['api_key'],
                    scraper_api_key=self.config.get('scraper_api_key'),
                    existing_client=self._get_reusable_client()  # Reuse browser session
                )

                # Store client for reuse
                if result.get('_client'):
                    self._shared_client = result.pop('_client')
                    self._shared_client_source = self.config['data_source']

                progress.remove_task(task)

            self.analysis_view.display_results(result)

        except Exception as e:
            self.console.print(f"\n[error]Error during analysis: {str(e)}[/error]")

        Prompt.ask("\nPress Enter to continue")

    def show_help(self):
        """Display help and documentation."""
        self.clear_screen()
        self.console.print(Panel(
            "[title]📖 HELP & DOCUMENTATION[/title]",
            expand=False
        ))

        help_text = """
# Citation Impact Analyzer

## 🚀 Quick Start (For YOUR Papers)
1. **Set Your Profile** (Settings → Options 7 & 8):
   - Google Scholar ID: From `scholar.google.com/citations?user=YOUR_ID`
   - Semantic Scholar ID: From your S2 profile URL
   
2. **Use "My Papers"**: Direct access to your publications - no searching!
   - Faster analysis
   - Fewer CAPTCHAs
   - Direct citation links

## 📊 Understanding Results
- **High-Profile Scholars**: Authors citing you with h-index ≥ threshold
- **Influential Citations**: High-impact citations of your work
- **Institution Breakdown**: Universities, Industry, Government citing you
- **Venue Analysis**: Top conferences/journals citing your work
- **Deep Insights**: Visualizations & trends

## 💡 Tips for Best Experience
- **Set your Google Scholar ID** - most comprehensive data
- **Use "My Papers"** instead of search when possible
- **Comprehensive mode** combines Semantic Scholar + Google Scholar
- **Filter by h-index** in "All Authors" view to find key citers

## 🔧 Data Sources
| Source | Pros | Cons |
|--------|------|------|
| Semantic Scholar | Fast, API-based | May miss some papers |
| Google Scholar | Most complete | Slower, CAPTCHAs |
| Comprehensive | Best of both | Slowest |

## ❓ Avoiding CAPTCHAs
- Use "My Papers" with your saved profile
- Don't search - navigate directly via profile
- If CAPTCHA appears, solve it once; session persists
        """
        md = Markdown(help_text)
        self.console.print(md)
        Prompt.ask("\nPress Enter to continue")

    def manage_settings(self):
        """Delegate to settings manager."""
        self.settings_manager.manage_settings()

    def run(self):
        """Main application loop."""
        try:
            while True:
                try:
                    self.clear_screen()
                    self.show_header()

                    choice = self.show_main_menu()

                    if choice == "1":
                        self.my_papers()  # NEW: Direct profile-based access
                    elif choice == "2":
                        self.analyze_paper()  # Search any paper
                    elif choice == "3":
                        self.browse_author_papers()  # Other authors
                    elif choice == "4":
                        self.manage_settings()
                    elif choice == "5":
                        self.show_help()
                    elif choice == "6":
                        self.clear_screen()
                        self.console.print("\n[success]Thank you for using Citation Impact Analyzer![/success]")
                        self.console.print("[dim]Good luck with your research! 🎓[/dim]\n")
                        self._cleanup()  # Close browser before exit
                        sys.exit(0)
                except EOFError:
                    raise
                except Exception as e:
                    # Don't kill the whole session (and the open browser) on
                    # an unexpected error - show the traceback and go back to
                    # the main menu
                    self.console.print(f"\n[error]Unexpected error: {str(e)}[/error]")
                    self.console.print_exception()
                    Prompt.ask("\nPress Enter to return to the main menu")

        except (KeyboardInterrupt, EOFError):
            self.clear_screen()
            self.console.print("\n[warning]Application interrupted by user.[/warning]")
            self.console.print("[dim]Goodbye! 👋[/dim]\n")
            self._cleanup()  # Close browser before exit
            sys.exit(0)


def main():
    """Entry point for the terminal UI."""
    ui = TerminalUI()
    ui.run()


if __name__ == "__main__":
    main()

