from pydantic import BaseModel

class Section(BaseModel):
    course_code: str
    section: str
    title: str
    credits: float
    days: str
    start_time: str
    end_time: str
    evening: bool
    enrollment: int = 0
    allowed_rooms: list[str] = []     # empty = any room
    room: str | None = None           # pre-assigned room, if any


    @property
    def section_id(self) -> str:
        return f"{self.course_code}-{self.section}"
