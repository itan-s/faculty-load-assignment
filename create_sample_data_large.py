"""Creates synthetic sample data for Case 1: faculty.xlsx, courses.xlsx, workload_policy.pdf"""
import pandas as pd
import fitz  # PyMuPDF

# ---------- 1. Faculty ----------
# Expanded to 20 faculty. Same columns and semantics.
faculty = pd.DataFrame([
    # ID,    Name,          Rank,        BaseLoad, Release, QualifiedCourses,               PreferredDays, AcceptsEvening
    ["F001", "Dr. Adams",    "Professor",   12,      3,      "CS101,CS301,CS401",           "MW",          "No"],
    ["F002", "Dr. Baker",    "Professor",   12,      0,      "CS101,CS201,CS350",           "TTh",         "No"],
    ["F003", "Dr. Chen",     "Associate",   12,      0,      "CS201,CS301,CS410",           "MW",          "Yes"],
    ["F004", "Dr. Diaz",     "Associate",   12,      3,      "CS101,CS210,CS310",           "TTh",         "No"],
    ["F005", "Dr. Evans",    "Assistant",   12,      0,      "CS101,CS210,CS201",           "MW",          "Yes"],
    ["F006", "Dr. Farah",    "Assistant",   12,      0,      "CS310,CS350,CS410",           "TTh",         "Yes"],
    ["F007", "Dr. Gomez",    "Assistant",   12,      3,      "CS101,CS201,CS301",           "MW",          "No"],
    ["F008", "Mr. Hassan",   "Lecturer",    15,      0,      "CS101,CS210",                 "Any",         "Yes"],
    ["F009", "Ms. Ivanov",   "Lecturer",    15,      0,      "CS101,CS201,CS210",           "Any",         "Yes"],
    ["F010", "Dr. Jones",    "Professor",   12,      6,      "CS401,CS410,CS350",           "MW",          "No"],

    # New faculty, mirroring patterns above to reach ~20 total
    ["F011", "Dr. Kim",      "Professor",   12,      0,      "CS101,CS301,CS350",           "MW",          "No"],
    ["F012", "Dr. Lopez",    "Associate",   12,      0,      "CS201,CS310,CS410",           "TTh",         "Yes"],
    ["F013", "Dr. Malik",    "Assistant",   12,      0,      "CS101,CS210,CS310",           "MW",          "Yes"],
    ["F014", "Dr. Nguyen",   "Assistant",   12,      3,      "CS201,CS301,CS350",           "TTh",         "No"],
    ["F015", "Dr. Ortiz",    "Assistant",   12,      0,      "CS210,CS310,CS410",           "MW",          "Yes"],
    ["F016", "Ms. Park",     "Lecturer",    15,      0,      "CS101,CS201",                 "Any",         "Yes"],
    ["F017", "Mr. Quinn",    "Lecturer",    15,      0,      "CS101,CS210,CS310",           "Any",         "Yes"],
    ["F018", "Dr. Rivera",   "Associate",   12,      0,      "CS301,CS350,CS401",           "MW",          "No"],
    ["F019", "Dr. Singh",    "Assistant",   12,      0,      "CS201,CS301,CS410",           "TTh",         "Yes"],
    ["F020", "Dr. Taylor",   "Professor",   12,      0,      "CS101,CS350,CS401",           "MW",          "No"],
], columns=["FacultyID", "Name", "Rank", "BaseLoadCredits",
            "ReleaseCredits", "QualifiedCourses", "PreferredDays", "AcceptsEvening"])
faculty.to_excel("data/raw/faculty.xlsx", index=False)
print("Created data/raw/faculty.xlsx")

# ---------- 2. Course sections ----------
# Expanded to create more demand than total faculty capacity.
# Each course is 3 credits. Tenure-track base 12, lecturers 15, so total capacity is high;
# slightly exceed this so the solver must handle tight capacity while following policy.
courses = pd.DataFrame([
    # Code,   Sec, Title,                     Credits, Days,  Start,  End,    Evening, Enrollment, AllowedRooms,         Room
    ["CS101", "01", "Intro to Programming",      3,   "MW",   "09:00","10:15","No",    35,        "",                   ""],
    ["CS101", "02", "Intro to Programming",      3,   "TTh",  "09:00","10:15","No",    35,        "",                   ""],
    ["CS101", "03", "Intro to Programming",      3,   "MW",   "18:00","19:15","Yes",   30,        "",                   ""],
    ["CS101", "04", "Intro to Programming",      3,   "TTh",  "13:00","14:15","No",    38,        "",                   ""],
    ["CS101", "05", "Intro to Programming",      3,   "MW",   "11:00","12:15","No",    32,        "",                   ""],
    ["CS101", "06", "Intro to Programming",      3,   "TTh",  "15:00","16:15","No",    28,        "",                   ""],

    ["CS201", "01", "Data Structures",           3,   "MW",   "10:30","11:45","No",    30,        "",                   ""],
    ["CS201", "02", "Data Structures",           3,   "TTh",  "10:30","11:45","No",    28,        "",                   ""],
    ["CS201", "03", "Data Structures",           3,   "MW",   "13:00","14:15","No",    30,        "",                   ""],
    ["CS201", "04", "Data Structures",           3,   "TTh",  "14:30","15:45","No",    26,        "",                   ""],

    ["CS210", "01", "Computer Organization",     3,   "MW",   "13:00","14:15","No",    22,        "LAB-01,LAB-02",       ""],
    ["CS210", "02", "Computer Organization",     3,   "TTh",  "18:00","19:15","Yes",   20,        "LAB-01,LAB-02",       ""],
    ["CS210", "03", "Computer Organization",     3,   "MW",   "15:00","16:15","No",    24,        "LAB-01,LAB-02",       ""],

    ["CS301", "01", "Algorithms",                3,   "MW",   "09:00","10:15","No",    25,        "",                   ""],
    ["CS301", "02", "Algorithms",                3,   "TTh",  "13:00","14:15","No",    25,        "",                   ""],
    ["CS301", "03", "Algorithms",                3,   "MW",   "14:30","15:45","No",    24,        "",                   ""],

    ["CS310", "01", "Databases",                 3,   "MW",   "14:30","15:45","No",    24,        "LAB-01,LAB-02",       "LAB-02"],
    ["CS310", "02", "Databases",                 3,   "TTh",  "11:00","12:15","No",    26,        "LAB-01,LAB-02",       ""],

    ["CS350", "01", "Software Engineering",      3,   "TTh",  "09:00","10:15","No",    26,        "",                   ""],
    ["CS350", "02", "Software Engineering",      3,   "MW",   "16:30","17:45","No",    24,        "",                   ""],

    ["CS401", "01", "Operating Systems",         3,   "MW",   "10:30","11:45","No",    18,        "",                   ""],
    ["CS401", "02", "Operating Systems",         3,   "TTh",  "16:30","17:45","No",    20,        "",                   ""],

    ["CS410", "01", "Machine Learning",          3,   "TTh",  "14:30","15:45","No",    20,        "",                   ""],
    ["CS410", "02", "Machine Learning",          3,   "MW",   "18:00","19:15","Yes",   15,        "",                   ""],
    ["CS410", "03", "Machine Learning",          3,   "MW",   "08:00","09:15","No",    18,        "",                   ""],
], columns=["CourseCode", "Section", "Title", "Credits", "Days", "StartTime",
            "EndTime", "Evening", "Enrollment", "AllowedRooms", "Room"])
courses.to_excel("data/raw/courses.xlsx", index=False)
print("Created data/raw/courses.xlsx")

# ---------- 3. Classrooms details  ----------
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
print("Created data/raw/rooms.xlsx")

# ---------- 4. Policy PDF ----------
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
print("Created data/raw/workload_policy.pdf")
