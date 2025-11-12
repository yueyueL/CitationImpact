"""Configuration management for CitationImpact"""

import json
import shutil
from pathlib import Path
from typing import Dict, Any, Optional


class ConfigManager:
    """Manages user configuration with persistent storage"""

    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize configuration manager

        Args:
            config_dir: Custom config directory (defaults to <project>/.citationimpact)
        """
        home_dir = Path.home() / '.CitationImpact'

        if config_dir is None:
            project_root = Path(__file__).resolve().parent.parent
            preferred_dir = project_root / '.citationimpact'
            selected_dir = preferred_dir
        else:
            selected_dir = Path(config_dir)
            preferred_dir = None

        # Ensure the selected directory exists; fall back to home directory if creation fails
        try:
            is_new_dir = not selected_dir.exists()
            selected_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            if config_dir is None:
                print(f"[Config] Warning: Could not create {selected_dir} ({exc}). Falling back to {home_dir}.")
                selected_dir = home_dir
                is_new_dir = not selected_dir.exists()
                selected_dir.mkdir(parents=True, exist_ok=True)
            else:
                raise

        self.config_dir = selected_dir

        # Migrate legacy configuration from the home directory if needed
        if config_dir is None and preferred_dir is not None and selected_dir == preferred_dir and home_dir.exists():
            self._migrate_legacy_config(home_dir)

        # Print info about where config is saved (only for new directories)
        if is_new_dir:
            print(f"[Config] Created local data directory: {self.config_dir}")
            print(f"[Config] This folder will store: API keys, cached results, and settings")

        # Config file path
        self.config_file = self.config_dir / 'config.json'

        # Default configuration
        self.defaults = {
            'h_index_threshold': 20,
            'max_citations': 100,
            'data_source': 'api',
            'email': None,
            'api_key': None,
            'timeout': 15,
            'max_retries': 3,
            'default_semantic_scholar_author_id': None,
            'default_google_scholar_author_id': None,
        }

        # Load or create config
        self.config = self.load()

    def load(self) -> Dict[str, Any]:
        """Load configuration from file or create with defaults"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                # Merge with defaults to handle new settings
                return {**self.defaults, **config}
            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not load config from {self.config_file}: {e}")
                return self.defaults.copy()
        else:
            # Create new config with defaults
            self.save(self.defaults)
            return self.defaults.copy()

    def save(self, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Save configuration to file

        Args:
            config: Configuration to save (uses self.config if None)

        Returns:
            True if successful, False otherwise
        """
        if config is None:
            config = self.config

        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
            return True
        except IOError as e:
            print(f"Error: Could not save config to {self.config_file}: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value"""
        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> bool:
        """
        Set a configuration value and save

        Args:
            key: Configuration key
            value: Configuration value

        Returns:
            True if saved successfully
        """
        self.config[key] = value
        return self.save()

    def update(self, updates: Dict[str, Any]) -> bool:
        """
        Update multiple configuration values and save

        Args:
            updates: Dictionary of updates

        Returns:
            True if saved successfully
        """
        self.config.update(updates)
        return self.save()

    def reset(self) -> bool:
        """Reset configuration to defaults"""
        self.config = self.defaults.copy()
        return self.save()

    def get_config_path(self) -> Path:
        """Get the configuration directory path"""
        return self.config_dir

    def get_all(self) -> Dict[str, Any]:
        """Get all configuration as dictionary"""
        return self.config.copy()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _migrate_legacy_config(self, legacy_dir: Path) -> None:
        """
        Copy legacy configuration stored in ~/.CitationImpact into the project-level
        data directory if those files do not already exist.
        """
        if not legacy_dir.exists() or legacy_dir.resolve() == self.config_dir.resolve():
            return

        migrated = False
        for item in legacy_dir.iterdir():
            destination = self.config_dir / item.name
            if destination.exists():
                continue

            try:
                if item.is_dir():
                    shutil.copytree(item, destination)
                else:
                    shutil.copy2(item, destination)
                migrated = True
            except Exception as exc:  # pragma: no cover - best effort migration
                print(f"[Config] Warning: Could not migrate '{item}' from legacy directory: {exc}")

        if migrated:
            print(f"[Config] Migrated existing data from {legacy_dir} to {self.config_dir}")


# Global instance for easy access
_config_manager = None


def get_config_manager() -> ConfigManager:
    """Get or create global configuration manager"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def get_config(key: str, default: Any = None) -> Any:
    """Get a configuration value (convenience function)"""
    return get_config_manager().get(key, default)


def set_config(key: str, value: Any) -> bool:
    """Set a configuration value (convenience function)"""
    return get_config_manager().set(key, value)


def get_export_dir() -> Path:
    """Get the directory for exported reports"""
    config_dir = get_config_manager().get_config_path()
    export_dir = config_dir / 'exports'
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir


def get_cache_dir() -> Path:
    """Get the directory for cached data"""
    config_dir = get_config_manager().get_config_path()
    cache_dir = config_dir / 'cache'
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir
