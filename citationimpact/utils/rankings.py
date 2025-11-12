"""
Utilities to load and use rankings data (CORE, QS, CCF, etc.)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Any

import pandas as pd

# Path to data directory
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CORE_DIR = DATA_DIR / "core_rankings"
UNI_DIR = DATA_DIR / "university_rankings"
VENUE_DIR = DATA_DIR / "venues_rankings"

# Cache for loaded data
_core_rankings_cache: Optional[Dict[str, str]] = None
_university_rankings_cache: Optional[Dict[str, Dict[str, Any]]] = None


def _store_venue_rank(
    storage: Dict[str, Dict[str, Any]],
    keys: Iterable[str],
    rank: Optional[str],
    *,
    source: str,
) -> None:
    """Store venue ranking under multiple key variations for the given source."""
    if not rank:
        return
    rank_value = str(rank).strip()
    if not rank_value:
        return

    normalized_keys: List[str] = []
    for key in keys:
        if not key:
            continue
        clean = str(key).strip()
        if not clean:
            continue
        normalized_keys.extend([clean, clean.lower(), clean.upper()])

    if not normalized_keys:
        return

    # Reuse existing entry if any of the keys already mapped
    entry = None
    for key in normalized_keys:
        entry = storage.get(key)
        if entry:
            break

    if entry is None:
        entry = {
            "canonical": normalized_keys[0],
            "aliases": set(),  # type: ignore[dict-item]
            "sources": {},     # type: ignore[dict-item]
        }

    aliases: set = entry.setdefault("aliases", set())  # type: ignore[assignment]
    sources: Dict[str, str] = entry.setdefault("sources", {})  # type: ignore[assignment]
    sources[source] = rank_value

    # Update canonical name if we received a cleaner one
    first_key = keys[0] if keys else normalized_keys[0]
    if first_key:
        entry["canonical"] = str(first_key).strip() or entry["canonical"]

    for key in normalized_keys:
        storage[key] = entry
        aliases.add(key)


def _store_university_entry(
    storage: Dict[str, Dict[str, Any]],
    name: str,
    rank: Any,
    *,
    tier: Optional[str] = None,
    aliases: Optional[Iterable[str]] = None,
    country: Optional[str] = None,
    source: Optional[str] = None,
    source_key: str = "other",
    overwrite: bool = True,
) -> None:
    """Store university ranking with helpful key variations and multi-source support."""
    if name is None:
        return

    name_clean = str(name).strip()
    if not name_clean:
        return

    try:
        if pd.isna(rank):  # type: ignore[attr-defined]
            return
    except TypeError:
        pass

    if isinstance(rank, str):
        rank_str = rank.replace("=", "").strip()
        if not rank_str or not rank_str.replace(".", "").replace("-", "").isdigit():
            return
        rank_value = int(float(rank_str))
    elif isinstance(rank, (int, float)):
        if pd.isna(rank):  # type: ignore[attr-defined]
            return
        rank_value = int(rank)
    else:
        return

    tier_value = tier or determine_university_tier(rank_value)

    # Try to find an existing entry (case-insensitive)
    entry = None
    for variant in (name_clean, name_clean.lower(), name_clean.upper()):
        if variant in storage:
            entry = storage[variant]
            break

    if entry is None:
        entry = {
            "canonical": name_clean,
            "aliases": set(),
            "sources": {},
            "primary_source": None,
            "rank": None,
            "tier": None,
            "country": str(country).strip() if country else None,
        }
    else:
        if country and not entry.get("country"):
            entry["country"] = str(country).strip()

    sources: Dict[str, Dict[str, Any]] = entry.setdefault("sources", {})
    sources[source_key] = {
        "rank": rank_value,
        "tier": tier_value,
        "country": str(country).strip() if country else entry.get("country"),
        "label": source or source_key,
    }

    preferred_order = ["qs", "usnews"]
    current_primary = entry.get("primary_source")
    if (
        current_primary is None
        or source_key in preferred_order
        and (
            current_primary not in preferred_order
            or preferred_order.index(source_key) < preferred_order.index(current_primary)
        )
    ):
        entry["primary_source"] = source_key
        entry["rank"] = rank_value
        entry["tier"] = tier_value

    alias_list: List[str] = []
    if aliases:
        for alias in aliases:
            alias_clean = str(alias).strip()
            if alias_clean:
                alias_list.append(alias_clean)

    alias_list.extend(extract_parenthetical_aliases(name_clean))
    alias_list.extend(heuristic_university_aliases(name_clean))

    entry_aliases: set = entry.setdefault("aliases", set())
    entry_aliases.add(name_clean)

    def _assign(key: str, allow_override: bool, record_alias: bool = False) -> None:
        if not key:
            return
        if not allow_override and key in storage:
            return
        storage[key] = entry
        if record_alias:
            entry_aliases.add(key)

    _assign(name_clean, overwrite, record_alias=True)
    _assign(name_clean.lower(), True)
    _assign(name_clean.upper(), True)

    for alias in alias_list:
        alias_clean = alias.strip()
        if not alias_clean:
            continue
        entry_aliases.add(alias_clean)
        _assign(alias_clean, True, record_alias=True)
        _assign(alias_clean.lower(), True)
        _assign(alias_clean.upper(), True)


def extract_parenthetical_aliases(text: str) -> List[str]:
    """Return aliases found inside parentheses or brackets."""
    aliases: List[str] = []
    for match in re.findall(r"\(([^()]+)\)", text or ""):
        parts = re.split(r"[,/;]+", match)
        aliases.extend(part.strip() for part in parts if part.strip())
    return aliases


def heuristic_university_aliases(name: str) -> List[str]:
    """Generate heuristic aliases (e.g. UC Berkeley from University of California, Berkeley)."""
    aliases: List[str] = []
    if not name:
        return aliases

    base = re.sub(r"\(.*?\)", "", name).strip()
    lower = base.lower()

    if lower.startswith("university of california"):
        remainder = base[len("University of California"):].strip()
        remainder = remainder.lstrip(", ")
        if remainder:
            aliases.append(f"UC {remainder}")

    return aliases


def determine_university_tier(rank: int) -> str:
    """Convert numeric ranking to a tier label."""
    if rank <= 10:
        return "Top 10"
    if rank <= 25:
        return "Top 25"
    if rank <= 50:
        return "Top 50"
    if rank <= 100:
        return "Top 100"
    if rank <= 200:
        return "Top 200"
    if rank <= 500:
        return "Top 500"
    return "Ranked"


def parse_rank_value(value: Any) -> Optional[int]:
    """Best-effort parser that turns a value into an integer rank."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if pd.isna(value):  # type: ignore[attr-defined]
            return None
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("=", "").replace("#", "")
    if text.isdigit():
        return int(text)
    try:
        return int(float(text))
    except ValueError:
        return None


def load_core_rankings() -> Optional[Dict[str, str]]:
    """
    Load CORE rankings from processed JSON file

    Returns:
        Dict mapping venue names to rankings (A*, A, B, C) or None if not available
    """
    global _core_rankings_cache

    if _core_rankings_cache is not None:
        return _core_rankings_cache

    rankings: Dict[str, str] = {}

    # Processed JSON exports (e.g. from update scripts)
    if CORE_DIR.exists():
        for json_path in sorted(CORE_DIR.glob("*processed.json")):
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                print(f"[Warning] Failed to parse CORE rankings JSON ({json_path.name}): {exc}")
                continue
            except OSError as exc:
                print(f"[Warning] Failed to load CORE rankings ({json_path.name}): {exc}")
                continue
            if not isinstance(data, dict):
                print(f"[Warning] CORE rankings file has invalid format ({json_path.name})")
                continue
            for key, rank in data.items():
                _store_venue_rank(rankings, [key], rank, source="core")

        for csv_path in sorted(CORE_DIR.glob("*.csv")):
            try:
                df = pd.read_csv(csv_path)
            except Exception as exc:  # pragma: no cover - defensive logging
                print(f"[Warning] Failed to load CORE CSV ({csv_path.name}): {exc}")
                continue

            available_rank_columns = [
                column
                for column in ["2023", "2022", "2021", "Rank", "Rating", "core2023"]
                if column in df.columns
            ]
            for _, row in df.iterrows():
                acronym = str(row.get("Acronym", "")).strip()
                title = str(row.get("Title", "")).strip()
                rank_value = None
                for column in available_rank_columns:
                    candidate = row.get(column)
                    if pd.isna(candidate):
                        continue
                    candidate_str = str(candidate).strip()
                    if candidate_str and candidate_str.lower() != "nan":
                        rank_value = candidate_str
                        break
                if rank_value:
                    _store_venue_rank(rankings, [acronym, title], rank_value, source="core")

    # Additional venue datasets (e.g. CCF, ICORE)
    if VENUE_DIR.exists():
        icore_path = VENUE_DIR / "ICORE2023.csv"
        if icore_path.exists():
            try:
                df_icore = pd.read_csv(icore_path)
                for _, row in df_icore.iterrows():
                    rank_value = str(row.get("Rank", "")).strip()
                    acronym = str(row.get("Acronym", "")).strip()
                    title = str(row.get("Title", "")).strip()
                    if rank_value:
                        _store_venue_rank(rankings, [acronym, title], rank_value, source="icore")
            except Exception as exc:  # pragma: no cover - defensive logging
                print(f"[Warning] Failed to load ICORE rankings: {exc}")

        ccf_path = VENUE_DIR / "CCF_Ranking_2022.json"
        if ccf_path.exists():
            try:
                ccf_data = json.loads(ccf_path.read_text(encoding="utf-8"))
                entries = ccf_data.get("list", []) if isinstance(ccf_data, dict) else []
                for item in entries:
                    if not isinstance(item, dict):
                        continue
                    rank_value = item.get("rank")
                    name = item.get("name")
                    abbr = item.get("abbr")
                    if rank_value:
                        _store_venue_rank(rankings, [abbr, name], rank_value, source="ccf")
            except json.JSONDecodeError as exc:
                print(f"[Warning] Failed to parse CCF rankings JSON: {exc}")
            except OSError as exc:
                print(f"[Warning] Failed to load CCF rankings JSON: {exc}")

    if not rankings:
        print("[Info] CORE/venue rankings not found. Run: python3 data/update_core_rankings.py")
        rankings = {}

    _core_rankings_cache = rankings
    return rankings


def _find_venue_entry(rankings: Optional[Dict[str, Dict[str, Any]]], venue_name: str) -> Optional[Dict[str, Any]]:
    """Return the ranking entry for a venue using fuzzy matching."""
    if not rankings or not venue_name:
        return None

    normalized = venue_name.strip()
    if not normalized:
        return None

    # Exact match
    if normalized in rankings:
        return rankings[normalized]

    # Case-variant match
    for key in {normalized.lower(), normalized.upper(), normalized.title()}:
        if key in rankings:
            return rankings[key]

    # Partial match (avoid noisy very short tokens)
    venue_lower = normalized.lower()
    for key, entry in rankings.items():
        key_lower = key.lower()
        if min(len(key_lower), len(venue_lower)) < 4:
            continue
        if venue_lower in key_lower or key_lower in venue_lower:
            return entry

    return None


def _find_university_entry(rankings: Optional[Dict[str, Dict[str, Any]]], university_name: str) -> Optional[Dict[str, Any]]:
    """Return the ranking entry for a university using fuzzy matching."""
    if not rankings or not university_name:
        return None

    normalized = university_name.strip()
    if not normalized:
        return None

    for key in (normalized, normalized.lower(), normalized.upper()):
        if key in rankings:
            return rankings[key]

    uni_lower = normalized.lower()
    for key, entry in rankings.items():
        key_lower = key.lower()
        if min(len(key_lower), len(uni_lower)) < 4:
            continue
        if uni_lower in key_lower or key_lower in uni_lower:
            return entry

    return None


def load_university_rankings() -> Optional[Dict[str, Dict]]:
    """
    Load university rankings from processed JSON file

    Returns:
        Dict mapping university names to {'rank': int, 'tier': str} or None if not available
    """
    global _university_rankings_cache

    if _university_rankings_cache is not None:
        return _university_rankings_cache

    rankings: Dict[str, Dict[str, Any]] = {}

    # Lowest priority: legacy lookup JSONs (do not overwrite newer data)
    if UNI_DIR.exists():
        for json_path in sorted(UNI_DIR.glob("*lookup*.json")):
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                print(f"[Warning] Failed to parse university rankings JSON ({json_path.name}): {exc}")
                continue
            except OSError as exc:
                print(f"[Warning] Failed to load university rankings ({json_path.name}): {exc}")
                continue
            if not isinstance(data, dict):
                continue
            for name, info in data.items():
                if not isinstance(info, dict):
                    continue
                rank_value = info.get("rank")
                tier_value = info.get("tier")
                country = info.get("country") if isinstance(info.get("country"), str) else None
                filename_lower = json_path.name.lower()
                if "qs" in filename_lower:
                    source_key = "qs"
                elif "usnews" in filename_lower or "us_news" in filename_lower:
                    source_key = "usnews"
                else:
                    source_key = "json"
                _store_university_entry(
                    rankings,
                    name,
                    rank_value,
                    tier=tier_value,
                    country=country,
                    source=json_path.name,
                    source_key=source_key,
                    overwrite=False,
                )

        # Higher priority: CSV exports (may override older data)
        for csv_path in sorted(UNI_DIR.glob("*.csv")):
            _load_university_csv(csv_path, rankings)

    if not rankings:
        print("[Info] University rankings not found. Run: python3 data/update_qs_rankings.py")
        rankings = {}

    _university_rankings_cache = rankings
    return rankings


def _load_university_csv(csv_path: Path, rankings: Dict[str, Dict[str, Any]]) -> None:
    """Load a university ranking CSV, handling multiple schema variants."""
    try:
        df = pd.read_csv(csv_path)
    except Exception:
        # Retry with offset header if first row looks like repeated header
        try:
            df = pd.read_csv(csv_path, header=1)
        except Exception as exc:  # pragma: no cover - defensive logging
            print(f"[Warning] Failed to load university CSV ({csv_path.name}): {exc}")
            return

    # Detect and remove duplicate header rows (common in QS exports)
    if not df.empty and isinstance(df.iloc[0, 0], str) and df.iloc[0, 0].lower().startswith("rank"):
        df = df.drop(index=0).reset_index(drop=True)

    columns_lower = {col.lower(): col for col in df.columns}
    filename_lower = csv_path.name.lower()
    if "qs" in filename_lower:
        source_key = "qs"
    elif "usnews" in filename_lower or "us_news" in filename_lower:
        source_key = "usnews"
    else:
        source_key = "csv"

    rank_col = (
        columns_lower.get("rank")
        or columns_lower.get("rank display")
        or columns_lower.get("2024 rank")
        or columns_lower.get("overall rank")
    )
    name_col = (
        columns_lower.get("institution")
        or columns_lower.get("institution name")
        or columns_lower.get("university")
        or columns_lower.get("name")
    )

    if not rank_col or not name_col:
        return

    tier_col = columns_lower.get("tier")
    aliases_col = columns_lower.get("aliases")
    country_col = columns_lower.get("country") or columns_lower.get("location")

    for _, row in df.iterrows():
        name = row.get(name_col)
        rank_value = parse_rank_value(row.get(rank_col))
        if rank_value is None:
            continue

        tier_value = row.get(tier_col) if tier_col else None
        if isinstance(tier_value, float) and pd.isna(tier_value):
            tier_value = None

        alias_values: List[str] = []
        if aliases_col and aliases_col in row:
            alias_field = row.get(aliases_col)
            if isinstance(alias_field, str):
                alias_values.extend(
                    alias.strip()
                    for alias in re.split(r"[|,/;]+", alias_field)
                    if alias.strip()
                )

        country_value = row.get(country_col) if country_col else None

        _store_university_entry(
            rankings,
            name,
            rank_value,
            tier=tier_value,
            aliases=alias_values,
            country=country_value,
            source=csv_path.name,
            source_key=source_key,
            overwrite=True,
        )


def get_core_rank(venue_name: str) -> Optional[str]:
    """
    Get CORE ranking for a conference/journal

    Args:
        venue_name: Venue name or acronym

    Returns:
        Ranking (A*, A, B, C) or None if not found
    """
    # Input validation
    if not venue_name or not isinstance(venue_name, str) or not venue_name.strip():
        return None

    venue_name = venue_name.strip()
    rankings = load_core_rankings()

    entry = _find_venue_entry(rankings, venue_name)
    if not entry:
        return None
    sources = entry.get("sources", {})
    return sources.get("core") or sources.get("icore") or sources.get("ccf")


def get_ccf_rank(venue_name: str) -> Optional[str]:
    """Return the CCF ranking (if available) for a venue."""
    entry = _find_venue_entry(load_core_rankings(), venue_name)
    if not entry:
        return None
    return entry.get("sources", {}).get("ccf")


def get_venue_rankings(venue_name: str) -> Dict[str, Optional[str]]:
    """Return all known rankings for a venue grouped by source."""
    entry = _find_venue_entry(load_core_rankings(), venue_name)
    if not entry:
        return {}
    sources = entry.get("sources", {})
    known = {
        "core": sources.get("core"),
        "icore": sources.get("icore"),
        "ccf": sources.get("ccf"),
    }
    other = {k: v for k, v in sources.items() if k not in known}
    if other:
        known["other"] = other
    known["canonical"] = entry.get("canonical")
    aliases = entry.get("aliases", set())
    if isinstance(aliases, set):
        known["aliases"] = sorted(
            alias for alias in aliases if alias and alias != known["canonical"]
        )
    return known


def get_university_rank(university_name: str) -> Optional[Tuple[int, str]]:
    """
    Get QS ranking for a university

    Args:
        university_name: University name

    Returns:
        Tuple of (ranking, tier) or None if not found
        Example: (5, "Top 10")
    """
    # Input validation
    if not university_name or not isinstance(university_name, str) or not university_name.strip():
        return None

    entry = _find_university_entry(load_university_rankings(), university_name.strip())
    if not entry:
        return None
    rank = entry.get("rank")
    tier = entry.get("tier")
    if rank is None or tier is None:
        return None
    return (rank, tier)


def get_university_rankings(university_name: str) -> Dict[str, Any]:
    """Return all known rankings (QS, US News, etc.) for a university."""
    entry = _find_university_entry(load_university_rankings(), university_name.strip())
    if not entry:
        return {}
    sources: Dict[str, Dict[str, Any]] = entry.get("sources", {})
    sources_copy = {key: dict(value) for key, value in sources.items()}
    result: Dict[str, Any] = {
        "canonical": entry.get("canonical"),
        "country": entry.get("country"),
        "primary_source": entry.get("primary_source"),
        "sources": sources_copy,
        "qs": sources_copy.get("qs"),
        "usnews": sources_copy.get("usnews"),
    }
    other = {k: v for k, v in sources_copy.items() if k not in {"qs", "usnews"}}
    if other:
        result["other"] = other
    aliases = entry.get("aliases")
    if isinstance(aliases, set):
        result["aliases"] = sorted(alias for alias in aliases if alias)
    elif aliases:
        result["aliases"] = aliases
    return result


def get_venue_tier_from_core(core_rank: str) -> str:
    """
    Convert CORE ranking to tier description

    Args:
        core_rank: CORE ranking (A*, A, B, C)

    Returns:
        Tier description
    """
    tier_map = {
        'A*': 'Tier 1 (CORE A* - Flagship)',
        'A': 'Tier 2 (CORE A - Excellent)',
        'B': 'Tier 3 (CORE B - Good)',
        'C': 'Tier 4 (CORE C - Acceptable)'
    }

    return tier_map.get(core_rank, f'CORE {core_rank}')


def enrich_venue_with_core_rank(venue_name: str, h_index: int, h_index_tier: str) -> Dict:
    """
    Enrich venue data with CORE ranking (if available)

    Args:
        venue_name: Venue name
        h_index: Venue h-index
        h_index_tier: H-index tier (e.g., "Tier 1 (Top 5%)")

    Returns:
        Dict with h-index and CORE ranking info
    """
    result = {
        'venue_name': venue_name,
        'h_index': h_index,
        'h_index_tier': h_index_tier,
        'core_rank': None,
        'ccf_rank': None,
        'icore_rank': None,
        'core_tier': None,
        'combined_tier': h_index_tier,
        'rank_sources': {}
    }

    rank_info = get_venue_rankings(venue_name)
    result['rank_sources'] = rank_info

    # Try to get CORE ranking
    core_rank = rank_info.get('core')
    if core_rank:
        result['core_rank'] = core_rank
        result['core_tier'] = get_venue_tier_from_core(core_rank)
    ccf_rank = rank_info.get('ccf')
    if ccf_rank:
        result['ccf_rank'] = ccf_rank
    icore_rank = rank_info.get('icore')
    if icore_rank:
        result['icore_rank'] = icore_rank

    combined_parts = [h_index_tier]
    if result['core_tier']:
        combined_parts.append(result['core_tier'])
    if ccf_rank:
        combined_parts.append(f"CCF {ccf_rank}")
    if icore_rank:
        combined_parts.append(f"iCORE {icore_rank}")
    result['combined_tier'] = " / ".join(part for part in combined_parts if part)

    return result


def enrich_author_with_university_rank(author_name: str, affiliation: str, h_index: int) -> Dict:
    """
    Enrich author data with university ranking (if applicable)

    Args:
        author_name: Author name
        affiliation: Affiliation name
        h_index: Author h-index

    Returns:
        Dict with author info and university ranking
    """
    result = {
        'author_name': author_name,
        'affiliation': affiliation,
        'h_index': h_index,
        'university_rank': None,
        'university_tier': None,
        'usnews_rank': None,
        'usnews_tier': None,
        'university_rankings': {},
        'primary_university_source': None,
    }

    # Try to get university ranking
    rank_info = get_university_rankings(affiliation)
    if rank_info:
        result['university_rankings'] = rank_info
        result['primary_university_source'] = rank_info.get('primary_source')

        qs_info = rank_info.get('qs')
        if qs_info:
            result['university_rank'] = qs_info.get('rank')
            result['university_tier'] = qs_info.get('tier')

        usnews_info = rank_info.get('usnews')
        if usnews_info:
            result['usnews_rank'] = usnews_info.get('rank')
            result['usnews_tier'] = usnews_info.get('tier')

        if result['university_rank'] is None and rank_info.get('primary_source'):
            primary_data = rank_info.get('sources', {}).get(rank_info['primary_source'])
            if primary_data:
                result['university_rank'] = primary_data.get('rank')
                result['university_tier'] = primary_data.get('tier')

    return result


def get_rankings_statistics(venues: list, universities: list) -> Dict:
    """
    Get statistics about rankings coverage

    Args:
        venues: List of venue names
        universities: List of university names

    Returns:
        Dict with statistics
    """
    stats = {
        'venues': {
            'total': len(venues),
            'with_core_rank': 0,
            'core_a_star': 0,
            'core_a': 0,
            'core_b': 0,
            'core_c': 0
        },
        'universities': {
            'total': len(universities),
            'with_ranking': 0,
            'top_10': 0,
            'top_25': 0,
            'top_50': 0,
            'top_100': 0,
            'with_ranking_usnews': 0,
            'top_10_usnews': 0,
            'top_25_usnews': 0,
            'top_50_usnews': 0,
            'top_100_usnews': 0,
        }
    }

    # Check venues
    for venue in venues:
        core_rank = get_core_rank(venue)
        if core_rank:
            stats['venues']['with_core_rank'] += 1
            if core_rank == 'A*':
                stats['venues']['core_a_star'] += 1
            elif core_rank == 'A':
                stats['venues']['core_a'] += 1
            elif core_rank == 'B':
                stats['venues']['core_b'] += 1
            elif core_rank == 'C':
                stats['venues']['core_c'] += 1

    # Check universities
    for university in universities:
        rank_info = get_university_rankings(university)
        if not rank_info:
            continue

        qs_info = rank_info.get('qs')
        if qs_info and qs_info.get('rank'):
            ranking = qs_info['rank']
            stats['universities']['with_ranking'] += 1
            if ranking <= 10:
                stats['universities']['top_10'] += 1
            if ranking <= 25:
                stats['universities']['top_25'] += 1
            if ranking <= 50:
                stats['universities']['top_50'] += 1
            if ranking <= 100:
                stats['universities']['top_100'] += 1

        us_info = rank_info.get('usnews')
        if us_info and us_info.get('rank'):
            ranking_us = us_info['rank']
            stats['universities']['with_ranking_usnews'] += 1
            if ranking_us <= 10:
                stats['universities']['top_10_usnews'] += 1
            if ranking_us <= 25:
                stats['universities']['top_25_usnews'] += 1
            if ranking_us <= 50:
                stats['universities']['top_50_usnews'] += 1
            if ranking_us <= 100:
                stats['universities']['top_100_usnews'] += 1

    return stats
