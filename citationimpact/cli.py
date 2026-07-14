"""
Command-line interface for CitationImpact.

Running with no arguments launches the interactive terminal UI (the classic
experience). Subcommands enable scripted, non-interactive use:

    citation-impact analyze "Paper title" --format markdown -o report.md
    citation-impact analyze "Paper title" --format json -o -      # to stdout
    citation-impact analyze "Paper title" --format bundle -o out/ # CSV bundle dir
    citation-impact cache list
    citation-impact cache clear --days 30
"""

import argparse
import contextlib
import sys
from typing import List, Optional


def _build_parser() -> argparse.ArgumentParser:
    from . import __version__

    parser = argparse.ArgumentParser(
        prog='citation-impact',
        description='Analyze who cites your research and generate grant-ready impact reports.',
    )
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    subparsers = parser.add_subparsers(dest='command')

    analyze = subparsers.add_parser(
        'analyze',
        help='Analyze a paper non-interactively and export a report',
    )
    analyze.add_argument('title', help='Paper title (or Semantic Scholar paper ID)')
    analyze.add_argument(
        '-f', '--format',
        default='markdown',
        choices=['markdown', 'md', 'latex', 'tex', 'csv', 'bibtex', 'bib', 'json', 'tree', 'html', 'bundle'],
        help="Report format (default: markdown); 'tree' is a plain-text citation tree; "
             "'bundle' writes a directory of CSV files",
    )
    analyze.add_argument(
        '-o', '--output',
        default=None,
        help="Output file path, or '-' for stdout; for --format bundle, the target "
             "directory (default: <config>/exports/ with a generated name)",
    )
    analyze.add_argument('--max-citations', type=int, default=None,
                         help='How many citations to analyze (default: from config)')
    analyze.add_argument('--h-index-threshold', type=int, default=None,
                         help='Minimum h-index for "high-profile" scholars (default: from config)')
    analyze.add_argument('--data-source', choices=['api', 'google_scholar', 'comprehensive'],
                         default=None, help='Data source (default: from config)')
    analyze.add_argument('--no-cache', action='store_true',
                         help='Skip the result cache and fetch fresh data')

    cache = subparsers.add_parser('cache', help='Inspect or clear cached results')
    cache_sub = cache.add_subparsers(dest='cache_command', required=True)
    cache_sub.add_parser('list', help='List cached analyses')
    cache_clear = cache_sub.add_parser('clear', help='Clear cached analyses')
    cache_clear.add_argument('--days', type=int, default=None,
                             help='Only clear entries older than N days (default: clear all)')

    return parser


def _cmd_analyze(args: argparse.Namespace) -> int:
    from . import analyze_paper_impact
    from .config import get_config_manager
    from .export import build_report, export_bundle, export_report

    if args.format == 'bundle' and args.output == '-':
        print("Error: --format bundle writes a directory of CSV files; "
              "'-' (stdout) is not supported. Use -o to name the target directory.",
              file=sys.stderr)
        return 2

    config = get_config_manager()

    # When the report goes to stdout, keep pipeline/cache progress prints on
    # stderr so stdout stays a clean, machine-readable report.
    if args.output == '-':
        progress_ctx = contextlib.redirect_stdout(sys.stderr)
    else:
        progress_ctx = contextlib.nullcontext()

    try:
        with progress_ctx:
            result = analyze_paper_impact(
                paper_title=args.title,
                h_index_threshold=(args.h_index_threshold
                                   if args.h_index_threshold is not None
                                   else config.get('h_index_threshold', 20)),
                max_citations=(args.max_citations
                               if args.max_citations is not None
                               else config.get('max_citations', 100)),
                data_source=(args.data_source
                             if args.data_source is not None
                             else config.get('data_source', 'api')),
                email=config.get('email'),
                semantic_scholar_key=config.get('api_key'),
                scraper_api_key=config.get('scraper_api_key'),
                use_cache=not args.no_cache,
            )
    except (ValueError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    client = result.pop('_client', None)
    if client is not None and hasattr(client, 'close'):
        try:
            client.close()
        except Exception:
            pass

    if result.get('error'):
        print(f"Analysis failed: {result['error']}", file=sys.stderr)
        return 1

    if args.format == 'bundle':
        target = export_bundle(result, args.output)
        print(f"\nBundle written to: {target}")
        for path in sorted(target.glob('*.csv')):
            print(f"  - {path.name}")
    elif args.output == '-':
        print(build_report(result, args.format))
    else:
        path = export_report(result, args.format, args.output)
        print(f"\nReport written to: {path}")
    return 0


def _cmd_cache(args: argparse.Namespace) -> int:
    from .cache import get_result_cache

    cache = get_result_cache()
    if args.cache_command == 'list':
        entries = cache.list_cache()
        if not entries:
            print("No cached analyses.")
            return 0
        for entry in entries:
            title = entry.get('paper_title', 'Unknown')
            cached_at = entry.get('cached_at', 'unknown time')
            source = entry.get('data_source', '?')
            print(f"- {title}  [{source}, cached {cached_at}]")
        print(f"\n{len(entries)} cached analyses.")
    elif args.cache_command == 'clear':
        removed = cache.clear(max_age_days=args.days)
        print(f"Removed {removed} cache entries.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    # No arguments → launch the interactive UI (backward-compatible default)
    if not argv:
        from .ui.app import main as ui_main
        ui_main()
        return 0

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == 'analyze':
        return _cmd_analyze(args)
    if args.command == 'cache':
        return _cmd_cache(args)

    parser.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
