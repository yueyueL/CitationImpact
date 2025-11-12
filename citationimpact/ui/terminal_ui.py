"""
Terminal UI for CitationImpact - Interactive command-line interface
"""
import sys
from typing import Optional, Dict, Any, List
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.layout import Layout
from rich.text import Text
from rich.markdown import Markdown
from rich import box
from rich.theme import Theme

from citationimpact import analyze_paper_impact
from citationimpact.config import ConfigManager
from .drill_down import (
    show_institution_details,
    show_venue_details,
    show_scholar_details,
    show_influential_details
)


class TerminalUI:
    """Interactive terminal UI for CitationImpact analysis."""
    def __init__(self):
        """Initialize the terminal UI."""
        # Custom theme for professional look
        custom_theme = Theme({
            "info": "cyan",
            "warning": "yellow",
            "error": "bold red",
            "success": "bold green",
            "highlight": "bold magenta",
            "title": "bold blue"
        })

        self.console = Console(theme=custom_theme)

        # Load configuration from persistent storage
        self.config_manager = ConfigManager()
        self.config = self.config_manager.get_all()

        # Show config location on first run
        self.config_dir = self.config_manager.get_config_path()

    def clear_screen(self):
        """Clear the terminal screen."""
        self.console.clear()

    def _get_field(self, obj, field_name: str, default=None):
        """
        Get a field from either a dict or dataclass object
        
        Args:
            obj: Dictionary or dataclass instance
            field_name: Field name to retrieve
            default: Default value if field not found
            
        Returns:
            Field value or default
        """
        if isinstance(obj, dict):
            return obj.get(field_name, default)
        return getattr(obj, field_name, default)

    def _make_clickable(self, text: str, url: str = '', paper_id: str = '') -> str:
        """Return clickable text if URL or paper ID is available."""
        if url:
            return f'[link={url}]{text}[/link]'
        if paper_id:
            return f'[link=https://www.semanticscholar.org/paper/{paper_id}]{text}[/link]'
        return text

    def _format_university_rankings(self, rankings: Dict[str, Any]) -> str:
        """Format QS / US News rankings for display."""
        if not rankings:
            return "N/A"

        def _format_entry(label: str, data: Optional[Dict[str, Any]]) -> Optional[str]:
            if not data:
                return None
            rank = data.get("rank")
            if rank is None:
                return None
            entry = f"{label} #{rank}"
            tier = data.get("tier")
            if tier:
                entry += f" ({tier})"
            return entry

        parts: List[str] = []
        qs_part = _format_entry("QS", rankings.get("qs"))
        if qs_part:
            parts.append(qs_part)
        usnews_part = _format_entry("US News", rankings.get("usnews"))
        if usnews_part:
            parts.append(usnews_part)

        if not parts and rankings.get("primary_source"):
            primary = rankings["primary_source"]
            primary_data = rankings.get("sources", {}).get(primary)
            primary_label = (primary_data or {}).get("label", primary.title())
            primary_part = _format_entry(primary_label, primary_data)
            if primary_part:
                parts.append(primary_part)

        return " | ".join(parts) if parts else "N/A"

    def _render_summary_screen(self, result: Dict[str, Any]) -> None:
        """Clear screen and render summary contents."""
        self.clear_screen()
        self._render_summary(result)

    def _render_summary(self, result: Dict[str, Any]) -> None:
        """Render the main summary panels."""
        header_panel = Panel(
            f"[bold]{result.get('paper_title', 'Analysis')}[/bold]",
            title="📊 Impact Analysis Results",
            border_style="cyan",
            padding=(1, 2)
        )
        self.console.print(header_panel)
        self.console.print("[dim]Tip: Cmd/Ctrl + click underlined titles to open them in your browser.[/dim]\n")

        overview_table = Table.grid(padding=(0, 2))
        overview_table.add_column(style="cyan")
        overview_table.add_column(justify="right", style="bold yellow")
        overview_metrics = [
            ("Total Citations", result.get('total_citations', 0)),
            ("Citations Analyzed", result.get('analyzed_citations', 0)),
            ("High-Profile Scholars", len(result.get('high_profile_scholars', []))),
            ("Influential Citations", len(result.get('influential_citations', []))),
            ("Methodological Citations", len(result.get('methodological_citations', [])))
        ]
        for label, value in overview_metrics:
            overview_table.add_row(label, str(value))
        self.console.print(Panel(overview_table, title="📈 Overview", border_style="cyan"))

        institutions = result.get('institutions', {})
        summary_counts = {k: v for k, v in institutions.items() if isinstance(v, (int, float))}
        if summary_counts:
            inst_table = Table(box=box.ROUNDED, header_style="bold cyan")
            inst_table.add_column("Type", style="magenta")
            inst_table.add_column("Count", justify="right", style="bold yellow")
            inst_table.add_column("Percent", justify="right", style="cyan")
            total = sum(summary_counts.values()) or 1
            for inst_type, count in summary_counts.items():
                percent = count / total * 100
                inst_table.add_row(inst_type, str(count), f"{percent:.1f}%")
            self.console.print(Panel(inst_table, title="🏛️ Institution Summary", border_style="magenta"))
        else:
            self.console.print(Panel("[dim]No institution data available[/dim]", title="🏛️ Institution Summary", border_style="magenta"))

        venues = result.get('venues', {})
        if venues:
            venue_grid = Table.grid(padding=(0, 2))
            venue_grid.add_column(style="cyan")
            venue_grid.add_column(justify="right", style="bold yellow")
            venue_grid.add_row("Total Venues", str(venues.get('total', 0)))
            venue_grid.add_row("Unique Venues", str(venues.get('unique', 0)))
            venue_grid.add_row("Top-Tier Percentage", f"{venues.get('top_tier_percentage', 0):.1f}%")
            self.console.print(Panel(venue_grid, title="📚 Venue Snapshot", border_style="green"))

            top_venues = venues.get('most_common', [])[:5]
            if top_venues:
                top_table = Table(box=box.ROUNDED, header_style="bold cyan")
                top_table.add_column("#", justify="right", style="bold magenta", width=4)
                top_table.add_column("Venue", style="bold", max_width=40)
                top_table.add_column("Citations", justify="right", style="bold yellow", width=9)
                top_table.add_column("Tier", style="cyan", max_width=25)
                rankings = venues.get('rankings', {})
                for idx, (venue_name, count) in enumerate(top_venues, 1):
                    info = rankings.get(venue_name, {})
                    tier = info.get('rank_tier', 'N/A')
                    core = info.get('core_rank')
                    ccf = info.get('ccf_rank')
                    icore = info.get('icore_rank')
                    parts = [tier]
                    if core:
                        parts.append(f"CORE {core}")
                    if ccf:
                        parts.append(f"CCF {ccf}")
                    if icore:
                        parts.append(f"iCORE {icore}")
                    tier_display = " • ".join(part for part in parts if part)
                    display_name = venue_name if len(venue_name) <= 40 else venue_name[:37] + "..."
                    top_table.add_row(str(idx), display_name, str(count), tier_display)
                self.console.print(Panel(top_table, title="🏆 Top Citing Venues", border_style="green"))

        scholars = result.get('high_profile_scholars', [])[:5]
        if scholars:
            scholar_table = Table(box=box.ROUNDED, header_style="bold cyan")
            scholar_table.add_column("#", justify="right", style="bold magenta", width=4)
            scholar_table.add_column("Scholar", style="bold", max_width=22)
            scholar_table.add_column("H-Index", justify="right", style="bold yellow", width=8)
            scholar_table.add_column("Institution", style="cyan", max_width=30)
            scholar_table.add_column("Citing Paper", style="dim")
            for idx, scholar in enumerate(scholars, 1):
                info = self._extract_scholar_info(scholar)
                institution = info['affiliation'] or 'Unknown'
                inst_type = info['institution_type'] or ''
                if inst_type and inst_type.lower() not in ('n/a', 'other'):
                    institution += f" ({inst_type})"
                ranking_display = self._format_university_rankings(info.get('university_rankings', {}))
                if ranking_display != "N/A":
                    institution += f" • {ranking_display}"
                if len(institution) > 30:
                    institution = institution[:27] + "..."
                citing_display = self._make_clickable(info['citing_paper'] or 'Unknown', info['paper_url'], info['paper_id'])
                scholar_table.add_row(str(idx), info['name'], str(info['h_index']), institution, citing_display)
            self.console.print(Panel(scholar_table, title="🌟 High-Profile Scholars (Top 5)", border_style="magenta"))
        else:
            self.console.print(Panel("[dim]No high-profile scholars identified yet[/dim]", title="🌟 High-Profile Scholars", border_style="magenta"))

        influential = result.get('influential_citations', [])[:3]
        if influential:
            inf_table = Table(box=box.ROUNDED, header_style="bold cyan")
            inf_table.add_column("#", style="bold magenta", justify="right", width=4)
            inf_table.add_column("Citing Paper", style="bold")
            inf_table.add_column("Year", justify="center", style="bold yellow", width=6)
            inf_table.add_column("Venue", style="cyan", max_width=30)
            for idx, citation in enumerate(influential, 1):
                preview = self._format_citation_preview(citation)
                title_display = self._make_clickable(preview['title'], preview['url'], preview['paper_id'])
                venue = preview['venue'] or 'Unknown'
                if len(venue) > 30:
                    venue = venue[:27] + "..."
                year = preview['year'] if preview['year'] not in ('', None) else 'N/A'
                inf_table.add_row(str(idx), title_display, str(year), venue)
            self.console.print(Panel(inf_table, title="💡 Influential Citations (Top 3)", border_style="yellow"))
        else:
            self.console.print(Panel("[dim]No influential citations identified yet[/dim]", title="💡 Influential Citations", border_style="yellow"))

    def _extract_scholar_info(self, scholar: Any) -> Dict[str, Any]:
        """Return normalized scholar info dictionary."""
        return {
            'name': self._get_field(scholar, 'name', 'Unknown'),
            'h_index': self._get_field(scholar, 'h_index', 'N/A'),
            'affiliation': self._get_field(scholar, 'affiliation', 'Unknown'),
            'institution_type': self._get_field(scholar, 'institution_type', 'N/A'),
            'citing_paper': self._get_field(scholar, 'citing_paper', 'Unknown'),
            'paper_url': self._get_field(scholar, 'paper_url', ''),
            'paper_id': self._get_field(scholar, 'paper_id', ''),
            'university_rankings': self._get_field(scholar, 'university_rankings', {}) or {},
            'university_rank': self._get_field(scholar, 'university_rank', None),
            'university_tier': self._get_field(scholar, 'university_tier', None),
            'usnews_rank': self._get_field(scholar, 'usnews_rank', None),
            'usnews_tier': self._get_field(scholar, 'usnews_tier', None),
            'primary_university_source': self._get_field(scholar, 'primary_university_source', None),
        }

    def _format_citation_preview(self, citation: Any) -> Dict[str, Any]:
        """Extract title, venue, year, url, paper_id from citation."""
        title = self._get_field(citation, 'citing_paper_title', self._get_field(citation, 'title', 'Unknown'))
        venue = self._get_field(citation, 'venue', 'Unknown')
        year = self._get_field(citation, 'year', 'N/A')
        url = self._get_field(citation, 'url', '')
        paper_id = self._get_field(citation, 'paper_id', '')
        return {
            'title': title,
            'venue': venue,
            'year': year,
            'url': url,
            'paper_id': paper_id
        }

    def show_header(self):
        """Display the application header."""
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

        menu_items = [
            ("1", "🔍 Analyze a Paper", "Analyze citation impact of a research paper"),
            ("2", "👤 Browse Author Papers", "Select from an author's publications"),
            ("3", "⚙️  Settings", "View and adjust configuration"),
            ("4", "📖 Help & Documentation", "Learn how to use the analyzer"),
            ("5", "❌ Exit", "Exit the application")
        ]

        for key, title, desc in menu_items:
            self.console.print(f"  [highlight]{key}.[/highlight] {title}")
            self.console.print(f"     [dim]{desc}[/dim]")
            self.console.print()

        choice = Prompt.ask(
            "[bold]Select an option[/bold]",
            choices=["1", "2", "3", "4", "5"],
            default="1"
        )
        return choice

    def manage_settings(self):
        """Unified settings menu - view and configure in one place."""
        while True:
            self.clear_screen()
            self.console.print(Panel(
                "[title]⚙️  SETTINGS MANAGER[/title]",
                expand=False
            ))

            # Show config file location
            self.console.print(f"\n[dim]Configuration saved in: {self.config_dir}/config.json[/dim]\n")

            # Display current settings in a table
            table = Table(
                box=box.ROUNDED,
                show_header=True,
                header_style="bold cyan"
            )

            table.add_column("#", style="bold magenta", width=3)
            table.add_column("Setting", style="bold")
            table.add_column("Current Value", style="yellow")
            table.add_column("Description", style="dim")

            settings = [
                ("1", "H-Index Threshold",
                 str(self.config['h_index_threshold']),
                 "Min h-index for high-profile scholars"),
                ("2", "Max Citations",
                 str(self.config['max_citations']),
                 "Number of citations to analyze (1-1000)"),
                ("3", "Data Source",
                 self.config['data_source'],
                 "API mode (fast) or Google Scholar"),
                ("4", "Email",
                 self.config.get('email') or "[dim]Not set[/dim]",
                 "For OpenAlex polite pool (faster API)"),
                ("5", "API Key",
                 "[dim]Set[/dim]" if self.config.get('api_key') else "[dim]Not set[/dim]",
                 "Semantic Scholar API key (optional)"),
                ("6", "Default Semantic Scholar Author ID",
                 self.config.get('default_semantic_scholar_author_id') or "[dim]Not set[/dim]",
                 "Used when browsing author papers in API mode"),
                ("7", "Default Google Scholar Author ID",
                 self.config.get('default_google_scholar_author_id') or "[dim]Not set[/dim]",
                 "Used when browsing author papers in Google Scholar mode"),
                ("8", "Data Location & Cache",
                 "[dim]View/Manage[/dim]",
                 "Show where data is stored & manage cache"),
            ]

            for num, setting, value, desc in settings:
                table.add_row(num, setting, value, desc)

            self.console.print(table)

            # Menu options
            self.console.print("\n[info]Options:[/info]")
            self.console.print("  • Enter [highlight]1-8[/highlight] to edit a setting")
            self.console.print("  • Enter [highlight]r[/highlight] to reset to defaults")
            self.console.print("  • Enter [highlight]b[/highlight] to go back to main menu")

            choice = Prompt.ask(
                "\n[bold]Select option[/bold]",
                default="b"
            ).lower()

            if choice == 'b':
                break
            elif choice == 'r':
                if Confirm.ask("[warning]Reset all settings to defaults?[/warning]", default=False):
                    self.config_manager.reset()
                    self.config = self.config_manager.get_all()
                    self.console.print("[success]✓ Settings reset to defaults[/success]")
                    Prompt.ask("\nPress Enter to continue")
            elif choice == '1':
                self._edit_h_index_threshold()
            elif choice == '2':
                self._edit_max_citations()
            elif choice == '3':
                self._edit_data_source()
            elif choice == '4':
                self._edit_email()
            elif choice == '5':
                self._edit_api_key()
            elif choice == '6':
                self._edit_default_semantic_author_id()
            elif choice == '7':
                self._edit_default_google_author_id()
            elif choice == '8':
                self._manage_data_and_cache()
            else:
                self.console.print("[error]Invalid option[/error]")
                Prompt.ask("\nPress Enter to continue")

    def _edit_h_index_threshold(self):
        """Edit h-index threshold setting."""
        self.console.print("\n[info]High-Profile Scholar Threshold[/info]")
        self.console.print(f"Current value: [highlight]{self.config['h_index_threshold']}[/highlight]")
        self.console.print("[dim]Scholars with h-index ≥ this value are considered 'high-profile'[/dim]")

        new_value = IntPrompt.ask(
            "\nEnter new threshold",
            default=self.config['h_index_threshold']
        )

        if new_value > 0:
            self.config['h_index_threshold'] = new_value
            self.config_manager.set('h_index_threshold', new_value)
            self.console.print("[success]✓ H-index threshold updated[/success]")
        else:
            self.console.print("[error]Value must be positive[/error]")

        Prompt.ask("\nPress Enter to continue")

    def _edit_max_citations(self):
        """Edit max citations setting."""
        self.console.print("\n[info]Maximum Citations to Analyze[/info]")
        self.console.print(f"Current value: [highlight]{self.config['max_citations']}[/highlight]")
        self.console.print("[dim]More citations = slower but more comprehensive (max: 1000)[/dim]")

        new_value = IntPrompt.ask(
            "\nEnter new maximum",
            default=self.config['max_citations']
        )

        if 1 <= new_value <= 1000:
            self.config['max_citations'] = new_value
            self.config_manager.set('max_citations', new_value)
            self.console.print("[success]✓ Max citations updated[/success]")
        else:
            self.console.print("[error]Value must be between 1 and 1000[/error]")

        Prompt.ask("\nPress Enter to continue")

    def _edit_data_source(self):
        """Edit data source setting."""
        self.console.print("\n[info]Data Source[/info]")
        self.console.print(f"Current value: [highlight]{self.config['data_source']}[/highlight]")
        self.console.print("[dim]• 'api': Semantic Scholar + OpenAlex (fast, recommended)[/dim]")
        self.console.print("[dim]• 'google_scholar': Web scraping (slow, may hit CAPTCHAs)[/dim]")

        new_value = Prompt.ask(
            "\nSelect data source",
            choices=["api", "google_scholar"],
            default=self.config['data_source']
        )

        self.config['data_source'] = new_value
        self.config_manager.set('data_source', new_value)
        self.console.print("[success]✓ Data source updated[/success]")
        Prompt.ask("\nPress Enter to continue")

    def _edit_email(self):
        """Edit email setting."""
        self.console.print("\n[info]Email (Optional)[/info]")
        current = self.config.get('email') or "Not set"
        self.console.print(f"Current value: [highlight]{current}[/highlight]")
        self.console.print("[dim]Providing an email gives you access to OpenAlex 'polite pool' (faster API)[/dim]")

        if Confirm.ask("\nDo you want to set/change your email?", default=False):
            email = Prompt.ask("Enter email address (or leave empty to clear)")

            if email.strip():
                self.config['email'] = email.strip()
                self.config_manager.set('email', email.strip())
                self.console.print("[success]✓ Email updated[/success]")
            else:
                self.config['email'] = None
                self.config_manager.set('email', None)
                self.console.print("[success]✓ Email cleared[/success]")

        Prompt.ask("\nPress Enter to continue")

    def _edit_api_key(self):
        """Edit API key setting."""
        self.console.print("\n[info]Semantic Scholar API Key (Optional)[/info]")
        current = "Set" if self.config.get('api_key') else "Not set"
        self.console.print(f"Current: [highlight]{current}[/highlight]")
        self.console.print("[dim]Get a free API key at: https://www.semanticscholar.org/product/api[/dim]")
        self.console.print("[dim]Provides higher rate limits for API requests[/dim]")

        if Confirm.ask("\nDo you want to set/change your API key?", default=False):
            api_key = Prompt.ask("Enter API key (or leave empty to clear)")

            if api_key.strip():
                self.config['api_key'] = api_key.strip()
                self.config_manager.set('api_key', api_key.strip())
                self.console.print("[success]✓ API key updated[/success]")
            else:
                self.config['api_key'] = None
                self.config_manager.set('api_key', None)
                self.console.print("[success]✓ API key cleared[/success]")

        Prompt.ask("\nPress Enter to continue")

    def _edit_default_semantic_author_id(self):
        """Edit default Semantic Scholar author ID."""
        current = self.config.get('default_semantic_scholar_author_id')
        display = current or "[dim]Not set[/dim]"
        self.console.print("\n[info]Default Semantic Scholar Author ID[/info]")
        self.console.print(f"Current value: [highlight]{display}[/highlight]")
        prompt_kwargs = {}
        if current:
            prompt_kwargs['default'] = current
        new_value = Prompt.ask(
            "Enter Semantic Scholar author ID (e.g., 1745629) or leave empty to clear",
            **prompt_kwargs
        ).strip()

        if new_value:
            self.config['default_semantic_scholar_author_id'] = new_value
            self.config_manager.set('default_semantic_scholar_author_id', new_value)
            self.console.print("[success]✓ Default Semantic Scholar author ID updated[/success]")
        else:
            self.config['default_semantic_scholar_author_id'] = None
            self.config_manager.set('default_semantic_scholar_author_id', None)
            self.console.print("[success]✓ Default Semantic Scholar author ID cleared[/success]")

        Prompt.ask("\nPress Enter to continue")

    def _edit_default_google_author_id(self):
        """Edit default Google Scholar author ID."""
        current = self.config.get('default_google_scholar_author_id')
        display = current or "[dim]Not set[/dim]"
        self.console.print("\n[info]Default Google Scholar Author ID[/info]")
        self.console.print(f"Current value: [highlight]{display}[/highlight]")
        prompt_kwargs = {}
        if current:
            prompt_kwargs['default'] = current
        new_value = Prompt.ask(
            "Enter Google Scholar author ID (e.g., waVL0PgAAAAJ) or leave empty to clear",
            **prompt_kwargs
        ).strip()

        if new_value:
            self.config['default_google_scholar_author_id'] = new_value
            self.config_manager.set('default_google_scholar_author_id', new_value)
            self.console.print("[success]✓ Default Google Scholar author ID updated[/success]")
        else:
            self.config['default_google_scholar_author_id'] = None
            self.config_manager.set('default_google_scholar_author_id', None)
            self.console.print("[success]✓ Default Google Scholar author ID cleared[/success]")

        Prompt.ask("\nPress Enter to continue")

    def _manage_data_and_cache(self):
        """Manage data location and cache."""
        from citationimpact import get_result_cache, get_author_cache
        import os

        self.clear_screen()
        self.console.print(Panel(
            "[title]📂 DATA LOCATION & CACHE MANAGEMENT[/title]",
            expand=False
        ))

        # Show data location
        config_dir = self.config_manager.get_config_path()
        self.console.print("\n[info]Data Storage Location:[/info]")
        self.console.print(f"  [highlight]{config_dir}[/highlight]")
        self.console.print(f"\n[dim]This folder contains:[/dim]")
        self.console.print(f"[dim]  • config.json - Your settings and API key[/dim]")
        self.console.print(f"[dim]  • cache/ - Cached analysis results (7 days)[/dim]")
        self.console.print(f"[dim]  • author_cache/ - Cached author profiles (30 days)[/dim]")
        self.console.print(f"[dim]  • exports/ - Exported reports[/dim]")

        # Check if directory exists and show size
        if config_dir.exists():
            # Calculate total size
            total_size = 0
            cache_count = 0
            author_cache_count = 0

            cache_dir = config_dir / 'cache'
            author_cache_dir = config_dir / 'author_cache'

            if cache_dir.exists():
                for f in cache_dir.glob("*.json"):
                    total_size += f.stat().st_size
                    cache_count += 1

            if author_cache_dir.exists():
                for f in author_cache_dir.glob("*.json"):
                    total_size += f.stat().st_size
                    author_cache_count += 1

            size_mb = total_size / (1024 * 1024)

            self.console.print(f"\n[info]Cache Statistics:[/info]")
            self.console.print(f"  • Analysis results cached: [highlight]{cache_count}[/highlight]")
            self.console.print(f"  • Author profiles cached: [highlight]{author_cache_count}[/highlight]")
            self.console.print(f"  • Total cache size: [highlight]{size_mb:.2f} MB[/highlight]")
        else:
            self.console.print("\n[warning]⚠️  Data directory not created yet (will be created on first use)[/warning]")

        # Open folder option
        self.console.print("\n[info]Options:[/info]")
        self.console.print("  1. Open folder in file manager")
        self.console.print("  2. Clear analysis result cache")
        self.console.print("  3. Clear author profile cache")
        self.console.print("  4. Clear all caches")
        self.console.print("  b. Go back")

        choice = Prompt.ask("\n[bold]Select option[/bold]", default="b").lower()

        if choice == '1':
            # Open folder
            import platform
            import subprocess

            try:
                if platform.system() == 'Windows':
                    os.startfile(config_dir)
                elif platform.system() == 'Darwin':  # macOS
                    subprocess.run(['open', config_dir])
                else:  # Linux
                    subprocess.run(['xdg-open', config_dir])
                self.console.print("[success]✓ Opened folder in file manager[/success]")
            except Exception as e:
                self.console.print(f"[error]Could not open folder: {e}[/error]")
                self.console.print(f"[info]Manual path: {config_dir}[/info]")

        elif choice == '2':
            if Confirm.ask("[warning]Clear analysis result cache?[/warning]", default=False):
                result_cache = get_result_cache()
                count = result_cache.clear()
                self.console.print(f"[success]✓ Cleared {count} analysis results[/success]")

        elif choice == '3':
            if Confirm.ask("[warning]Clear author profile cache?[/warning]", default=False):
                author_cache = get_author_cache()
                count = author_cache.clear()
                self.console.print(f"[success]✓ Cleared {count} author profiles[/success]")

        elif choice == '4':
            if Confirm.ask("[warning]Clear ALL caches?[/warning]", default=False):
                result_cache = get_result_cache()
                author_cache = get_author_cache()
                count1 = result_cache.clear()
                count2 = author_cache.clear()
                self.console.print(f"[success]✓ Cleared {count1} analysis results and {count2} author profiles[/success]")

        Prompt.ask("\nPress Enter to continue")

    def show_help(self):
        """Display help documentation."""
        self.clear_screen()

        help_text = """
# 📖 Citation Impact Analyzer - Help Guide

## What Does This Tool Do?

The Citation Impact Analyzer helps researchers demonstrate the **significance** and
**influence** of their work by analyzing:

- **High-Profile Citations**: Who is citing your work? Are they prominent researchers?
- **Institution Breakdown**: Where are citations coming from? (Universities, Industry, Government)
- **Venue Quality**: What journals/conferences cite your work? Top-tier? Emerging?
- **Influential Citations**: Which citations are particularly impactful?
- **Methodological Impact**: Who is building on or extending your methods?

## Key Features

### 1. High-Profile Scholar Detection
Identifies citing authors with h-index ≥ threshold (default: 20)

### 2. Institution Analysis
Categorizes citations from:
- Universities (with QS rankings for top institutions)
- Industry (Google, Microsoft, Meta, etc.)
- Government (NIH, DARPA, NASA, etc.)

### 3. Dynamic Venue Rankings
Ranks journals/conferences by h-index:
- **Tier 1**: h-index > 100 (Top flagship venues)
- **Tier 2**: h-index 50-100 (Excellent venues)
- **Tier 3**: h-index 20-50 (Good venues)
- **Tier 4**: h-index < 20 (Emerging venues)

### 4. CORE Rankings (Computer Science)
Conference rankings: A*, A, B, C

### 5. Influential Citations
AI-powered detection via Semantic Scholar

## How to Use

1. **Analyze a Paper**: Enter your paper title
2. **Configure Settings**: Adjust analysis parameters
3. **Review Results**: Get comprehensive impact report

## Tips

- Use exact paper titles for best results
- API mode is faster and more reliable than Google Scholar
- Higher h-index thresholds = more selective "high-profile" classification
- Analyze more citations for comprehensive results (but slower)

## Data Sources

- **Semantic Scholar API**: Citation data, influence detection
- **OpenAlex API**: Author h-indices, affiliations, venue data
- **Google Scholar**: Fallback option (slower, may hit CAPTCHAs)

## Support

For issues or questions, see the project repository or documentation.
        """
        md = Markdown(help_text)
        self.console.print(md)
        Prompt.ask("\nPress Enter to continue")

    def analyze_paper(self):
        """Interactive paper analysis workflow."""
        self.clear_screen()
        self.console.print(Panel(
            "[title]🔍 ANALYZE PAPER IMPACT[/title]",
            expand=False
        ))

        # Get paper title
        self.console.print("\n[info]Enter the title of the paper to analyze:[/info]")
        self.console.print("[dim]Tip: Use the exact title for best results[/dim]\n")

        paper_title = Prompt.ask("[bold]Paper title[/bold]")

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

        # Perform analysis
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
                    semantic_scholar_key=self.config['api_key']
                )

                progress.remove_task(task)

            # Display results
            self.display_results(result)

        except Exception as e:
            self.console.print(f"\n[error]Error during analysis: {str(e)}[/error]")

        Prompt.ask("\nPress Enter to continue")

    def _looks_like_author_id(self, text: str, data_source: str) -> bool:
        """
        Determine if text looks like an author ID

        Args:
            text: Input text
            data_source: 'api' or 'google_scholar'

        Returns:
            True if it looks like an ID, False if it looks like a name
        """
        text = text.strip()

        # If it contains spaces, it's likely a name
        if ' ' in text:
            return False

        if data_source == 'google_scholar':
            # Google Scholar IDs are alphanumeric, typically 12 characters
            # Example: waVL0PgAAAAJ, 2hXXXXXXXXXJ
            # Usually contains both letters and numbers, no spaces
            if len(text) >= 10 and any(c.isalpha() for c in text) and any(c.isdigit() for c in text):
                return True
        else:
            # Semantic Scholar IDs are typically numeric
            # Example: 1745629, 143687321
            if text.isdigit():
                return True

        # Default: treat as name
        return False

    def browse_author_papers(self):
        """Browse papers by author and select one to analyze."""
        self.clear_screen()
        self.console.print(Panel(
            "[title]👤 BROWSE AUTHOR PAPERS[/title]",
            expand=False
        ))

        # Check data source
        data_source = self.config.get('data_source', 'api')

        # Get author identifier
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
                self.console.print("[error]Error: Author input cannot be empty[/error]")
                Prompt.ask("\nPress Enter to continue")
                return

        try:
            # Create appropriate API client based on data source
            if data_source == 'google_scholar':
                from citationimpact.clients import get_google_scholar_client
                api = get_google_scholar_client(use_proxy=False)
            else:
                from citationimpact.clients import get_api_client
                api = get_api_client(
                    semantic_scholar_key=self.config.get('api_key'),
                    email=self.config.get('email')
                )

            # Determine if input is an ID or name
            author_id = None
            is_id = self._looks_like_author_id(author_input, data_source)

            if is_id:
                # Treat as ID
                self.console.print(f"\n[info]Using author ID: {author_input}[/info]")
                author_id = author_input
            else:
                # Search by name
                self.console.print(f"\n[info]Searching for author: {author_input}...[/info]")

                if data_source == 'google_scholar':
                    # Google Scholar doesn't have a direct search API, try to get by name
                    self.console.print("[warning]Google Scholar search by name is limited. Consider using Google Scholar ID.[/warning]")
                    # For now, we'll show an error for Google Scholar name search
                    self.console.print("[error]Please use a Google Scholar ID for Google Scholar mode.[/error]")
                    self.console.print("[info]To find an author's Google Scholar ID:[/info]")
                    self.console.print("[dim]  1. Go to https://scholar.google.com/[/dim]")
                    self.console.print("[dim]  2. Search for the author[/dim]")
                    self.console.print("[dim]  3. Click on their profile[/dim]")
                    self.console.print("[dim]  4. The ID is in the URL: scholar.google.com/citations?user=ID_HERE[/dim]")
                    Prompt.ask("\nPress Enter to continue")
                    return
                else:
                    author_id = api.search_author(author_input)
                    if not author_id:
                        self.console.print(f"[error]Author '{author_input}' not found[/error]")
                        Prompt.ask("\nPress Enter to continue")
                        return

            # Check cache first
            from citationimpact import get_author_cache
            author_cache = get_author_cache()

            cached_profile = author_cache.get(author_id, data_source)

            if cached_profile:
                # Use cached data
                author_info = cached_profile['author_info']
                publications = cached_profile['publications']
            else:
                # Fetch fresh data
                # Get author info
                self.console.print(f"\n[info]Fetching author information...[/info]")
                author_info = api.get_author_by_id(author_id)

                if not author_info:
                    self.console.print("[error]Could not retrieve author information[/error]")
                    Prompt.ask("\nPress Enter to continue")
                    return

                # Get publications
                self.console.print(f"\n[info]Fetching publications...[/info]")
                publications = api.get_author_publications(author_id, limit=50)

                if not publications:
                    self.console.print("[error]No publications found for this author[/error]")
                    Prompt.ask("\nPress Enter to continue")
                    return

                # Cache the profile
                author_cache.set(author_id, data_source, author_info, publications)

            # Display author info (handle both Semantic Scholar and Google Scholar formats)
            if data_source == 'google_scholar':
                # Google Scholar format
                author_name = author_info.get('name', 'Unknown')
                self.console.print(f"\n[success]Found author: {author_name}[/success]")
                if author_info.get('affiliation'):
                    self.console.print(f"[dim]Affiliation: {author_info['affiliation']}[/dim]")
                if author_info.get('hindex'):
                    self.console.print(f"[dim]H-index: {author_info['hindex']}[/dim]")
                if author_info.get('citedby'):
                    self.console.print(f"[dim]Total citations: {author_info['citedby']}[/dim]")
            else:
                # Semantic Scholar format
                author_name = author_info.get('name', 'Unknown')
                self.console.print(f"\n[success]Found author: {author_name}[/success]")
                if author_info.get('affiliations'):
                    affil = author_info['affiliations'][0] if isinstance(author_info['affiliations'], list) else author_info['affiliations']
                    self.console.print(f"[dim]Affiliation: {affil}[/dim]")
                if author_info.get('hIndex'):
                    self.console.print(f"[dim]H-index: {author_info['hIndex']}[/dim]")
                if author_info.get('paperCount'):
                    self.console.print(f"[dim]Papers: {author_info['paperCount']}[/dim]")

            if not publications:
                self.console.print("[error]No publications found for this author[/error]")
                Prompt.ask("\nPress Enter to continue")
                return

            # Display publications in a table
            self.clear_screen()
            self.console.print(Panel(
                f"[title]📚 Publications by {author_name}[/title]",
                expand=False,
                border_style="cyan"
            ))

            papers_table = Table(
                box=box.ROUNDED,
                show_header=True,
                header_style="bold cyan"
            )

            papers_table.add_column("#", style="bold magenta", width=4, justify="right")
            papers_table.add_column("Title", style="bold", max_width=60)
            papers_table.add_column("Year", justify="center", style="yellow", width=6)
            papers_table.add_column("Citations", justify="right", style="green", width=10)
            papers_table.add_column("Venue", style="dim", max_width=30)

            # Show top papers (handle both formats)
            display_count = min(20, len(publications))
            for i, paper in enumerate(publications[:display_count], 1):
                title = paper.get('title', 'Unknown')
                if len(title) > 60:
                    title = title[:57] + "..."
                venue = paper.get('venue', 'Unknown')
                if venue and len(venue) > 30:
                    venue = venue[:27] + "..."
                # Handle different citation count keys
                if data_source == 'google_scholar':
                    citations = paper.get('citations', 0)
                else:
                    citations = paper.get('citationCount', 0)

                papers_table.add_row(
                    str(i),
                    title,
                    str(paper.get('year', 'N/A')),
                    str(citations),
                    venue or 'N/A'
                )

            self.console.print(f"\n[info]Showing top {display_count} papers (sorted by citations)[/info]\n")
            self.console.print(papers_table)

            # Let user select a paper
            self.console.print(f"\n[info]Select a paper to analyze (1-{display_count}) or 0 to cancel:[/info]")

            while True:
                choice = Prompt.ask("[bold]Paper number[/bold]", default="0")

                try:
                    choice_num = int(choice)
                    if choice_num == 0:
                        return
                    elif 1 <= choice_num <= display_count:
                        selected_paper = publications[choice_num - 1]
                        paper_title = selected_paper.get('title', '')

                        # Show selected paper info
                        self.console.print(f"\n[success]Selected:[/success] {paper_title}")

                        # Handle different citation count keys
                        if data_source == 'google_scholar':
                            citations = selected_paper.get('citations', 0)
                        else:
                            citations = selected_paper.get('citationCount', 0)

                        self.console.print(f"[dim]Citations: {citations}[/dim]")

                        # Confirm and analyze
                        if Confirm.ask("\n[bold]Analyze this paper?[/bold]", default=True):
                            # Pass the data_source that was used for browsing
                            self._analyze_paper_by_title(paper_title, force_data_source=data_source)
                        return
                    else:
                        self.console.print(f"[error]Please enter a number between 1 and {display_count}[/error]")
                except ValueError:
                    self.console.print("[error]Please enter a valid number[/error]")

        except Exception as e:
            self.console.print(f"\n[error]Error browsing author papers: {str(e)}[/error]")
            Prompt.ask("\nPress Enter to continue")

    def _analyze_paper_by_title(self, paper_title: str, force_data_source: str = None):
        """Helper method to analyze a paper given its title.

        Args:
            paper_title: Title of the paper to analyze
            force_data_source: If provided, use this data source instead of config
                              (used when browsing via Google Scholar to ensure consistency)
        """
        # Check if cached result exists
        from citationimpact import get_result_cache

        # Use forced data source if provided (from browse_author_papers)
        # This ensures if you browse via Google Scholar, analysis also uses Google Scholar
        data_source = force_data_source if force_data_source else self.config['data_source']

        # Notify user if data source was auto-switched
        if force_data_source and force_data_source != self.config['data_source']:
            self.console.print(f"\n[info]ℹ️  Auto-switched to '{force_data_source}' data source[/info]")
            self.console.print(f"[dim]   (Paper was browsed via {force_data_source}, will analyze with same source)[/dim]")

        cache = get_result_cache()
        params = {
            'h_index_threshold': self.config['h_index_threshold'],
            'max_citations': self.config['max_citations'],
            'data_source': data_source
        }

        cached_result = cache.get(paper_title, params)

        # Confirm settings
        self.console.print("\n[info]Analysis Settings:[/info]")
        self.console.print(f"  • H-Index Threshold: [highlight]{self.config['h_index_threshold']}[/highlight]")
        self.console.print(f"  • Max Citations: [highlight]{self.config['max_citations']}[/highlight]")
        self.console.print(f"  • Data Source: [highlight]{data_source}[/highlight]")

        # Ask about cache usage
        use_cache = True
        if cached_result:
            self.console.print("\n[success]✓ Cached result available for this paper![/success]")
            if not Confirm.ask("[bold]Use cached result (faster)?[/bold]", default=True):
                use_cache = False
                self.console.print("[info]Will fetch fresh data...[/info]")
        else:
            self.console.print("\n[dim]No cached result found - will fetch fresh data[/dim]")

        if not Confirm.ask("\n[bold]Proceed with analysis?[/bold]", default=True):
            return

        # If user wants cached result and it exists, return it
        if use_cache and cached_result:
            self.console.print("\n[info]Loading cached result...[/info]")
            self.display_results(cached_result)
            Prompt.ask("\nPress Enter to continue")
            return

        # Perform analysis
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
                    data_source=data_source,  # Use the (possibly forced) data source
                    email=self.config['email'],
                    semantic_scholar_key=self.config['api_key'],
                    use_cache=use_cache  # Pass the cache preference
                )

                progress.remove_task(task)

            # Display results
            self.display_results(result)

        except Exception as e:
            self.console.print(f"\n[error]Error during analysis: {str(e)}[/error]")

        Prompt.ask("\nPress Enter to continue")

    def display_results(self, result: Dict[str, Any]):
        """Display analysis results with a refreshed layout."""
        if result.get('error'):
            self.clear_screen()
            self.console.print(Panel(
                f"[error]Analysis Error: {result['error']}[/error]",
                title='❌ Error',
                border_style='red'
            ))
            return

        self._render_summary_screen(result)
        self._show_detail_menu(result)

    def _show_detail_menu(self, result: Dict[str, Any]):
        """Interactive menu for drill-down views."""
        while True:
            menu = Table.grid(padding=(0, 1))
            menu.add_column(style='bold magenta', justify='right')
            menu.add_column(style='white')
            menu.add_row('1.', '🏛️  Institution breakdown (universities, industry, government)')
            menu.add_row('2.', '📚 Venue details (full list with rankings)')
            menu.add_row('3.', '🌟 All high-profile scholars')
            menu.add_row('4.', '💡 All influential citations')
            menu.add_row('5.', '💾 Save report to file')
            menu.add_row('6.', '⬅️  Back to main menu')

            self.console.print("\n[info]📊 View Details:[/info]")
            self.console.print(menu)

            choice = Prompt.ask("\n[bold]Select option (1-6)[/bold]", default="6").strip()

            if choice == '1':
                show_institution_details(self.console, result)
                self._render_summary_screen(result)
                continue
            if choice == '2':
                show_venue_details(self.console, result)
                self._render_summary_screen(result)
                continue
            if choice == '3':
                show_scholar_details(self.console, result)
                self._render_summary_screen(result)
                continue
            if choice == '4':
                show_influential_details(self.console, result)
                self._render_summary_screen(result)
                continue
            if choice == '5':
                self.export_results(result)
                self._render_summary_screen(result)
                continue
            if choice == '6':
                break

            self.console.print('[error]Invalid option. Please choose between 1 and 6.[/error]')
            continue

    def show_detailed_citations(self, result: Dict[str, Any]):
        """Display detailed citation information with links."""
        self.console.print("\n")
        self.console.print(Panel(
            "[title]📄 DETAILED CITATION INFORMATION[/title]",
            expand=False,
            border_style="cyan"
        ))

        # Combine influential and methodological citations
        all_citations = []

        if result.get('influential_citations'):
            for citation in result['influential_citations']:
                all_citations.append(('Influential', citation))

        if result.get('methodological_citations'):
            # Avoid duplicates
            def _get_title(c):
                if isinstance(c, dict):
                    return c.get('citing_paper_title') or c.get('title')
                return getattr(c, 'citing_paper_title', None)

            influential_titles = {
                _get_title(c) for c in result.get('influential_citations', [])
            }
            for citation in result['methodological_citations']:
                title = _get_title(citation)
                if title not in influential_titles:
                    all_citations.append(('Methodological', citation))

        if not all_citations:
            self.console.print("\n[warning]No detailed citations available.[/warning]")
            return

        self.console.print(f"\n[info]Found {len(all_citations)} notable citations. Showing details...[/info]\n")

        for i, (citation_type, citation) in enumerate(all_citations, 1):
            # Create a table for each citation
            citation_table = Table(
                title=f"Citation #{i} - {citation_type}",
                box=box.SIMPLE,
                show_header=False,
                title_style="bold magenta"
            )
            citation_table.add_column("Field", style="bold cyan", width=15)
            citation_table.add_column("Value", style="white")

            def _get_field(obj, attr, default=""):
                if isinstance(obj, dict):
                    return obj.get(attr, default)
                return getattr(obj, attr, default)

            title = _get_field(citation, 'citing_paper_title', _get_field(citation, 'title', 'Unknown'))
            citation_table.add_row("Title", title)

            # Authors
            citing_authors = _get_field(citation, 'citing_authors', [])
            if citing_authors:
                authors_str = ', '.join(citing_authors[:5])
                if len(citing_authors) > 5:
                    authors_str += f" ... ({len(citing_authors)} total)"
                citation_table.add_row("Authors", authors_str)

            # Venue and year
            venue = _get_field(citation, 'venue', '')
            year = _get_field(citation, 'year', '')
            if venue:
                citation_table.add_row("Venue", venue)
            if year:
                citation_table.add_row("Year", str(year))

            # Links - THE KEY FEATURE!
            url = _get_field(citation, 'url', '')
            doi = _get_field(citation, 'doi', '')
            paper_id = _get_field(citation, 'paper_id', '')

            if url:
                citation_table.add_row("🔗 Link", f"[link={url}]{url}[/link]")
            if doi:
                citation_table.add_row("📖 DOI", doi)
            if paper_id:
                citation_table.add_row("🆔 S2 ID", paper_id)

            # Citation type
            citation_table.add_row("Type", f"[highlight]{citation_type}[/highlight]")

            self.console.print(citation_table)
            self.console.print()

            # Pause after every 5 citations
            if i % 5 == 0 and i < len(all_citations):
                if not Confirm.ask(f"[dim]Continue viewing citations? ({len(all_citations) - i} remaining)[/dim]", default=True):
                    break

        self.console.print(f"\n[success]✓ Displayed {min(i, len(all_citations))} citations[/success]")

    def _serialize_citation(self, citation: Any) -> Dict[str, Any]:
        """Convert citation objects or dicts into JSON-serializable dicts."""
        if isinstance(citation, dict):
            get = citation.get
            title = get('citing_paper_title') or get('title') or 'Unknown'
            authors = get('citing_authors') or []
            venue = get('venue', 'Unknown')
            year = get('year', 0)
            paper_id = get('paper_id', '')
            doi = get('doi', '')
            url = get('url', '')
        else:
            title = getattr(citation, 'citing_paper_title', getattr(citation, 'title', 'Unknown'))
            authors = getattr(citation, 'citing_authors', []) or []
            venue = getattr(citation, 'venue', 'Unknown')
            year = getattr(citation, 'year', 0)
            paper_id = getattr(citation, 'paper_id', '')
            doi = getattr(citation, 'doi', '')
            url = getattr(citation, 'url', '')

        return {
            'title': title,
            'authors': authors,
            'venue': venue,
            'year': year,
            'paper_id': paper_id,
            'doi': doi,
            'url': url
        }

    def export_results(self, result: Dict[str, Any]):
        """Export results to a file."""
        import json
        from datetime import datetime

        filename = Prompt.ask(
            "[bold]Enter filename[/bold]",
            default=f"impact_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )

        try:
            # Convert result to JSON-serializable format
            export_data = {
                'paper_title': result['paper_title'],
                'total_citations': result['total_citations'],
                'analyzed_citations': result['analyzed_citations'],
                'analysis_date': datetime.now().isoformat(),
                'high_profile_scholars': [
                    {
                        'name': (s.get('name') if isinstance(s, dict) else getattr(s, 'name', 'Unknown')),
                        'h_index': (s.get('h_index') if isinstance(s, dict) else getattr(s, 'h_index', None)),
                        'affiliation': (s.get('affiliation') if isinstance(s, dict) else getattr(s, 'affiliation', 'Unknown')),
                        'institution_type': (s.get('institution_type') if isinstance(s, dict) else getattr(s, 'institution_type', 'Unknown'))
                    }
                    for s in result.get('high_profile_scholars', [])
                ],
                'institutions': result.get('institutions', {}),
                'venues': {
                    'total': result.get('venues', {}).get('total', 0),
                    'unique': result.get('venues', {}).get('unique', 0),
                    'top_tier_percentage': result.get('venues', {}).get('top_tier_percentage', 0),
                    'most_common': result.get('venues', {}).get('most_common', [])
                },
                'influential_citations': [
                    self._serialize_citation(c)
                    for c in result.get('influential_citations', [])
                ],
                'methodological_citations': [
                    self._serialize_citation(c)
                    for c in result.get('methodological_citations', [])
                ]
            }

            with open(filename, 'w') as f:
                json.dump(export_data, f, indent=2)

            self.console.print(f"[success]✓ Report saved to {filename}[/success]")

        except Exception as e:
            self.console.print(f"[error]Error saving report: {str(e)}[/error]")

    def run(self):
        """Main application loop."""
        try:
            while True:
                self.clear_screen()
                self.show_header()

                choice = self.show_main_menu()

                if choice == "1":
                    self.analyze_paper()
                elif choice == "2":
                    self.browse_author_papers()
                elif choice == "3":
                    self.manage_settings()
                elif choice == "4":
                    self.show_help()
                elif choice == "5":
                    self.clear_screen()
                    self.console.print("\n[success]Thank you for using Citation Impact Analyzer![/success]")
                    self.console.print("[dim]Good luck with your research! 🎓[/dim]\n")
                    sys.exit(0)

        except KeyboardInterrupt:
            self.clear_screen()
            self.console.print("\n[warning]Application interrupted by user.[/warning]")
            self.console.print("[dim]Goodbye! 👋[/dim]\n")
            sys.exit(0)
        except Exception as e:
            self.console.print(f"\n[error]Unexpected error: {str(e)}[/error]")
            sys.exit(1)


def main():
    """Entry point for the terminal UI."""
    ui = TerminalUI()
    ui.run()


if __name__ == "__main__":
    main()
