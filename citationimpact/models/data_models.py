"""Data models for citation analysis"""

from dataclasses import dataclass
from typing import List


@dataclass
class Author:
    """Author information from APIs with unified profile"""
    name: str
    h_index: int
    affiliation: str
    institution_type: str
    works_count: int = 0
    citation_count: int = 0
    # Research profile IDs (for disambiguation and linking)
    semantic_scholar_id: str = ""  # Semantic Scholar author ID
    google_scholar_id: str = ""    # Google Scholar author ID (for profile link)
    orcid_id: str = ""             # ORCID identifier
    homepage: str = ""             # Personal/lab homepage
    # Data source info
    h_index_source: str = ""       # Which API provided h-index (gs/s2/openalex)

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
    
    def get_profile_url(self) -> str:
        """Get the best profile URL for this author"""
        if self.google_scholar_id:
            return f"https://scholar.google.com/citations?user={self.google_scholar_id}"
        if self.semantic_scholar_id:
            return f"https://www.semanticscholar.org/author/{self.semantic_scholar_id}"
        if self.orcid_id:
            return f"https://orcid.org/{self.orcid_id}"
        if self.homepage:
            return self.homepage
        return ""


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
class AuthorInfo:
    """Author information with unique identifiers for disambiguation"""
    name: str
    author_id: str = ""  # Semantic Scholar author ID (unique identifier)
    
    def __post_init__(self):
        """Validate AuthorInfo data"""
        if not isinstance(self.name, str):
            raise ValueError("name must be a string")
        if not isinstance(self.author_id, str):
            raise ValueError("author_id must be a string")


@dataclass
class Citation:
    """Citation with context and influence"""
    citing_paper_title: str
    citing_authors: List[str]  # Keep for backward compatibility
    venue: str
    year: int
    is_influential: bool
    contexts: List[str]
    intents: List[str]
    paper_id: str = ""  # Semantic Scholar paper ID
    doi: str = ""  # Digital Object Identifier
    url: str = ""  # Direct link to paper (Semantic Scholar or DOI)
    # New field: List of AuthorInfo objects with IDs for accurate author lookup
    authors_with_ids: List[AuthorInfo] = None  # List of AuthorInfo objects
    # Impact metrics for the citing paper (helps show "highly-cited papers cite you")
    citation_count: int = 0  # How many citations the CITING paper has
    influential_citation_count: int = 0  # Influential citations of the citing paper

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
        # Initialize authors_with_ids to empty list if None
        if self.authors_with_ids is None:
            object.__setattr__(self, 'authors_with_ids', [])
        elif not isinstance(self.authors_with_ids, list):
            raise ValueError("authors_with_ids must be a list")
        if not isinstance(self.citation_count, int) or self.citation_count < 0:
            object.__setattr__(self, 'citation_count', 0)
        if not isinstance(self.influential_citation_count, int) or self.influential_citation_count < 0:
            object.__setattr__(self, 'influential_citation_count', 0)
