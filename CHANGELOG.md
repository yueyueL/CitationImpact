# Changelog

## 1.4.0 (2026-07-13)

### New output formats
- **CSV bundle** (`--format bundle`): writes `citing_papers.csv`, `authors.csv`
  (with country + match confidence), `venues.csv`, and `timeline.csv` into one
  directory for spreadsheet analysis.
- **Citation tree**: interactive terminal tree (menu option 8, groupable by
  year / venue / institution) and a plain-text export (`--format tree`).
- **HTML report** (`--format html`): a single self-contained HTML file with
  stat tiles, citation timeline chart, world map of citing institutions,
  citation-intent chart with context quotes, scholar/venue tables, and a
  collapsible citation tree. Works offline, light/dark aware.

### International reach
- Citing authors' institution **countries** are now captured from OpenAlex
  (ISO codes on every author, a per-country breakdown in results, a
  "cited across N countries" grant statement, country column in exports).

### Reliability
- Live end-to-end testing caught and fixed a crash: OpenAlex returns explicit
  `null` for `summary_stats` / `last_known_institutions` / `affiliations` on
  some records; all parsing sites are now null-safe (regression-tested).
- `max_citations` is clamped to Semantic Scholar's 1000-limit in API mode
  instead of failing with HTTP 400.
- Full-diff regression audit confirmed and fixed 10 defects introduced during
  the sprint, including: Google Scholar citation IDs leaking from one analysis
  into the next; OpenAlex title lookups breaking on commas (filter injection);
  author dedup creating "chimera" entries (one person's identity with another's
  h-index); Rich-markup crashes on citation text containing bracket tokens
  (e.g. `[/INST]`, `[sic]`); scripted `-o -` output polluted by progress
  prints (now on stderr); explicit `--h-index-threshold 0` being ignored;
  12-letter surnames misread as Google Scholar IDs.
- Data-quality safeguards: correct Semantic Scholar request pacing with an API
  key (was 40 req/s against a ~1 req/s allowance, causing silent mass
  failures), `Retry-After` honored on 429s, per-run API-failure tracking with a
  visible "data may be incomplete" banner in the UI and all report formats, and
  degraded results are no longer written to the 7-day cache. The alarm is
  proportional: a few transient failures produce a note, not the banner.
- **Batch author fetching**: citing-author profiles are now fetched from
  Semantic Scholar's batch endpoint (one request for up to 500 authors instead
  of one per author), then enriched via OpenAlex as before — analyses make an
  order of magnitude fewer requests and survive strict rate limits.
- **Adaptive throttle**: consecutive rate-limit failures automatically slow
  request pacing (up to 8×) and recover on success. OpenAlex now runs at half
  its polite-pool allowance by default; set your email in Settings to join the
  polite pool (dramatically more reliable than anonymous access).

## 1.3.1 (2026-07-12)

### Author disambiguation overhaul (fixes reported same-name mix-ups)
Addresses the reported issue where authors sharing a name could be mistaken
for each other. Author resolution is now **ID-first with evidence-verified
fallbacks**:

- Every resolved author profile carries a `match_confidence` provenance:
  `id` (unique Semantic Scholar / Google Scholar identifier), `verified`
  (name search corroborated by the candidate's publication list), or
  `name` (unverified name-only match).
- Name-keyed author-cache hits are now **gated**: a cached profile that
  merely shares an author's name is only reused when its stored publications
  contain the citing paper. Unverifiable name hits are rejected rather than
  trusted.
- **Browse Other Authors by name** now shows a disambiguation picker
  (name, affiliation, h-index, paper count from Semantic Scholar author
  search) instead of silently using the first same-named hit.
- The UI marks each author with ✓ (ID-matched), ≈ (verified), or ? (name-only,
  may be a different person), with a legend; the summary shows
  "Author profiles: N ID-matched, N verified, N name-only", and the Markdown
  export gains a Match column.
- Exports now use the configured h-index threshold in their labels instead of
  a hardcoded "≥ 20".

## 1.3.0 (2026-07-12)

### New features
- **Field-normalized impact (FWCI)**: analyses now fetch the Field-Weighted
  Citation Impact and field citation percentile from OpenAlex (1.0 = world
  average for the same field/year), shown in the overview, grant summary,
  impact statements, and exports. Degrades gracefully when unavailable.
- **Self-citation detection**: every analysis now reports how many citations
  are independent of the original authors (matched by Semantic Scholar author
  ID, falling back to name compatibility) — the number grant reviewers ask for.
- **"How Your Work Is Used"**: new drill-down (option 7) showing the citation
  intent distribution (methodology / background / result) and sample in-text
  context quotes from citing papers.
- **Report exporter** (`citationimpact/export.py`): export analyses as
  grant-ready **Markdown**, **LaTeX** (appendix-ready section), **CSV** (all
  citing papers), **BibTeX**, or JSON — from the results screen (`e`) or the CLI.
- **Non-interactive CLI** (`citationimpact/cli.py`): script the tool without
  menus — `citation-impact analyze "Paper title" --format markdown -o report.md`,
  `citation-impact cache list|clear`, `citation-impact --version`.
  Running `./citation-impact` with no arguments still opens the interactive UI.
- **Test suite**: 200+ pytest tests covering exporters, models, categorization,
  rankings, caches, analyzer logic, clients, UI helpers, and the CLI.
- **CI**: GitHub Actions workflow running the suite on Python 3.9–3.12.

### Bug fixes (72 verified defects, found by multi-agent audit)
Highlights — full details in git history:
- **Institution misclassification (critical)**: substring matching classified
  Princeton/Cincinnati as *Industry* (`'inc'`), and any "Department of …",
  Newcastle, or NIST-like affiliation as *Government* (`'epa'`, `'cas'`,
  `'nist'` substrings). Now word-boundary matched.
- **Wrong university credit**: fuzzy matchers gave "National University" NUS's
  Top-10 rank and matched arbitrary superstring venues; QS range ranks
  (601-610 etc., 60% of the file) were silently dropped; ICORE junk strings
  ("Unranked", "TBR") were surfaced as ranks.
- **Dead features revived**: methodological citations (S2 returns lowercase
  intents), Crossref citation-count/venue merging (key mismatch/unreachable
  branch), S2 DOI enrichment (externalIds never requested), ORCID fallback
  (wrong class name + list/dict mismatch), DBLP author publications
  (nonexistent endpoint), GS-only papers yielding 0 citations in
  comprehensive mode.
- **Crashes fixed**: google_scholar mode signature mismatches, unified
  search_paper on zero-score results, null citationCounts, ORCID null-name
  records, QS range-rank parsing, None affiliations.
- **Correctness**: author dedup no longer merges distinct authors (first-initial
  guard) and no longer loses repeat citers' papers; publication-overlap cache
  matching no longer attributes co-authors' profiles to each other; author-profile
  cache no longer merges same-name researchers; grant statements no longer
  conflate author counts with university counts and respect the configured
  h-index threshold; citation URLs no longer dropped by an operator-precedence
  bug; "recent citations" now really spans 2 years.
- **Robustness**: config writes are atomic (API keys can't be destroyed by a
  failed save); connection errors are retried; cache expiry handles unlink
  races; UTF-8 enforced for profile files; shared client no longer reused
  across data-source switches (stale-mode analyses); browse-author-by-name
  works in API mode; Selenium clients are tracked and closed.

### Packaging & hygiene
- `setup.py` console entry point referenced a nonexistent module; now installs
  working `citation-impact` / `citationimpact-ui` commands; version
  single-sourced from `citationimpact/__init__.py` (was 0.1.0 vs 1.2.0).
- Added `pyproject.toml`, `.gitignore` (the `.citationimpact/` folder holding
  plaintext API keys was previously trackable), and untracked committed
  `__pycache__` files.

## 1.2.0

- Prior release (see git history).
