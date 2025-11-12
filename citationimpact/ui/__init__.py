"""Terminal UI system for CitationImpact."""

from .terminal_ui import TerminalUI, main
from .drill_down import (
    show_institution_details,
    show_venue_details,
    show_scholar_details,
    show_influential_details
)

__all__ = [
    'TerminalUI',
    'main',
    'show_institution_details',
    'show_venue_details',
    'show_scholar_details',
    'show_influential_details'
]
