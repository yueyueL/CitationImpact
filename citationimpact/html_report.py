"""
Self-contained HTML report builder for CitationImpact.

build_html_report(result) turns an analysis result dict (from
CitationImpactAnalyzer.analyze_paper, or loaded back from the JSON cache)
into ONE self-contained HTML document: all CSS/JS inline, no external
requests of any kind (no CDNs, webfonts, or remote images), system font
stack, light theme by default with dark theme via prefers-color-scheme.

Every section degrades gracefully when its data is missing, because cached
results produced by older versions may lack newer keys.

Chart colors follow the validated dataviz reference palette:
- single-series magnitude marks use categorical slot 1 (blue),
- the world-map dots use the sequential blue ramp (flipped anchor in dark),
- match-confidence chips use the fixed status scale, always with text labels.
"""

import html
import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .export import _field, _match_label

# --------------------------------------------------------------------------- #
# Country reference data (ISO2 -> (lat, lon) geographic centroid, and names)
# --------------------------------------------------------------------------- #

COUNTRY_CENTROIDS: Dict[str, Tuple[float, float]] = {
    'AE': (23.4, 53.8), 'AF': (33.9, 67.7), 'AL': (41.2, 20.2), 'AM': (40.1, 45.0),
    'AO': (-11.2, 17.9), 'AR': (-38.4, -63.6), 'AT': (47.5, 14.6), 'AU': (-25.3, 133.8),
    'AZ': (40.1, 47.6), 'BA': (43.9, 17.7), 'BD': (23.7, 90.4), 'BE': (50.5, 4.5),
    'BF': (12.2, -1.6), 'BG': (42.7, 25.5), 'BH': (26.0, 50.6), 'BJ': (9.3, 2.3),
    'BN': (4.5, 114.7), 'BO': (-16.3, -63.6), 'BR': (-14.2, -51.9), 'BT': (27.5, 90.4),
    'BW': (-22.3, 24.7), 'BY': (53.7, 28.0), 'CA': (56.1, -106.3), 'CH': (46.8, 8.2),
    'CL': (-35.7, -71.5), 'CM': (7.4, 12.4), 'CN': (35.9, 104.2), 'CO': (4.6, -74.3),
    'CR': (9.7, -83.8), 'CU': (21.5, -77.8), 'CY': (35.1, 33.4), 'CZ': (49.8, 15.5),
    'DE': (51.2, 10.5), 'DK': (56.3, 9.5), 'DO': (18.7, -70.2), 'DZ': (28.0, 1.7),
    'EC': (-1.8, -78.2), 'EE': (58.6, 25.0), 'EG': (26.8, 30.8), 'ES': (40.5, -3.7),
    'ET': (9.1, 40.5), 'FI': (61.9, 25.7), 'FJ': (-17.7, 178.0), 'FR': (46.2, 2.2),
    'GB': (55.4, -3.4),
    'GE': (42.3, 43.4), 'GH': (7.9, -1.0), 'GR': (39.1, 21.8), 'GT': (15.8, -90.2),
    'HK': (22.3, 114.1), 'HN': (15.2, -86.2), 'HR': (45.1, 15.2), 'HU': (47.2, 19.5),
    'ID': (-0.8, 113.9), 'IE': (53.4, -8.2), 'IL': (31.0, 34.9), 'IN': (20.6, 79.0),
    'IQ': (33.2, 43.7), 'IR': (32.4, 53.7), 'IS': (65.0, -19.0), 'IT': (41.9, 12.6),
    'JM': (18.1, -77.3), 'JO': (30.6, 36.2), 'JP': (36.2, 138.3), 'KE': (-0.02, 37.9),
    'KG': (41.2, 74.8), 'KH': (12.6, 105.0), 'KR': (35.9, 127.8), 'KW': (29.3, 47.5),
    'KZ': (48.0, 66.9), 'LA': (19.9, 102.5), 'LB': (33.9, 35.9), 'LK': (7.9, 80.8),
    'LT': (55.2, 23.9), 'LU': (49.8, 6.1), 'LV': (56.9, 24.6), 'LY': (26.3, 17.2),
    'MA': (31.8, -7.1), 'MD': (47.4, 28.4), 'ME': (42.7, 19.4), 'MG': (-18.8, 46.9),
    'MK': (41.6, 21.7), 'ML': (17.6, -4.0), 'MM': (21.9, 96.0), 'MN': (46.9, 103.8),
    'MO': (22.2, 113.5), 'MT': (35.9, 14.4), 'MU': (-20.3, 57.6), 'MX': (23.6, -102.6),
    'MY': (4.2, 102.0), 'MZ': (-18.7, 35.5), 'NA': (-23.0, 18.5), 'NE': (17.6, 8.1),
    'NG': (9.1, 8.7), 'NI': (12.9, -85.2), 'NL': (52.1, 5.3), 'NO': (60.5, 8.5),
    'NP': (28.4, 84.1), 'NZ': (-40.9, 174.9), 'OM': (21.5, 55.9), 'PA': (8.5, -80.8),
    'PE': (-9.2, -75.0), 'PH': (12.9, 121.8), 'PK': (30.4, 69.3), 'PL': (51.9, 19.1),
    'PR': (18.2, -66.6), 'PT': (39.4, -8.2), 'PY': (-23.4, -58.4), 'QA': (25.4, 51.2),
    'RO': (45.9, 25.0), 'RS': (44.0, 21.0), 'RU': (61.5, 105.3), 'RW': (-1.9, 29.9),
    'SA': (23.9, 45.1), 'SD': (12.9, 30.2), 'SE': (60.1, 18.6), 'SG': (1.35, 103.8),
    'SI': (46.2, 15.0), 'SK': (48.7, 19.7), 'SN': (14.5, -14.5), 'SV': (13.8, -88.9),
    'SY': (34.8, 39.0), 'TH': (15.9, 101.0), 'TN': (33.9, 9.5), 'TR': (39.0, 35.2),
    'TT': (10.7, -61.2), 'TW': (23.7, 121.0), 'TZ': (-6.4, 34.9), 'UA': (48.4, 31.2),
    'UG': (1.4, 32.3), 'US': (39.8, -98.6), 'UY': (-32.5, -55.8), 'UZ': (41.4, 64.6),
    'VE': (6.4, -66.6), 'VN': (14.1, 108.3), 'YE': (15.6, 48.5), 'ZA': (-30.6, 22.9),
    'ZM': (-13.1, 27.8), 'ZW': (-19.0, 29.2),
}

COUNTRY_NAMES: Dict[str, str] = {
    'AE': 'United Arab Emirates', 'AF': 'Afghanistan', 'AL': 'Albania', 'AM': 'Armenia',
    'AO': 'Angola', 'AR': 'Argentina', 'AT': 'Austria', 'AU': 'Australia',
    'AZ': 'Azerbaijan', 'BA': 'Bosnia and Herzegovina', 'BD': 'Bangladesh', 'BE': 'Belgium',
    'BF': 'Burkina Faso', 'BG': 'Bulgaria', 'BH': 'Bahrain', 'BJ': 'Benin',
    'BN': 'Brunei', 'BO': 'Bolivia', 'BR': 'Brazil', 'BT': 'Bhutan',
    'BW': 'Botswana', 'BY': 'Belarus', 'CA': 'Canada', 'CH': 'Switzerland',
    'CL': 'Chile', 'CM': 'Cameroon', 'CN': 'China', 'CO': 'Colombia',
    'CR': 'Costa Rica', 'CU': 'Cuba', 'CY': 'Cyprus', 'CZ': 'Czechia',
    'DE': 'Germany', 'DK': 'Denmark', 'DO': 'Dominican Republic', 'DZ': 'Algeria',
    'EC': 'Ecuador', 'EE': 'Estonia', 'EG': 'Egypt', 'ES': 'Spain',
    'ET': 'Ethiopia', 'FI': 'Finland', 'FJ': 'Fiji', 'FR': 'France',
    'GB': 'United Kingdom',
    'GE': 'Georgia', 'GH': 'Ghana', 'GR': 'Greece', 'GT': 'Guatemala',
    'HK': 'Hong Kong', 'HN': 'Honduras', 'HR': 'Croatia', 'HU': 'Hungary',
    'ID': 'Indonesia', 'IE': 'Ireland', 'IL': 'Israel', 'IN': 'India',
    'IQ': 'Iraq', 'IR': 'Iran', 'IS': 'Iceland', 'IT': 'Italy',
    'JM': 'Jamaica', 'JO': 'Jordan', 'JP': 'Japan', 'KE': 'Kenya',
    'KG': 'Kyrgyzstan', 'KH': 'Cambodia', 'KR': 'South Korea', 'KW': 'Kuwait',
    'KZ': 'Kazakhstan', 'LA': 'Laos', 'LB': 'Lebanon', 'LK': 'Sri Lanka',
    'LT': 'Lithuania', 'LU': 'Luxembourg', 'LV': 'Latvia', 'LY': 'Libya',
    'MA': 'Morocco', 'MD': 'Moldova', 'ME': 'Montenegro', 'MG': 'Madagascar',
    'MK': 'North Macedonia', 'ML': 'Mali', 'MM': 'Myanmar', 'MN': 'Mongolia',
    'MO': 'Macao', 'MT': 'Malta', 'MU': 'Mauritius', 'MX': 'Mexico',
    'MY': 'Malaysia', 'MZ': 'Mozambique', 'NA': 'Namibia', 'NE': 'Niger',
    'NG': 'Nigeria', 'NI': 'Nicaragua', 'NL': 'Netherlands', 'NO': 'Norway',
    'NP': 'Nepal', 'NZ': 'New Zealand', 'OM': 'Oman', 'PA': 'Panama',
    'PE': 'Peru', 'PH': 'Philippines', 'PK': 'Pakistan', 'PL': 'Poland',
    'PR': 'Puerto Rico', 'PT': 'Portugal', 'PY': 'Paraguay', 'QA': 'Qatar',
    'RO': 'Romania', 'RS': 'Serbia', 'RU': 'Russia', 'RW': 'Rwanda',
    'SA': 'Saudi Arabia', 'SD': 'Sudan', 'SE': 'Sweden', 'SG': 'Singapore',
    'SI': 'Slovenia', 'SK': 'Slovakia', 'SN': 'Senegal', 'SV': 'El Salvador',
    'SY': 'Syria', 'TH': 'Thailand', 'TN': 'Tunisia', 'TR': 'Turkey',
    'TT': 'Trinidad and Tobago', 'TW': 'Taiwan', 'TZ': 'Tanzania', 'UA': 'Ukraine',
    'UG': 'Uganda', 'US': 'United States', 'UY': 'Uruguay', 'UZ': 'Uzbekistan',
    'VE': 'Venezuela', 'VN': 'Vietnam', 'YE': 'Yemen', 'ZA': 'South Africa',
    'ZM': 'Zambia', 'ZW': 'Zimbabwe',
}


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _esc(value: Any) -> str:
    """HTML-escape arbitrary (possibly None) values for element/attribute text."""
    return html.escape(str(value if value is not None else ''), quote=True)


def _fmt_int(value: Any) -> str:
    """Thousands-separated integer string ('1,284'); non-numeric -> '0'."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return '0'


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _nice_step(max_value: int, target_ticks: int = 4) -> int:
    """Pick a clean integer tick step (1/2/5 x 10^k) for a 0-based axis."""
    if max_value <= target_ticks:
        return 1
    raw = max_value / target_ticks
    magnitude = 10 ** math.floor(math.log10(raw))
    for mult in (1, 2, 5, 10):
        if mult * magnitude >= raw:
            return int(mult * magnitude)
    return int(10 * magnitude)


def _note(text: str) -> str:
    """A muted inline note used when a section has no data."""
    return f'<p class="note">{_esc(text)}</p>'


def _section(title: str, body: str, subtitle: str = '') -> str:
    sub = f'<p class="section-sub">{_esc(subtitle)}</p>' if subtitle else ''
    return (f'<section class="card">'
            f'<h2>{_esc(title)}</h2>{sub}{body}</section>')


# Fixed status scale (palette.md) — always paired with a text label.
_MATCH_CHIP_CLASSES = {'ID': 'chip-good', 'verified': 'chip-warn', 'name-only': 'chip-serious'}
_MATCH_CHIP_TEXT = {'ID': 'ID-matched', 'verified': 'verified', 'name-only': 'name-only'}


def _match_chip(match_confidence: Any) -> str:
    label = _match_label(match_confidence)
    css = _MATCH_CHIP_CLASSES.get(label, 'chip-serious')
    text = _MATCH_CHIP_TEXT.get(label, 'name-only')
    return (f'<span class="chip {css}"><span class="chip-dot"></span>'
            f'{_esc(text)}</span>')


# --------------------------------------------------------------------------- #
# Header / stat tiles / statements
# --------------------------------------------------------------------------- #

def _render_header(result: Dict[str, Any]) -> str:
    title = result.get('paper_title', 'Unknown Paper')
    generated = datetime.now().strftime('%Y-%m-%d')
    total = _fmt_int(result.get('total_citations', 0))
    analyzed = _fmt_int(result.get('analyzed_citations', 0))
    return (
        '<header class="report-header">'
        '<p class="kicker">Citation Impact Report</p>'
        f'<h1>{_esc(title)}</h1>'
        f'<p class="meta">Generated {_esc(generated)} &middot; '
        f'{total} total citations &middot; {analyzed} analyzed</p>'
        '</header>'
    )


def _quality_banner(result: Dict[str, Any]) -> str:
    """
    Amber warning card shown directly under the header when the analysis was
    flagged as degraded (API failures). Styled with the --status-warn token
    plus an explicit text label ("Data may be incomplete") - never color
    alone. Returns '' for results without data_quality (legacy cache) and a
    plain note for non-degraded warnings.
    """
    data_quality = result.get('data_quality')
    if not isinstance(data_quality, dict):
        return ''
    warnings = [str(w) for w in (data_quality.get('warnings') or []) if w]
    if data_quality.get('degraded'):
        items = ''.join(f'<li>{_esc(w)}</li>' for w in warnings) or (
            '<li>API failures occurred during this analysis; '
            're-run later for complete data.</li>')
        return ('<section class="card quality-banner" role="alert">'
                '<p class="quality-title">&#9888; Data may be incomplete</p>'
                f'<ul class="quality-list">{items}</ul></section>')
    if warnings:
        return _note(' '.join(warnings))
    return ''


def _stat_tiles(result: Dict[str, Any]) -> str:
    impact_stats = result.get('impact_stats', {}) or {}
    author_stats = impact_stats.get('author_stats', {}) or {}
    inst_stats = impact_stats.get('institution_stats', {}) or {}
    field_normalized = result.get('field_normalized') or {}
    self_stats = result.get('self_citation_stats') or {}
    countries = result.get('countries') or {}
    if not isinstance(countries, dict):
        countries = {}
    counts = countries.get('counts') or {}
    if not isinstance(counts, dict):
        counts = {}

    tiles: List[str] = []

    def tile(label: str, value: str, sub: str = '') -> str:
        sub_html = f'<span class="tile-sub">{_esc(sub)}</span>' if sub else ''
        return (f'<div class="tile"><span class="tile-label">{_esc(label)}</span>'
                f'<span class="tile-value">{_esc(value)}</span>{sub_html}</div>')

    tiles.append(tile('Total citations', _fmt_int(result.get('total_citations', 0)),
                      f"{_fmt_int(result.get('influential_citations_count', 0))} influential"))

    fwci = field_normalized.get('fwci')
    if fwci is not None:
        try:
            sub = ''
            percentile = field_normalized.get('citation_percentile')
            if percentile is not None:
                pct = percentile * 100 if percentile <= 1 else percentile
                sub = f"{pct:.0f}th field percentile"
            tiles.append(tile('FWCI', f"{float(fwci):.2f}", sub))
        except (TypeError, ValueError):
            pass

    high_profile = author_stats.get('high_profile_count')
    if high_profile is None:
        scholars = result.get('high_profile_scholars', []) or []
        high_profile = len(scholars) if scholars else None
    if high_profile is not None:
        threshold = result.get('h_index_threshold', 20)
        tiles.append(tile('High-profile scholars', _fmt_int(high_profile),
                          f"h-index ≥ {threshold}"))

    independent_pct = self_stats.get('independent_percentage')
    if independent_pct is not None:
        try:
            tiles.append(tile('Independent citations', f"{float(independent_pct):.0f}%",
                              'non-self citations'))
        except (TypeError, ValueError):
            pass

    n_countries = inst_stats.get('countries_count') or (len(counts) if counts else 0)
    if n_countries:
        tiles.append(tile('Countries', _fmt_int(n_countries), 'of citing authors'))

    return '<div class="tiles">' + ''.join(tiles) + '</div>'


def _statements_section(result: Dict[str, Any]) -> str:
    impact_stats = result.get('impact_stats', {}) or {}
    statements = impact_stats.get('summary_statements', []) or []
    if not statements:
        return ''
    items = ''.join(f'<li>{_esc(s)}</li>' for s in statements)
    return _section('Impact Statements', f'<ul class="statements">{items}</ul>',
                    'Copy-ready sentences for grant applications')


# --------------------------------------------------------------------------- #
# a. Citation timeline (SVG column chart)
# --------------------------------------------------------------------------- #

def _timeline_section(result: Dict[str, Any]) -> str:
    yearly = result.get('yearly_stats', []) or []
    points: List[Tuple[int, int]] = []
    for entry in yearly:
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            year, count = _to_int(entry[0], -1), _to_int(entry[1], 0)
            if year > 0:
                points.append((year, max(0, count)))
    points.sort(key=lambda p: p[0])

    if not points:
        return _section('Citation Timeline', _note('No yearly citation data available.'))

    width, height = 720.0, 240.0
    m_left, m_right, m_top, m_bottom = 44.0, 10.0, 14.0, 26.0
    plot_w = width - m_left - m_right
    plot_h = height - m_top - m_bottom
    baseline = m_top + plot_h

    max_count = max(c for _, c in points)
    step = _nice_step(max_count)
    top_tick = max(step, int(math.ceil(max_count / step)) * step)
    n = len(points)
    slot = plot_w / n
    bar_w = max(2.0, min(24.0, slot - 2.0))

    parts: List[str] = []
    parts.append(f'<svg class="chart" viewBox="0 0 {width:.0f} {height:.0f}" '
                 f'role="img" aria-label="Citations per year">')

    # Recessive horizontal gridlines + integer y ticks
    tick = step
    while tick <= top_tick:
        y = baseline - (tick / top_tick) * plot_h
        parts.append(f'<line class="grid" x1="{m_left:.1f}" y1="{y:.1f}" '
                     f'x2="{width - m_right:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text class="tick" x="{m_left - 6:.1f}" y="{y + 3.5:.1f}" '
                     f'text-anchor="end">{_fmt_int(tick)}</text>')
        tick += step
    parts.append(f'<text class="tick" x="{m_left - 6:.1f}" y="{baseline + 3.5:.1f}" '
                 f'text-anchor="end">0</text>')
    # Baseline
    parts.append(f'<line class="axis" x1="{m_left:.1f}" y1="{baseline:.1f}" '
                 f'x2="{width - m_right:.1f}" y2="{baseline:.1f}"/>')

    label_every = max(1, int(math.ceil(n / 12)))
    max_idx = max(range(n), key=lambda i: points[i][1])

    for i, (year, count) in enumerate(points):
        x = m_left + i * slot + (slot - bar_w) / 2
        h = (count / top_tick) * plot_h if top_tick else 0.0
        y_top = baseline - h
        noun = 'citation' if count == 1 else 'citations'
        tip = f"{year} — {count} {noun}"
        parts.append(f'<g class="hit" tabindex="0" data-tip="{_esc(tip)}">')
        # Transparent full-slot hit target (bigger than the mark)
        parts.append(f'<rect class="hit-area" x="{m_left + i * slot:.1f}" y="{m_top:.1f}" '
                     f'width="{slot:.1f}" height="{plot_h:.1f}"/>')
        if h > 0:
            r = min(4.0, bar_w / 2, h)
            parts.append(
                f'<path class="mark" d="M{x:.1f},{baseline:.1f} L{x:.1f},{y_top + r:.1f} '
                f'Q{x:.1f},{y_top:.1f} {x + r:.1f},{y_top:.1f} '
                f'L{x + bar_w - r:.1f},{y_top:.1f} '
                f'Q{x + bar_w:.1f},{y_top:.1f} {x + bar_w:.1f},{y_top + r:.1f} '
                f'L{x + bar_w:.1f},{baseline:.1f} Z"/>'
            )
        # Direct label on the extreme only; ticks + tooltips carry the rest
        if i == max_idx and count > 0:
            parts.append(f'<text class="value" x="{x + bar_w / 2:.1f}" '
                         f'y="{y_top - 4:.1f}" text-anchor="middle">{_fmt_int(count)}</text>')
        parts.append('</g>')
        if i % label_every == 0:
            parts.append(f'<text class="tick" x="{m_left + i * slot + slot / 2:.1f}" '
                         f'y="{baseline + 16:.1f}" text-anchor="middle">{year}</text>')

    parts.append('</svg>')
    return _section('Citation Timeline', ''.join(parts), 'Citations received per year')


# --------------------------------------------------------------------------- #
# b. World map (equirectangular dot map)
# --------------------------------------------------------------------------- #

def _world_map_section(result: Dict[str, Any]) -> str:
    countries = result.get('countries') or {}
    if not isinstance(countries, dict):
        countries = {}
    counts_raw = countries.get('counts') or {}
    if not isinstance(counts_raw, dict):
        counts_raw = {}
    counts: Dict[str, int] = {}
    for code, n in counts_raw.items():
        n = _to_int(n, 0)
        if n > 0:
            counts[str(code).upper()] = n
    unknown = _to_int(countries.get('unknown'), 0)

    if not counts:
        return _section(
            'International Reach',
            _note('No country data available (country detection requires OpenAlex data).'))

    width, height = 960.0, 500.0
    pad = 10.0
    map_w, map_h = width - 2 * pad, height - 2 * pad

    def project(lat: float, lon: float) -> Tuple[float, float]:
        x = pad + (lon + 180.0) / 360.0 * map_w
        y = pad + (90.0 - lat) / 180.0 * map_h
        return x, y

    parts: List[str] = []
    parts.append(f'<svg class="chart map" viewBox="0 0 {width:.0f} {height:.0f}" '
                 f'role="img" aria-label="Citing authors by country">')
    parts.append(f'<rect class="map-surface" x="{pad}" y="{pad}" '
                 f'width="{map_w}" height="{map_h}" rx="6"/>')

    # Graticule: meridians/parallels every 30 degrees; equator slightly stronger
    for lon in range(-150, 180, 30):
        x, _ = project(0, lon)
        parts.append(f'<line class="grid" x1="{x:.1f}" y1="{pad}" '
                     f'x2="{x:.1f}" y2="{pad + map_h:.1f}"/>')
    for lat in range(-60, 90, 30):
        _, y = project(lat, 0)
        css = 'axis' if lat == 0 else 'grid'
        parts.append(f'<line class="{css}" x1="{pad}" y1="{y:.1f}" '
                     f'x2="{pad + map_w:.1f}" y2="{y:.1f}"/>')

    known = [(code, n) for code, n in counts.items() if code in COUNTRY_CENTROIDS]
    missing = sorted(code for code in counts if code not in COUNTRY_CENTROIDS)
    max_count = max((n for _, n in known), default=1)

    # Draw larger dots first so small neighbours stay visible and hoverable
    for code, n in sorted(known, key=lambda kv: -kv[1]):
        lat, lon = COUNTRY_CENTROIDS[code]
        x, y = project(lat, lon)
        # Dot AREA proportional to count; min radius 4, max ~22
        r = max(4.0, 22.0 * math.sqrt(n / max_count))
        bucket = min(4, int(n / max_count * 5))
        name = COUNTRY_NAMES.get(code, code)
        noun = 'citing author' if n == 1 else 'citing authors'
        tip = f"{name} — {n} {noun}"
        parts.append(f'<g class="hit" tabindex="0" data-tip="{_esc(tip)}">')
        parts.append(f'<circle class="hit-area" cx="{x:.1f}" cy="{y:.1f}" '
                     f'r="{max(r + 6.0, 12.0):.1f}"/>')
        parts.append(f'<circle class="dot seq-{bucket}" data-iso="{_esc(code)}" '
                     f'cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}"/>')
        parts.append(f'<text class="dot-label" x="{x + r + 4:.1f}" y="{y + 3.5:.1f}">'
                     f'{_esc(code)}</text>')
        parts.append('</g>')

    parts.append('</svg>')

    # Compact sorted table: the accessible fallback for the map
    rows = []
    for code, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        name = COUNTRY_NAMES.get(code, code)
        rows.append(f'<tr><td>{_esc(name)}</td>'
                    f'<td class="num">{_fmt_int(n)}</td></tr>')
    if unknown > 0:
        rows.append(f'<tr><td class="muted">Unknown</td>'
                    f'<td class="num">{_fmt_int(unknown)}</td></tr>')
    table = ('<table class="data-table country-table">'
             '<thead><tr><th>Country</th><th class="num">Authors</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table>')

    notes = ''
    if missing:
        listed = ', '.join(f'{_esc(c)} ({_fmt_int(counts[c])})' for c in missing)
        notes = _note(f'Other/unknown locations not shown on the map: {listed}')

    body = f'<div class="map-layout"><div class="map-pane">{"".join(parts)}{notes}</div>' \
           f'<div class="table-pane">{table}</div></div>'
    return _section('International Reach', body,
                    'Citing authors by country (dot area is proportional to count)')


# --------------------------------------------------------------------------- #
# Horizontal bar rows (shared by intents and institutions)
# --------------------------------------------------------------------------- #

def _hbar_rows(rows: List[Tuple[str, int, str]]) -> str:
    """Render horizontal bars: (label, count, value_label); direct-labeled."""
    max_count = max((n for _, n, _ in rows), default=1) or 1
    out: List[str] = ['<div class="hbars">']
    for label, count, value_label in rows:
        pct = (count / max_count) * 100.0
        out.append(
            '<div class="hbar-row">'
            f'<span class="hbar-label">{_esc(label)}</span>'
            '<span class="hbar-track">'
            f'<span class="hbar-fill" style="width:{pct:.1f}%"></span>'
            f'<span class="hbar-value">{_esc(value_label)}</span>'
            '</span></div>'
        )
    out.append('</div>')
    return ''.join(out)


# --------------------------------------------------------------------------- #
# c. How the work is used (intents + context quotes)
# --------------------------------------------------------------------------- #

def _insights_section(result: Dict[str, Any]) -> str:
    insights = result.get('citation_insights') or {}
    if not isinstance(insights, dict):
        insights = {}
    intent_counts = insights.get('intent_counts') or {}
    if not isinstance(intent_counts, dict):
        intent_counts = {}
    context_samples = insights.get('context_samples') or []
    if not intent_counts and not context_samples:
        return _section('How This Work Is Used',
                        _note('No citation intent or context data available.'))

    body: List[str] = []
    if intent_counts:
        ordered = sorted(
            ((str(k), _to_int(v, 0)) for k, v in intent_counts.items()),
            key=lambda kv: -kv[1])
        rows = [(name.capitalize(), n, _fmt_int(n)) for name, n in ordered[:8]]
        tail = sum(n for _, n in ordered[8:])
        if tail > 0:
            rows.append(('Other', tail, _fmt_int(tail)))
        body.append(_hbar_rows(rows))

    for sample in context_samples[:5]:
        if not isinstance(sample, dict):
            continue
        context = str(sample.get('context', '')).replace('\n', ' ').strip()
        if not context:
            continue
        title = sample.get('title', 'Unknown')
        year = sample.get('year', '')
        source = f'{title} ({year})' if year else str(title)
        body.append(f'<blockquote class="quote"><p>&ldquo;{_esc(context)}&rdquo;</p>'
                    f'<footer>&mdash; {_esc(source)}</footer></blockquote>')

    return _section('How This Work Is Used', ''.join(body),
                    'Citation intents and sample citation contexts')


# --------------------------------------------------------------------------- #
# d. Institution breakdown
# --------------------------------------------------------------------------- #

def _institutions_section(result: Dict[str, Any]) -> str:
    institutions = result.get('institutions', {}) or {}
    counts = {k: _to_int(v, 0) for k, v in institutions.items()
              if isinstance(v, (int, float))}
    total = sum(counts.values())
    if total <= 0:
        return _section('Institution Breakdown', _note('No institution data available.'))

    rows: List[Tuple[str, int, str]] = []
    for kind in ('University', 'Industry', 'Government', 'Other'):
        if kind in counts:
            n = counts[kind]
            rows.append((kind, n, f'{_fmt_int(n)} ({n / total * 100:.0f}%)'))
    return _section('Institution Breakdown', _hbar_rows(rows),
                    'Citing authors by institution type')


# --------------------------------------------------------------------------- #
# e. High-profile scholars
# --------------------------------------------------------------------------- #

def _scholars_section(result: Dict[str, Any]) -> str:
    scholars = result.get('high_profile_scholars', []) or []
    threshold = result.get('h_index_threshold', 20)
    if not scholars:
        return _section('High-Profile Scholars', _note('No high-profile scholars identified.'))

    rows: List[str] = []
    for s in scholars[:25]:
        name = _esc(_field(s, 'name', 'Unknown'))
        gs_id = _field(s, 'google_scholar_id', '')
        if gs_id:
            href = f'https://scholar.google.com/citations?user={_esc(gs_id)}'
            name_cell = f'<a href="{href}" rel="noopener">{name}</a>'
        else:
            name_cell = name
        affiliation = _esc(_field(s, 'affiliation', 'Unknown') or 'Unknown')
        country = _esc(_field(s, 'country', '') or '—')
        rank_parts = []
        if _field(s, 'university_rank'):
            rank_parts.append(f"QS #{_field(s, 'university_rank')}")
        if _field(s, 'usnews_rank'):
            rank_parts.append(f"US News #{_field(s, 'usnews_rank')}")
        rankings = _esc(', '.join(rank_parts) or '—')
        rows.append(
            f'<tr><td>{name_cell}</td>'
            f'<td class="num">{_fmt_int(_field(s, "h_index", 0))}</td>'
            f'<td>{affiliation}</td><td>{country}</td><td>{rankings}</td>'
            f'<td>{_match_chip(_field(s, "match_confidence", ""))}</td></tr>'
        )

    table = ('<div class="table-scroll"><table class="data-table">'
             '<thead><tr><th>Scholar</th><th class="num">h-index</th>'
             '<th>Affiliation</th><th>Country</th><th>Rankings</th><th>Match</th>'
             f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    return _section('High-Profile Scholars', table,
                    f'Citing researchers with h-index ≥ {threshold}')


# --------------------------------------------------------------------------- #
# f. Top venues
# --------------------------------------------------------------------------- #

def _venues_section(result: Dict[str, Any]) -> str:
    venues = result.get('venues', {}) or {}
    most_common = venues.get('most_common', []) or []
    if not most_common:
        return _section('Top Citing Venues', _note('No venue data available.'))

    rankings = venues.get('rankings', {}) or {}
    rows: List[str] = []
    for entry in most_common[:10]:
        if not (isinstance(entry, (list, tuple)) and len(entry) >= 2):
            continue
        venue_name, count = entry[0], entry[1]
        info = rankings.get(venue_name, {}) or {}
        chips = []
        if info.get('core_rank'):
            chips.append(f'<span class="chip chip-plain">CORE {_esc(info["core_rank"])}</span>')
        if info.get('ccf_rank'):
            chips.append(f'<span class="chip chip-plain">CCF {_esc(info["ccf_rank"])}</span>')
        if info.get('icore_rank'):
            chips.append(f'<span class="chip chip-plain">ICORE {_esc(info["icore_rank"])}</span>')
        rows.append(f'<tr><td>{_esc(venue_name)}</td>'
                    f'<td class="num">{_fmt_int(count)}</td>'
                    f'<td>{" ".join(chips) or "—"}</td></tr>')

    table = ('<div class="table-scroll"><table class="data-table">'
             '<thead><tr><th>Venue</th><th class="num">Citations</th><th>Rank</th>'
             f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')

    subtitle = ''
    if venues.get('unique'):
        try:
            subtitle = (f"{_fmt_int(venues.get('unique', 0))} unique venues; "
                        f"{float(venues.get('top_tier_percentage', 0) or 0):.1f}% "
                        f"of citations from top-tier venues")
        except (TypeError, ValueError):
            subtitle = f"{_fmt_int(venues.get('unique', 0))} unique venues"
    return _section('Top Citing Venues', table, subtitle)


# --------------------------------------------------------------------------- #
# g. Citation tree
# --------------------------------------------------------------------------- #

def _paper_link(paper: Dict[str, Any]) -> Optional[str]:
    # Only http(s) URLs may become clickable links: records loaded from
    # external APIs or the JSON cache could otherwise smuggle a script
    # scheme (e.g. javascript:) into an <a href> — html.escape does not
    # neutralize URL schemes.
    url = str(paper.get('url') or '').strip()
    if url.lower().startswith(('http://', 'https://')):
        return url
    paper_id = paper.get('paper_id') or ''
    if paper_id:
        return f'https://www.semanticscholar.org/paper/{paper_id}'
    return None


def _tree_section(result: Dict[str, Any]) -> str:
    try:
        from .ui.tree_view import build_citation_tree_data
        groups = build_citation_tree_data(result, group_by='year')
    except Exception:
        groups = {}
    if not groups:
        return _section('Citation Tree', _note('No citing papers available.'))

    parts: List[str] = []
    for idx, (label, papers) in enumerate(groups.items()):
        noun = 'citation' if len(papers) == 1 else 'citations'
        open_attr = ' open' if idx == 0 else ''
        parts.append(f'<details class="tree-group"{open_attr}>'
                     f'<summary>{_esc(label)} <span class="muted">&mdash; '
                     f'{len(papers)} {noun}</span></summary><ul class="tree-list">')
        for paper in papers:
            title = _esc(paper.get('title') or 'Unknown')
            href = _paper_link(paper)
            title_html = (f'<a href="{_esc(href)}" rel="noopener">{title}</a>'
                          if href else title)
            extras = []
            venue = paper.get('venue') or ''
            if venue and venue != 'Unknown':
                extras.append(f'<span class="muted">({_esc(venue)})</span>')
            cites = _to_int(paper.get('citation_count'), 0)
            if cites > 0:
                extras.append(f'<span class="muted">[{_fmt_int(cites)} cites]</span>')
            if paper.get('is_influential'):
                extras.append('<span title="Influential citation">⭐</span>')
            parts.append(f'<li>{title_html} {" ".join(extras)}</li>')
        parts.append('</ul></details>')

    return _section('Citation Tree', ''.join(parts), 'Citing papers grouped by year')


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--page);
  color: var(--ink);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  line-height: 1.5;
  --page: #f9f9f7; --surface: #fcfcfb;
  --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7;
  --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6;
  --seq-0: #86b6ef; --seq-1: #5598e7; --seq-2: #2a78d6;
  --seq-3: #1c5cab; --seq-4: #104281;
  --status-good: #0ca30c; --status-warn: #fab219; --status-serious: #ec835a;
}
@media (prefers-color-scheme: dark) {
  body {
    --page: #0d0d0d; --surface: #1a1a19;
    --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835;
    --border: rgba(255,255,255,0.10);
    --series-1: #3987e5;
    --seq-0: #184f95; --seq-1: #2a78d6; --seq-2: #5598e7;
    --seq-3: #86b6ef; --seq-4: #b7d3f6;
  }
}
.page { max-width: 980px; margin: 0 auto; padding: 32px 20px 48px; }
.report-header { margin-bottom: 20px; }
.kicker { margin: 0; color: var(--ink-2); font-size: 13px;
  text-transform: uppercase; letter-spacing: 0.08em; }
h1 { margin: 4px 0 6px; font-size: 26px; line-height: 1.25; }
.meta { margin: 0; color: var(--ink-2); font-size: 14px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px; margin-bottom: 20px; }
.tile { background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 16px; display: flex; flex-direction: column; }
.tile-label { color: var(--ink-2); font-size: 13px; }
.tile-value { font-size: 30px; font-weight: 600; margin-top: 2px; }
.tile-sub { color: var(--muted); font-size: 12px; margin-top: 2px; }
.card { background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 20px; margin-bottom: 16px; }
.card h2 { margin: 0 0 2px; font-size: 17px; }
.section-sub { margin: 0 0 14px; color: var(--ink-2); font-size: 13px; }
.note { color: var(--muted); font-size: 14px; margin: 8px 0 0; }
.muted { color: var(--muted); }
.statements { margin: 8px 0 0; padding-left: 20px; }
.statements li { margin-bottom: 6px; }
.chart { width: 100%; height: auto; display: block; }
.chart .grid { stroke: var(--grid); stroke-width: 1; }
.chart .axis { stroke: var(--axis); stroke-width: 1; }
.chart .tick { fill: var(--muted); font-size: 11px;
  font-variant-numeric: tabular-nums; }
.chart .value { fill: var(--ink-2); font-size: 11px; }
.chart .mark { fill: var(--series-1); }
.chart .hit-area { fill: transparent; }
.chart .hit { cursor: default; outline: none; }
.chart .hit:hover .mark, .chart .hit:focus .mark,
.chart .hit:hover .dot, .chart .hit:focus .dot { opacity: 0.8; }
.map-surface { fill: var(--surface); stroke: none; }
.dot { stroke: var(--surface); stroke-width: 2; }
.seq-0 { fill: var(--seq-0); } .seq-1 { fill: var(--seq-1); }
.seq-2 { fill: var(--seq-2); } .seq-3 { fill: var(--seq-3); }
.seq-4 { fill: var(--seq-4); }
.dot-label { fill: var(--ink-2); font-size: 10px; }
.map-layout { display: flex; gap: 20px; flex-wrap: wrap; }
.map-pane { flex: 3 1 480px; min-width: 0; }
.table-pane { flex: 1 1 200px; }
.hbars { display: flex; flex-direction: column; gap: 8px; }
.hbar-row { display: grid; grid-template-columns: 110px 1fr;
  align-items: center; gap: 10px; }
.hbar-label { font-size: 13px; color: var(--ink-2); text-align: right; }
.hbar-track { display: flex; align-items: center; gap: 8px; min-width: 0; }
.hbar-fill { display: inline-block; height: 18px; background: var(--series-1);
  border-radius: 0 4px 4px 0; min-width: 2px; }
.hbar-value { font-size: 12px; color: var(--ink-2); white-space: nowrap; }
.table-scroll { overflow-x: auto; }
.data-table { border-collapse: collapse; width: 100%; font-size: 14px; }
.data-table th { text-align: left; color: var(--ink-2); font-weight: 600;
  font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }
.data-table th, .data-table td { padding: 7px 10px;
  border-bottom: 1px solid var(--grid); }
.data-table td.num, .data-table th.num { text-align: right;
  font-variant-numeric: tabular-nums; }
.country-table { font-size: 13px; }
a { color: var(--series-1); }
.chip { display: inline-flex; align-items: center; gap: 5px;
  border: 1px solid var(--border); border-radius: 999px;
  padding: 1px 9px; font-size: 11.5px; color: var(--ink-2);
  white-space: nowrap; }
.chip-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.chip-good .chip-dot { background: var(--status-good); }
.chip-warn .chip-dot { background: var(--status-warn); }
.chip-serious .chip-dot { background: var(--status-serious); }
.quality-banner { border-left: 4px solid var(--status-warn); }
.quality-title { margin: 0; font-size: 15px; font-weight: 600; }
.quality-list { margin: 6px 0 0; padding-left: 20px; font-size: 14px;
  color: var(--ink-2); }
.quote { margin: 14px 0 0; padding: 2px 0 2px 14px;
  border-left: 3px solid var(--grid); color: var(--ink-2); }
.quote p { margin: 0 0 4px; font-style: italic; }
.quote footer { font-size: 13px; color: var(--muted); }
.tree-group { margin-bottom: 6px; }
.tree-group summary { cursor: pointer; font-weight: 600; padding: 4px 0; }
.tree-list { list-style: none; margin: 4px 0 10px; padding-left: 18px;
  border-left: 1px solid var(--grid); }
.tree-list li { margin: 4px 0; font-size: 14px; }
.report-footer { color: var(--muted); font-size: 13px; text-align: center;
  margin-top: 24px; }
.ci-tip { position: fixed; z-index: 10; background: var(--surface);
  color: var(--ink); border: 1px solid var(--border); border-radius: 6px;
  padding: 5px 10px; font-size: 12.5px; pointer-events: none;
  box-shadow: 0 2px 8px rgba(0,0,0,0.15); max-width: 280px; }
"""

# Tooltip helper: labels are untrusted data, so the tip is set via textContent.
_JS = """
(function () {
  var tip = document.createElement('div');
  tip.className = 'ci-tip';
  tip.setAttribute('role', 'status');
  tip.hidden = true;
  document.body.appendChild(tip);
  function place(x, y) {
    var pad = 12;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var left = Math.min(x + pad, window.innerWidth - w - 8);
    var top = y - h - pad;
    if (top < 4) top = y + pad;
    tip.style.left = Math.max(4, left) + 'px';
    tip.style.top = top + 'px';
  }
  function show(el, x, y) {
    var text = el.getAttribute('data-tip');
    if (!text) return;
    tip.textContent = text;
    tip.hidden = false;
    place(x, y);
  }
  function hide() { tip.hidden = true; }
  var hits = document.querySelectorAll('[data-tip]');
  for (var i = 0; i < hits.length; i++) {
    (function (el) {
      el.addEventListener('pointermove', function (e) { show(el, e.clientX, e.clientY); });
      el.addEventListener('pointerleave', hide);
      el.addEventListener('focus', function () {
        var r = el.getBoundingClientRect();
        show(el, r.left + r.width / 2, r.top);
      });
      el.addEventListener('blur', hide);
    })(hits[i]);
  }
})();
"""


def _footer(result: Dict[str, Any]) -> str:
    try:
        from . import __version__
        version = f'v{__version__}'
    except Exception:
        version = ''
    analysis_date = result.get('analysis_date') or datetime.now().strftime('%Y-%m-%d')
    return (f'<footer class="report-footer">Generated by CitationImpact {_esc(version)} '
            f'&middot; Analysis date: {_esc(str(analysis_date)[:10])}</footer>')


def build_html_report(result: Dict[str, Any]) -> str:
    """Build a self-contained single-file HTML impact report."""
    title = result.get('paper_title', 'Unknown Paper')
    body = ''.join([
        _render_header(result),
        _quality_banner(result),
        _stat_tiles(result),
        _statements_section(result),
        _timeline_section(result),
        _world_map_section(result),
        _insights_section(result),
        _institutions_section(result),
        _scholars_section(result),
        _venues_section(result),
        _tree_section(result),
        _footer(result),
    ])
    return (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>Citation Impact — {_esc(title)}</title>\n'
        f'<style>{_CSS}</style>\n'
        '</head>\n<body>\n'
        f'<div class="page">{body}</div>\n'
        f'<script>{_JS}</script>\n'
        '</body>\n</html>\n'
    )
