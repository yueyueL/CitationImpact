"""
Citation tree view for CitationImpact.

Shows citing papers as a tree rooted at the analyzed paper, grouped by
year, venue, or the citing author's institution type. Also provides a
plain-text (unicode box-drawing) version of the same tree for file export.
"""
from typing import Any, Dict, List

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Prompt
from rich.tree import Tree

from .components.prompts import get_field

# Leaf paper titles are truncated to roughly this many characters
TITLE_MAX_LEN = 70

# Rich display caps leaves per group; the text export always includes all
MAX_LEAVES_PER_GROUP = 20

_UNKNOWN = 'Unknown'

GROUP_LABELS = {
    'year': 'Year',
    'venue': 'Venue',
    'institution': 'Institution Type',
}


def _extract_paper_info(citation: Any) -> Dict[str, Any]:
    """Extract paper info from a citation object or dict (defensive)."""
    title = get_field(citation, 'citing_paper_title', None) or \
        get_field(citation, 'title', None) or _UNKNOWN
    return {
        'title': title,
        'authors': get_field(citation, 'citing_authors', []) or [],
        'venue': get_field(citation, 'venue', None) or _UNKNOWN,
        'year': get_field(citation, 'year', 0),
        'paper_id': get_field(citation, 'paper_id', '') or '',
        'url': get_field(citation, 'url', '') or '',
        'citation_count': get_field(citation, 'citation_count', 0) or 0,
        'is_influential': bool(get_field(citation, 'is_influential', False)),
    }


def _gather_citing_papers(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Collect citing papers from all available sources.

    Same defensive gathering as show_all_citing_papers: influential
    citations first, then papers attached to all_authors entries,
    deduplicated by lowercased title.
    """
    all_papers: List[Dict[str, Any]] = []

    # From influential citations
    for c in result.get('influential_citations', []) or []:
        paper = _extract_paper_info(c)
        paper['is_influential'] = True
        all_papers.append(paper)

    # From all authors (which have citing papers)
    seen_titles = {p['title'].lower() for p in all_papers}
    for author in result.get('all_authors', []) or []:
        if isinstance(author, dict):
            citing_paper = author.get('citing_paper', '')
            if citing_paper and citing_paper.lower() not in seen_titles:
                all_papers.append({
                    'title': citing_paper,
                    'url': author.get('paper_url', '') or '',
                    'paper_id': author.get('paper_id', '') or '',
                    'year': author.get('year', 0),
                    'venue': author.get('venue', 'Unknown') or 'Unknown',
                    'authors': [author.get('name', 'Unknown')],
                    'is_influential': False,
                    'citation_count': author.get('paper_citations', 0) or 0,
                })
                seen_titles.add(citing_paper.lower())

    return all_papers


def _institution_lookup(result: Dict[str, Any]) -> Dict[str, str]:
    """Map lowercased citing-paper title -> institution_type via all_authors."""
    lookup: Dict[str, str] = {}
    for author in result.get('all_authors', []) or []:
        if not isinstance(author, dict):
            continue
        title = (author.get('citing_paper') or '').lower()
        if not title:
            continue
        inst_type = author.get('institution_type') or ''
        if inst_type and inst_type.lower() not in ('unknown', 'n/a'):
            # First informative institution type wins
            if lookup.get(title, _UNKNOWN) == _UNKNOWN:
                lookup[title] = inst_type
        else:
            lookup.setdefault(title, _UNKNOWN)
    return lookup


def build_citation_tree_data(result: Dict[str, Any],
                             group_by: str = 'year') -> Dict[str, List[Dict[str, Any]]]:
    """
    Group citing papers for the citation tree.

    Args:
        result: Analysis result dictionary
        group_by: 'year' (descending), 'venue', or 'institution'
                  (the citing author's institution_type)

    Returns:
        Ordered dict of {group_label: [paper dicts]}. The 'Unknown'
        bucket always sorts last.
    """
    papers = _gather_citing_papers(result)
    groups: Dict[str, List[Dict[str, Any]]] = {}

    if group_by == 'institution':
        lookup = _institution_lookup(result)
        for paper in papers:
            label = lookup.get(paper['title'].lower(), _UNKNOWN)
            groups.setdefault(label, []).append(paper)
    elif group_by == 'venue':
        for paper in papers:
            label = str(paper.get('venue') or _UNKNOWN)
            groups.setdefault(label, []).append(paper)
    else:  # 'year' (default)
        for paper in papers:
            year = paper.get('year')
            label = str(year) if year not in (None, '', 0, 'N/A') else _UNKNOWN
            groups.setdefault(label, []).append(paper)

    if group_by == 'year':
        # Newest years first; non-numeric labels (Unknown) last
        def year_key(item):
            try:
                return (0, -int(item[0]))
            except (TypeError, ValueError):
                return (1, 0)
        ordered = sorted(groups.items(), key=year_key)
    else:
        # Largest groups first, ties alphabetical; Unknown always last
        ordered = sorted(
            groups.items(),
            key=lambda kv: (kv[0] == _UNKNOWN, -len(kv[1]), kv[0].lower())
        )

    return dict(ordered)


def _truncate_title(title: str, max_len: int = TITLE_MAX_LEN) -> str:
    """Truncate a paper title to roughly max_len characters."""
    if len(title) > max_len:
        return title[:max_len - 3] + "..."
    return title


def _leaf_text(paper: Dict[str, Any], rich_markup: bool = True) -> str:
    """Format one leaf: title (venue) [N cites] ⭐ — rich or plain text."""
    title = _truncate_title(str(paper.get('title') or _UNKNOWN))

    if rich_markup:
        title = escape(title)
        url = paper.get('url') or ''
        paper_id = paper.get('paper_id') or ''
        if url:
            text = f"[link={url}]{title}[/link]"
        elif paper_id:
            text = f"[link=https://www.semanticscholar.org/paper/{paper_id}]{title}[/link]"
        else:
            text = title
    else:
        text = title

    venue = str(paper.get('venue') or '')
    if venue and venue != _UNKNOWN:
        text += f" [dim]({escape(venue)})[/dim]" if rich_markup else f" ({venue})"

    try:
        cites = int(paper.get('citation_count') or 0)
    except (TypeError, ValueError):
        cites = 0
    if cites > 0:
        text += f" [green]\\[{cites} cites][/green]" if rich_markup else f" [{cites} cites]"

    if paper.get('is_influential'):
        text += " ⭐"

    return text


def _group_branch_label(label: str, count: int, rich_markup: bool = True) -> str:
    """Format one group branch: '2024 — 12 citations'."""
    noun = 'citation' if count == 1 else 'citations'
    if rich_markup:
        return f"[bold cyan]{escape(label)}[/bold cyan] [dim]— {count} {noun}[/dim]"
    return f"{label} — {count} {noun}"


def _build_rich_tree(result: Dict[str, Any],
                     groups: Dict[str, List[Dict[str, Any]]]) -> Tree:
    """Build the rich Tree for the grouped citing papers."""
    root_title = str(result.get('paper_title') or 'Analyzed Paper')
    tree = Tree(f"[bold]{escape(root_title)}[/bold]", guide_style="dim")

    for label, papers in groups.items():
        branch = tree.add(_group_branch_label(label, len(papers)))
        for paper in papers[:MAX_LEAVES_PER_GROUP]:
            branch.add(_leaf_text(paper))
        if len(papers) > MAX_LEAVES_PER_GROUP:
            branch.add(f"[dim]… and {len(papers) - MAX_LEAVES_PER_GROUP} more[/dim]")

    return tree


def build_text_tree(result: Dict[str, Any], group_by: str = 'year') -> str:
    """
    Plain-text/unicode box-drawing version of the citation tree.

    Pure function (no rich objects) used for file export. Includes all
    papers (no per-group display cap).
    """
    groups = build_citation_tree_data(result, group_by)
    root_title = str(result.get('paper_title') or 'Analyzed Paper')
    lines = [root_title]

    if not groups:
        lines.append("└── (no citing papers)")
        return "\n".join(lines)

    group_items = list(groups.items())
    for g_idx, (label, papers) in enumerate(group_items):
        is_last_group = g_idx == len(group_items) - 1
        connector = "└── " if is_last_group else "├── "
        lines.append(f"{connector}{_group_branch_label(label, len(papers), rich_markup=False)}")

        child_prefix = "    " if is_last_group else "│   "
        for p_idx, paper in enumerate(papers):
            leaf_connector = "└── " if p_idx == len(papers) - 1 else "├── "
            lines.append(f"{child_prefix}{leaf_connector}{_leaf_text(paper, rich_markup=False)}")

    return "\n".join(lines)


def show_citation_tree(console: Console, result: Dict[str, Any],
                       group_by: str = 'year'):
    """Show the interactive citation tree with regrouping options."""
    while True:
        console.clear()
        console.print(Panel(
            "[title]🌳 CITATION TREE[/title]\n"
            "[dim]Citing papers grouped for a quick structural overview[/dim]",
            expand=False,
            border_style="green"
        ))

        groups = build_citation_tree_data(result, group_by)

        if not groups:
            console.print("\n[warning]No citing papers found[/warning]")
            Prompt.ask("\nPress Enter to return")
            return

        total = sum(len(papers) for papers in groups.values())
        group_name = GROUP_LABELS.get(group_by, group_by)
        console.print(f"\n[info]{total} citing papers grouped by {group_name}[/info]\n")

        console.print(_build_rich_tree(result, groups))
        console.print("\n[dim]⭐ = Influential citation • \\[N cites] = citing paper's own citation count[/dim]")

        console.print("\n[bold cyan]━━━ TREE OPTIONS ━━━[/bold cyan]")
        console.print("  [highlight]y[/highlight] Group by Year")
        console.print("  [highlight]v[/highlight] Group by Venue")
        console.print("  [highlight]i[/highlight] Group by Institution")
        console.print("  [highlight]b[/highlight] Back")

        choice = Prompt.ask("\n[bold]Select option[/bold]", default="b").lower()

        if choice == 'b':
            break
        elif choice == 'y':
            group_by = 'year'
        elif choice == 'v':
            group_by = 'venue'
        elif choice == 'i':
            group_by = 'institution'
