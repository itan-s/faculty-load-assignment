"""Creates a tiny synthetic dataset designed to force overloads when
allow_soft_overload=True.

- 2 faculty total.
- F001 is the only one qualified for CS999 (4 sections, 3 credits each).
- F002 is only qualified for CS101 (1 section, 3 credits).
- F001's required_load is 6 credits, but there are 12 credits of CS999.
  With strong coverage reward and soft overload enabled, the solver
  should overload F001 to cover most or all CS999 sections.
"""

import pandas as pd
import fitz  # PyMuPDF

# ---------- 1. Faculty ----------
faculty = pd.DataFrame([
    # ID,    Name,       Rank,       BaseLoad, Release, QualifiedCourses,  PreferredDays, AcceptsEvening
    ["F001", "Dr. Over",  "Professor",  6,       0,      "CS999",           "Any",         "Yes"],
    ["F002", "Dr. Spare", "Assistant",  12,      0,      "CS101",           "Any",         "Yes"],
], columns=["FacultyID", "Name", "Rank", "BaseLoadCredits",
            "ReleaseCredits", "QualifiedCourses", "PreferredDays", "AcceptsEvening"])
faculty.to_excel("data/raw/faculty.xlsx", index=False)
print("Created data/raw/faculty.xlsx (forced overload demo)")

# ---------- 2. Courses ----------
rows = []

# 4 non-overlapping CS999 sections, all only teachable by F001.
cs999_slots = [
    ("M", "08:00", "09:15"),
    ("M", "09:30", "10:45"),
    ("M", "11:00", "12:15"),
    ("M", "13:00", "14:15"),
]
for i, (day, start, end) in enumerate(cs999_slots, start=1):
    rows.append([
        "CS999",
        f"{i:02d}",
        "Overload Demo Course",
        3,
        day,
        start,
        end,
        "No",
        30,
        "",
        "",
    ])

# 1 CS101 section for F002 to soak up some load.
rows.append([
    "CS101",
    "01",
    "Intro for Spare",
    3,
    "T",
    "09:00",
    "10:15",
    "No",
    30,
    "",
    "",
])

courses = pd.DataFrame(rows, columns=[
    "CourseCode", "Section", "Title", "Credits", "Days", "StartTime",
    "EndTime", "Evening", "Enrollment", "AllowedRooms", "Room"
])
courses.to_excel("data/raw/courses.xlsx", index=False)
print(f"Created data/raw/courses.xlsx (forced overload demo) with {len(courses)} sections.")

# ---------- 3. Rooms ----------
# Make rooms unconstraining: enough capacity and wide availability.
rooms = pd.DataFrame([
    ["RM-101", "Main",  100, "Yes", "M 07:00-18:00; T 07:00-18:00", "Lecture"],
], columns=["RoomID", "Building", "Capacity", "Available", "Availability", "RoomType"])
rooms.to_excel("data/raw/rooms.xlsx", index=False)
print("Created data/raw/rooms.xlsx (forced overload demo)")

# ---------- 4. Policy PDF ----------
# Simple policy: standard loads and minimum load as usual.
policy_text = """DEPARTMENT TEACHING WORKLOAD POLICY

1. Standard Teaching Load
Full-time tenure-track faculty (Professor, Associate, Assistant) shall teach
6 credit hours per semester in this minimal demo. Lecturers shall teach 15 credit hours per semester.

2. Release Time
Approved release time (research grants, administrative roles) reduces the
required teaching load by the stated number of credits.

3. Minimum Load
No full-time faculty member may teach fewer than 6 credit hours per semester
unless on approved leave.

4. Course Qualifications
Faculty may only be assigned to courses for which they are listed as qualified
by the department curriculum committee.

5. Evening Classes
No faculty member shall be assigned more than 2 evening sections per semester.
Faculty who have indicated they do not accept evening classes shall not be
assigned evening sections except with written consent.

6. Course Preparations
No faculty member shall be assigned more than 3 distinct course preparations
(unique course codes) per semester.
"""
doc = fitz.open()
page = doc.new_page()
page.insert_text((50, 50), policy_text, fontsize=10)
doc.save("data/raw/workload_policy.pdf")
print("Created data/raw/workload_policy.pdf (forced overload demo)")
