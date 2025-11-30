"""
Settings management UI for CitationImpact.
"""
from typing import Dict, Any
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm, IntPrompt
from rich import box

from citationimpact.config import ConfigManager
from citationimpact import get_result_cache, get_author_cache


class SettingsManager:
    """Handles all settings-related UI functionality."""
    
    def __init__(self, console: Console, config_manager: ConfigManager, config: Dict[str, Any]):
        self.console = console
        self.config_manager = config_manager
        self.config = config
        self.config_dir = config_manager.get_config_path()
    
    def manage_settings(self):
        """Unified settings menu - view and configure in one place."""
        while True:
            self._clear_screen()
            self.console.print(Panel(
                "[title]⚙️  SETTINGS MANAGER[/title]",
                expand=False
            ))

            # Show config file location
            self.console.print(f"\n[dim]Configuration saved in: {self.config_dir}/config.json[/dim]\n")

            # Display current settings in a table
            table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
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
                ("6", "ScraperAPI Key",
                 "[dim]Set[/dim]" if self.config.get('scraper_api_key') else "[dim]Not set[/dim]",
                 "For reliable Google Scholar access (paid)"),
                ("7", "Default Semantic Scholar Author ID",
                 self.config.get('default_semantic_scholar_author_id') or "[dim]Not set[/dim]",
                 "Used when browsing author papers in API mode"),
                ("8", "Default Google Scholar Author ID",
                 self.config.get('default_google_scholar_author_id') or "[dim]Not set[/dim]",
                 "Used when browsing author papers in Google Scholar mode"),
                ("9", "Data Location & Cache",
                 "[dim]View/Manage[/dim]",
                 "Show where data is stored & manage cache"),
            ]

            for num, setting, value, desc in settings:
                table.add_row(num, setting, value, desc)

            self.console.print(table)

            # Menu options
            self.console.print("\n[info]Options:[/info]")
            self.console.print("  • Enter [highlight]1-9[/highlight] to edit a setting")
            self.console.print("  • Enter [highlight]r[/highlight] to reset to defaults")
            self.console.print("  • Enter [highlight]b[/highlight] to go back to main menu")

            choice = Prompt.ask("\n[bold]Select option[/bold]", default="b").lower()

            if choice == 'b':
                break
            elif choice == 'r':
                if Confirm.ask("[warning]Reset all settings to defaults?[/warning]", default=False):
                    self.config_manager.reset()
                    self.config.update(self.config_manager.get_all())
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
                self._edit_scraper_api_key()
            elif choice == '7':
                self._edit_default_semantic_author_id()
            elif choice == '8':
                self._edit_default_google_author_id()
            elif choice == '9':
                self._manage_data_and_cache()
            else:
                self.console.print("[error]Invalid option[/error]")
                Prompt.ask("\nPress Enter to continue")

    def _clear_screen(self):
        """Clear the terminal screen."""
        self.console.clear()

    def _edit_h_index_threshold(self):
        """Edit h-index threshold setting."""
        self.console.print("\n[info]High-Profile Scholar Threshold[/info]")
        self.console.print(f"Current value: [highlight]{self.config['h_index_threshold']}[/highlight]")
        self.console.print("[dim]Scholars with h-index ≥ this value are considered 'high-profile'[/dim]")

        new_value = IntPrompt.ask("\nEnter new threshold", default=self.config['h_index_threshold'])

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

        new_value = IntPrompt.ask("\nEnter new maximum", default=self.config['max_citations'])

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
        
        options = [
            ("api", "Semantic Scholar + OpenAlex", "fast, recommended"),
            ("comprehensive", "S2 + Google Scholar combined", "most complete, slower"),
            ("google_scholar", "Web scraping only", "slow, may hit CAPTCHAs"),
        ]
        
        self.console.print()
        current_idx = 1
        for i, (key, name, desc) in enumerate(options, 1):
            marker = "→" if self.config['data_source'] == key else " "
            self.console.print(f"  {marker} [bold]{i}[/bold]. {key} - {name} [dim]({desc})[/dim]")
            if self.config['data_source'] == key:
                current_idx = i
        
        self.console.print()
        choice = Prompt.ask("Select option", choices=["1", "2", "3"], default=str(current_idx))
        
        new_value = options[int(choice) - 1][0]
        self.config['data_source'] = new_value
        self.config_manager.set('data_source', new_value)
        self.console.print(f"[success]✓ Data source set to '{new_value}'[/success]")
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

    def _edit_scraper_api_key(self):
        """Edit ScraperAPI key setting."""
        self.console.print("\n[info]ScraperAPI Key (For Google Scholar)[/info]")
        current = "Set" if self.config.get('scraper_api_key') else "Not set"
        self.console.print(f"Current: [highlight]{current}[/highlight]")
        self.console.print()
        self.console.print("[dim]ScraperAPI handles anti-bot detection for Google Scholar.[/dim]")
        self.console.print("[dim]This is the most reliable way to use Google Scholar/Comprehensive mode.[/dim]")
        self.console.print()
        self.console.print("[bold]Get your API key at:[/bold] https://www.scraperapi.com/")

        if Confirm.ask("\nDo you want to set/change your ScraperAPI key?", default=False):
            api_key = Prompt.ask("Enter ScraperAPI key (or leave empty to clear)")
            if api_key.strip():
                self.config['scraper_api_key'] = api_key.strip()
                self.config_manager.set('scraper_api_key', api_key.strip())
                self.console.print("[success]✓ ScraperAPI key saved[/success]")
            else:
                self.config['scraper_api_key'] = None
                self.config_manager.set('scraper_api_key', None)
                self.console.print("[success]✓ ScraperAPI key cleared[/success]")

        Prompt.ask("\nPress Enter to continue")

    def _edit_default_semantic_author_id(self):
        """Edit default Semantic Scholar author ID."""
        self.console.print("\n[info]Default Semantic Scholar Author ID[/info]")
        current = self.config.get('default_semantic_scholar_author_id') or "Not set"
        self.console.print(f"Current: [highlight]{current}[/highlight]")
        self.console.print("[dim]Find your ID at: semanticscholar.org/me[/dim]")

        author_id = Prompt.ask("\nEnter author ID (or leave empty to clear)", default="")
        if author_id.strip():
            self.config['default_semantic_scholar_author_id'] = author_id.strip()
            self.config_manager.set('default_semantic_scholar_author_id', author_id.strip())
            self.console.print("[success]✓ Author ID saved[/success]")
        else:
            self.config['default_semantic_scholar_author_id'] = None
            self.config_manager.set('default_semantic_scholar_author_id', None)
            self.console.print("[success]✓ Author ID cleared[/success]")

        Prompt.ask("\nPress Enter to continue")

    def _edit_default_google_author_id(self):
        """Edit default Google Scholar author ID."""
        self.console.print("\n[info]Default Google Scholar Author ID[/info]")
        current = self.config.get('default_google_scholar_author_id') or "Not set"
        self.console.print(f"Current: [highlight]{current}[/highlight]")
        self.console.print("[dim]Find your ID in your Google Scholar profile URL[/dim]")
        self.console.print("[dim]Example: scholar.google.com/citations?user=[bold]waVL0PgAAAAJ[/bold][/dim]")

        author_id = Prompt.ask("\nEnter author ID (or leave empty to clear)", default="")
        if author_id.strip():
            self.config['default_google_scholar_author_id'] = author_id.strip()
            self.config_manager.set('default_google_scholar_author_id', author_id.strip())
            self.console.print("[success]✓ Author ID saved[/success]")
        else:
            self.config['default_google_scholar_author_id'] = None
            self.config_manager.set('default_google_scholar_author_id', None)
            self.console.print("[success]✓ Author ID cleared[/success]")

        Prompt.ask("\nPress Enter to continue")

    def _manage_data_and_cache(self):
        """Show data location and cache management options."""
        import os
        from pathlib import Path
        
        self._clear_screen()
        self.console.print(Panel(
            "[title]📂 DATA LOCATION & CACHE MANAGEMENT[/title]",
            expand=False
        ))

        config_dir = Path(self.config_dir)
        cache_dir = config_dir / "cache"
        author_cache_dir = config_dir / "author_cache"

        self.console.print(f"\n[bold]Configuration Directory:[/bold]")
        self.console.print(f"  {config_dir}")
        self.console.print(f"\n[bold]Analysis Cache:[/bold]")
        self.console.print(f"  {cache_dir}")
        self.console.print(f"\n[bold]Author Profile Cache:[/bold]")
        self.console.print(f"  {author_cache_dir}")

        # Calculate cache stats
        if cache_dir.exists() or author_cache_dir.exists():
            total_size = 0
            cache_count = 0
            author_cache_count = 0

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
            self.console.print("\n[warning]⚠️  Data directory not created yet[/warning]")

        # Options
        self.console.print("\n[info]Options:[/info]")
        self.console.print("  1. Open folder in file manager")
        self.console.print("  2. [cyan]Select & delete paper analysis cache[/cyan]")
        self.console.print("  3. [cyan]Select & delete author profiles[/cyan]")
        self.console.print("  4. Clear ALL analysis results")
        self.console.print("  5. Clear ALL author profiles")
        self.console.print("  6. Clear ALL caches")
        self.console.print("  b. Go back")

        choice = Prompt.ask("\n[bold]Select option[/bold]", default="b").lower()

        if choice == '1':
            self._open_folder(config_dir)
        elif choice == '2':
            self._select_and_delete_paper_cache()
        elif choice == '3':
            self._select_and_delete_author_cache()
        elif choice == '4':
            if Confirm.ask("[warning]Clear ALL analysis result cache?[/warning]", default=False):
                result_cache = get_result_cache()
                count = result_cache.clear()
                self.console.print(f"[success]✓ Cleared {count} analysis results[/success]")
        elif choice == '5':
            if Confirm.ask("[warning]Clear ALL author profile cache?[/warning]", default=False):
                author_cache = get_author_cache()
                count = author_cache.clear()
                self.console.print(f"[success]✓ Cleared {count} author profiles[/success]")
        elif choice == '6':
            if Confirm.ask("[warning]Clear ALL caches?[/warning]", default=False):
                result_cache = get_result_cache()
                author_cache = get_author_cache()
                count1 = result_cache.clear()
                count2 = author_cache.clear()
                self.console.print(f"[success]✓ Cleared {count1} analysis results and {count2} author profiles[/success]")

        Prompt.ask("\nPress Enter to continue")

    def _open_folder(self, path):
        """Open folder in file manager."""
        import platform
        import subprocess
        
        try:
            if platform.system() == 'Windows':
                import os
                os.startfile(path)
            elif platform.system() == 'Darwin':
                subprocess.run(['open', path])
            else:
                subprocess.run(['xdg-open', path])
            self.console.print("[success]✓ Opened folder in file manager[/success]")
        except Exception as e:
            self.console.print(f"[error]Could not open folder: {e}[/error]")
            self.console.print(f"[info]Manual path: {path}[/info]")

    def _select_and_delete_paper_cache(self):
        """Select specific paper analysis results to delete."""
        self._clear_screen()
        self.console.print(Panel("[title]📄 SELECT PAPER CACHE TO DELETE[/title]", expand=False))
        
        result_cache = get_result_cache()
        cache_entries = result_cache.list_cache()
        
        if not cache_entries:
            self.console.print("\n[dim]No cached paper analyses found.[/dim]")
            Prompt.ask("\nPress Enter to continue")
            return
        
        table = Table(
            title=f"Cached Paper Analyses ({len(cache_entries)} entries)",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan"
        )
        
        table.add_column("#", style="bold magenta", width=3)
        table.add_column("Paper Title", style="bold", max_width=50)
        table.add_column("Citations", justify="right", style="yellow", width=10)
        table.add_column("Cached", style="dim", width=12)
        table.add_column("Data Source", style="cyan", width=15)
        
        for idx, entry in enumerate(cache_entries, 1):
            title = entry.get('paper_title', 'Unknown')[:50]
            if len(entry.get('paper_title', '')) > 50:
                title += '...'
            
            citations = str(entry.get('analyzed_citations', 'N/A'))
            cached_at = entry.get('cached_at', '')[:10]
            data_source = entry.get('data_source', 'api')
            
            table.add_row(str(idx), title, citations, cached_at, data_source)
        
        self.console.print()
        self.console.print(table)
        
        self.console.print("\n[info]Enter numbers to delete (comma-separated), 'all' or 'b' to go back[/info]")
        choice = Prompt.ask("\n[bold]Delete which entries?[/bold]", default="b")
        
        if choice.lower() == 'b':
            return
        
        if choice.lower() == 'all':
            if Confirm.ask("[warning]Delete ALL cached paper analyses?[/warning]", default=False):
                count = result_cache.clear()
                self.console.print(f"[success]✓ Deleted {count} entries[/success]")
        else:
            try:
                indices = [int(x.strip()) - 1 for x in choice.split(',')]
                deleted = 0
                for idx in sorted(indices, reverse=True):
                    if 0 <= idx < len(cache_entries):
                        entry = cache_entries[idx]
                        cache_key = entry.get('cache_key', '')
                        if cache_key and result_cache.delete(cache_key):
                            deleted += 1
                
                self.console.print(f"[success]✓ Deleted {deleted} entries[/success]")
            except ValueError:
                self.console.print("[error]Invalid input. Enter numbers separated by commas.[/error]")
        
        Prompt.ask("\nPress Enter to continue")

    def _select_and_delete_author_cache(self):
        """Select specific author profiles to delete."""
        self._clear_screen()
        self.console.print(Panel("[title]👤 SELECT AUTHOR PROFILES TO DELETE[/title]", expand=False))
        
        author_cache = get_author_cache()
        profiles = author_cache.list_profiles()
        
        if not profiles:
            self.console.print("\n[dim]No cached author profiles found.[/dim]")
            Prompt.ask("\nPress Enter to continue")
            return
        
        profiles.sort(key=lambda x: x.get('name', '').lower())
        
        table = Table(
            title=f"Cached Author Profiles ({len(profiles)} entries)",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan"
        )
        
        table.add_column("#", style="bold magenta", width=3)
        table.add_column("Name", style="bold", max_width=25)
        table.add_column("H-Index", justify="right", style="yellow", width=8)
        table.add_column("Source", style="dim", width=8)
        table.add_column("Affiliation", max_width=30)
        
        for idx, profile in enumerate(profiles, 1):
            name = profile.get('name', 'Unknown')
            h_index = str(profile.get('h_index', 0))
            h_source = profile.get('h_index_source', '')
            source_str = "GS" if h_source == 'google_scholar' else "S2" if h_source else ""
            affiliation = profile.get('affiliation', 'Unknown')
            if len(affiliation) > 30:
                affiliation = affiliation[:27] + "..."
            
            table.add_row(str(idx), name, h_index, source_str, affiliation)
        
        self.console.print()
        self.console.print(table)
        
        self.console.print("\n[info]Enter numbers to delete (comma-separated), 'all' or 'b' to go back[/info]")
        choice = Prompt.ask("\n[bold]Delete which profiles?[/bold]", default="b")
        
        if choice.lower() == 'b':
            return
        
        if choice.lower() == 'all':
            if Confirm.ask("[warning]Delete ALL cached author profiles?[/warning]", default=False):
                count = author_cache.clear()
                self.console.print(f"[success]✓ Deleted {count} profiles[/success]")
        else:
            try:
                indices = [int(x.strip()) - 1 for x in choice.split(',')]
                deleted = 0
                for idx in sorted(indices, reverse=True):
                    if 0 <= idx < len(profiles):
                        profile = profiles[idx]
                        name = profile.get('name', '')
                        if name and author_cache.delete_profile(name=name):
                            deleted += 1
                
                self.console.print(f"[success]✓ Deleted {deleted} profiles[/success]")
            except ValueError:
                self.console.print("[error]Invalid input. Enter numbers separated by commas.[/error]")
        
        Prompt.ask("\nPress Enter to continue")

