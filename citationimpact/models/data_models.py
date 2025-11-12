"""Data models for citation analysis"""

from dataclasses import dataclass
from typing import List


@dataclass
class Author:
    """Author information from APIs"""
    name: str
    h_index: int
    affiliation: str
    institution_type: str
    works_count: int = 0
    citation_count: int = 0

    def __post_init__(self):
        """Validate Author data"""
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Author name must be a non-empty string")
        if not isinstance(self.h_index, int) or self.h_index < 0:
            raise ValueError("h_index must be a non-negative integer")
        if not isinstance(self.affiliation, str):
            raise ValueError("affiliation must be a string")
        if not isinstance(self.institution_type, str):
            raise ValueError("institution_type must be a string")
        if not isinstance(self.works_count, int) or self.works_count < 0:
            raise ValueError("works_count must be a non-negative integer")
        if not isinstance(self.citation_count, int) or self.citation_count < 0:
            raise ValueError("citation_count must be a non-negative integer")


@dataclass
class Venue:
    """Venue information from APIs"""
    name: str
    h_index: int
    type: str
    works_count: int = 0
    cited_by_count: int = 0
    rank_tier: str = 'Unranked'

    def __post_init__(self):
        """Validate Venue data"""
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Venue name must be a non-empty string")
        if not isinstance(self.h_index, int) or self.h_index < 0:
            raise ValueError("h_index must be a non-negative integer")
        if not isinstance(self.type, str):
            raise ValueError("type must be a string")
        if not isinstance(self.works_count, int) or self.works_count < 0:
            raise ValueError("works_count must be a non-negative integer")
        if not isinstance(self.cited_by_count, int) or self.cited_by_count < 0:
            raise ValueError("cited_by_count must be a non-negative integer")
        if not isinstance(self.rank_tier, str):
            raise ValueError("rank_tier must be a string")


@dataclass
class Citation:
    """Citation with context and influence"""
    citing_paper_title: str
    citing_authors: List[str]
    venue: str
    year: int
    is_influential: bool
    contexts: List[str]
    intents: List[str]
    paper_id: str = ""  # Semantic Scholar paper ID
    doi: str = ""  # Digital Object Identifier
    url: str = ""  # Direct link to paper (Semantic Scholar or DOI)

    def __post_init__(self):
        """Validate Citation data"""
        if not isinstance(self.citing_paper_title, str):
            raise ValueError("citing_paper_title must be a string")
        if not isinstance(self.citing_authors, list):
            raise ValueError("citing_authors must be a list")
        if not isinstance(self.venue, str):
            raise ValueError("venue must be a string")
        if not isinstance(self.year, int):
            raise ValueError("year must be an integer")
        if not isinstance(self.is_influential, bool):
            raise ValueError("is_influential must be a boolean")
        if not isinstance(self.contexts, list):
            raise ValueError("contexts must be a list")
        if not isinstance(self.intents, list):
            raise ValueError("intents must be a list")
        if not isinstance(self.paper_id, str):
            raise ValueError("paper_id must be a string")
        if not isinstance(self.doi, str):
            raise ValueError("doi must be a string")
        if not isinstance(self.url, str):
            raise ValueError("url must be a string")
