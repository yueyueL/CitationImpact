"""
Result caching for CitationImpact - Avoid re-fetching data
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Dict, Any, Optional, List
from dataclasses import is_dataclass, asdict

from .config import get_config_manager


class ResultCache:
    """Cache analysis results to avoid re-fetching"""

    def __init__(self):
        """Initialize cache"""
        config_manager = get_config_manager()
        self.cache_dir = config_manager.get_config_path() / 'cache'
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Cache settings
        self.max_age_days = 7  # Cache results for 7 days

    def _get_cache_key(self, paper_title: str, params: Dict[str, Any]) -> str:
        """
        Generate cache key from paper title and analysis parameters

        Args:
            paper_title: Paper title
            params: Analysis parameters (h_index_threshold, max_citations, etc.)

        Returns:
            Cache key (hash string)
        """
        # Create a string representation of all parameters
        cache_data = {
            'paper_title': paper_title.lower().strip(),
            'h_index_threshold': params.get('h_index_threshold', 20),
            'max_citations': params.get('max_citations', 100),
            'data_source': params.get('data_source', 'api')
        }

        # Create hash
        cache_str = json.dumps(cache_data, sort_keys=True)
        return hashlib.md5(cache_str.encode()).hexdigest()

    def _get_cache_file(self, cache_key: str) -> Path:
        """Get cache file path for a cache key"""
        return self.cache_dir / f"{cache_key}.json"

    def has_cached_result(self, paper_title: str, data_source: str = 'comprehensive') -> bool:
        """
        Check if a paper has cached analysis results (quick check, no file load)
        
        Args:
            paper_title: Paper title
            data_source: 'api', 'google_scholar', or 'comprehensive'
            
        Returns:
            True if cached result exists and is not expired
        """
        # Check common parameter combinations
        params_to_check = [
            {'h_index_threshold': 20, 'max_citations': 100, 'data_source': data_source},
            {'h_index_threshold': 20, 'max_citations': 100, 'data_source': 'api'},
            {'h_index_threshold': 20, 'max_citations': 100, 'data_source': 'comprehensive'},
        ]
        
        for params in params_to_check:
            cache_key = self._get_cache_key(paper_title, params)
            cache_file = self._get_cache_file(cache_key)
            
            if cache_file.exists():
                try:
                    with open(cache_file, 'r') as f:
                        cached_data = json.load(f)
                    
                    # Check expiry
                    cached_time = datetime.fromisoformat(cached_data['cached_at'])
                    age = datetime.now() - cached_time
                    
                    if age <= timedelta(days=self.max_age_days):
                        return True
                except (json.JSONDecodeError, KeyError, ValueError):
                    pass
        
        return False

    def get(self, paper_title: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Get cached result if available and not expired

        Args:
            paper_title: Paper title
            params: Analysis parameters

        Returns:
            Cached result or None if not found/expired
        """
        cache_key = self._get_cache_key(paper_title, params)
        cache_file = self._get_cache_file(cache_key)

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, 'r') as f:
                cached_data = json.load(f)

            # Check expiry
            cached_time = datetime.fromisoformat(cached_data['cached_at'])
            age = datetime.now() - cached_time

            if age > timedelta(days=self.max_age_days):
                # Cache expired
                cache_file.unlink()  # Delete expired cache
                return None

            # Return cached result
            print(f"[Cache] Using cached result from {cached_time.strftime('%Y-%m-%d %H:%M')}")
            print(f"[Cache] Age: {age.days} days, {age.seconds // 3600} hours")
            return cached_data['result']

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"[Cache] Warning: Could not load cache: {e}")
            # Delete corrupted cache
            if cache_file.exists():
                cache_file.unlink()
            return None

    def set(self, paper_title: str, params: Dict[str, Any], result: Dict[str, Any]) -> bool:
        """
        Cache analysis result

        Args:
            paper_title: Paper title
            params: Analysis parameters
            result: Analysis result to cache

        Returns:
            True if cached successfully
        """
        cache_key = self._get_cache_key(paper_title, params)
        cache_file = self._get_cache_file(cache_key)

        try:
            sanitized_result = _sanitize_for_json(result)

            # Prepare cache data
            cache_data = {
                'paper_title': paper_title,
                'params': params,
                'result': sanitized_result,
                'cached_at': datetime.now().isoformat()
            }

            temp_file = cache_file.with_suffix(cache_file.suffix + '.tmp')
            try:
                with temp_file.open('w', encoding='utf-8') as f:
                    json.dump(cache_data, f, indent=2, ensure_ascii=False)
                temp_file.replace(cache_file)
            finally:
                if temp_file.exists():
                    temp_file.unlink(missing_ok=True)

            print(f"[Cache] Saved result to cache")
            return True

        except (IOError, TypeError) as e:
            print(f"[Cache] Warning: Could not save cache: {e}")
            return False

    def clear(self, max_age_days: Optional[int] = None) -> int:
        """
        Clear old cache entries

        Args:
            max_age_days: Clear entries older than this (None = clear all)

        Returns:
            Number of entries cleared
        """
        count = 0

        for cache_file in self.cache_dir.glob("*.json"):
            should_delete = False

            if max_age_days is None:
                # Clear all
                should_delete = True
            else:
                # Check age
                try:
                    with open(cache_file, 'r') as f:
                        cached_data = json.load(f)
                    cached_time = datetime.fromisoformat(cached_data['cached_at'])
                    age = datetime.now() - cached_time
                    if age > timedelta(days=max_age_days):
                        should_delete = True
                except Exception:
                    # If can't read, delete it
                    should_delete = True

            if should_delete:
                try:
                    cache_file.unlink()
                    count += 1
                except Exception as e:
                    print(f"[Cache] Warning: Could not delete {cache_file.name}: {e}")

        if count > 0:
            print(f"[Cache] Cleared {count} cache entries")

        return count

    def list_cache(self) -> list:
        """
        List all cached results with details

        Returns:
            List of cache info dictionaries
        """
        cache_list = []

        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, 'r') as f:
                    cached_data = json.load(f)

                cached_time = datetime.fromisoformat(cached_data['cached_at'])
                age = datetime.now() - cached_time
                
                result = cached_data.get('result', {})

                cache_list.append({
                    'paper_title': cached_data.get('paper_title', 'Unknown'),
                    'cached_at': cached_time.strftime('%Y-%m-%d'),
                    'age_days': age.days,
                    'cache_key': cache_file.stem,  # filename without .json
                    'file': cache_file.name,
                    'size_kb': cache_file.stat().st_size / 1024,
                    'analyzed_citations': result.get('analyzed_citations', 0),
                    'data_source': cached_data.get('params', {}).get('data_source', 'api')
                })
            except Exception:
                continue

        # Sort by cached time (newest first)
        cache_list.sort(key=lambda x: x['cached_at'], reverse=True)

        return cache_list
    
    def delete(self, cache_key: str) -> bool:
        """
        Delete a specific cache entry
        
        Args:
            cache_key: The cache key (filename without .json)
            
        Returns:
            True if deleted successfully
        """
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        if cache_file.exists():
            try:
                cache_file.unlink()
                return True
            except IOError:
                return False
        return False


class AuthorProfileCache:
    """
    Smart researcher profile cache with multiple ID lookup and auto-update
    
    Features:
    - Lookup by any ID (name, Google Scholar ID, Semantic Scholar ID, ORCID)
    - Auto-merge new information into existing profiles
    - Don't search again if profile exists in cache
    - Update missing fields when new data is found
    """

    def __init__(self):
        """Initialize author profile cache"""
        config_manager = get_config_manager()
        self.cache_dir = config_manager.get_config_path() / 'author_cache'
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Index file maps all IDs to profile files
        self.index_file = self.cache_dir / '_index.json'
        self._index = self._load_index()

        # Cache settings
        self.max_age_days = 30  # Cache author profiles for 30 days

    def _load_index(self) -> Dict[str, str]:
        """Load the ID-to-profile index"""
        if self.index_file.exists():
            try:
                with open(self.index_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}
    
    def _save_index(self):
        """Save the ID-to-profile index"""
        try:
            with open(self.index_file, 'w') as f:
                json.dump(self._index, f, indent=2)
        except IOError:
            pass
    
    def _normalize_name(self, name: str) -> str:
        """Normalize author name for lookup"""
        if not name:
            return ""
        import re
        normalized = name.lower().strip()
        normalized = re.sub(r'[^\w\s\-]', '', normalized)
        normalized = ' '.join(normalized.split())
        return normalized
    
    def _normalize_title(self, title: str) -> str:
        """Normalize publication title for matching"""
        if not title:
            return ""
        import re
        # Remove common prefixes, punctuation, lowercase
        normalized = title.lower().strip()
        normalized = re.sub(r'[^\w\s]', '', normalized)  # Remove punctuation
        normalized = ' '.join(normalized.split())  # Normalize whitespace
        # Remove common filler words for better matching
        stopwords = {'a', 'an', 'the', 'of', 'for', 'in', 'on', 'to', 'and', 'with'}
        words = [w for w in normalized.split() if w not in stopwords]
        return ' '.join(words[:10])  # First 10 significant words
    
    def _get_publication_keys(self, publications: List[Dict]) -> List[str]:
        """Generate lookup keys from publication titles"""
        keys = []
        if not publications:
            return keys
        
        for pub in publications[:10]:  # Use top 10 publications for matching
            title = pub.get('title', '') or pub.get('bib', {}).get('title', '')
            if title:
                norm_title = self._normalize_title(title)
                if len(norm_title) > 20:  # Only use substantial titles
                    keys.append(f"pub:{norm_title[:50]}")  # Cap at 50 chars
        return keys
    
    def _get_lookup_keys(self, author_info: Dict[str, Any]) -> List[str]:
        """Get all possible lookup keys for an author"""
        keys = []
        
        # Name-based key
        name = author_info.get('name', '')
        if name:
            keys.append(f"name:{self._normalize_name(name)}")
        
        # ID-based keys
        gs_id = author_info.get('google_scholar_id', '')
        if gs_id:
            keys.append(f"gs:{gs_id}")
        
        s2_id = author_info.get('semantic_scholar_id', '')
        if s2_id:
            keys.append(f"s2:{s2_id}")
        
        orcid = author_info.get('orcid_id', '')
        if orcid:
            keys.append(f"orcid:{orcid}")
        
        return keys

    def _get_cache_key(self, author_id: str, data_source: str) -> str:
        """
        Generate cache key from author ID and data source

        Args:
            author_id: Author identifier
            data_source: 'api' or 'google_scholar'

        Returns:
            Cache key (hash string)
        """
        cache_data = {
            'author_id': author_id.lower().strip(),
            'data_source': data_source
        }
        cache_str = json.dumps(cache_data, sort_keys=True)
        return hashlib.md5(cache_str.encode()).hexdigest()

    def _get_cache_file(self, cache_key: str) -> Path:
        """Get cache file path for a cache key"""
        return self.cache_dir / f"{cache_key}.json"
    
    def get_by_any_id(
        self, 
        name: str = None, 
        google_scholar_id: str = None,
        semantic_scholar_id: str = None,
        orcid_id: str = None,
        publications: List[Dict] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached author profile by any available ID or publication match
        
        Args:
            name: Author name
            google_scholar_id: Google Scholar ID
            semantic_scholar_id: Semantic Scholar ID
            orcid_id: ORCID identifier
            publications: List of publication dicts (for matching by paper overlap)
            
        Returns:
            Cached author_info dict or None
        """
        # Try each ID type
        lookup_keys = []
        if google_scholar_id:
            lookup_keys.append(f"gs:{google_scholar_id}")
        if semantic_scholar_id:
            lookup_keys.append(f"s2:{semantic_scholar_id}")
        if orcid_id:
            lookup_keys.append(f"orcid:{orcid_id}")
        if name:
            lookup_keys.append(f"name:{self._normalize_name(name)}")
        
        # Also try publication-based matching
        if publications:
            pub_keys = self._get_publication_keys(publications)
            lookup_keys.extend(pub_keys)
        
        # Check index for any matching key
        for key in lookup_keys:
            if key in self._index:
                cache_file = self.cache_dir / self._index[key]
                if cache_file.exists():
                    try:
                        with open(cache_file, 'r') as f:
                            cached_data = json.load(f)
                        
                        # Check expiry
                        cached_time = datetime.fromisoformat(cached_data['cached_at'])
                        age = datetime.now() - cached_time
                        
                        if age <= timedelta(days=self.max_age_days):
                            return cached_data.get('profile', {}).get('author_info')
                    except (json.JSONDecodeError, KeyError, ValueError):
                        pass
        
        return None
    
    def update_profile(self, author_info: Dict[str, Any], publications: List[Dict] = None) -> bool:
        """
        Update or create author profile, merging with existing data
        
        If profile exists, merge new IDs/info into it.
        If not, create new profile.
        
        Uses MULTIPLE matching strategies:
        1. ID-based: Google Scholar ID, Semantic Scholar ID, ORCID
        2. Name-based: Normalized name
        3. Publication-based: Match by shared paper titles (best for disambiguation!)
        
        Args:
            author_info: Author information dict with profile IDs
            publications: List of publication dicts (optional, for matching)
            
        Returns:
            True if updated successfully
        """
        publications = publications or []
        
        # Check if we have an existing profile by IDs first
        existing = self.get_by_any_id(
            name=author_info.get('name'),
            google_scholar_id=author_info.get('google_scholar_id'),
            semantic_scholar_id=author_info.get('semantic_scholar_id'),
            orcid_id=author_info.get('orcid_id')
        )
        
        # If not found by ID/name, try matching by publications
        if not existing and publications:
            existing = self.find_by_publications(publications)
        
        if existing:
            # Merge: keep existing values, add new non-empty values
            merged = existing.copy()
            for key, value in author_info.items():
                if value and (not merged.get(key) or merged.get(key) == 'Unknown'):
                    merged[key] = value
            # Prefer higher h-index
            if author_info.get('h_index', 0) > merged.get('h_index', 0):
                merged['h_index'] = author_info['h_index']
                merged['h_index_source'] = author_info.get('h_index_source', '')
            author_info = merged
        
        # Generate a unique profile filename
        profile_id = hashlib.md5(
            json.dumps(author_info, sort_keys=True).encode()
        ).hexdigest()[:12]
        profile_filename = f"profile_{profile_id}.json"
        cache_file = self.cache_dir / profile_filename
        
        # Extract just titles for storage (to keep cache small)
        pub_titles = []
        for pub in publications[:20]:  # Store top 20 publication titles
            title = pub.get('title', '') or pub.get('bib', {}).get('title', '')
            if title:
                pub_titles.append({'title': title})
        
        try:
            # Save profile with publications
            cache_data = {
                'profile': {
                    'author_info': author_info,
                    'publications': pub_titles  # Store publication titles for matching
                },
                'cached_at': datetime.now().isoformat()
            }
            
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            
            # Update index with all lookup keys (IDs + names)
            lookup_keys = self._get_lookup_keys(author_info)
            for key in lookup_keys:
                self._index[key] = profile_filename
            
            # Also index by publication titles (for disambiguation)
            pub_keys = self._get_publication_keys(publications)
            for key in pub_keys:
                self._index[key] = profile_filename
            
            self._save_index()
            
            return True
            
        except (IOError, TypeError) as e:
            return False
    
    def find_by_publications(self, publications: List[Dict], min_overlap: int = 2) -> Optional[Dict[str, Any]]:
        """
        Find matching author profile by publication overlap
        
        This is the KEY method for author disambiguation!
        If two entries share at least `min_overlap` papers, they're the same person.
        
        Examples:
        - "C. Tantithamthavorn" and "Chakkrit Tantithamthavorn" share papers → SAME PERSON
        - Two "Li Li" with different papers → DIFFERENT PEOPLE
        
        Args:
            publications: List of publication dicts with 'title' key
            min_overlap: Minimum number of matching papers required (default: 2)
            
        Returns:
            Cached author_info dict or None
        """
        if not publications:
            return None
        
        # Get publication keys for incoming publications
        pub_keys = self._get_publication_keys(publications)
        if len(pub_keys) < min_overlap:
            return None  # Not enough papers to match
        
        # Count matches per profile
        profile_matches = {}  # profile_filename -> match count
        for key in pub_keys:
            if key in self._index:
                profile_file = self._index[key]
                profile_matches[profile_file] = profile_matches.get(profile_file, 0) + 1
        
        # Find profile with most matches (if >= min_overlap)
        best_profile = None
        best_count = 0
        for profile_file, count in profile_matches.items():
            if count >= min_overlap and count > best_count:
                best_profile = profile_file
                best_count = count
        
        if best_profile:
            cache_file = self.cache_dir / best_profile
            if cache_file.exists():
                try:
                    with open(cache_file, 'r') as f:
                        cached_data = json.load(f)
                    author_info = cached_data.get('profile', {}).get('author_info')
                    if author_info:
                        print(f"[Cache] 🔗 Matched author by {best_count} shared publications!")
                        return author_info
                except (json.JSONDecodeError, KeyError):
                    pass
        
        return None

    def get(self, author_id: str, data_source: str) -> Optional[Dict[str, Any]]:
        """
        Get cached author profile if available and not expired
        (Legacy method for backward compatibility)

        Args:
            author_id: Author identifier
            data_source: 'api' or 'google_scholar'

        Returns:
            Cached profile with 'author_info' and 'publications' or None
        """
        cache_key = self._get_cache_key(author_id, data_source)
        cache_file = self._get_cache_file(cache_key)

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, 'r') as f:
                cached_data = json.load(f)

            # Check expiry
            cached_time = datetime.fromisoformat(cached_data['cached_at'])
            age = datetime.now() - cached_time

            if age > timedelta(days=self.max_age_days):
                # Cache expired
                cache_file.unlink()  # Delete expired cache
                return None

            return cached_data['profile']

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            # Delete corrupted cache
            if cache_file.exists():
                cache_file.unlink()
            return None

    def set(self, author_id: str, data_source: str, author_info: Dict[str, Any], publications: List[Dict]) -> bool:
        """
        Cache author profile and publications

        Args:
            author_id: Author identifier
            data_source: 'api' or 'google_scholar'
            author_info: Author information dict
            publications: List of publications

        Returns:
            True if cached successfully
        """
        cache_key = self._get_cache_key(author_id, data_source)
        cache_file = self._get_cache_file(cache_key)

        try:
            sanitized_profile = _sanitize_for_json({
                'author_info': author_info,
                'publications': publications
            })

            # Prepare cache data
            cache_data = {
                'author_id': author_id,
                'data_source': data_source,
                'profile': sanitized_profile,
                'cached_at': datetime.now().isoformat()
            }

            temp_file = cache_file.with_suffix(cache_file.suffix + '.tmp')
            try:
                with temp_file.open('w', encoding='utf-8') as f:
                    json.dump(cache_data, f, indent=2, ensure_ascii=False)
                temp_file.replace(cache_file)
            finally:
                if temp_file.exists():
                    temp_file.unlink(missing_ok=True)

            return True

        except (IOError, TypeError) as e:
            return False

    def list_profiles(self) -> List[Dict[str, Any]]:
        """
        List all cached researcher profiles
        
        Returns:
            List of author_info dicts
        """
        profiles = []
        seen_files = set()
        
        for key, filename in self._index.items():
            if filename in seen_files:
                continue
            seen_files.add(filename)
            
            profile_file = self.cache_dir / filename
            if profile_file.exists():
                try:
                    with open(profile_file, 'r') as f:
                        data = json.load(f)
                    
                    # Check expiry
                    cached_time = datetime.fromisoformat(data['cached_at'])
                    age = datetime.now() - cached_time
                    
                    if age <= timedelta(days=self.max_age_days):
                        info = data.get('profile', {}).get('author_info', {})
                        if info:
                            profiles.append(info)
                except (json.JSONDecodeError, IOError, KeyError):
                    pass
        
        return profiles

    def delete_profile(
        self, 
        name: str = None,
        google_scholar_id: str = None,
        semantic_scholar_id: str = None
    ) -> bool:
        """
        Delete a specific author profile
        
        Args:
            name: Author name
            google_scholar_id: Google Scholar ID
            semantic_scholar_id: Semantic Scholar ID
            
        Returns:
            True if deleted successfully
        """
        # Find the profile file
        lookup_keys = []
        if name:
            lookup_keys.append(f"name:{self._normalize_name(name)}")
        if google_scholar_id:
            lookup_keys.append(f"gs:{google_scholar_id}")
        if semantic_scholar_id:
            lookup_keys.append(f"s2:{semantic_scholar_id}")
        
        profile_filename = None
        for key in lookup_keys:
            if key in self._index:
                profile_filename = self._index[key]
                break
        
        if not profile_filename:
            return False
        
        # Delete the profile file
        profile_file = self.cache_dir / profile_filename
        if profile_file.exists():
            try:
                profile_file.unlink()
            except IOError:
                return False
        
        # Remove all index entries pointing to this file
        keys_to_remove = [k for k, v in self._index.items() if v == profile_filename]
        for key in keys_to_remove:
            del self._index[key]
        
        self._save_index()
        return True

    def clear(self, max_age_days: Optional[int] = None) -> int:
        """
        Clear old cache entries

        Args:
            max_age_days: Clear entries older than this (None = clear all)

        Returns:
            Number of entries cleared
        """
        count = 0

        for cache_file in self.cache_dir.glob("*.json"):
            # Skip the index file
            if cache_file.name == '_index.json':
                continue
                
            should_delete = False

            if max_age_days is None:
                # Clear all
                should_delete = True
            else:
                # Check age
                try:
                    with open(cache_file, 'r') as f:
                        cached_data = json.load(f)
                    cached_time = datetime.fromisoformat(cached_data['cached_at'])
                    age = datetime.now() - cached_time
                    if age > timedelta(days=max_age_days):
                        should_delete = True
                except Exception:
                    # If can't read, delete it
                    should_delete = True

            if should_delete:
                try:
                    cache_file.unlink()
                    count += 1
                except Exception as e:
                    print(f"[Cache] Warning: Could not delete {cache_file.name}: {e}")

        # Clear the index if we deleted everything
        if max_age_days is None:
            self._index = {}
            self._save_index()

        if count > 0:
            print(f"[Cache] Cleared {count} author cache entries")

        return count


# Global cache instances
_result_cache = None
_author_cache = None


def get_result_cache() -> ResultCache:
    """Get or create global result cache"""
    global _result_cache
    if _result_cache is None:
        _result_cache = ResultCache()
    return _result_cache


def get_author_cache() -> AuthorProfileCache:
    """Get or create global author profile cache"""
    global _author_cache
    if _author_cache is None:
        _author_cache = AuthorProfileCache()
    return _author_cache


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert objects into JSON-serialisable structures."""
    if is_dataclass(obj):
        return _sanitize_for_json(asdict(obj))
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(item) for item in obj]
    if isinstance(obj, set):
        return [_sanitize_for_json(item) for item in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    return obj


class MyPublicationsCache:
    """
    Cache for user's own publications list from Google Scholar / Semantic Scholar.
    
    Avoids hitting Google Scholar on every "My Papers" request.
    User controls when to refresh (press 'r' in My Papers view).
    """

    def __init__(self):
        """Initialize publications cache"""
        config_manager = get_config_manager()
        self.cache_dir = config_manager.get_config_path() / 'author_cache'
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # No auto-expiry - user decides when to refresh

    def _get_cache_key(self, author_id: str, data_source: str) -> str:
        """Generate cache key from author ID and source"""
        cache_data = {
            'author_id': author_id.lower().strip(),
            'data_source': data_source,
            'type': 'publications'
        }
        cache_str = json.dumps(cache_data, sort_keys=True)
        return hashlib.md5(cache_str.encode()).hexdigest()

    def _get_cache_file(self, cache_key: str) -> Path:
        """Get cache file path"""
        return self.cache_dir / f"{cache_key}.json"

    def get(self, author_id: str, data_source: str = 'google_scholar') -> Optional[List[Dict]]:
        """
        Get cached publications if available.
        
        No auto-expiry - user decides when to refresh via 'r' key.
        
        Returns:
            List of publication dicts or None if not cached
        """
        cache_key = self._get_cache_key(author_id, data_source)
        cache_file = self._get_cache_file(cache_key)

        if not cache_file.exists():
            return None

        try:
            with open(cache_file, 'r') as f:
                cached_data = json.load(f)

            cached_time = datetime.fromisoformat(cached_data['cached_at'])

            publications = cached_data.get('profile', {}).get('author_info', {}).get('publications', [])
            if publications:
                print(f"[Cache] Using cached publications from {cached_time.strftime('%Y-%m-%d %H:%M')}")
                print(f"[Cache] Found {len(publications)} papers (press 'r' to refresh from profile)")
                return publications
            
            return None

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"[Cache] Warning: Could not load publications cache: {e}")
            return None
    
    def clear(self, author_id: str, data_source: str = 'google_scholar') -> bool:
        """Clear cached publications for an author (used when user presses 'r')."""
        cache_key = self._get_cache_key(author_id, data_source)
        cache_file = self._get_cache_file(cache_key)
        
        if cache_file.exists():
            try:
                cache_file.unlink()
                print(f"[Cache] Cleared publications cache for {author_id}")
                return True
            except Exception:
                pass
        return False

    def set(self, author_id: str, publications: List[Dict], data_source: str = 'google_scholar',
            author_info: Dict = None) -> bool:
        """
        Cache publications list.
        
        Args:
            author_id: Author's ID (GS or S2)
            publications: List of publication dicts
            data_source: 'google_scholar' or 'api'
            author_info: Optional author profile info
        """
        cache_key = self._get_cache_key(author_id, data_source)
        cache_file = self._get_cache_file(cache_key)

        try:
            cache_data = {
                'author_id': author_id,
                'data_source': data_source,
                'profile': {
                    'author_info': author_info or {}
                },
                'cached_at': datetime.now().isoformat()
            }
            
            # Add publications to author_info
            if 'publications' not in cache_data['profile']['author_info']:
                cache_data['profile']['author_info']['publications'] = []
            cache_data['profile']['author_info']['publications'] = _sanitize_for_json(publications)

            with open(cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)

            print(f"[Cache] Saved {len(publications)} publications to cache")
            return True

        except Exception as e:
            print(f"[Cache] Warning: Could not save publications cache: {e}")
            return False


# Singleton instance
_my_publications_cache = None

def get_my_publications_cache() -> MyPublicationsCache:
    """Get singleton instance of publications cache"""
    global _my_publications_cache
    if _my_publications_cache is None:
        _my_publications_cache = MyPublicationsCache()
    return _my_publications_cache
