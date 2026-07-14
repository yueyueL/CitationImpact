"""Tests for ResultCache behavior (isolated to a temp config dir via conftest)."""

import json
from datetime import datetime, timedelta

from citationimpact.cache import get_result_cache


PARAMS = {'h_index_threshold': 20, 'max_citations': 100, 'data_source': 'api'}


def _result(title='My Paper'):
    return {'paper_title': title, 'total_citations': 3, 'analyzed_citations': 3,
            'error': None}


def test_set_then_get_roundtrip():
    cache = get_result_cache()
    assert cache.get('My Paper', PARAMS) is None
    assert cache.set('My Paper', PARAMS, _result())
    cached = cache.get('My Paper', PARAMS)
    assert cached is not None
    assert cached['total_citations'] == 3


def test_key_is_case_insensitive_on_title():
    cache = get_result_cache()
    cache.set('My Paper', PARAMS, _result())
    assert cache.get('  MY PAPER ', PARAMS) is not None


def test_different_params_miss():
    cache = get_result_cache()
    cache.set('My Paper', PARAMS, _result())
    other = dict(PARAMS, max_citations=50)
    assert cache.get('My Paper', other) is None


def test_expired_entry_is_dropped():
    cache = get_result_cache()
    cache.set('My Paper', PARAMS, _result())
    # Rewrite the cache file with an old timestamp
    key = cache._get_cache_key('My Paper', PARAMS)
    cache_file = cache._get_cache_file(key)
    data = json.loads(cache_file.read_text())
    data['cached_at'] = (datetime.now() - timedelta(days=30)).isoformat()
    cache_file.write_text(json.dumps(data))

    assert cache.get('My Paper', PARAMS) is None
    assert not cache_file.exists()  # expired entries are deleted


def test_corrupted_entry_is_dropped():
    cache = get_result_cache()
    cache.set('My Paper', PARAMS, _result())
    key = cache._get_cache_key('My Paper', PARAMS)
    cache_file = cache._get_cache_file(key)
    cache_file.write_text('{not json')

    assert cache.get('My Paper', PARAMS) is None
    assert not cache_file.exists()


def test_list_cache_reports_entries():
    cache = get_result_cache()
    cache.set('Paper A', PARAMS, _result('Paper A'))
    cache.set('Paper B', PARAMS, _result('Paper B'))
    entries = cache.list_cache()
    titles = {e['paper_title'] for e in entries}
    assert titles == {'Paper A', 'Paper B'}


def test_clear_removes_entries():
    cache = get_result_cache()
    cache.set('Paper A', PARAMS, _result('Paper A'))
    removed = cache.clear()
    assert removed >= 1
    assert cache.get('Paper A', PARAMS) is None
