"""
Drill-down views for detailed analysis results
"""

from typing import Dict, Any, List
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich import box


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
    
    # Menu to select institution type
    console.print("\n[info]Select institution type to view:[/info]")
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
            
            # Try to get paper link/ID for clickable link
            paper_url = author.get('paper_url', '')
            paper_id = author.get('paper_id', '')
            
            # Make title clickable if we have a URL
            if paper_url:
                paper_display = f"[link={paper_url}]{paper_title}[/link]"
            elif paper_id:
                # Construct Semantic Scholar URL from paper ID
                s2_url = f"https://www.semanticscholar.org/paper/{paper_id}"
                paper_display = f"[link={s2_url}]{paper_title}[/link]"
            else:
                paper_display = paper_title
            
            table.add_row(
                author.get('name', 'Unknown'),
                str(author.get('h_index', 'N/A')),
                _format_rankings(author.get('university_rankings', {}) or {}),
                paper_display
            )
        
        if len(authors) > 10:
            table.add_row(f"... and {len(authors) - 10} more", "", "", "", style="dim")
        
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
    """Show all high-profile scholars with details"""
    console.clear()
    console.print(Panel(
        "[title]🌟 HIGH-PROFILE SCHOLARS - COMPLETE LIST[/title]",
        expand=False,
        border_style="cyan"
    ))
    
    scholars = result.get('high_profile_scholars', [])
    
    if not scholars:
        console.print("\n[warning]No high-profile scholars found[/warning]")
        Prompt.ask("\nPress Enter to continue")
        return
    
    console.print(f"\n[info]Showing all {len(scholars)} high-profile scholars[/info]\n")
    
    table = Table(
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan"
    )
    table.add_column("#", style="bold magenta", width=4, justify="right")
    table.add_column("Name", style="bold", max_width=25)
    table.add_column("H-Index", justify="right", style="yellow", width=8)
    table.add_column("Institution", style="cyan", max_width=40)
    table.add_column("Citing Paper (clickable)", style="dim")  # No max_width for full titles
    
    for idx, scholar in enumerate(scholars, 1):
        if isinstance(scholar, dict):
            name = scholar.get('name', 'Unknown')
            h_index = scholar.get('h_index', 'N/A')
            affiliation = scholar.get('affiliation', 'Unknown')
            citing_paper = scholar.get('citing_paper', 'Unknown')
        else:
            name = getattr(scholar, 'name', 'Unknown')
            h_index = getattr(scholar, 'h_index', 'N/A')
            affiliation = getattr(scholar, 'affiliation', 'Unknown')
            citing_paper = getattr(scholar, 'citing_paper', 'Unknown')
        
        # Truncate long affiliations but keep full paper titles
        if len(affiliation) > 40:
            affiliation = affiliation[:37] + "..."
        
        # Make citing paper clickable if URL available
        paper_url = scholar.get('paper_url', '') if isinstance(scholar, dict) else getattr(scholar, 'paper_url', '')
        paper_id = scholar.get('paper_id', '') if isinstance(scholar, dict) else getattr(scholar, 'paper_id', '')
        
        if paper_url:
            citing_paper_display = f"[link={paper_url}]{citing_paper}[/link]"
        elif paper_id:
            s2_url = f"https://www.semanticscholar.org/paper/{paper_id}"
            citing_paper_display = f"[link={s2_url}]{citing_paper}[/link]"
        else:
            citing_paper_display = citing_paper
        
        table.add_row(
            str(idx),
            name,
            str(h_index),
            affiliation,
            citing_paper_display
        )
        
        # Pause every 20 rows
        if idx % 20 == 0 and idx < len(scholars):
            console.print(table)
            console.print()
            if not Confirm.ask(f"[dim]Continue? ({len(scholars) - idx} remaining)[/dim]", default=True):
                return
            # Start new table
            table = Table(
                box=box.ROUNDED,
                show_header=True,
                header_style="bold cyan"
            )
            table.add_column("#", style="bold magenta", width=4, justify="right")
            table.add_column("Name", style="bold", max_width=25)
            table.add_column("H-Index", justify="right", style="yellow", width=8)
            table.add_column("Institution", style="cyan", max_width=40)
            table.add_column("Citing Paper", style="dim", max_width=40)
    
    console.print(table)
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

