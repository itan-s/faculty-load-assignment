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

    @property
    def section_id(self) -> str:
        return f"{self.course_code}-{self.section}"
