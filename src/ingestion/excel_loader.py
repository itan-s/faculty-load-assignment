import pandas as pd
from src.models.faculty import FacultyProfile
from src.models.course import Section
from src.models.room import Room 
from src.solvers.room_solver import parse_availability

# CLIENT-CONFIG: map Excel columns -> preference keys.
# To support a new preference: add one line here + one checker in supervisor_agent.py
PREFERENCE_COLUMNS = {
    "PreferredDays":  "preferred_days",
    "AcceptsEvening": "accepts_evening",
}

def load_faculty(path: str = "data/raw/faculty.xlsx"):
    df = pd.read_excel(path)
    out = []
    for _, row in df.iterrows():
        prefs = {}
        for col, key in PREFERENCE_COLUMNS.items():
            if col in df.columns and pd.notna(row.get(col)):
                prefs[key] = row[col]
        out.append(FacultyProfile(
            faculty_id=row["FacultyID"],
            name=row["Name"],
            rank=row["Rank"],
            base_load_credits=row["BaseLoadCredits"],
            release_credits=row["ReleaseCredits"],
            qualified_courses=[c.strip() for c in str(row["QualifiedCourses"]).split(",")],
            preferences=prefs,
        ))
    return out


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
            enrollment=int(row.get("Enrollment", 0) or 0),
            allowed_rooms=[r.strip() for r in str(row["AllowedRooms"]).split(",")]
                          if pd.notna(row.get("AllowedRooms")) and str(row.get("AllowedRooms")).strip()
                          else [],
            room=str(row["Room"]).strip()
                 if pd.notna(row.get("Room")) and str(row.get("Room")).strip()
                 else None,
        )
        for _, row in df.iterrows()
    ]

def load_rooms(path: str = "data/raw/rooms.xlsx") -> list[Room]:
    df = pd.read_excel(path)
    return [
        Room(
            room_id=str(row["RoomID"]).strip(),
            building=str(row.get("Building", "")),
            capacity=int(row.get("Capacity", 0) or 0),
            available=str(row.get("Available", "Yes")).strip().lower() == "yes",
            availability=parse_availability(row.get("Availability", "")),
            room_type=str(row.get("RoomType", "Lecture")).strip(),
        )
        for _, row in df.iterrows()
    ]

if __name__ == "__main__":
    for f in load_faculty():
        print(f"{f.faculty_id} {f.name:<12} must teach {f.required_load} credits")
    print(f"\n{len(load_sections())} sections loaded.")
