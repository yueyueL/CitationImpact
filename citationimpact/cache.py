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
                except:
                    # If can't read, delete it
                    should_delete = True

            if should_delete:
                cache_file.unlink()
                count += 1

        if count > 0:
            print(f"[Cache] Cleared {count} cache entries")

        return count

    def list_cache(self) -> list:
        """
        List all cached results

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

                cache_list.append({
                    'paper_title': cached_data.get('paper_title', 'Unknown'),
                    'cached_at': cached_time,
                    'age_days': age.days,
                    'file': cache_file.name,
                    'size_kb': cache_file.stat().st_size / 1024
                })
            except:
                continue

        # Sort by cached time (newest first)
        cache_list.sort(key=lambda x: x['cached_at'], reverse=True)

        return cache_list


class AuthorProfileCache:
    """Cache author profiles and publications to avoid re-fetching"""

    def __init__(self):
        """Initialize author profile cache"""
        config_manager = get_config_manager()
        self.cache_dir = config_manager.get_config_path() / 'author_cache'
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Cache settings
        self.max_age_days = 30  # Cache author profiles for 30 days (longer than results)

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

    def get(self, author_id: str, data_source: str) -> Optional[Dict[str, Any]]:
        """
        Get cached author profile if available and not expired

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

            # Return cached profile
            print(f"[Cache] Using cached author profile from {cached_time.strftime('%Y-%m-%d %H:%M')}")
            print(f"[Cache] Age: {age.days} days")
            return cached_data['profile']

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"[Cache] Warning: Could not load author cache: {e}")
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

            print(f"[Cache] Saved author profile to cache")
            return True

        except (IOError, TypeError) as e:
            print(f"[Cache] Warning: Could not save author cache: {e}")
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
                except:
                    # If can't read, delete it
                    should_delete = True

            if should_delete:
                cache_file.unlink()
                count += 1

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
