import pandas as pd
from src.models.faculty import FacultyProfile
from src.models.course import Section

def load_faculty(path: str = "data/raw/faculty.xlsx") -> list[FacultyProfile]:
    df = pd.read_excel(path)
    return [
        FacultyProfile(
            faculty_id=row["FacultyID"],
            name=row["Name"],
            rank=row["Rank"],
            base_load_credits=row["BaseLoadCredits"],
            release_credits=row["ReleaseCredits"],
            qualified_courses=[c.strip() for c in str(row["QualifiedCourses"]).split(",")],
            preferred_days=row["PreferredDays"],
            accepts_evening=str(row["AcceptsEvening"]).strip().lower() == "yes",
        )
        for _, row in df.iterrows()
    ]

def load_sections(path: str = "data/raw/courses.xlsx") -> list[Section]:
    df = pd.read_excel(path)
    return [
        Section(
            course_code=row["CourseCode"],
            section=str(row["Section"]).zfill(2),
            title=row["Title"],
            credits=row["Credits"],
            days=row["Days"],
            start_time=str(row["StartTime"]),
            end_time=str(row["EndTime"]),
            evening=str(row["Evening"]).strip().lower() == "yes",
        )
        for _, row in df.iterrows()
    ]

if __name__ == "__main__":
    for f in load_faculty():
        print(f"{f.faculty_id} {f.name:<12} must teach {f.required_load} credits")
    print(f"\n{len(load_sections())} sections loaded.")
