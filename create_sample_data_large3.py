"""Creates synthetic sample data for Case 3 (very high demand, likely overload pressure)."""
import pandas as pd
import fitz  # PyMuPDF

# ---------- 1. Faculty (same as Case 1 / 2) ----------
faculty = pd.DataFrame([
    ["F001", "Dr. Adams",    "Professor",   12,  3, "CS101,CS301,CS401",           "MW",  "No"],
    ["F002", "Dr. Baker",    "Professor",   12,  0, "CS101,CS201,CS350",           "TTh", "No"],
    ["F003", "Dr. Chen",     "Associate",   12,  0, "CS201,CS301,CS410",           "MW",  "Yes"],
    ["F004", "Dr. Diaz",     "Associate",   12,  3, "CS101,CS210,CS310",           "TTh", "No"],
    ["F005", "Dr. Evans",    "Assistant",   12,  0, "CS101,CS210,CS201",           "MW",  "Yes"],
    ["F006", "Dr. Farah",    "Assistant",   12,  0, "CS310,CS350,CS410",           "TTh", "Yes"],
    ["F007", "Dr. Gomez",    "Assistant",   12,  3, "CS101,CS201,CS301",           "MW",  "No"],
    ["F008", "Mr. Hassan",   "Lecturer",    15,  0, "CS101,CS210",                 "Any", "Yes"],
    ["F009", "Ms. Ivanov",   "Lecturer",    15,  0, "CS101,CS201,CS210",           "Any", "Yes"],
    ["F010", "Dr. Jones",    "Professor",   12,  6, "CS401,CS410,CS350",           "MW",  "No"],
    ["F011", "Dr. Kim",      "Professor",   12,  0, "CS101,CS301,CS350",           "MW",  "No"],
    ["F012", "Dr. Lopez",    "Associate",   12,  0, "CS201,CS310,CS410",           "TTh", "Yes"],
    ["F013", "Dr. Malik",    "Assistant",   12,  0, "CS101,CS210,CS310",           "MW",  "Yes"],
    ["F014", "Dr. Nguyen",   "Assistant",   12,  3, "CS201,CS301,CS350",           "TTh", "No"],
    ["F015", "Dr. Ortiz",    "Assistant",   12,  0, "CS210,CS310,CS410",           "MW",  "Yes"],
    ["F016", "Ms. Park",     "Lecturer",    15,  0, "CS101,CS201",                 "Any", "Yes"],
    ["F017", "Mr. Quinn",    "Lecturer",    15,  0, "CS101,CS210,CS310",           "Any", "Yes"],
    ["F018", "Dr. Rivera",   "Associate",   12,  0, "CS301,CS350,CS401",           "MW",  "No"],
    ["F019", "Dr. Singh",    "Assistant",   12,  0, "CS201,CS301,CS410",           "TTh", "Yes"],
    ["F020", "Dr. Taylor",   "Professor",   12,  0, "CS101,CS350,CS401",           "MW",  "No"],
], columns=["FacultyID", "Name", "Rank", "BaseLoadCredits",
            "ReleaseCredits", "QualifiedCourses", "PreferredDays", "AcceptsEvening"])
faculty.to_excel("data/raw/faculty.xlsx", index=False)
print("Created data/raw/faculty.xlsx (Case 3 overload test)")

# ---------- 2. Courses: many sections to force high demand ----------
rows = []
# Reuse core patterns but make many sections across core courses
course_defs = [
    ("CS101", "Intro to Programming",      "MW",  "09:00","10:15","No"),
    ("CS101", "Intro to Programming",      "TTh", "09:00","10:15","No"),
    ("CS201", "Data Structures",           "MW",  "10:30","11:45","No"),
    ("CS201", "Data Structures",           "TTh", "10:30","11:45","No"),
    ("CS210", "Computer Organization",     "MW",  "13:00","14:15","No"),
    ("CS210", "Computer Organization",     "TTh", "18:00","19:15","Yes"),
    ("CS301", "Algorithms",                "MW",  "14:30","15:45","No"),
    ("CS301", "Algorithms",                "TTh", "13:00","14:15","No"),
    ("CS310", "Databases",                 "MW",  "09:00","10:15","No"),
    ("CS350", "Software Engineering",      "TTh", "09:00","10:15","No"),
    ("CS401", "Operating Systems",         "MW",  "15:00","16:15","No"),
    ("CS410", "Machine Learning",          "TTh", "14:30","15:45","No"),
]

sec_num = 1
for code, title, days, start, end, evening in course_defs:
    # create multiple sections per pattern
    for k in range(1, 7):  # 6 sections each → 12 patterns * 6 = 72 sections
        rows.append([
            code,
            f"{k:02d}",
            title,
            3,
            days,
            start,
            end,
            evening,
            25,          # enrollment
            "",          # AllowedRooms
            "",          # Room
        ])
        sec_num += 1

courses = pd.DataFrame(rows, columns=[
    "CourseCode", "Section", "Title", "Credits", "Days", "StartTime",
    "EndTime", "Evening", "Enrollment", "AllowedRooms", "Room"
])
print(f"Created data/raw/courses.xlsx (Case 3 overload test) with {len(courses)} sections.")
courses.to_excel("data/raw/courses.xlsx", index=False)

# ---------- 3. Rooms (reuse from Case 2) ----------
rooms = pd.DataFrame([
    ["RM-101", "Main",  40, "Yes", "MW 07:00-17:00; TTh 07:00-17:00", "Lecture"],
    ["RM-102", "Main",  40, "Yes", "MW 07:00-17:00; TTh 07:00-17:00", "Lecture"],
    ["RM-201", "Main",  30, "Yes", "MW 07:00-17:00; TTh 07:00-17:00", "Lecture"],
    ["RM-202", "Main",  26, "Yes", "",                                "Lecture"],
    ["LAB-01", "Annex", 25, "Yes", "MW 08:00-21:00; TTh 08:00-21:00", "Laboratory"],
    ["LAB-02", "Annex", 24, "Yes", "MW 08:00-17:00; TTh 08:00-17:00", "Laboratory"],
    ["RM-301", "Annex", 50, "No",  "",                                "Lecture"],
], columns=["RoomID", "Building", "Capacity", "Available", "Availability", "RoomType"])
rooms.to_excel("data/raw/rooms.xlsx", index=False)
print("Created data/raw/rooms.xlsx (Case 3 overload test)")

# ---------- 4. Policy PDF (same content) ----------
policy_text = """DEPARTMENT TEACHING WORKLOAD POLICY

1. Standard Teaching Load
Full-time tenure-track faculty (Professor, Associate, Assistant) shall teach
12 credit hours per semester. Lecturers shall teach 15 credit hours per semester.

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
print("Created data/raw/workload_policy.pdf (Case 3 overload test)")
