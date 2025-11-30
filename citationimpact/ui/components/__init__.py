"""
Reusable UI components for the terminal interface.
"""
from .tables import (
    create_overview_table,
    create_institution_table,
    create_venue_table,
    create_scholar_table,
    create_settings_table,
)
from .prompts import (
    get_field,
    make_clickable,
    format_university_rankings,
)

__all__ = [
    'create_overview_table',
    'create_institution_table',
    'create_venue_table',
    'create_scholar_table',
    'create_settings_table',
    'get_field',
    'make_clickable',
    'format_university_rankings',
]

