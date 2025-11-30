"""
Table creation helpers for the terminal UI.
"""
from typing import Any, Dict, List, Tuple, Optional
from rich.table import Table
from rich.console import Console
from rich import box

from .prompts import get_adaptive_widths, make_author_clickable, make_paper_clickable


def create_overview_table(result: Dict[str, Any]) -> Table:
    """
    Create the overview metrics table.
    
    Args:
        result: Analysis result dictionary
        
    Returns:
        Rich Table with overview metrics
    """
    table = Table.grid(padding=(0, 2))
    table.add_column(style="cyan")
    table.add_column(justify="right", style="bold yellow")
    
    metrics = [
        ("Total Citations", result.get('total_citations', 0)),
        ("Citations Analyzed", result.get('analyzed_citations', 0)),
        ("High-Profile Scholars", len(result.get('high_profile_scholars', []))),
        ("Influential Citations", len(result.get('influential_citations', []))),
        ("Methodological Citations", len(result.get('methodological_citations', [])))
    ]
    
    for label, value in metrics:
        table.add_row(label, str(value))
    
    return table


def create_institution_table(institutions: Dict[str, Any]) -> Table:
    """
    Create the institution summary table.
    
    Args:
        institutions: Institution data dictionary
        
    Returns:
        Rich Table with institution breakdown
    """
    table = Table(box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Count", justify="right", style="bold yellow")
    table.add_column("Percent", justify="right", style="cyan")
    
    summary_counts = {k: v for k, v in institutions.items() if isinstance(v, (int, float))}
    total = sum(summary_counts.values()) or 1
    
    for inst_type, count in summary_counts.items():
        percent = count / total * 100
        table.add_row(inst_type, str(count), f"{percent:.1f}%")
    
    return table


def create_venue_table(venues: List[Tuple[str, int]], rankings: Dict[str, Any], 
                       console_width: int = 120) -> Table:
    """
    Create the top venues table with adaptive widths.
    
    Args:
        venues: List of (venue_name, count) tuples
        rankings: Dictionary of venue rankings
        console_width: Terminal width for adaptive sizing
        
    Returns:
        Rich Table with venue information
    """
    widths = get_adaptive_widths(console_width)
    
    table = Table(box=box.ROUNDED, header_style="bold cyan", expand=True)
    table.add_column("#", justify="right", style="bold magenta", width=widths['rank'])
    table.add_column("Venue", style="bold", max_width=widths['venue'])
    table.add_column("Cites", justify="right", style="bold yellow", width=6)
    table.add_column("Tier", style="cyan")
    
    for idx, (venue_name, count) in enumerate(venues, 1):
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
        
        display_name = venue_name if len(venue_name) <= widths['venue'] else venue_name[:widths['venue']-3] + "..."
        table.add_row(str(idx), display_name, str(count), tier_display)
    
    return table


def create_scholar_table(console_width: int = 120) -> Table:
    """
    Create an empty scholar table with adaptive widths.
    
    Args:
        console_width: Terminal width for adaptive sizing
        
    Returns:
        Rich Table ready to have scholars added
    """
    widths = get_adaptive_widths(console_width)
    
    table = Table(box=box.ROUNDED, header_style="bold cyan", expand=True)
    table.add_column("#", justify="right", style="bold magenta", width=widths['rank'])
    table.add_column("Scholar", style="bold", max_width=widths['author'])
    table.add_column("H", justify="right", style="bold yellow", width=widths['h_index'])
    table.add_column("Institution", style="cyan", max_width=widths['institution'])
    table.add_column("Citing Paper", style="dim", max_width=widths['paper'])
    return table


def create_authors_table(console_width: int = 120) -> Table:
    """
    Create a table for showing all authors with adaptive widths and links.
    
    Args:
        console_width: Terminal width for adaptive sizing
        
    Returns:
        Rich Table ready for author rows
    """
    widths = get_adaptive_widths(console_width)
    
    table = Table(box=box.ROUNDED, header_style="bold cyan", expand=True)
    table.add_column("#", justify="right", style="bold magenta", width=widths['rank'])
    table.add_column("Author (click)", style="bold", max_width=widths['author'])
    table.add_column("H", justify="right", style="yellow", width=widths['h_index'])
    table.add_column("Institution", style="cyan", max_width=widths['institution'])
    table.add_column("Type", style="dim", width=widths['type'])
    table.add_column("Citing Paper (click)", max_width=widths['paper'])
    return table


def create_papers_table(console_width: int = 120) -> Table:
    """
    Create a table for showing citing papers with adaptive widths and links.
    
    Args:
        console_width: Terminal width for adaptive sizing
        
    Returns:
        Rich Table ready for paper rows
    """
    widths = get_adaptive_widths(console_width)
    
    table = Table(box=box.ROUNDED, header_style="bold cyan", expand=True)
    table.add_column("#", justify="right", style="bold magenta", width=widths['rank'])
    table.add_column("Paper (click to view)", style="bold", max_width=widths['paper'] + 10)
    table.add_column("Year", justify="center", style="yellow", width=widths['year'])
    table.add_column("Venue", style="cyan", max_width=widths['venue'])
    table.add_column("Cites", justify="right", style="green", width=6)
    table.add_column("🌟", justify="center", width=3)  # Influential marker
    return table


def create_settings_table() -> Table:
    """
    Create an empty settings table with headers.
    
    Returns:
        Rich Table ready to have settings added
    """
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("#", style="bold magenta", width=3)
    table.add_column("Setting", style="bold")
    table.add_column("Current Value", style="yellow")
    table.add_column("Description", style="dim")
    return table

