"""Tests for AuthorProfileCache.get_by_any_id verify_titles verification.

Covers contract item 4 of the author-disambiguation upgrade: a name-only
cache hit must be corroborated by publication-title overlap when the caller
supplies verify_titles, while real-ID matches bypass verification entirely.
Isolated to a temp config dir via conftest.
"""

import json
from datetime import datetime, timedelta

from citationimpact.cache import get_author_cache


TITLE_A = 'Deep Learning for Automated Program Repair in Large Codebases'
TITLE_B = 'A Study of Software Vulnerability Detection with Graph Networks'
TITLE_C = 'Quantum Entanglement Approaches to Molecular Biology Simulations'


def _store(cache, name='Li Li', gs_id='', s2_id='', orcid='', titles=(TITLE_A, TITLE_B)):
    """Store a profile with publications and return its author_info"""
    author_info = {
        'name': name,
        'h_index': 25,
        'affiliation': 'Test University',
    }
    if gs_id:
        author_info['google_scholar_id'] = gs_id
    if s2_id:
        author_info['semantic_scholar_id'] = s2_id
    if orcid:
        author_info['orcid_id'] = orcid
    publications = [{'title': t} for t in titles]
    assert cache.update_profile(author_info, publications)
    return author_info


# ---------------------------------------------------------------------------
# Backward compatibility: no verify_titles keeps old behavior
# ---------------------------------------------------------------------------

def test_name_lookup_without_verify_titles_still_hits():
    cache = get_author_cache()
    _store(cache, name='Li Li', s2_id='s123')
    info = cache.get_by_any_id(name='Li Li')
    assert info is not None
    assert info['semantic_scholar_id'] == 's123'


def test_verify_titles_none_is_default():
    cache = get_author_cache()
    _store(cache, name='Li Li')
    # Explicit None behaves like omitting the argument
    assert cache.get_by_any_id(name='Li Li', verify_titles=None) is not None


# ---------------------------------------------------------------------------
# Name-only matches require title overlap when verify_titles is provided
# ---------------------------------------------------------------------------

def test_name_match_verified_by_title_overlap():
    cache = get_author_cache()
    _store(cache, name='Li Li')
    info = cache.get_by_any_id(name='Li Li', verify_titles=[TITLE_A])
    assert info is not None
    assert info['name'] == 'Li Li'


def test_name_match_rejected_without_title_overlap():
    cache = get_author_cache()
    _store(cache, name='Li Li')
    assert cache.get_by_any_id(name='Li Li', verify_titles=[TITLE_C]) is None


def test_name_match_verified_despite_case_and_punctuation():
    cache = get_author_cache()
    _store(cache, name='Li Li')
    noisy = 'DEEP learning, for: the automated Program Repair in LARGE codebases!!'
    assert cache.get_by_any_id(name='Li Li', verify_titles=[noisy]) is not None


def test_name_match_verified_when_any_one_title_overlaps():
    cache = get_author_cache()
    _store(cache, name='Li Li')
    info = cache.get_by_any_id(name='Li Li', verify_titles=[TITLE_C, TITLE_B])
    assert info is not None


def test_empty_verify_titles_rejects_name_only_match():
    cache = get_author_cache()
    _store(cache, name='Li Li')
    # Verification requested but no titles to verify against: fail closed
    assert cache.get_by_any_id(name='Li Li', verify_titles=[]) is None
    assert cache.get_by_any_id(name='Li Li', verify_titles=['', None]) is None


def test_name_match_rejected_when_profile_has_no_publications():
    cache = get_author_cache()
    assert cache.update_profile({'name': 'No Pubs', 'h_index': 5}, [])
    assert cache.get_by_any_id(name='No Pubs', verify_titles=[TITLE_A]) is None
    # But without verification it still hits
    assert cache.get_by_any_id(name='No Pubs') is not None


# ---------------------------------------------------------------------------
# Real-ID matches bypass verification entirely
# ---------------------------------------------------------------------------

def test_gs_id_match_ignores_verify_titles():
    cache = get_author_cache()
    _store(cache, name='Li Li', gs_id='gsABC')
    info = cache.get_by_any_id(google_scholar_id='gsABC', verify_titles=[TITLE_C])
    assert info is not None
    assert info['google_scholar_id'] == 'gsABC'


def test_s2_id_match_ignores_verify_titles():
    cache = get_author_cache()
    _store(cache, name='Li Li', s2_id='s2XYZ')
    info = cache.get_by_any_id(semantic_scholar_id='s2XYZ', verify_titles=[TITLE_C])
    assert info is not None
    assert info['semantic_scholar_id'] == 's2XYZ'


def test_orcid_match_ignores_verify_titles():
    cache = get_author_cache()
    _store(cache, name='Li Li', orcid='0000-0001-2345-6789')
    info = cache.get_by_any_id(orcid_id='0000-0001-2345-6789', verify_titles=[TITLE_C])
    assert info is not None


def test_id_match_wins_even_when_name_would_fail_verification():
    cache = get_author_cache()
    _store(cache, name='Li Li', s2_id='s2XYZ')
    # Both an ID and a name are supplied; the ID match must return the
    # profile even though verify_titles has no overlap
    info = cache.get_by_any_id(name='Li Li', semantic_scholar_id='s2XYZ',
                               verify_titles=[TITLE_C])
    assert info is not None


# ---------------------------------------------------------------------------
# Publication-overlap keys still corroborate when the name key fails
# ---------------------------------------------------------------------------

def test_publication_key_match_survives_failed_name_verification():
    cache = get_author_cache()
    _store(cache, name='Li Li', titles=(TITLE_A, TITLE_B))
    # Name key would fail verification (no overlap in verify_titles), but
    # the publications argument matches stored pub:* index keys, so the
    # name was not the only matching criterion
    info = cache.get_by_any_id(
        name='Li Li',
        publications=[{'title': TITLE_A}, {'title': TITLE_B}],
        verify_titles=[TITLE_C],
    )
    assert info is not None


def test_no_match_when_name_fails_and_publications_unknown():
    cache = get_author_cache()
    _store(cache, name='Li Li', titles=(TITLE_A, TITLE_B))
    info = cache.get_by_any_id(
        name='Li Li',
        publications=[{'title': TITLE_C}],
        verify_titles=[TITLE_C],
    )
    assert info is None


# ---------------------------------------------------------------------------
# Storage format keeps titles available for verification
# ---------------------------------------------------------------------------

def test_update_profile_preserves_titles_for_later_verification():
    cache = get_author_cache()
    _store(cache, name='Li Li', s2_id='s2XYZ', titles=(TITLE_A,))
    # Refresh the profile without supplying publications (e.g. ID re-fetch)
    assert cache.update_profile({'name': 'Li Li', 'semantic_scholar_id': 's2XYZ',
                                 'h_index': 30}, [])
    # Stored titles must survive the refresh so verification still works
    assert cache.get_by_any_id(name='Li Li', verify_titles=[TITLE_A]) is not None
    assert cache.get_by_any_id(name='Li Li', verify_titles=[TITLE_C]) is None


def test_bib_nested_titles_are_matched():
    cache = get_author_cache()
    # scholarly-style publications nest the title under 'bib'
    author_info = {'name': 'Jane Roe', 'h_index': 12}
    publications = [{'bib': {'title': TITLE_B}}, {'bib': {'title': TITLE_A}}]
    assert cache.update_profile(author_info, publications)
    assert cache.get_by_any_id(name='Jane Roe', verify_titles=[TITLE_B]) is not None
    assert cache.get_by_any_id(name='Jane Roe', verify_titles=[TITLE_C]) is None


def test_expired_profile_is_not_returned_even_with_overlap():
    cache = get_author_cache()
    _store(cache, name='Li Li')
    # Age every profile file beyond max_age_days
    for cache_file in cache.cache_dir.glob('profile_*.json'):
        data = json.loads(cache_file.read_text())
        data['cached_at'] = (datetime.now() - timedelta(days=90)).isoformat()
        cache_file.write_text(json.dumps(data))
    assert cache.get_by_any_id(name='Li Li', verify_titles=[TITLE_A]) is None
