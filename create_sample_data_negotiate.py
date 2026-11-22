"""Creates a small synthetic dataset designed so load negotiation visibly changes the plan.

Goal:
- Initial plan should give one faculty a heavier load (e.g., 9 credits),
  another a medium load (6), and another a light load (3).
- A negotiation request like:
    "Reduce Dr. Heavy's load to 6 credits and increase Dr. Light's to 6."
  should be feasible and only require moving ONE section, so the solver,
  with stability, will likely accept the change.

Design:
- 3 faculty, all qualified for the same courses.
- 5 sections total (= 15 credits) across CS101 and CS102.
- Non-overlapping times, simple room setup.
"""

import pandas as pd
import fitz  # PyMuPDF

# ---------- 1. Faculty ----------
faculty = pd.DataFrame([
    # FacultyID, Name,        Rank,       BaseLoadCredits, ReleaseCredits, QualifiedCourses,       PreferredDays, AcceptsEvening
    ["F001",     "Dr. Light",  "Assistant", 12,              0,             "CS101,CS102",          "Any",         "Yes"],
    ["F002",     "Dr. Medium", "Associate", 12,              0,             "CS101,CS102",          "Any",         "Yes"],
    ["F003",     "Dr. Heavy",  "Professor", 12,              0,             "CS101,CS102",          "Any",         "Yes"],
], columns=[
    "FacultyID", "Name", "Rank", "BaseLoadCredits",
    "ReleaseCredits", "QualifiedCourses", "PreferredDays", "AcceptsEvening"
])
faculty.to_excel("data/raw/faculty.xlsx", index=False)
print("Created data/raw/faculty.xlsx (negotiation-working demo)")

# ---------- 2. Courses ----------
# 5 sections (3 credits each) at non-overlapping times:
# Idea: initial solver is likely to give:
# - Dr. Heavy 9 credits (3 sections),
# - Dr. Medium 6 credits (2 sections),
# - Dr. Light 0 credits (or 3/3/9 depending on fairness).
# Then we can move one section from Heavy to Light.

courses = pd.DataFrame([
    # CourseCode, Section, Title,             Credits, Days, StartTime, EndTime, Evening, Enrollment, AllowedRooms, Room
    ["CS101",      "01",   "Intro to Prog",   3,      "M",   "08:00",   "09:15", "No",    30,         "",          ""],
    ["CS101",      "02",   "Intro to Prog",   3,      "M",   "09:30",   "10:45", "No",    30,         "",          ""],
    ["CS101",      "03",   "Intro to Prog",   3,      "M",   "11:00",   "12:15", "No",    30,         "",          ""],
    ["CS102",      "01",   "Data Structures", 3,      "M",   "13:00",   "14:15", "No",    30,         "",          ""],
    ["CS102",      "02",   "Data Structures", 3,      "M",   "14:30",   "15:45", "No",    30,         "",          ""],
], columns=[
    "CourseCode", "Section", "Title", "Credits", "Days", "StartTime",
    "EndTime", "Evening", "Enrollment", "AllowedRooms", "Room"
])
courses.to_excel("data/raw/courses.xlsx", index=False)
print("Created data/raw/courses.xlsx (negotiation-working demo)")

# ---------- 3. Rooms ----------
rooms = pd.DataFrame([
    ["RM-101", "Main",  40, "Yes", "M 07:00-18:00", "Lecture"],
    ["RM-102", "Main",  40, "Yes", "M 07:00-18:00", "Lecture"],
], columns=["RoomID", "Building", "Capacity", "Available", "Availability", "RoomType"])
rooms.to_excel("data/raw/rooms.xlsx", index=False)
print("Created data/raw/rooms.xlsx (negotiation-working demo)")

# ---------- 4. Policy PDF ----------
# Here we keep min_load_full_time at 0 (or omit it) so reductions below 6 are allowed.
policy_text = """DEPARTMENT TEACHING WORKLOAD POLICY

1. Standard Teaching Load
Full-time tenure-track faculty (Professor, Associate, Assistant) shall teach
12 credit hours per semester. Lecturers shall teach 15 credit hours per semester.

2. Release Time
Approved release time (research grants, administrative roles) reduces the
required teaching load by the stated number of credits.

3. Minimum Load
For this demonstration scenario, no strict minimum load is enforced;
faculty may be assigned fewer than 6 credit hours without policy violation.

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
print("Created data/raw/workload_policy.pdf (negotiation-working demo)")
