from pydantic import BaseModel
from typing import Any

class FacultyProfile(BaseModel):
    faculty_id: str
    name: str
    rank: str
    base_load_credits: float
    release_credits: float = 0.0
    qualified_courses: list[str] = []

    # Generic preference storage: any mapped Excel column lands here.
    preferences: dict[str, Any] = {}

    @property
    def required_load(self) -> float:
        return self.base_load_credits - self.release_credits
