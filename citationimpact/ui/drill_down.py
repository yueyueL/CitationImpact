"""
Drill-down views for detailed analysis results
"""

from typing import Dict, Any, List
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich import box

from .components.prompts import (
    get_adaptive_widths, make_author_clickable, make_paper_clickable, get_field
)


def _format_rankings(info: Dict[str, Any]) -> str:
    """Format university rankings (QS, US News) for display."""
    if not info:
        return "N/A"

    def _format_entry(label: str, data: Dict[str, Any]) -> str:
        if not data:
            return ""
        rank = data.get("rank")
        if rank is None:
            return ""
        text = f"{label} #{rank}"
        tier = data.get("tier")
        if tier:
            text += f" ({tier})"
        return text

    parts: List[str] = []
    qs_part = _format_entry("QS", info.get("qs") or {})
    if qs_part:
        parts.append(qs_part)
    us_part = _format_entry("US News", info.get("usnews") or {})
    if us_part:
        parts.append(us_part)

    if not parts and info.get("primary_source"):
        primary = info["primary_source"]
        primary_data = info.get("sources", {}).get(primary, {})
        label = primary_data.get("label", primary.title())
        primary_part = _format_entry(label, primary_data)
        if primary_part:
            parts.append(primary_part)

    return " | ".join(parts) if parts else "N/A"


def show_institution_details(console: Console, result: Dict[str, Any]):
    """Show detailed breakdown by institution with citing papers"""
    console.clear()
    console.print(Panel(
        "[title]🏛️  INSTITUTION DETAILS[/title]",
        expand=False,
        border_style="cyan"
    ))
    
    institutions = result.get('institutions', {}).get('details', {})
    
    # Show summary of top institutions first
    all_groups = {}
    for cat, authors in institutions.items():
        for author in authors:
            inst_name = author.get('affiliation', 'Unknown')
            if inst_name not in all_groups:
                all_groups[inst_name] = {'count': 0, 'type': cat}
            all_groups[inst_name]['count'] += 1
            
    top_insts = sorted(all_groups.items(), key=lambda x: x[1]['count'], reverse=True)[:5]
    
    if top_insts:
        console.print("\n[bold]🏆 Top 5 Citing Institutions (All Types):[/bold]")
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold cyan")
        grid.add_column(style="yellow")
        grid.add_column(style="dim")
        
        for name, data in top_insts:
            grid.add_row(name[:40], str(data['count']), f"({data['type']})")
        console.print(grid)
        console.print()

    # Menu to select institution type
    console.print("\n[info]Select institution type to view details:[/info]")
    console.print("  1. Universities")
    console.print("  2. Industry")
    console.print("  3. Government")
    console.print("  4. Other")
    console.print("  b. Go back")
    
    choice = Prompt.ask("\n[bold]Select option[/bold]", default="b").lower()
    
    if choice == 'b':
        return
    
    type_map = {'1': 'University', '2': 'Industry', '3': 'Government', '4': 'Other'}
    selected_type = type_map.get(choice)
    
    if not selected_type or selected_type not in institutions:
        console.print("[error]Invalid selection or no data available[/error]")
        Prompt.ask("\nPress Enter to continue")
        return
    
    # Show institutions of selected type
    console.clear()
    console.print(Panel(
        f"[title]{selected_type} Institutions[/title]",
        expand=False,
        border_style="cyan"
    ))
    
    inst_authors = institutions[selected_type]
    
    # Group by institution name
    inst_groups = {}
    for author in inst_authors:
        inst_name = author.get('affiliation', 'Unknown')
        if inst_name not in inst_groups:
            inst_groups[inst_name] = []
        inst_groups[inst_name].append(author)
    
    # Sort by number of authors
    sorted_insts = sorted(inst_groups.items(), key=lambda x: len(x[1]), reverse=True)
    
    console.print(f"\n[info]Found {len(sorted_insts)} {selected_type.lower()} institutions[/info]\n")
    
    for inst_name, authors in sorted_insts[:20]:  # Top 20
        # Create table for each institution
        table = Table(
            title=f"{inst_name} ({len(authors)} authors)",
            box=box.SIMPLE,
            show_header=True,
            title_style="bold cyan"
        )
        table.add_column("Author", style="bold", max_width=25)
        table.add_column("H-Index", justify="right", style="yellow", width=8)
        table.add_column("Rankings", style="cyan", max_width=28)
        table.add_column("Citing Paper", style="dim")  # No max_width - show full title
        
        for author in authors[:10]:  # Top 10 authors per institution
            paper_title = author.get('citing_paper', 'Unknown')
            author_name = author.get('name', 'Unknown')
            
            # Build author profile link (prefer Google Scholar)
            gs_id = author.get('google_scholar_id', '')
            s2_id = author.get('semantic_scholar_id', '')
            homepage = author.get('homepage', '')
            
            # Make author name clickable
            if gs_id:
                gs_url = f"https://scholar.google.com/citations?user={gs_id}"
                author_display = f"[link={gs_url}]{author_name}[/link]"
            elif s2_id:
                s2_url = f"https://www.semanticscholar.org/author/{s2_id}"
                author_display = f"[link={s2_url}]{author_name}[/link]"
            elif homepage:
                author_display = f"[link={homepage}]{author_name}[/link]"
            else:
                author_display = author_name
            
            # Try to get paper link/ID for clickable link
            paper_url = author.get('paper_url', '')
            paper_id = author.get('paper_id', '')
            
            # Make title clickable if we have a URL
            if paper_url:
                paper_display = f"[link={paper_url}]{paper_title}[/link]"
            elif paper_id:
                # Construct Semantic Scholar URL from paper ID
                s2_paper_url = f"https://www.semanticscholar.org/paper/{paper_id}"
                paper_display = f"[link={s2_paper_url}]{paper_title}[/link]"
            else:
                paper_display = paper_title
            
            # Use pre-formatted h_index_display if available, else format with source
            h_display = author.get('h_index_display')
            if h_display is None or h_display == '':
                h_index = author.get('h_index', 'N/A')
                h_source = author.get('h_index_source', '')
                if h_source == 'google_scholar':
                    h_display = f"{h_index} [dim](GS)[/dim]"
                else:
                    h_display = str(h_index)
            else:
                h_display = str(h_display)  # Ensure it's a string!
            
            table.add_row(
                author_display,
                h_display,
                _format_rankings(author.get('university_rankings', {}) or {}),
                paper_display
            )
        
        if len(authors) > 10:
            table.add_row(f"... and {len(authors) - 10} more", "", "", "")
        
        # Print each institution's table (was incorrectly outside the loop!)
        console.print(table)
        console.print()
    
    Prompt.ask("\nPress Enter to continue")


def show_venue_details(console: Console, result: Dict[str, Any]):
    """Show detailed breakdown by venue with citing papers"""
    console.clear()
    console.print(Panel(
        "[title]📚 VENUE DETAILS[/title]",
        expand=False,
        border_style="cyan"
    ))
    
    venues = result.get('venues', {})
    most_common = venues.get('most_common', [])
    rankings = venues.get('rankings', {})
    
    # Show all venues with details
    console.print(f"\n[info]Top {len(most_common)} citing venues[/info]\n")
    
    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan"
    )
    table.add_column("#", style="bold magenta", width=4, justify="right")
    table.add_column("Venue", style="bold", max_width=50)
    table.add_column("Citations", justify="right", style="yellow", width=10)
    table.add_column("H-Index", justify="right", style="green", width=8)
    table.add_column("Tier", style="cyan", max_width=20)
    table.add_column("CORE", style="magenta", width=6)
    table.add_column("CCF", style="magenta", width=6)
    
    for idx, (venue_name, count) in enumerate(most_common, 1):
        venue_info = rankings.get(venue_name, {})
        h_index = venue_info.get('h_index', 'N/A')
        tier = venue_info.get('rank_tier', 'N/A')
        core = venue_info.get('core_rank', '—')
        ccf = venue_info.get('ccf_rank', '—')
        
        # Truncate long venue names
        display_name = venue_name
        if len(display_name) > 50:
            display_name = display_name[:47] + "..."
        
        table.add_row(
            str(idx),
            display_name,
            str(count),
            str(h_index),
            tier,
            str(core),
            str(ccf)
        )
    
    console.print(table)
    if not most_common:
        Prompt.ask("\nPress Enter to continue")
        return

    while True:
        console.print("\n[info]Enter the venue number to view citing papers, or 'b' to go back.[/info]")
        choice = Prompt.ask("[bold]Selection[/bold]", default="b").strip()
        if choice.lower() == 'b':
            break
        if not choice.isdigit():
            console.print("[warning]Please enter a valid number or 'b'.[/warning]")
            continue
        idx = int(choice)
        if idx < 1 or idx > len(most_common):
            console.print("[warning]Number out of range.[/warning]")
            continue

        venue_name, _ = most_common[idx - 1]
        venue_info = rankings.get(venue_name, {})
        citations = venue_info.get('citations', [])

        console.clear()
        console.print(Panel(f"[title]📚 {venue_name} — Citing Papers[/title]", border_style="green"))

        if not citations:
            console.print("\n[dim]No citing paper details recorded for this venue.[/dim]\n")
            Prompt.ask("Press Enter to return")
            console.clear()
            console.print(Panel("[title]📚 VENUE DETAILS[/title]", expand=False, border_style="cyan"))
            console.print(table)
            console.print(f"\n[info]Top {len(most_common)} citing venues[/info]\n")
            continue

        citation_table = Table(box=box.SIMPLE_HEAVY)
        citation_table.add_column("#", justify="right", style="bold magenta", width=4)
        citation_table.add_column("Citing Paper", style="bold")
        citation_table.add_column("Year", justify="center", style="yellow", width=6)
        citation_table.add_column("Authors", style="cyan", max_width=40)

        max_rows = 20
        for i, citation in enumerate(citations[:max_rows], 1):
            title = citation.get('title', 'Unknown')
            url = citation.get('url', '')
            paper_id = citation.get('paper_id', '')
            if url:
                title_display = f"[link={url}]{title}[/link]"
            elif paper_id:
                title_display = f"[link=https://www.semanticscholar.org/paper/{paper_id}]{title}[/link]"
            else:
                title_display = title
            year = citation.get('year')
            authors = citation.get('authors') or []
            authors_display = ', '.join(authors[:3])
            if len(authors) > 3:
                authors_display += f" … ({len(authors)} total)"

            citation_table.add_row(
                str(i),
                title_display,
                str(year) if year not in (None, '', 'Unknown') else 'N/A',
                authors_display or 'Unknown'
            )

        console.print(citation_table)
        if len(citations) > max_rows:
            console.print(f"[dim]… and {len(citations) - max_rows} more citing papers[/dim]\n")
        Prompt.ask("\nPress Enter to return to the venue list")
        console.clear()
        console.print(Panel("[title]📚 VENUE DETAILS[/title]", expand=False, border_style="cyan"))
        console.print(table)
        console.print(f"\n[info]Top {len(most_common)} citing venues[/info]\n")



def show_scholar_details(console: Console, result: Dict[str, Any]):
    """Show all high-profile scholars with details and clickable links"""
    console.clear()
    widths = get_adaptive_widths(console.width or 120)
    
    console.print(Panel(
        "[title]🌟 HIGH-PROFILE SCHOLARS[/title]\n"
        "[dim]Click names for profiles, click papers to view[/dim]",
        expand=False,
        border_style="cyan"
    ))
    
    scholars = result.get('high_profile_scholars', [])
    
    if not scholars:
        console.print("\n[warning]No high-profile scholars found[/warning]")
        Prompt.ask("\nPress Enter to continue")
        return
    
    console.print(f"\n[info]Found {len(scholars)} high-profile scholars (h-index ≥ 20)[/info]")
    
    # Sort options
    console.print("[dim]Sort by: [1] H-Index [2] Name [3] Institution[/dim]")
    sort_choice = Prompt.ask("Sort", default="1")
    
    if sort_choice == "2":
        scholars = sorted(scholars, key=lambda x: get_field(x, 'name', ''))
    elif sort_choice == "3":
        scholars = sorted(scholars, key=lambda x: get_field(x, 'affiliation', ''))
    else:
        scholars = sorted(scholars, key=lambda x: get_field(x, 'h_index', 0), reverse=True)
    
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", expand=True)
    table.add_column("#", style="bold magenta", width=widths['rank'], justify="right")
    table.add_column("Scholar (click)", style="bold", max_width=widths['author'])
    table.add_column("H", justify="right", style="yellow", width=widths['h_index'])
    table.add_column("Institution", style="cyan", max_width=widths['institution'])
    table.add_column("Citing Paper (click)", style="dim", max_width=widths['paper'])
    
    for idx, scholar in enumerate(scholars, 1):
        h_index = get_field(scholar, 'h_index', 'N/A')
        affiliation = get_field(scholar, 'affiliation', 'Unknown')
        
        # Truncate affiliation
        if len(affiliation) > widths['institution']:
            affiliation = affiliation[:widths['institution']-3] + "..."
        
        # Make clickable using helpers
        author_display = make_author_clickable(scholar, widths['author'])
        paper_display = make_paper_clickable(scholar, widths['paper'])
        
        table.add_row(str(idx), author_display, str(h_index), affiliation, paper_display)
        
        # Pause every 25 rows
        if idx % 25 == 0 and idx < len(scholars):
            console.print(table)
            console.print()
            if not Confirm.ask(f"[dim]Continue? ({len(scholars) - idx} remaining)[/dim]", default=True):
                break
            # Start new table with same settings
            table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", expand=True)
            table.add_column("#", style="bold magenta", width=widths['rank'], justify="right")
            table.add_column("Scholar (click)", style="bold", max_width=widths['author'])
            table.add_column("H", justify="right", style="yellow", width=widths['h_index'])
            table.add_column("Institution", style="cyan", max_width=widths['institution'])
            table.add_column("Citing Paper (click)", style="dim", max_width=widths['paper'])
    
    console.print(table)
    
    # Quick stats
    avg_h = sum(get_field(s, 'h_index', 0) for s in scholars) // len(scholars) if scholars else 0
    console.print(f"\n[dim]Average h-index: {avg_h}[/dim]")
    
    Prompt.ask("\nPress Enter to continue")


def show_influential_details(console: Console, result: Dict[str, Any]):
    """Show all influential citations with full details"""
    console.clear()
    console.print(Panel(
        "[title]💡 INFLUENTIAL CITATIONS - COMPLETE LIST[/title]",
        expand=False,
        border_style="cyan"
    ))
    
    influential = result.get('influential_citations', [])
    
    if not influential:
        console.print("\n[warning]No influential citations found[/warning]")
        Prompt.ask("\nPress Enter to continue")
        return
    
    console.print(f"\n[info]Showing all {len(influential)} influential citations[/info]\n")
    
    for idx, citation in enumerate(influential, 1):
        # Handle both dict and Citation object
        if isinstance(citation, dict):
            title = citation.get('paper', citation.get('citing_paper_title', 'Unknown'))
            authors = citation.get('authors', citation.get('citing_authors', []))
            venue = citation.get('venue', 'Unknown')
            year = citation.get('year', 'N/A')
            contexts = citation.get('contexts', [])
            url = citation.get('url', '')
            paper_id = citation.get('paper_id', '')
            doi = citation.get('doi', '')
        else:
            title = getattr(citation, 'citing_paper_title', 'Unknown')
            authors = getattr(citation, 'citing_authors', [])
            venue = getattr(citation, 'venue', 'Unknown')
            year = getattr(citation, 'year', 'N/A')
            contexts = getattr(citation, 'contexts', [])
            url = getattr(citation, 'url', '')
            paper_id = getattr(citation, 'paper_id', '')
            doi = getattr(citation, 'doi', '')
        
        # Create table for each citation
        table = Table(
            title=f"Influential Citation #{idx}",
            box=box.SIMPLE,
            show_header=False,
            title_style="bold magenta"
        )
        table.add_column("Field", style="bold cyan", width=12)
        table.add_column("Value", style="white")
        
        # Make title clickable if URL available
        if url:
            title_display = f"[link={url}]{title}[/link]"
        elif paper_id:
            s2_url = f"https://www.semanticscholar.org/paper/{paper_id}"
            title_display = f"[link={s2_url}]{title}[/link]"
        else:
            title_display = title
        
        table.add_row("Title", title_display)
        
        if authors:
            authors_str = ', '.join(authors[:5])
            if len(authors) > 5:
                authors_str += f" ... ({len(authors)} total)"
            table.add_row("Authors", authors_str)
        table.add_row("Venue", venue)
        table.add_row("Year", str(year))
        
        # Show links
        if url:
            table.add_row("🔗 Link", f"[link={url}]{url}[/link]")
        if doi:
            table.add_row("📖 DOI", doi)
        if paper_id:
            table.add_row("🆔 S2 ID", paper_id)
        
        # Show citation contexts if available
        if contexts:
            for ctx_idx, context in enumerate(contexts[:2], 1):
                table.add_row(f"Context {ctx_idx}", context[:300] + "..." if len(context) > 300 else context)
        
        console.print(table)
        console.print()
        
        # Pause every 5 citations
        if idx % 5 == 0 and idx < len(influential):
            if not Confirm.ask(f"[dim]Continue? ({len(influential) - idx} remaining)[/dim]", default=True):
                return
    
    Prompt.ask("\nPress Enter to continue")


def show_all_authors_view(console: Console, result: Dict[str, Any]):
    """Show ALL citing authors with filtering and sorting options."""
    all_authors = result.get('all_authors', [])
    
    if not all_authors:
        console.print("[warning]No author data available[/warning]")
        Prompt.ask("\nPress Enter to continue")
        return
    
    # Get adaptive widths
    widths = get_adaptive_widths(console.width or 120)
    
    # Main loop for filtering
    current_filter = None
    min_h_index = 0
    sort_by = 'h_index'  # Default sort
    
    while True:
        console.clear()
        console.print(Panel(
            "[title]👥 ALL CITING AUTHORS[/title]\n"
            "[dim]Click author names for profiles, click papers to view[/dim]",
            expand=False,
            border_style="cyan"
        ))
        
        # Apply filters
        filtered_authors = all_authors.copy()
        
        if current_filter:
            filtered_authors = [a for a in filtered_authors 
                              if current_filter.lower() in a.get('affiliation', '').lower() 
                              or current_filter.lower() in a.get('name', '').lower()]
        
        if min_h_index > 0:
            filtered_authors = [a for a in filtered_authors if a.get('h_index', 0) >= min_h_index]
        
        # Sort
        if sort_by == 'h_index':
            filtered_authors.sort(key=lambda x: x.get('h_index', 0), reverse=True)
        elif sort_by == 'name':
            filtered_authors.sort(key=lambda x: x.get('name', '').lower())
        elif sort_by == 'institution':
            filtered_authors.sort(key=lambda x: x.get('affiliation', '').lower())
        
        # Show stats
        console.print(f"\n[info]Showing {len(filtered_authors)} of {len(all_authors)} authors[/info]")
        if current_filter:
            console.print(f"[dim]Filter: '{current_filter}'[/dim]")
        if min_h_index > 0:
            console.print(f"[dim]Min H-Index: {min_h_index}[/dim]")
        console.print(f"[dim]Sorted by: {sort_by}[/dim]\n")
        
        # Create adaptive table
        table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", expand=True)
        table.add_column("#", style="bold magenta", width=widths['rank'], justify="right")
        table.add_column("Author (click)", style="bold", max_width=widths['author'])
        table.add_column("H", justify="right", style="yellow", width=widths['h_index'])
        table.add_column("Cites", justify="right", style="green", width=7)  # Total citations
        table.add_column("Institution", style="cyan", max_width=widths['institution'] - 5)
        table.add_column("Type", style="dim", width=widths['type'])
        table.add_column("Citing Paper (click)", max_width=widths['paper'])
        
        # Show first 30 authors
        display_count = min(30, len(filtered_authors))
        for idx, author in enumerate(filtered_authors[:display_count], 1):
            h_index = author.get('h_index', 0)
            h_source = author.get('h_index_source', '')
            h_display = f"{h_index} [dim](GS)[/dim]" if h_source == 'google_scholar' else str(h_index)
            
            # Total citations from author's profile
            total_cites = author.get('total_citations', 0)
            cites_display = str(total_cites) if total_cites > 0 else '-'
            
            affiliation = author.get('affiliation', 'Unknown')
            max_aff_len = widths['institution'] - 8
            if len(affiliation) > max_aff_len:
                affiliation = affiliation[:max_aff_len-3] + "..."
            
            inst_type = author.get('institution_type', 'Unknown')
            
            # Make author clickable
            author_display = make_author_clickable(author, widths['author'])
            
            # Make paper clickable
            paper_display = make_paper_clickable(author, widths['paper'])
            
            table.add_row(str(idx), author_display, h_display, cites_display, affiliation, inst_type, paper_display)
        
        if len(filtered_authors) > display_count:
            table.add_row("", f"[dim]... and {len(filtered_authors) - display_count} more[/dim]", "", "", "", "", "")
        
        console.print(table)
        
        # Options menu
        console.print("\n[bold cyan]━━━ OPTIONS ━━━[/bold cyan]")
        console.print("  [highlight]f[/highlight] Filter by name/institution")
        console.print("  [highlight]h[/highlight] Set minimum H-Index")
        console.print("  [highlight]s[/highlight] Change sort order")
        console.print("  [highlight]c[/highlight] Clear all filters")
        console.print("  [highlight]a[/highlight] Show ALL (paginated)")
        console.print("  [highlight]e[/highlight] Export to CSV")
        console.print("  [highlight]b[/highlight] Back")
        
        choice = Prompt.ask("\n[bold]Select option[/bold]", default="b").lower()
        
        if choice == 'b':
            break
        elif choice == 'f':
            current_filter = Prompt.ask("Enter filter text (name or institution)", default="")
        elif choice == 'h':
            try:
                min_h_index = int(Prompt.ask("Minimum H-Index", default="0"))
            except ValueError:
                min_h_index = 0
        elif choice == 's':
            console.print("\n  1. H-Index (high to low)")
            console.print("  2. Name (A-Z)")
            console.print("  3. Institution (A-Z)")
            sort_choice = Prompt.ask("Sort by", default="1")
            sort_by = {'1': 'h_index', '2': 'name', '3': 'institution'}.get(sort_choice, 'h_index')
        elif choice == 'c':
            current_filter = None
            min_h_index = 0
        elif choice == 'a':
            _show_all_authors_paginated(console, filtered_authors)
        elif choice == 'e':
            _export_authors_csv(console, filtered_authors)


def _show_all_authors_paginated(console: Console, authors: List[Dict]):
    """Show all authors with pagination and clickable links."""
    widths = get_adaptive_widths(console.width or 120)
    page_size = 20
    total_pages = (len(authors) + page_size - 1) // page_size
    current_page = 0
    
    while True:
        console.clear()
        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, len(authors))
        
        console.print(f"\n[bold]Page {current_page + 1} of {total_pages}[/bold] ({len(authors)} total authors)\n")
        
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold cyan", expand=True)
        table.add_column("#", style="bold magenta", width=widths['rank'])
        table.add_column("Author (click)", style="bold", max_width=widths['author'])
        table.add_column("H", justify="right", style="yellow", width=widths['h_index'])
        table.add_column("Cites", justify="right", style="green", width=7)  # Total citations
        table.add_column("Institution", style="cyan", max_width=widths['institution'] - 5)
        table.add_column("Citing Paper (click)", max_width=widths['paper'])
        
        for idx, author in enumerate(authors[start_idx:end_idx], start_idx + 1):
            h_index = author.get('h_index', 0)
            h_source = author.get('h_index_source', '')
            h_display = f"{h_index} [dim](GS)[/dim]" if h_source == 'google_scholar' else str(h_index)
            
            # Total citations from author's profile
            total_cites = author.get('total_citations', 0)
            cites_display = str(total_cites) if total_cites > 0 else '-'
            
            # Make clickable
            author_display = make_author_clickable(author, widths['author'])
            paper_display = make_paper_clickable(author, widths['paper'])
            affiliation = author.get('affiliation', 'Unknown')
            max_aff_len = widths['institution'] - 8
            if len(affiliation) > max_aff_len:
                affiliation = affiliation[:max_aff_len-3] + "..."
            
            table.add_row(str(idx), author_display, h_display, cites_display, affiliation, paper_display)
        
        console.print(table)
        
        # Clear navigation with page info
        nav_parts = []
        if current_page > 0:
            nav_parts.append("[bold]p[/bold]=Prev")
        if current_page < total_pages - 1:
            nav_parts.append("[bold]n[/bold]=Next")
        nav_parts.append("[bold]e[/bold]=Export")
        nav_parts.append("[bold]b[/bold]=Back")
        
        console.print(f"\n[dim]Page {current_page + 1}/{total_pages} | {' | '.join(nav_parts)}[/dim]")
        nav = Prompt.ask("Navigate", default="b").lower()
        
        if nav == 'n' and current_page < total_pages - 1:
            current_page += 1
        elif nav == 'p' and current_page > 0:
            current_page -= 1
        elif nav == 'e':
            _export_authors_csv(console, authors)
        elif nav == 'b':
            break


def _export_authors_csv(console: Console, authors: List[Dict]):
    """Export authors to CSV file."""
    from datetime import datetime
    import csv
    
    filename = Prompt.ask(
        "[bold]Filename[/bold]",
        default=f"citing_authors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    
    try:
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Name', 'H-Index', 'H-Index Source', 'Total Citations', 'Institution', 'Institution Type', 'Citing Paper', 'Paper Citations', 'Google Scholar ID', 'Semantic Scholar ID', 'Profile URL'])
            
            for author in authors:
                # Build profile URL
                gs_id = author.get('google_scholar_id', '')
                s2_id = author.get('semantic_scholar_id', '')
                profile_url = ''
                if gs_id:
                    profile_url = f"https://scholar.google.com/citations?user={gs_id}"
                elif s2_id:
                    profile_url = f"https://www.semanticscholar.org/author/{s2_id}"
                
                writer.writerow([
                    author.get('name', ''),
                    author.get('h_index', ''),
                    author.get('h_index_source', ''),
                    author.get('total_citations', 0),  # Author's total citations
                    author.get('affiliation', ''),
                    author.get('institution_type', ''),
                    author.get('citing_paper', ''),
                    author.get('paper_citations', 0),  # Citing paper's citation count
                    gs_id,
                    s2_id,
                    profile_url
                ])
        
        console.print(f"[success]✓ Exported {len(authors)} authors to {filename}[/success]")
    except Exception as e:
        console.print(f"[error]Export failed: {e}[/error]")
    
    Prompt.ask("\nPress Enter to continue")

