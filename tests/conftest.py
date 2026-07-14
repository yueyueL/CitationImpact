"""Shared fixtures: isolate config/cache into a temp directory for every test."""

import sys
from pathlib import Path

import pytest

# Make the repo root importable when running pytest from anywhere
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import citationimpact.cache as cache_module
import citationimpact.config as config_module
from citationimpact.config import ConfigManager


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Point the global config/cache singletons at a fresh temp directory."""
    manager = ConfigManager(config_dir=tmp_path / 'config')
    monkeypatch.setattr(config_module, '_config_manager', manager)
    monkeypatch.setattr(cache_module, '_result_cache', None)
    monkeypatch.setattr(cache_module, '_author_cache', None)
    monkeypatch.setattr(cache_module, '_my_publications_cache', None)
    yield manager
