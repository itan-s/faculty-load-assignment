from pydantic import BaseModel

class FacultyProfile(BaseModel):
    faculty_id: str
    name: str
    rank: str
    base_load_credits: float
    release_credits: float = 0.0
    qualified_courses: list[str] = []
    preferred_days: str = "Any"
    accepts_evening: bool = True

    @property
    def required_load(self) -> float:
        """Credits this person must actually teach this semester."""
        return self.base_load_credits - self.release_credits
