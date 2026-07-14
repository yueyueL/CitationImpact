"""
Analysis results display for CitationImpact.
"""
import os
from typing import Dict, Any, List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt
from rich.markup import escape
from rich import box

from .components.prompts import (
    get_field, make_clickable, format_university_rankings,
    make_author_clickable, make_paper_clickable, get_adaptive_widths
)
from .components.tables import (
    create_overview_table,
    create_institution_table,
    create_venue_table,
    create_scholar_table,
    create_papers_table,
    confidence_marker,
    CONFIDENCE_LEGEND,
)
from .drill_down import (
    show_institution_details,
    show_venue_details,
    show_all_authors_view
)


class AnalysisView:
    """Handles displaying analysis results."""

    def __init__(self, console: Console, config: Optional[Dict[str, Any]] = None):
        self.console = console
        self.config = config or {}

    def _h_index_threshold(self) -> int:
        """The user-configured high-profile h-index threshold."""
        return self.config.get('h_index_threshold', 20)

    def display_results(self, result: Dict[str, Any]):
        """Display analysis results with interactive drill-down."""
        if not result:
            self.console.print("[error]No results to display[/error]")
            return

        if result.get('error'):
            self.console.print(f"\n[error]Analysis Error: {result['error']}[/error]")
            return

        while True:
            self._render_summary_screen(result)
            
            self.console.print("\n[bold cyan]━━━ DRILL-DOWN OPTIONS ━━━[/bold cyan]")
            self.console.print("  [highlight]1[/highlight] 📋 Grant Impact Summary (copy-ready statements)")
            self.console.print("  [highlight]2[/highlight] 📄 All Citing Papers")
            self.console.print("  [highlight]3[/highlight] 👥 All Citing Authors (sort by h-index)")
            self.console.print("  [highlight]4[/highlight] 🏛️  By Institution")
            self.console.print("  [highlight]5[/highlight] 📚 By Venue")
            self.console.print("  [highlight]6[/highlight] 📈 Timeline & Stats")
            self.console.print("  [highlight]7[/highlight] 💬 How Your Work Is Used (citation contexts)")
            self.console.print("  [highlight]8[/highlight] 🌳 Citation Tree")
            self.console.print("  [highlight]e[/highlight] 💾 Export Report (markdown/latex/csv/bibtex/json)")
            self.console.print("  [highlight]b[/highlight] Back to Menu")

            choice = Prompt.ask("\n[bold]Select option[/bold]", default="b").lower()

            if choice == 'b':
                break
            elif choice == '1':
                self.show_grant_impact_summary(result)
            elif choice == '2':
                self.show_all_citing_papers(result)
            elif choice == '3':
                # Combined view: All authors sorted by h-index (includes high-profile)
                show_all_authors_view(self.console, result)
            elif choice == '4':
                show_institution_details(self.console, result)
            elif choice == '5':
                show_venue_details(self.console, result)
            elif choice == '6':
                self.show_deep_insights(result)
            elif choice == '7':
                self.show_citation_contexts(result)
            elif choice == '8':
                from .tree_view import show_citation_tree
                show_citation_tree(self.console, result)
            elif choice == 'e':
                self.export_results(result)

    def _render_summary_screen(self, result: Dict[str, Any]) -> None:
        """Clear screen and render summary contents."""
        self.console.clear()
        self._render_summary(result)

    def _render_summary(self, result: Dict[str, Any]) -> None:
        """Render the main summary panels."""
        # Data-quality banner FIRST (data_quality is absent on results from
        # older caches, so every access is defensive)
        data_quality = result.get('data_quality')
        if not isinstance(data_quality, dict):
            data_quality = {}
        dq_warnings = [str(w) for w in (data_quality.get('warnings') or []) if w]
        if data_quality.get('degraded'):
            warning_text = "\n".join(f"⚠ {escape(w)}" for w in dq_warnings) or \
                "⚠ API failures occurred during this analysis; data may be incomplete."
            self.console.print(Panel(
                warning_text,
                title="⚠ Data May Be Incomplete",
                border_style="yellow",
                padding=(0, 2)
            ))
        elif dq_warnings:
            self.console.print(f"[dim]Note: {escape(' '.join(dq_warnings))}[/dim]")

        # Header
        header_panel = Panel(
            f"[bold]{result.get('paper_title', 'Analysis')}[/bold]",
            title="📊 Impact Analysis Results",
            border_style="cyan",
            padding=(1, 2)
        )
        self.console.print(header_panel)
        self.console.print("[dim]Tip: Cmd/Ctrl + click underlined titles to open them in your browser.[/dim]\n")

        # Overview metrics
        overview_table = create_overview_table(result)
        self.console.print(Panel(overview_table, title="📈 Overview", border_style="cyan"))

        # Field-normalized impact + independence (when available)
        extra_lines = []
        field_normalized = result.get('field_normalized')
        if field_normalized:
            fwci = field_normalized.get('fwci')
            if fwci is not None:
                extra_lines.append(
                    f"[bold]FWCI:[/bold] [yellow]{fwci:.2f}[/yellow] "
                    f"[dim](1.0 = world average for field & year, via OpenAlex)[/dim]"
                )
            percentile = field_normalized.get('citation_percentile')
            if percentile is not None:
                pct = percentile * 100 if percentile <= 1 else percentile
                badge = ""
                if field_normalized.get('is_top_1_percent'):
                    badge = " [bold green]TOP 1%[/bold green]"
                elif field_normalized.get('is_top_10_percent'):
                    badge = " [bold green]TOP 10%[/bold green]"
                extra_lines.append(
                    f"[bold]Field citation percentile:[/bold] [yellow]{pct:.0f}[/yellow]{badge}"
                )
        self_stats = result.get('self_citation_stats')
        if self_stats:
            extra_lines.append(
                f"[bold]Independent citations:[/bold] [yellow]{self_stats.get('independent_count', 0)}"
                f"/{result.get('analyzed_citations', 0)}[/yellow] "
                f"[dim]({self_stats.get('independent_percentage', 0):.0f}% not self-citations)[/dim]"
            )
        if extra_lines:
            self.console.print(Panel(
                "\n".join(extra_lines),
                title="🌍 Field-Normalized Impact",
                border_style="yellow"
            ))

        # Quick Impact Highlights (for grants) - show key numbers
        impact_stats = result.get('impact_stats', {})
        if impact_stats:
            thresholds = impact_stats.get('citation_thresholds', {})
            author_stats = impact_stats.get('author_stats', {})
            inst_stats = impact_stats.get('institution_stats', {})

            # Profile quality line: how reliably citing authors were matched
            # (counts may be absent on results served from an older cache)
            id_count = author_stats.get('id_matched_count', 0) or 0
            verified_count = author_stats.get('verified_count', 0) or 0
            name_only_count = author_stats.get('name_only_count', 0) or 0
            if (id_count + verified_count + name_only_count) > 0:
                self.console.print(
                    f"[dim]Author profiles: {id_count} ID-matched, "
                    f"{verified_count} verified, {name_only_count} name-only[/dim]"
                )

            highlights = []
            if author_stats.get('high_profile_count', 0) > 0:
                highlights.append(f"[green]✓[/green] {author_stats['high_profile_count']} high-profile scholars (h≥{self._h_index_threshold()})")
            if inst_stats.get('from_qs_top_100', 0) > 0:
                highlights.append(f"[green]✓[/green] {inst_stats['from_qs_top_100']} from QS Top 100")
            if thresholds.get('over_100', 0) > 0:
                highlights.append(f"[green]✓[/green] {thresholds['over_100']} highly-cited (100+) papers cite you")
            
            if highlights:
                highlight_text = "  •  ".join(highlights)
                self.console.print(Panel(
                    f"[bold]Grant Highlights:[/bold] {highlight_text}\n[dim]→ Select option 1 for full grant-ready statements[/dim]",
                    title="📋 Impact Summary",
                    border_style="green"
                ))

        # Institution summary
        institutions = result.get('institutions', {})
        summary_counts = {k: v for k, v in institutions.items() if isinstance(v, (int, float))}
        if summary_counts:
            inst_table = create_institution_table(institutions)
            self.console.print(Panel(inst_table, title="🏛️ Institution Summary", border_style="magenta"))
        else:
            self.console.print(Panel("[dim]No institution data available[/dim]", title="🏛️ Institution Summary", border_style="magenta"))

        # International reach: known citing-author countries (absent on results
        # from older caches; '' / unknown countries are never counted)
        country_counts = (result.get('countries') or {}).get('counts') or {}
        if country_counts:
            top_countries = sorted(country_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
            top_display = ", ".join(f"{code} {count}" for code, count in top_countries)
            self.console.print(
                f"[dim]International reach: {len(country_counts)} countries (top: {top_display})[/dim]"
            )

        # Venue summary
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
                rankings = venues.get('rankings', {})
                top_table = create_venue_table(top_venues, rankings)
                self.console.print(Panel(top_table, title="🏆 Top Citing Venues", border_style="green"))

        # High-profile scholars
        scholars = result.get('high_profile_scholars', [])[:5]
        if scholars:
            scholar_table = create_scholar_table()
            for idx, scholar in enumerate(scholars, 1):
                info = self._extract_scholar_info(scholar)
                institution = info['affiliation'] or 'Unknown'
                inst_type = info['institution_type'] or ''
                if inst_type and inst_type.lower() not in ('n/a', 'other'):
                    institution += f" ({inst_type})"
                ranking_display = format_university_rankings(info.get('university_rankings', {}))
                if ranking_display != "N/A":
                    institution += f" • {ranking_display}"
                if len(institution) > 30:
                    institution = institution[:27] + "..."
                citing_display = make_clickable(info['citing_paper'] or 'Unknown', info['paper_url'], info['paper_id'])
                # Make author name clickable to their Google Scholar profile
                author_name = info['name']
                if info.get('google_scholar_id'):
                    gs_url = f"https://scholar.google.com/citations?user={info['google_scholar_id']}"
                    author_name = f"[link={gs_url}]{info['name']}[/link]"
                # Match-confidence marker: how reliably this author was matched
                author_name = f"{author_name} {confidence_marker(info.get('match_confidence', ''))}"
                scholar_table.add_row(str(idx), author_name, str(info['h_index_display']), institution, citing_display)
            self.console.print(Panel(scholar_table, title="🌟 High-Profile Scholars (Top 5)", border_style="magenta"))
            self.console.print(f"[dim]{CONFIDENCE_LEGEND}[/dim]")
        else:
            self.console.print(Panel("[dim]No high-profile scholars identified yet[/dim]", title="🌟 High-Profile Scholars", border_style="magenta"))

        # Influential citations
        influential = result.get('influential_citations', [])[:3]
        if influential:
            inf_table = Table(box=box.ROUNDED, header_style="bold cyan")
            inf_table.add_column("#", style="bold magenta", justify="right", width=4)
            inf_table.add_column("Citing Paper", style="bold")
            inf_table.add_column("Year", justify="center", style="bold yellow", width=6)
            inf_table.add_column("Venue", style="cyan", max_width=30)
            for idx, citation in enumerate(influential, 1):
                preview = self._format_citation_preview(citation)
                title_display = make_clickable(preview['title'], preview['url'], preview['paper_id'])
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
        h_index = get_field(scholar, 'h_index', 0)
        h_index_display = get_field(scholar, 'h_index_display', str(h_index))
        citing_papers = get_field(scholar, 'citing_papers', [])
        citing_paper = get_field(scholar, 'citing_paper', 'Unknown')
        
        # If multiple citing papers, show count
        if citing_papers and len(citing_papers) > 1:
            citing_paper = f"{citing_papers[0][:30]}... (+{len(citing_papers)-1} more)"
        
        return {
            'name': get_field(scholar, 'name', 'Unknown'),
            'h_index': h_index,
            'h_index_display': h_index_display,  # Shows source (e.g., "9 (GS)")
            'affiliation': get_field(scholar, 'affiliation', 'Unknown'),
            'institution_type': get_field(scholar, 'institution_type', 'N/A'),
            'citing_paper': citing_paper,
            'citing_papers': citing_papers,
            'paper_url': get_field(scholar, 'paper_url', ''),
            'paper_id': get_field(scholar, 'paper_id', ''),
            'google_scholar_id': get_field(scholar, 'google_scholar_id', ''),
            'semantic_scholar_id': get_field(scholar, 'semantic_scholar_id', ''),
            'match_confidence': get_field(scholar, 'match_confidence', '') or '',
            'university_rankings': get_field(scholar, 'university_rankings', {}) or {},
            'university_rank': get_field(scholar, 'university_rank', None),
            'university_tier': get_field(scholar, 'university_tier', None),
            'usnews_rank': get_field(scholar, 'usnews_rank', None),
            'usnews_tier': get_field(scholar, 'usnews_tier', None),
            'primary_university_source': get_field(scholar, 'primary_university_source', None),
        }

    def _format_citation_preview(self, citation: Any) -> Dict[str, Any]:
        """Extract title, venue, year, url, paper_id from citation."""
        title = get_field(citation, 'citing_paper_title', get_field(citation, 'title', 'Unknown'))
        venue = get_field(citation, 'venue', 'Unknown')
        year = get_field(citation, 'year', 'N/A')
        url = get_field(citation, 'url', '')
        paper_id = get_field(citation, 'paper_id', '')
        return {
            'title': title,
            'venue': venue,
            'year': year,
            'url': url,
            'paper_id': paper_id
        }

    def _extract_paper_info(self, citation) -> Dict[str, Any]:
        """Extract paper info from a citation object or dict."""
        if isinstance(citation, dict):
            return {
                'title': citation.get('citing_paper_title', citation.get('title', 'Unknown')),
                'authors': citation.get('citing_authors', []),
                'venue': citation.get('venue', 'Unknown'),
                'year': citation.get('year', 0),
                'paper_id': citation.get('paper_id', ''),
                'doi': citation.get('doi', ''),
                'url': citation.get('url', ''),
                'citation_count': citation.get('citation_count', 0),
                'is_influential': citation.get('is_influential', False)
            }
        else:
            return {
                'title': getattr(citation, 'citing_paper_title', getattr(citation, 'title', 'Unknown')),
                'authors': getattr(citation, 'citing_authors', []) or [],
                'venue': getattr(citation, 'venue', 'Unknown'),
                'year': getattr(citation, 'year', 0),
                'paper_id': getattr(citation, 'paper_id', ''),
                'doi': getattr(citation, 'doi', ''),
                'url': getattr(citation, 'url', ''),
                'citation_count': getattr(citation, 'citation_count', 0),
                'is_influential': getattr(citation, 'is_influential', False)
            }

    def show_all_citing_papers(self, result: Dict[str, Any]):
        """
        Show ALL citing papers with clickable links.
        
        This is what researchers really want - see exactly who cites them!
        """
        self.console.clear()
        widths = get_adaptive_widths(self.console.width or 120)
        
        self.console.print(Panel(
            "[title]📄 ALL CITING PAPERS[/title]\n[dim]Click paper titles to open in browser[/dim]",
            expand=False,
            border_style="cyan"
        ))
        
        # Gather all citations from various sources
        all_papers = []
        
        # From influential citations
        for c in result.get('influential_citations', []):
            paper = self._extract_paper_info(c)
            paper['is_influential'] = True
            all_papers.append(paper)
        
        # From all authors (which have citing papers)
        seen_titles = {p['title'].lower() for p in all_papers}
        for author in result.get('all_authors', []):
            if isinstance(author, dict):
                citing_paper = author.get('citing_paper', '')
                paper_url = author.get('paper_url', '')
                paper_id = author.get('paper_id', '')
                if citing_paper and citing_paper.lower() not in seen_titles:
                    all_papers.append({
                        'title': citing_paper,
                        'url': paper_url,
                        'paper_id': paper_id,
                        'year': author.get('year', 0),
                        'venue': author.get('venue', 'Unknown'),
                        'authors': [author.get('name', 'Unknown')],
                        'is_influential': False,
                        'citation_count': author.get('paper_citations', 0)
                    })
                    seen_titles.add(citing_paper.lower())
        
        if not all_papers:
            self.console.print("[warning]No citing papers found[/warning]")
            Prompt.ask("\nPress Enter to return")
            return
        
        # Sort options
        self.console.print(f"\n[info]Found {len(all_papers)} citing papers[/info]")
        self.console.print("\n[dim]Sort by: [1] Year (newest) [2] Citations [3] Venue[/dim]")
        sort_choice = Prompt.ask("Sort", default="1")
        
        if sort_choice == "2":
            all_papers.sort(key=lambda x: x.get('citation_count', 0), reverse=True)
        elif sort_choice == "3":
            all_papers.sort(key=lambda x: x.get('venue', 'ZZZ'))
        else:
            all_papers.sort(key=lambda x: x.get('year', 0), reverse=True)
        
        # Create adaptive table
        table = Table(box=box.ROUNDED, expand=True, header_style="bold cyan")
        table.add_column("#", style="bold magenta", width=widths['rank'])
        table.add_column("Paper (click)", style="bold", max_width=widths['paper'] + 10)
        table.add_column("Year", justify="center", style="yellow", width=widths['year'])
        table.add_column("Venue", style="dim", max_width=widths['venue'])
        table.add_column("Cites", justify="right", style="green", width=6)
        table.add_column("🌟", justify="center", width=3)  # Influential marker
        
        for i, paper in enumerate(all_papers[:50], 1):  # Show up to 50
            # Make paper title clickable using helper
            title_display = make_paper_clickable(paper, widths['paper'] + 10)
            
            year = str(paper.get('year', 'N/A')) if paper.get('year') else 'N/A'
            venue = paper.get('venue', 'Unknown')
            if len(venue) > widths['venue']:
                venue = venue[:widths['venue']-3] + "..."
            cites = str(paper.get('citation_count', 0)) if paper.get('citation_count') else '-'
            influential = "⭐" if paper.get('is_influential') else ""
            
            table.add_row(str(i), title_display, year, venue, cites, influential)
        
        self.console.print()
        self.console.print(table)
        
        if len(all_papers) > 50:
            self.console.print(f"\n[dim]Showing 50 of {len(all_papers)} papers. Export for full list.[/dim]")
        
        self.console.print("\n[dim]⭐ = Influential citation (builds on your methodology)[/dim]")
        
        # Option to view specific paper's authors
        self.console.print("\n[info]Enter paper # to see its authors, or 'b' to go back[/info]")
        choice = Prompt.ask("Select", default="b")
        
        if choice.lower() != 'b':
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(all_papers):
                    paper = all_papers[idx]
                    self._show_paper_authors(paper, result)
            except ValueError:
                pass
    
    def _show_paper_authors(self, paper: Dict, result: Dict[str, Any]):
        """Show authors of a specific citing paper with clickable profiles"""
        widths = get_adaptive_widths(self.console.width or 120)
        self.console.print(f"\n[bold]Authors of: {paper.get('title', 'Unknown')[:60]}...[/bold]")
        
        # Find authors for this paper
        paper_title_lower = paper.get('title', '').lower()
        authors_found = []
        
        for author in result.get('all_authors', []):
            if isinstance(author, dict):
                citing_paper = author.get('citing_paper', '').lower()
                if citing_paper == paper_title_lower or paper_title_lower in citing_paper:
                    authors_found.append(author)
        
        if authors_found:
            table = Table(box=box.SIMPLE, expand=True)
            table.add_column("Author (click for profile)", style="bold", max_width=widths['author'])
            table.add_column("H", justify="right", style="yellow", width=widths['h_index'])
            table.add_column("Affiliation", style="cyan", max_width=widths['institution'])
            
            for author in authors_found:
                h_index = author.get('h_index', 'N/A')
                h_source = author.get('h_index_source', '')
                h_display = f"{h_index} [dim](GS)[/dim]" if h_source == 'google_scholar' else str(h_index)
                
                affiliation = author.get('affiliation', 'Unknown')
                if len(affiliation) > widths['institution']:
                    affiliation = affiliation[:widths['institution']-3] + "..."
                
                # Make author clickable
                author_display = make_author_clickable(author, widths['author'])
                
                table.add_row(author_display, h_display, affiliation)
            
            self.console.print(table)
        else:
            self.console.print("[dim]Author details not available for this paper[/dim]")
        
        Prompt.ask("\nPress Enter to continue")

    def show_grant_impact_summary(self, result: Dict[str, Any]):
        """
        Show grant-friendly impact summary with copy-ready statements.
        
        This is THE KEY FEATURE for researchers - ready-to-use text for grants!
        """
        self.console.clear()
        self.console.print(Panel(
            "[title]📋 GRANT IMPACT SUMMARY[/title]\n[dim]Copy-ready statements for grants, tenure files, and funding applications[/dim]",
            expand=False,
            border_style="green"
        ))
        
        impact_stats = result.get('impact_stats', {})
        
        # 1. Ready-to-use impact statements
        # The analyzer hardcodes "h-index ≥ 20" in its copy-ready statements;
        # substitute the user's configured threshold so the text stays
        # factually correct with non-default settings.
        threshold = self._h_index_threshold()
        statements = [
            s.replace('h-index ≥ 20', f'h-index ≥ {threshold}')
            for s in impact_stats.get('summary_statements', [])
        ]
        if statements:
            self.console.print("\n[bold green]✨ Ready-to-Use Impact Statements[/bold green]")
            self.console.print("[dim]Copy these directly into your grant proposal:[/dim]\n")
            
            for i, statement in enumerate(statements, 1):
                self.console.print(f"  [cyan]{i}.[/cyan] {statement}")
            self.console.print()
        
        # 2. Key metrics table
        self.console.print("[bold yellow]📊 Key Metrics for Grants[/bold yellow]\n")
        
        metrics_table = Table(box=box.ROUNDED, show_header=False)
        metrics_table.add_column("Metric", style="bold cyan")
        metrics_table.add_column("Value", style="bold yellow", justify="right")
        metrics_table.add_column("Context", style="dim")
        
        author_stats = impact_stats.get('author_stats', {})
        inst_stats = impact_stats.get('institution_stats', {})
        thresholds = impact_stats.get('citation_thresholds', {})
        
        metrics_table.add_row(
            "High-Profile Scholars",
            str(author_stats.get('high_profile_count', 0)),
            f"Authors with h-index ≥ {self._h_index_threshold()} citing your work"
        )
        metrics_table.add_row(
            "Max Citing Author H-Index",
            str(author_stats.get('max_h_index', 0)),
            "Highest h-index among citing authors"
        )
        metrics_table.add_row(
            "From QS Top 100 Universities",
            str(inst_stats.get('from_qs_top_100', 0)),
            "Authors from world-leading institutions"
        )
        metrics_table.add_row(
            "Highly-Cited Papers (100+)",
            str(thresholds.get('over_100', 0)),
            "Papers with 100+ citations that cite you"
        )
        metrics_table.add_row(
            "Recent Citations (2 yrs)",
            str(impact_stats.get('recent_citations_count', 0)),
            "Shows continued relevance"
        )
        metrics_table.add_row(
            "University Researchers",
            f"{inst_stats.get('university_percentage', 0):.0f}%",
            "Academic adoption rate"
        )

        field_normalized = result.get('field_normalized')
        if field_normalized and field_normalized.get('fwci') is not None:
            metrics_table.add_row(
                "Field-Weighted Citation Impact",
                f"{field_normalized['fwci']:.2f}",
                "1.0 = world average for field & year (OpenAlex)"
            )
        self_stats = result.get('self_citation_stats')
        if self_stats:
            metrics_table.add_row(
                "Independent Citations",
                f"{self_stats.get('independent_percentage', 0):.0f}%",
                "Citations not involving the original authors"
            )

        self.console.print(metrics_table)
        
        # 3. Highly-cited papers that cite you
        highly_cited = impact_stats.get('highly_cited_citing_papers', [])
        if highly_cited:
            self.console.print("\n[bold magenta]🏆 Highly-Cited Papers That Cite You[/bold magenta]")
            self.console.print("[dim]Use these as evidence of impact in high-profile research:[/dim]\n")
            
            hc_table = Table(box=box.SIMPLE)
            hc_table.add_column("#", style="bold", width=3)
            hc_table.add_column("Paper", style="bold", max_width=50)
            hc_table.add_column("Citations", style="yellow", justify="right", width=10)
            hc_table.add_column("Year", style="cyan", width=6)
            hc_table.add_column("Venue", style="dim", max_width=25)
            
            for i, paper in enumerate(highly_cited[:10], 1):
                title = paper.get('title', 'Unknown')
                if len(title) > 50:
                    title = title[:47] + "..."
                venue = paper.get('venue', 'Unknown')
                if len(venue) > 25:
                    venue = venue[:22] + "..."
                
                # Make clickable
                url = paper.get('url', '')
                if url:
                    title = f"[link={url}]{title}[/link]"
                
                hc_table.add_row(
                    str(i),
                    title,
                    str(paper.get('citations', 0)),
                    str(paper.get('year', 'N/A')),
                    venue
                )
            
            self.console.print(hc_table)
            
            if len(highly_cited) > 10:
                self.console.print(f"[dim]... and {len(highly_cited) - 10} more highly-cited papers[/dim]")
        
        # 4. Quick copy text
        self.console.print("\n[bold]📝 Quick Copy Text[/bold]")
        self.console.print("[dim]One-liner for your CV or bio:[/dim]\n")
        
        total = result.get('total_citations', 0)
        hp_count = author_stats.get('high_profile_count', 0)
        top_uni = inst_stats.get('from_qs_top_100', 0)
        
        quick_text = f'"This work has been cited {total} times, including by {hp_count} high-profile researchers (h-index ≥ {self._h_index_threshold()}) from {top_uni} QS Top 100 universities."'
        self.console.print(f"  [green]{quick_text}[/green]")
        
        Prompt.ask("\n\nPress Enter to return")

    def _render_ascii_bar_chart(self, title: str, data: Dict[str, int], color: str = "cyan"):
        """Render a simple bar chart using a Table (replaces missing BarChart in newer Rich versions)."""
        if not data:
            return

        max_val = max(data.values()) if data else 1
        
        # Use a grid/table for alignment
        table = Table(title=title, box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column("Label", justify="right", style="bold")
        table.add_column("Bar", style=color)
        table.add_column("Value", justify="left", style="yellow")
        
        for label, value in data.items():
            # Scale bar length to max 40 chars
            bar_len = int((value / max_val) * 40)
            bar = "█" * bar_len
            if bar_len == 0 and value > 0:
                bar = "▏"
            table.add_row(str(label), bar, str(value))
            
        self.console.print(table)
        self.console.print()

    def show_deep_insights(self, result: Dict[str, Any]):
        """Show deep insights and visualizations."""
        self.console.clear()
        self.console.print(Panel(
            "[title]🧠 DEEP INSIGHTS & VISUALIZATIONS[/title]",
            expand=False,
            border_style="magenta"
        ))
        
        # 1. Citation Velocity (Timeline)
        yearly_stats = result.get('yearly_stats', [])
        if yearly_stats:
            years = [str(y) for y, c in yearly_stats if y is not None]
            counts = [c for y, c in yearly_stats if y is not None]
            
            if years and counts:
                data = dict(zip(years, counts))
                self._render_ascii_bar_chart("📈 Citation Velocity (By Year)", data, "cyan")

        # 2. Venue Tier Distribution
        venues = result.get('venues', {})
        if venues:
            self.console.print("\n[bold green]📚 Venue Tier Distribution[/bold green]")
            rankings = venues.get('rankings', {})
            
            tier_counts = {'Tier 1': 0, 'Tier 2': 0, 'Tier 3': 0, 'Unranked': 0}
            for venue_info in rankings.values():
                tier = venue_info.get('rank_tier', 'Unranked')
                if 'Tier 1' in tier: tier_counts['Tier 1'] += 1
                elif 'Tier 2' in tier: tier_counts['Tier 2'] += 1
                elif 'Tier 3' in tier: tier_counts['Tier 3'] += 1
                else: tier_counts['Unranked'] += 1
            
            total = sum(tier_counts.values())
            if total > 0:
                for tier, count in tier_counts.items():
                    pct = (count / total) * 100
                    bar = "█" * int(pct / 2)
                    self.console.print(f"{tier:10} | {count:3} ({pct:5.1f}%) [dim]{bar}[/dim]")
            self.console.print()

        # 3. Institution Type Distribution
        institutions = result.get('institutions', {})
        if institutions:
            inst_types = {
                'University': institutions.get('University', 0),
                'Industry': institutions.get('Industry', 0),
                'Government': institutions.get('Government', 0),
                'Other': institutions.get('Other', 0)
            }
            
            total = sum(inst_types.values())
            if total > 0:
                self._render_ascii_bar_chart("🏛️  Institution Type Distribution", inst_types, "magenta")

        Prompt.ask("\nPress Enter to return")

    def show_citation_contexts(self, result: Dict[str, Any]):
        """Show HOW citing papers use this work: intents and context quotes."""
        self.console.clear()
        self.console.print(Panel(
            "[title]💬 HOW YOUR WORK IS USED[/title]\n[dim]Citation intents and in-text context from citing papers (Semantic Scholar)[/dim]",
            expand=False,
            border_style="cyan"
        ))

        insights = result.get('citation_insights') or {}
        intent_counts = insights.get('intent_counts') or {}
        context_samples = insights.get('context_samples') or []

        if not intent_counts and not context_samples:
            self.console.print("\n[warning]No citation context data available.[/warning]")
            self.console.print("[dim]Context/intent data comes from the Semantic Scholar API — "
                               "it is not available in pure Google Scholar mode.[/dim]")
            Prompt.ask("\nPress Enter to return")
            return

        if intent_counts:
            intent_labels = {
                'methodology': 'Methodology (uses your methods)',
                'background': 'Background (builds on your ideas)',
                'result': 'Result (compares against your findings)',
                'uses': 'Uses (applies your work)',
                'extends': 'Extends (develops your work further)',
            }
            display = {intent_labels.get(k, k.capitalize()): v
                       for k, v in sorted(intent_counts.items(), key=lambda kv: -kv[1])}
            self._render_ascii_bar_chart("🎯 Citation Intent Distribution", display, "cyan")

        if context_samples:
            self.console.print("[bold green]📝 Sample Citation Contexts[/bold green]")
            self.console.print("[dim]How citing papers describe your work in their text:[/dim]\n")
            for i, sample in enumerate(context_samples[:10], 1):
                context = sample.get('context', '')
                if len(context) > 300:
                    context = context[:297] + "..."
                # Contexts/titles come verbatim from citing papers' text and
                # routinely contain [bracketed] tokens that Rich would parse
                # as markup (silently dropping them or raising MarkupError)
                context = escape(context)
                title = escape(sample.get('title') or 'Unknown')
                url = sample.get('url', '')
                title_display = f"[link={url}]{title}[/link]" if url else title
                # dict.get returns None for present-but-null keys; avoid '(None)'
                year = sample.get('year') or 'N/A'
                marker = " ⭐" if sample.get('is_influential') else ""
                self.console.print(f"  [cyan]{i}.[/cyan] [italic]“{context}”[/italic]")
                self.console.print(f"     [dim]— {title_display} ({year}){marker}[/dim]\n")

        Prompt.ask("\nPress Enter to return")

    def export_results(self, result: Dict[str, Any]):
        """Export results to a file in the chosen format."""
        from citationimpact.export import export_report, EXPORT_FORMATS, default_export_filename

        fmt = Prompt.ask(
            "[bold]Export format[/bold]",
            choices=list(EXPORT_FORMATS),
            default="markdown"
        )

        default_name = default_export_filename(result, fmt)
        filename = Prompt.ask(
            "[bold]Filename[/bold] [dim](Enter for exports folder)[/dim]",
            default=default_name
        )

        try:
            # Bare default name → write to the configured exports directory
            path = export_report(result, fmt, None if filename == default_name else filename)
            self.console.print(f"[success]✓ Report saved to {os.path.abspath(path)}[/success]")
        except Exception as e:
            self.console.print(f"[error]Error saving report: {str(e)}[/error]")

        # Pause so the message isn't wiped by the results screen redraw
        Prompt.ask("\nPress Enter to continue")

