"""
Helper functions for UI prompts and formatting.
"""
from typing import Any, Dict, List, Optional


def get_field(obj: Any, field_name: str, default: Any = None) -> Any:
    """
    Get a field from either a dict or dataclass object.
    
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


def make_clickable(text: str, url: str = '', paper_id: str = '') -> str:
    """
    Return clickable text if URL or paper ID is available.
    
    Args:
        text: Display text
        url: Optional URL to link to
        paper_id: Optional Semantic Scholar paper ID
        
    Returns:
        Rich markup with link if available
    """
    if url:
        return f'[link={url}]{text}[/link]'
    if paper_id:
        return f'[link=https://www.semanticscholar.org/paper/{paper_id}]{text}[/link]'
    return text


def make_author_clickable(author: Any, max_width: int = 0) -> str:
    """
    Make author name clickable with profile link.
    Tries: Google Scholar > Semantic Scholar > Homepage
    
    Args:
        author: Dict or object with author info
        max_width: If >0, truncate name to this width
        
    Returns:
        Rich markup with clickable link if available
    """
    name = get_field(author, 'name', 'Unknown')
    gs_id = get_field(author, 'google_scholar_id', '')
    s2_id = get_field(author, 'semantic_scholar_id', '')
    homepage = get_field(author, 'homepage', '')
    
    # Truncate if needed
    if max_width > 0 and len(name) > max_width:
        name = name[:max_width-3] + "..."
    
    # Build clickable link
    if gs_id:
        return f"[link=https://scholar.google.com/citations?user={gs_id}]{name}[/link]"
    elif s2_id:
        return f"[link=https://www.semanticscholar.org/author/{s2_id}]{name}[/link]"
    elif homepage:
        return f"[link={homepage}]{name}[/link]"
    return name


def make_paper_clickable(paper: Any, max_width: int = 0) -> str:
    """
    Make paper title clickable with link.
    Tries: URL > DOI > Semantic Scholar Paper ID
    
    Args:
        paper: Dict or object with paper info
        max_width: If >0, truncate title to this width
        
    Returns:
        Rich markup with clickable link if available
    """
    # Get title from various possible field names
    title = (get_field(paper, 'citing_paper_title') or 
             get_field(paper, 'title') or 
             get_field(paper, 'citing_paper') or 
             'Unknown')
    
    url = get_field(paper, 'url', '')
    paper_id = get_field(paper, 'paper_id', '')
    doi = get_field(paper, 'doi', '')
    
    # Truncate if needed
    if max_width > 0 and len(title) > max_width:
        title = title[:max_width-3] + "..."
    
    # Build clickable link
    if url:
        return f"[link={url}]{title}[/link]"
    elif doi:
        return f"[link=https://doi.org/{doi}]{title}[/link]"
    elif paper_id:
        return f"[link=https://www.semanticscholar.org/paper/{paper_id}]{title}[/link]"
    return title


def get_adaptive_widths(console_width: int) -> Dict[str, int]:
    """
    Calculate adaptive column widths based on terminal width.
    
    Args:
        console_width: Current terminal width
        
    Returns:
        Dict with suggested column widths
    """
    # Minimum terminal width we expect
    width = max(console_width or 80, 80)
    
    # Calculate proportional widths
    return {
        'rank': 4,
        'h_index': 6,
        'year': 6,
        'type': 10,
        'author': max(15, min(width // 6, 30)),
        'institution': max(20, min(width // 4, 45)),
        'paper': max(25, width // 3),
        'venue': max(20, min(width // 4, 40)),
    }


def format_university_rankings(rankings: Dict[str, Any]) -> str:
    """
    Format QS / US News rankings for display.
    
    Args:
        rankings: Dictionary with 'qs' and/or 'usnews' ranking data
        
    Returns:
        Formatted string like "QS #50 (Tier 1) | US News #30"
    """
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


def looks_like_author_id(text: str, data_source: str) -> bool:
    """
    Determine if text looks like an author ID.

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
        if len(text) >= 10 and any(c.isalpha() for c in text) and any(c.isdigit() for c in text):
            return True
    else:
        # Semantic Scholar IDs are typically numeric
        if text.isdigit():
            return True

    return False

