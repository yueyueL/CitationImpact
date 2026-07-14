"""
Report exporters for CitationImpact.

Turns an analysis result dict (from CitationImpactAnalyzer.analyze_paper) into
grant-ready documents: Markdown, LaTeX, CSV, BibTeX, or raw JSON.

All builders accept the result dict as produced by the analyzer OR as loaded
back from the JSON cache (where dataclasses have been converted to dicts),
so every field access is defensive.
"""

import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

EXPORT_FORMATS = ('markdown', 'latex', 'csv', 'bibtex', 'json', 'tree', 'html')

_FORMAT_EXTENSIONS = {
    'markdown': '.md',
    'latex': '.tex',
    'csv': '.csv',
    'bibtex': '.bib',
    'json': '.json',
    'tree': '.txt',
    'html': '.html',
}


def _field(obj: Any, key: str, default: Any = None) -> Any:
    """Get a field from a dict or an object attribute."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# Text labels for Author.match_confidence values ('' / unknown → name-only,
# matching the UI's treatment of legacy data as unverified)
_MATCH_LABELS = {'id': 'ID', 'verified': 'verified', 'name': 'name-only'}


def _match_label(match_confidence: Any) -> str:
    """Human-readable match-confidence label for exports."""
    return _MATCH_LABELS.get(str(match_confidence or '').strip().lower(), 'name-only')


def _citation_row(citation: Any) -> Dict[str, Any]:
    """Normalize a Citation dataclass or cached dict into a flat row."""
    title = _field(citation, 'citing_paper_title') or _field(citation, 'title') or 'Unknown'
    return {
        'title': title,
        'authors': _field(citation, 'citing_authors', []) or _field(citation, 'authors', []) or [],
        'venue': _field(citation, 'venue', '') or '',
        'year': _field(citation, 'year', None),
        'doi': _field(citation, 'doi', '') or '',
        'url': _field(citation, 'url', '') or '',
        'paper_id': _field(citation, 'paper_id', '') or '',
        'citation_count': _field(citation, 'citation_count', 0) or 0,
        'is_influential': bool(_field(citation, 'is_influential', False)),
    }


def _collect_citing_papers(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Gather a deduplicated list of citing papers from every result section."""
    papers: List[Dict[str, Any]] = []
    seen = set()

    def add(row: Dict[str, Any]):
        key = row['title'].lower().strip()
        if key and key not in seen:
            seen.add(key)
            papers.append(row)

    for c in result.get('influential_citations', []) or []:
        row = _citation_row(c)
        row['is_influential'] = True
        add(row)
    for c in result.get('methodological_citations', []) or []:
        add(_citation_row(c))
    for paper in (result.get('impact_stats', {}) or {}).get('highly_cited_citing_papers', []) or []:
        add({
            'title': paper.get('title', 'Unknown'),
            'authors': [],
            'venue': paper.get('venue', '') or '',
            'year': paper.get('year'),
            'doi': '',
            'url': paper.get('url', '') or '',
            'paper_id': '',
            'citation_count': paper.get('citations', 0) or 0,
            'is_influential': False,
        })
    for author in result.get('all_authors', []) or []:
        if not isinstance(author, dict):
            continue
        title = author.get('citing_paper', '')
        if title:
            add({
                'title': title,
                'authors': [author.get('name', 'Unknown')],
                'venue': author.get('venue', '') or '',
                'year': author.get('year'),
                'doi': '',
                'url': author.get('paper_url', '') or '',
                'paper_id': author.get('paper_id', '') or '',
                'citation_count': author.get('paper_citations', 0) or 0,
                'is_influential': False,
            })

    papers.sort(key=lambda p: (p.get('year') or 0, p.get('citation_count') or 0), reverse=True)
    return papers


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #

def build_markdown_report(result: Dict[str, Any]) -> str:
    """Build a grant-ready Markdown impact report."""
    lines: List[str] = []
    title = result.get('paper_title', 'Unknown Paper')
    generated = datetime.now().strftime('%Y-%m-%d')

    lines.append(f"# Citation Impact Report")
    lines.append("")
    lines.append(f"**Paper:** {title}")
    lines.append(f"**Generated:** {generated}")
    lines.append("")

    # Data-quality warning (data_quality is absent on results from older caches)
    data_quality = result.get('data_quality')
    if not isinstance(data_quality, dict):
        data_quality = {}
    dq_warnings = [str(w) for w in (data_quality.get('warnings') or []) if w]
    if data_quality.get('degraded'):
        for w in dq_warnings or ['API failures occurred during this analysis; '
                                 'data may be incomplete. Re-run later for complete data.']:
            lines.append(f"> ⚠ {w}")
        lines.append("")
    elif dq_warnings:
        for w in dq_warnings:
            lines.append(f"*Note: {w}*")
        lines.append("")

    # Overview
    lines.append("## Overview")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Total citations | {result.get('total_citations', 0)} |")
    lines.append(f"| Influential citations | {result.get('influential_citations_count', 0)} |")
    lines.append(f"| Citations analyzed | {result.get('analyzed_citations', 0)} |")

    impact_stats = result.get('impact_stats', {}) or {}
    author_stats = impact_stats.get('author_stats', {}) or {}
    inst_stats = impact_stats.get('institution_stats', {}) or {}
    thresholds = impact_stats.get('citation_thresholds', {}) or {}

    if author_stats:
        lines.append(f"| Unique citing authors | {author_stats.get('total_unique_authors', 0)} |")
        threshold = result.get('h_index_threshold', 20)
        lines.append(f"| High-profile scholars (h ≥ {threshold}) | {author_stats.get('high_profile_count', 0)} |")
        lines.append(f"| Highest citing-author h-index | {author_stats.get('max_h_index', 0)} |")
    if inst_stats:
        lines.append(f"| Citing authors from QS Top 100 | {inst_stats.get('from_qs_top_100', 0)} |")
        if inst_stats.get('countries_count', 0) > 0:
            lines.append(f"| Citing countries | {inst_stats['countries_count']} |")
    if impact_stats.get('recent_citations_count'):
        lines.append(f"| Citations in the last 2 years | {impact_stats['recent_citations_count']} |")

    field_normalized = result.get('field_normalized') or {}
    if field_normalized.get('fwci') is not None:
        lines.append(f"| Field-Weighted Citation Impact (FWCI) | {field_normalized['fwci']:.2f} |")
    percentile = field_normalized.get('citation_percentile')
    if percentile is not None:
        pct = percentile * 100 if percentile <= 1 else percentile
        lines.append(f"| Field citation percentile | {pct:.0f} |")

    self_stats = result.get('self_citation_stats') or {}
    if self_stats:
        lines.append(
            f"| Independent citations (non-self) | {self_stats.get('independent_count', 0)} "
            f"({self_stats.get('independent_percentage', 0):.0f}%) |"
        )
    lines.append("")

    # Profile quality: how reliably citing authors were matched (the counts
    # are absent on results produced before match-confidence tracking)
    id_matched = author_stats.get('id_matched_count', 0) or 0
    verified = author_stats.get('verified_count', 0) or 0
    name_only = author_stats.get('name_only_count', 0) or 0
    if (id_matched + verified + name_only) > 0:
        lines.append(
            f"*Author profiles: {id_matched} ID-matched, "
            f"{verified} verified, {name_only} name-only.*"
        )
        lines.append("")

    # Impact statements
    statements = impact_stats.get('summary_statements', []) or []
    if statements:
        lines.append("## Impact Statements (copy-ready)")
        lines.append("")
        for s in statements:
            lines.append(f"- {s}")
        lines.append("")

    # How the work is used (citation intents + sample contexts)
    insights = result.get('citation_insights') or {}
    intent_counts = insights.get('intent_counts') or {}
    context_samples = insights.get('context_samples') or []
    if intent_counts or context_samples:
        lines.append("## How This Work Is Used")
        lines.append("")
        if intent_counts:
            lines.append("| Citation intent | Count |")
            lines.append("|---|---|")
            for intent, count in sorted(intent_counts.items(), key=lambda kv: -kv[1]):
                lines.append(f"| {intent.capitalize()} | {count} |")
            lines.append("")
        for sample in context_samples[:5]:
            context = str(sample.get('context', '')).replace('\n', ' ')
            title = sample.get('title', 'Unknown')
            year = sample.get('year', '')
            lines.append(f"> “{context}”")
            lines.append(f"> — *{title}* ({year})")
            lines.append("")

    # Highly-cited citing papers
    highly_cited = impact_stats.get('highly_cited_citing_papers', []) or []
    if highly_cited:
        lines.append("## Highly-Cited Papers Citing This Work")
        lines.append("")
        lines.append("| Paper | Citations | Year | Venue |")
        lines.append("|---|---|---|---|")
        for p in highly_cited[:20]:
            paper_title = str(p.get('title', 'Unknown')).replace('|', '\\|')
            url = p.get('url', '')
            cell = f"[{paper_title}]({url})" if url else paper_title
            venue = str(p.get('venue', '') or '').replace('|', '\\|')
            lines.append(f"| {cell} | {p.get('citations', 0)} | {p.get('year', '')} | {venue} |")
        lines.append("")

    # High-profile scholars
    scholars = result.get('high_profile_scholars', []) or []
    if scholars:
        lines.append("## High-Profile Scholars Citing This Work")
        lines.append("")
        lines.append("| Scholar | h-index | Affiliation | Rankings | Match |")
        lines.append("|---|---|---|---|---|")
        for s in scholars[:25]:
            name = str(_field(s, 'name', 'Unknown')).replace('|', '\\|')
            gs_id = _field(s, 'google_scholar_id', '')
            if gs_id:
                name = f"[{name}](https://scholar.google.com/citations?user={gs_id})"
            affiliation = str(_field(s, 'affiliation', 'Unknown') or 'Unknown').replace('|', '\\|')
            rank_parts = []
            if _field(s, 'university_rank'):
                rank_parts.append(f"QS #{_field(s, 'university_rank')}")
            if _field(s, 'usnews_rank'):
                rank_parts.append(f"US News #{_field(s, 'usnews_rank')}")
            match = _match_label(_field(s, 'match_confidence', ''))
            lines.append(
                f"| {name} | {_field(s, 'h_index', 0)} | {affiliation} | "
                f"{', '.join(rank_parts) or '—'} | {match} |"
            )
        lines.append("")

    # Institutions
    institutions = result.get('institutions', {}) or {}
    counts = {k: v for k, v in institutions.items() if isinstance(v, (int, float))}
    if counts and sum(counts.values()) > 0:
        lines.append("## Institution Breakdown")
        lines.append("")
        lines.append("| Type | Citing authors |")
        lines.append("|---|---|")
        for k in ('University', 'Industry', 'Government', 'Other'):
            if k in counts:
                lines.append(f"| {k} | {counts[k]} |")
        lines.append("")

    # Venues
    venues = result.get('venues', {}) or {}
    most_common = venues.get('most_common', []) or []
    if most_common:
        lines.append("## Top Citing Venues")
        lines.append("")
        lines.append(
            f"{venues.get('unique', 0)} unique venues; "
            f"{venues.get('top_tier_percentage', 0):.1f}% of citations from top-tier venues."
        )
        lines.append("")
        lines.append("| Venue | Citations | Rank |")
        lines.append("|---|---|---|")
        rankings = venues.get('rankings', {}) or {}
        for venue_name, count in most_common[:10]:
            info = rankings.get(venue_name, {}) or {}
            rank_parts = []
            if info.get('core_rank'):
                rank_parts.append(f"CORE {info['core_rank']}")
            if info.get('ccf_rank'):
                rank_parts.append(f"CCF {info['ccf_rank']}")
            if info.get('icore_rank'):
                rank_parts.append(f"ICORE {info['icore_rank']}")
            safe_name = str(venue_name).replace('|', '\\|')
            lines.append(f"| {safe_name} | {count} | {', '.join(rank_parts) or '—'} |")
        lines.append("")

    # Timeline
    yearly = result.get('yearly_stats', []) or []
    if yearly:
        lines.append("## Citation Timeline")
        lines.append("")
        lines.append("| Year | Citations |")
        lines.append("|---|---|")
        for year, count in yearly:
            lines.append(f"| {year} | {count} |")
        lines.append("")

    lines.append("---")
    lines.append("*Generated by [CitationImpact](https://github.com/yueyueL/CitationImpact)*")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# LaTeX
# --------------------------------------------------------------------------- #

_LATEX_SPECIALS = {
    '\\': r'\textbackslash{}',
    '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#',
    '_': r'\_', '{': r'\{', '}': r'\}',
    '~': r'\textasciitilde{}', '^': r'\textasciicircum{}',
}


def latex_escape(text: Any) -> str:
    """Escape LaTeX special characters in arbitrary text."""
    return re.sub(
        r'[\\&%$#_{}~^]',
        lambda m: _LATEX_SPECIALS[m.group(0)],
        str(text if text is not None else ''),
    )


def build_latex_report(result: Dict[str, Any]) -> str:
    """Build a LaTeX section suitable for a grant appendix (no preamble needed)."""
    title = latex_escape(result.get('paper_title', 'Unknown Paper'))
    impact_stats = result.get('impact_stats', {}) or {}
    author_stats = impact_stats.get('author_stats', {}) or {}
    inst_stats = impact_stats.get('institution_stats', {}) or {}

    out: List[str] = []
    out.append(f"% Citation impact report generated by CitationImpact on {datetime.now():%Y-%m-%d}")
    out.append(f"\\section*{{Citation Impact: {title}}}")
    out.append("")

    # Data-quality warning (data_quality is absent on results from older caches)
    data_quality = result.get('data_quality')
    if not isinstance(data_quality, dict):
        data_quality = {}
    dq_warnings = [latex_escape(w) for w in (data_quality.get('warnings') or []) if w]
    if data_quality.get('degraded'):
        text = ' '.join(dq_warnings) or ('API failures occurred during this analysis; '
                                         'data may be incomplete. Re-run later for complete data.')
        out.append(f"\\emph{{Warning: {text}}}")
        out.append("")
    elif dq_warnings:
        out.append(f"\\emph{{Note: {' '.join(dq_warnings)}}}")
        out.append("")

    out.append("\\begin{itemize}")
    out.append(f"  \\item Total citations: {result.get('total_citations', 0)}")
    out.append(f"  \\item Influential citations: {result.get('influential_citations_count', 0)}")
    if author_stats.get('high_profile_count'):
        threshold = result.get('h_index_threshold', 20)
        out.append(
            f"  \\item Cited by {author_stats['high_profile_count']} high-profile researchers "
            f"(h-index $\\geq$ {threshold}), with citing-author h-index up to {author_stats.get('max_h_index', 0)}"
        )
    if inst_stats.get('from_qs_top_100'):
        out.append(
            f"  \\item Citing authors at {inst_stats['from_qs_top_100']} QS Top-100 universities"
        )
    field_normalized = result.get('field_normalized') or {}
    if field_normalized.get('fwci') is not None:
        out.append(
            f"  \\item Field-Weighted Citation Impact (FWCI): {field_normalized['fwci']:.2f} "
            f"(1.0 = world average for field and year; source: OpenAlex)"
        )
    self_stats = result.get('self_citation_stats') or {}
    if self_stats.get('independent_count'):
        out.append(
            f"  \\item {self_stats.get('independent_percentage', 0):.0f}\\% of analyzed citations "
            f"are independent of the original authors"
        )
    out.append("\\end{itemize}")
    out.append("")

    statements = impact_stats.get('summary_statements', []) or []
    if statements:
        out.append("\\paragraph{Impact statements}")
        out.append("\\begin{itemize}")
        for s in statements:
            out.append(f"  \\item {latex_escape(s)}")
        out.append("\\end{itemize}")
        out.append("")

    scholars = result.get('high_profile_scholars', []) or []
    if scholars:
        out.append("\\paragraph{Selected high-profile citing scholars}")
        out.append("\\begin{tabular}{l r l}")
        out.append("\\textbf{Scholar} & \\textbf{h-index} & \\textbf{Affiliation} \\\\")
        out.append("\\hline")
        for s in scholars[:15]:
            name = latex_escape(_field(s, 'name', 'Unknown'))
            aff = latex_escape(_field(s, 'affiliation', 'Unknown'))
            out.append(f"{name} & {_field(s, 'h_index', 0)} & {aff} \\\\")
        out.append("\\end{tabular}")
        out.append("")

    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# CSV / BibTeX / JSON
# --------------------------------------------------------------------------- #

def build_csv_report(result: Dict[str, Any]) -> str:
    """Build a CSV of all citing papers (one row per paper)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['title', 'authors', 'venue', 'year', 'citations', 'influential', 'doi', 'url'])
    for p in _collect_citing_papers(result):
        writer.writerow([
            p['title'],
            '; '.join(str(a) for a in p['authors']),
            p['venue'],
            p['year'] if p['year'] else '',
            p['citation_count'],
            'yes' if p['is_influential'] else 'no',
            p['doi'],
            p['url'],
        ])
    return buffer.getvalue()


def _bibtex_key(title: str, year: Any, index: int) -> str:
    """Generate a readable BibTeX key from title words and year."""
    words = re.findall(r'[A-Za-z]+', title)[:2]
    stem = ''.join(w.capitalize() for w in words) or f'Citation{index}'
    return f"{stem}{year or ''}"


def build_bibtex_report(result: Dict[str, Any]) -> str:
    """Build a BibTeX file of all citing papers."""
    entries: List[str] = []
    seen_keys = set()
    for i, p in enumerate(_collect_citing_papers(result), 1):
        key = _bibtex_key(p['title'], p['year'], i)
        while key in seen_keys:
            key += 'a'
        seen_keys.add(key)

        fields = [f"  title = {{{p['title']}}}"]
        if p['authors']:
            fields.append(f"  author = {{{' and '.join(str(a) for a in p['authors'])}}}")
        if p['year']:
            fields.append(f"  year = {{{p['year']}}}")
        if p['venue']:
            fields.append(f"  journal = {{{p['venue']}}}")
        if p['doi']:
            fields.append(f"  doi = {{{p['doi']}}}")
        if p['url']:
            fields.append(f"  url = {{{p['url']}}}")
        entries.append("@article{" + key + ",\n" + ",\n".join(fields) + "\n}")
    return "\n\n".join(entries) + ("\n" if entries else "")


def build_json_report(result: Dict[str, Any]) -> str:
    """Build a JSON export (dataclasses converted defensively)."""
    from .cache import _sanitize_for_json
    export_data = {k: v for k, v in result.items() if not k.startswith('_')}
    export_data['analysis_date'] = datetime.now().isoformat()
    return json.dumps(_sanitize_for_json(export_data), indent=2, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# CSV bundle (multi-file directory export)
# --------------------------------------------------------------------------- #

_AUTHOR_BUNDLE_HEADER = [
    'name', 'h_index', 'h_index_source', 'affiliation', 'institution_type',
    'country', 'match_confidence', 'university_rank', 'google_scholar_id',
    'semantic_scholar_id', 'total_citations', 'works_count', 'citing_papers_count',
]

_VENUE_BUNDLE_HEADER = [
    'venue', 'citations_from_venue', 'h_index', 'rank_tier',
    'core_rank', 'ccf_rank', 'icore_rank',
]


def _write_csv(path: Path, header: List[str], rows: List[List[Any]]) -> None:
    """Write a header + rows CSV file (header-only when rows is empty)."""
    with path.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def build_csv_bundle(result: Dict[str, Any], target_dir) -> List[Path]:
    """
    Write a complete CSV data dump into target_dir and return the file paths.

    Produces four files: citing_papers.csv (same content as the single-file
    CSV export), authors.csv, venues.csv, and timeline.csv. Empty result
    sections produce header-only files.
    """
    target = Path(target_dir).expanduser()
    target.mkdir(parents=True, exist_ok=True)

    # citing_papers.csv — reuse the single-file CSV report
    citing_path = target / 'citing_papers.csv'
    citing_path.write_text(build_csv_report(result), encoding='utf-8')

    # authors.csv — one row per citing author (csv writes None as '')
    author_rows: List[List[Any]] = []
    for author in result.get('all_authors', []) or []:
        if not isinstance(author, dict):
            continue
        author_rows.append([
            author.get('name', ''),
            author.get('h_index', 0),
            author.get('h_index_source', ''),
            author.get('affiliation', ''),
            author.get('institution_type', ''),
            author.get('country', ''),
            author.get('match_confidence', ''),
            author.get('university_rank', ''),
            author.get('google_scholar_id', ''),
            author.get('semantic_scholar_id', ''),
            author.get('total_citations', 0),
            author.get('works_count', 0),
            len(author.get('citing_papers') or []),
        ])
    authors_path = target / 'authors.csv'
    _write_csv(authors_path, _AUTHOR_BUNDLE_HEADER, author_rows)

    # venues.csv — one row per ranked venue
    rankings = (result.get('venues', {}) or {}).get('rankings', {}) or {}
    venue_rows: List[List[Any]] = []
    for venue_name, info in rankings.items():
        if not isinstance(info, dict):
            info = {}
        venue_rows.append([
            venue_name,
            len(info.get('citations') or []),
            info.get('h_index', ''),
            info.get('rank_tier', ''),
            info.get('core_rank', ''),
            info.get('ccf_rank', ''),
            info.get('icore_rank', ''),
        ])
    venues_path = target / 'venues.csv'
    _write_csv(venues_path, _VENUE_BUNDLE_HEADER, venue_rows)

    # timeline.csv — year,count rows
    timeline_rows: List[List[Any]] = []
    for entry in result.get('yearly_stats', []) or []:
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            timeline_rows.append([entry[0], entry[1]])
    timeline_path = target / 'timeline.csv'
    _write_csv(timeline_path, ['year', 'count'], timeline_rows)

    return [citing_path, authors_path, venues_path, timeline_path]


def export_bundle(result: Dict[str, Any], dir_path: Optional[str] = None) -> Path:
    """
    Write the CSV bundle to a directory and return that directory.

    If dir_path is None, writes to the configured export directory
    (<config>/exports/) under a generated impact_<slug>_<date>_bundle name.
    """
    if dir_path is None:
        from .config import get_export_dir
        stamp = datetime.now().strftime('%Y%m%d')
        target = get_export_dir() / f"impact_{_title_slug(result)}_{stamp}_bundle"
    else:
        target = Path(dir_path).expanduser()
    build_csv_bundle(result, target)
    return target


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #

def build_tree_report(result: Dict[str, Any]) -> str:
    """Build a plain-text citation tree (grouped by year)."""
    from .ui.tree_view import build_text_tree
    return build_text_tree(result, group_by='year')


def _build_html_report(result: Dict[str, Any]) -> str:
    """Build a self-contained HTML report (lazy import keeps startup light)."""
    from .html_report import build_html_report
    return build_html_report(result)


_BUILDERS = {
    'markdown': build_markdown_report,
    'latex': build_latex_report,
    'csv': build_csv_report,
    'bibtex': build_bibtex_report,
    'json': build_json_report,
    'tree': build_tree_report,
    'html': _build_html_report,
}


def build_report(result: Dict[str, Any], fmt: str) -> str:
    """Build a report string in the given format ('markdown', 'latex', 'csv', 'bibtex', 'json')."""
    fmt = fmt.lower()
    aliases = {'md': 'markdown', 'tex': 'latex', 'bib': 'bibtex'}
    fmt = aliases.get(fmt, fmt)
    if fmt not in _BUILDERS:
        raise ValueError(f"Unknown export format: {fmt}. Choose from {', '.join(EXPORT_FORMATS)}")
    return _BUILDERS[fmt](result)


def _title_slug(result: Dict[str, Any]) -> str:
    """Slugify the paper title for generated file/directory names."""
    title = result.get('paper_title', 'report')
    return re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:40] or 'report'


def default_export_filename(result: Dict[str, Any], fmt: str) -> str:
    """Suggest a filename like impact_attention-is-all_20260712.md."""
    fmt = {'md': 'markdown', 'tex': 'latex', 'bib': 'bibtex'}.get(fmt.lower(), fmt.lower())
    stamp = datetime.now().strftime('%Y%m%d')
    return f"impact_{_title_slug(result)}_{stamp}{_FORMAT_EXTENSIONS.get(fmt, '.txt')}"


def export_report(result: Dict[str, Any], fmt: str, path: Optional[str] = None) -> Path:
    """
    Write a report to disk and return the path.

    If path is None, writes to the configured export directory
    (<config>/exports/) with a generated filename.
    """
    content = build_report(result, fmt)
    if path is None:
        from .config import get_export_dir
        target = get_export_dir() / default_export_filename(result, fmt)
    else:
        target = Path(path).expanduser()
        if target.is_dir():
            target = target / default_export_filename(result, fmt)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding='utf-8')
    return target
