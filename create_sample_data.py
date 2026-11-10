"""Creates fake sample data: faculty.xlsx, courses.xlsx, workload_policy.pdf"""
import pandas as pd
import fitz  # PyMuPDF

# ---------- 1. Faculty ----------
faculty = pd.DataFrame([
    # ID, Name, Rank, BaseLoad, Release, QualifiedCourses, PreferredDays, AcceptsEvening
    ["F001", "Dr. Adams",  "Professor",   12, 3, "CS101,CS301,CS401", "MW",  "No"],
    ["F002", "Dr. Baker",  "Professor",   12, 0, "CS101,CS201,CS350", "TTh", "No"],
    ["F003", "Dr. Chen",   "Associate",   12, 0, "CS201,CS301,CS410", "MW",  "Yes"],
    ["F004", "Dr. Diaz",   "Associate",   12, 3, "CS101,CS210,CS310", "TTh", "No"],
    ["F005", "Dr. Evans",  "Assistant",   12, 0, "CS101,CS210,CS201", "MW",  "Yes"],
    ["F006", "Dr. Farah",  "Assistant",   12, 0, "CS310,CS350,CS410", "TTh", "Yes"],
    ["F007", "Dr. Gomez",  "Assistant",   12, 3, "CS101,CS201,CS301", "MW",  "No"],
    ["F008", "Mr. Hassan", "Lecturer",    15, 0, "CS101,CS210",        "Any", "Yes"],
    ["F009", "Ms. Ivanov", "Lecturer",    15, 0, "CS101,CS201,CS210", "Any", "Yes"],
    ["F010", "Dr. Jones",  "Professor",   12, 6, "CS401,CS410,CS350", "MW",  "No"],
], columns=["FacultyID", "Name", "Rank", "BaseLoadCredits",
            "ReleaseCredits", "QualifiedCourses", "PreferredDays", "AcceptsEvening"])
faculty.to_excel("data/raw/faculty.xlsx", index=False)
print("Created data/raw/faculty.xlsx")

# ---------- 2. Course sections ----------
courses = pd.DataFrame([
    # Code, Section, Title, Credits, Days, Start, End, Evening
    ["CS101", "01", "Intro to Programming",   3, "MW",  "09:00", "10:15", "No"],
    ["CS101", "02", "Intro to Programming",   3, "TTh", "09:00", "10:15", "No"],
    ["CS101", "03", "Intro to Programming",   3, "MW",  "18:00", "19:15", "Yes"],
    ["CS101", "04", "Intro to Programming",   3, "TTh", "13:00", "14:15", "No"],
    ["CS201", "01", "Data Structures",        3, "MW",  "10:30", "11:45", "No"],
    ["CS201", "02", "Data Structures",        3, "TTh", "10:30", "11:45", "No"],
    ["CS210", "01", "Computer Organization",  3, "MW",  "13:00", "14:15", "No"],
    ["CS210", "02", "Computer Organization",  3, "TTh", "18:00", "19:15", "Yes"],
    ["CS301", "01", "Algorithms",             3, "MW",  "09:00", "10:15", "No"],
    ["CS301", "02", "Algorithms",             3, "TTh", "13:00", "14:15", "No"],
    ["CS310", "01", "Databases",              3, "MW",  "14:30", "15:45", "No"],
    ["CS350", "01", "Software Engineering",   3, "TTh", "09:00", "10:15", "No"],
    ["CS401", "01", "Operating Systems",      3, "MW",  "10:30", "11:45", "No"],
    ["CS410", "01", "Machine Learning",       3, "TTh", "14:30", "15:45", "No"],
    ["CS410", "02", "Machine Learning",       3, "MW",  "18:00", "19:15", "Yes"],
], columns=["CourseCode", "Section", "Title", "Credits",
            "Days", "StartTime", "EndTime", "Evening"])
courses.to_excel("data/raw/courses.xlsx", index=False)
print("Created data/raw/courses.xlsx")

# ---------- 3. Policy PDF ----------
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
