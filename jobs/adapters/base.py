from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RawJob:
    """Common shape every adapter must produce."""

    title: str
    url: str
    description: str = ""  # plain text
    external_id: Optional[str] = None
    location: str = ""
    locations: list = field(default_factory=list)  # every location the posting lists
    country: str = ""  # ISO code when the platform provides one
    employment_type: str = ""
    workplace_type: str = ""
    department: str = ""
    seniority: str = ""
    posted_at: Optional[datetime] = None
    source_updated_at: Optional[datetime] = None


class BaseAdapter:
    key = ""
    label = ""

    def __init__(self, source):
        self.source = source

    def fetch_jobs(self):
        """Return list[RawJob] or raise jobs.adapters.http.FetchError."""
        raise NotImplementedError
