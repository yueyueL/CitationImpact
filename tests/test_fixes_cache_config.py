"""Regression tests for cache.py / config.py bug fixes.

Covers:
- has_cached_result probing configured/explicit/non-default parameters
- ResultCache.get / AuthorProfileCache.get surviving unlink() OSErrors
- update_profile no longer merging distinct same-named authors
- update_profile reusing the profile file (no orphans, fresh pub-key data)
- update_profile atomic UTF-8 writes
- source-aware h-index merging (Google Scholar wins over other sources)
- ConfigManager.save atomicity and load() non-dict JSON handling
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from citationimpact.cache import get_result_cache, get_author_cache
from citationimpact.config import ConfigManager, get_config_manager


PARAMS = {'h_index_threshold': 20, 'max_citations': 100, 'data_source': 'api'}

PUB_TITLES = [
    'An empirical study of deep learning defect prediction models in practice',
    'Automated program repair with large language models a comprehensive study',
    'Understanding software supply chain attacks through open source ecosystems',
]


def _result(title='My Paper'):
    return {'paper_title': title, 'total_citations': 3, 'analyzed_citations': 3,
            'error': None}


def _pubs(*titles):
    return [{'title': t} for t in titles]


# --------------------------------------------------------------------------
# has_cached_result: hardcoded-params bug + new optional params argument
# --------------------------------------------------------------------------

def test_has_cached_result_with_default_params():
    cache = get_result_cache()
    cache.set('My Paper', PARAMS, _result())
    assert cache.has_cached_result('My Paper')


def test_has_cached_result_missing_paper_is_false():
    cache = get_result_cache()
    assert not cache.has_cached_result('Unknown Paper')


def test_has_cached_result_respects_configured_settings():
    config = get_config_manager()
    config.update({'h_index_threshold': 30, 'max_citations': 200})
    cache = get_result_cache()
    custom = {'h_index_threshold': 30, 'max_citations': 200, 'data_source': 'api'}
    cache.set('My Paper', custom, _result())
    assert cache.has_cached_result('My Paper')


def test_has_cached_result_probes_google_scholar_source():
    cache = get_result_cache()
    gs_params = {'h_index_threshold': 20, 'max_citations': 100,
                 'data_source': 'google_scholar'}
    cache.set('My Paper', gs_params, _result())
    assert cache.has_cached_result('My Paper')


def test_has_cached_result_explicit_params_probe():
    cache = get_result_cache()
    custom = {'h_index_threshold': 55, 'max_citations': 321,
              'data_source': 'comprehensive'}
    cache.set('My Paper', custom, _result())
    # Not discoverable via defaults or the (default) configured settings...
    assert not cache.has_cached_result('My Paper')
    # ...but found when the caller passes the real parameters
    assert cache.has_cached_result('My Paper', params=custom)


# --------------------------------------------------------------------------
# unlink() failures inside get() are treated as a cache miss, not a crash
# --------------------------------------------------------------------------

def test_result_cache_expired_unlink_failure_is_miss(monkeypatch):
    cache = get_result_cache()
    cache.set('My Paper', PARAMS, _result())
    key = cache._get_cache_key('My Paper', PARAMS)
    cache_file = cache._get_cache_file(key)
    data = json.loads(cache_file.read_text())
    data['cached_at'] = (datetime.now() - timedelta(days=30)).isoformat()
    cache_file.write_text(json.dumps(data))

    def failing_unlink(self, missing_ok=False):
        raise PermissionError('denied')

    monkeypatch.setattr(Path, 'unlink', failing_unlink)
    assert cache.get('My Paper', PARAMS) is None  # must not raise


def test_author_cache_expired_unlink_failure_is_miss(monkeypatch):
    cache = get_author_cache()
    cache.set('A. Author', 'api', {'name': 'A. Author', 'h_index': 5}, [])
    key = cache._get_cache_key('A. Author', 'api')
    cache_file = cache._get_cache_file(key)
    data = json.loads(cache_file.read_text())
    data['cached_at'] = (datetime.now() - timedelta(days=60)).isoformat()
    cache_file.write_text(json.dumps(data))

    def failing_unlink(self, missing_ok=False):
        raise PermissionError('denied')

    monkeypatch.setattr(Path, 'unlink', failing_unlink)
    assert cache.get('A. Author', 'api') is None  # must not raise


# --------------------------------------------------------------------------
# update_profile: same-name authors must not be merged into one profile
# --------------------------------------------------------------------------

def test_same_name_different_gs_ids_stay_separate():
    cache = get_author_cache()
    cache.update_profile({'name': 'Wei Wang', 'google_scholar_id': 'aaa',
                          'h_index': 12, 'h_index_source': 'google_scholar'})
    cache.update_profile({'name': 'Wei Wang', 'google_scholar_id': 'bbb',
                          'h_index': 60, 'h_index_source': 'google_scholar'})

    first = cache.get_by_any_id(google_scholar_id='aaa')
    second = cache.get_by_any_id(google_scholar_id='bbb')
    assert first is not None and first['h_index'] == 12
    assert first['google_scholar_id'] == 'aaa'
    assert second is not None and second['h_index'] == 60
    assert second['google_scholar_id'] == 'bbb'


def test_same_name_disjoint_ids_stay_separate():
    cache = get_author_cache()
    cache.update_profile({'name': 'Wei Wang', 'semantic_scholar_id': 's111',
                          'h_index': 12, 'h_index_source': 'semantic_scholar'})
    # A different Wei Wang known only by GS id: no shared ID, no publications
    cache.update_profile({'name': 'Wei Wang', 'google_scholar_id': 'bbb',
                          'h_index': 60, 'h_index_source': 'google_scholar'})

    by_s2 = cache.get_by_any_id(semantic_scholar_id='s111')
    by_gs = cache.get_by_any_id(google_scholar_id='bbb')
    assert by_s2['h_index'] == 12
    assert not by_s2.get('google_scholar_id')
    assert by_gs['h_index'] == 60
    assert not by_gs.get('semantic_scholar_id')


def test_shared_id_profiles_merge_and_enrich():
    cache = get_author_cache()
    cache.update_profile({'name': 'Jane Doe', 'semantic_scholar_id': 's1',
                          'h_index': 10, 'h_index_source': 'semantic_scholar'})
    cache.update_profile({'name': 'Jane Doe', 'semantic_scholar_id': 's1',
                          'google_scholar_id': 'g1', 'h_index': 25,
                          'h_index_source': 'google_scholar'})
    info = cache.get_by_any_id(semantic_scholar_id='s1')
    assert info['google_scholar_id'] == 'g1'
    assert info['h_index'] == 25
    assert info['h_index_source'] == 'google_scholar'
    # The newly discovered GS id must be indexed for future lookups
    assert cache.get_by_any_id(google_scholar_id='g1') is not None


def test_publication_overlap_still_merges_name_variants():
    cache = get_author_cache()
    pubs = _pubs(*PUB_TITLES)
    cache.update_profile({'name': 'Chakkrit Tantithamthavorn',
                          'semantic_scholar_id': 's9', 'h_index': 30,
                          'h_index_source': 'semantic_scholar'},
                         publications=pubs)
    cache.update_profile({'name': 'C. Tantithamthavorn', 'h_index': 31,
                          'h_index_source': 'semantic_scholar'},
                         publications=pubs)
    info = cache.get_by_any_id(semantic_scholar_id='s9')
    assert info['h_index'] == 31


# --------------------------------------------------------------------------
# update_profile: stable profile file, no orphans, pub keys stay current
# --------------------------------------------------------------------------

def test_update_reuses_profile_file_and_pub_keys_serve_fresh_data():
    cache = get_author_cache()
    pubs = _pubs(*PUB_TITLES[:2])
    cache.update_profile({'name': 'Jane Doe', 'semantic_scholar_id': 's1',
                          'h_index': 10, 'h_index_source': 'semantic_scholar'},
                         publications=pubs)
    # Second update (no publications) discovers the GS profile
    cache.update_profile({'name': 'Jane Doe', 'semantic_scholar_id': 's1',
                          'google_scholar_id': 'XYZ', 'h_index': 25,
                          'h_index_source': 'google_scholar'})

    profile_files = list(cache.cache_dir.glob('profile_*.json'))
    assert len(profile_files) == 1  # no orphaned pre-merge file left behind

    # Publication-based lookup must serve the updated (merged) profile
    matched = cache.find_by_publications(pubs)
    assert matched is not None
    assert matched['google_scholar_id'] == 'XYZ'
    assert matched['h_index'] == 25


# --------------------------------------------------------------------------
# update_profile: atomic UTF-8 writes
# --------------------------------------------------------------------------

def test_unicode_names_roundtrip_as_utf8():
    cache = get_author_cache()
    assert cache.update_profile({'name': '张三', 'google_scholar_id': 'zzz',
                                 'h_index': 7,
                                 'h_index_source': 'google_scholar'})
    info = cache.get_by_any_id(google_scholar_id='zzz')
    assert info['name'] == '张三'
    # The profile file on disk must be valid UTF-8 JSON
    profile_file = cache.cache_dir / cache._index['gs:zzz']
    loaded = json.loads(profile_file.read_text(encoding='utf-8'))
    assert loaded['profile']['author_info']['name'] == '张三'


def test_failed_profile_write_does_not_corrupt_existing_profile():
    cache = get_author_cache()
    cache.update_profile({'name': 'Jane Doe', 'semantic_scholar_id': 's1',
                          'h_index': 10, 'h_index_source': 'semantic_scholar'})
    profile_file = cache.cache_dir / cache._index['s2:s1']
    original = profile_file.read_text(encoding='utf-8')

    # A non-JSON-serializable value must fail cleanly, not truncate the file
    assert cache.update_profile({'name': 'Jane Doe', 'semantic_scholar_id': 's1',
                                 'h_index': 12, 'junk': object()}) is False
    assert profile_file.read_text(encoding='utf-8') == original
    assert not list(cache.cache_dir.glob('*.tmp'))  # temp file cleaned up


# --------------------------------------------------------------------------
# update_profile: source-aware h-index merge
# --------------------------------------------------------------------------

def test_higher_s2_h_index_does_not_override_gs_source():
    cache = get_author_cache()
    cache.update_profile({'name': 'Jane Doe', 'semantic_scholar_id': 's1',
                          'google_scholar_id': 'g1', 'h_index': 30,
                          'h_index_source': 'google_scholar'})
    cache.update_profile({'name': 'Jane Doe', 'semantic_scholar_id': 's1',
                          'h_index': 33, 'h_index_source': 'semantic_scholar'})
    info = cache.get_by_any_id(google_scholar_id='g1')
    assert info['h_index'] == 30
    assert info['h_index_source'] == 'google_scholar'


def test_gs_h_index_wins_over_other_source_even_when_lower():
    cache = get_author_cache()
    cache.update_profile({'name': 'Jane Doe', 'semantic_scholar_id': 's1',
                          'h_index': 33, 'h_index_source': 'semantic_scholar'})
    cache.update_profile({'name': 'Jane Doe', 'semantic_scholar_id': 's1',
                          'google_scholar_id': 'g1', 'h_index': 30,
                          'h_index_source': 'google_scholar'})
    info = cache.get_by_any_id(semantic_scholar_id='s1')
    assert info['h_index'] == 30
    assert info['h_index_source'] == 'google_scholar'


def test_higher_h_index_wins_within_same_source():
    cache = get_author_cache()
    cache.update_profile({'name': 'Jane Doe', 'semantic_scholar_id': 's1',
                          'h_index': 10, 'h_index_source': 'semantic_scholar'})
    cache.update_profile({'name': 'Jane Doe', 'semantic_scholar_id': 's1',
                          'h_index': 12, 'h_index_source': 'semantic_scholar'})
    info = cache.get_by_any_id(semantic_scholar_id='s1')
    assert info['h_index'] == 12


# --------------------------------------------------------------------------
# ConfigManager: atomic save, TypeError handling, non-dict JSON in load()
# --------------------------------------------------------------------------

def test_config_save_failure_preserves_existing_file(isolated_config):
    manager = isolated_config
    assert manager.set('api_key', 'secret-key')
    before = manager.config_file.read_text()
    assert json.loads(before)['api_key'] == 'secret-key'

    # A TypeError from json.dump must not truncate/destroy the config file
    assert manager.set('default_google_scholar_author_id', object()) is False
    after = manager.config_file.read_text()
    assert json.loads(after)['api_key'] == 'secret-key'
    assert not list(manager.config_dir.glob('*.tmp'))  # temp file cleaned up


def test_config_load_non_dict_json_returns_defaults(tmp_path):
    manager = ConfigManager(config_dir=tmp_path / 'cfg2')
    manager.config_file.write_text('null')
    loaded = manager.load()  # must not raise
    assert loaded == manager.defaults
