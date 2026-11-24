import json
import difflib
import os
import re

from src.llm.client import ask_llm
from src.agents.constraints_and_faculty_intel_agent import run_constraints_agent
from src.agents.decision_support_and_governance_agent import run_governance_agent
from src.agents.assignment_and_negotiation_agent import (
    run_assignment_agent,
    propose_negotiated_plan, accept_pending_plan, reject_pending_plan,
    negotiation_pending,
)
from src.ingestion.excel_loader import load_faculty, load_sections, load_rooms
from src.validation.metrics import compute_metrics


# =====================================================================
# RESULT CONVENTION (used by CLI today, UI next)
#   {"type": "text",  "title": str, "content": str}
#   {"type": "table", "title": str, "rows": [dict, ...], "content": str (optional)}
#   {"type": "file",  "title": str, "path": str, "content": str}
#   {"type": "error", "content": str}
# =====================================================================


# =====================================================================
# PROMPTS
# =====================================================================

INTENT_SYSTEM_PROMPT = """You are a router for a teaching-load assistant system.
Classify the user's message into exactly ONE allowed intent and extract any
relevant parameters.

Allowed intents:

- "build_constraints": rebuild constraints from the official files.
- "generate_plan": generate a new teaching assignment plan.
- "recalculate_plan": regenerate the plan using existing constraints.
- "show_policy": show the policies and constraints used.
- "policy_violations": show violations in the current plan.
- "show_faculty": list faculty and teaching loads.
- "show_courses_offered": list all offered course sections.
- "show_courses_and_rooms": show section, faculty, and room assignments.
- "show_rooms": list rooms and availability.
- "who_can_teach_course": list faculty qualified for a course.
- "overloaded_faculty": show faculty above their required-load cap.
- "underloaded_faculty": show faculty below the policy minimum load.
- "courses_misassigned_or_unqualified": show unqualified assignments.
- "unmet_preferences": show unmet faculty preferences.
- "show_fairness_issues": show workload fairness issues.
- "explain_assignment": explain why an assignment was or was not made.
- "compare_plans": compare two named plans.
- "negotiate_plan": increase or reduce a faculty member's assigned load.
- "generate_admin_report": generate the administrative report and Excel file.
- "suggest_compliance_improvements": suggest valid compliance improvements.
- "what_if_change": simulate an explicit hypothetical policy or status change.
- "unknown": none of the above.

Return only a JSON object:

{
  "intent": "<allowed intent>",
  "params": {}
}

Parameter examples:

- who_can_teach_course:
  {"course_name": "Machine Learning"}
- explain_assignment:
  {"faculty_name": "Dr. Adams", "course_name": "CS101"}
- compare_plans:
  {"plan_a": "draft_v1", "plan_b": "negotiation_pending"}
- For "generate_plan", params might include {"year": "2027-2028"}.
- For "unmet_preferences", params might include {} for
  "Which faculty preferences could not be accommodated?".
- "what_if_change" should ONLY be used for explicit hypothetical changes to constraints
  or faculty status.

Do not classify ordinary load negotiation as what_if_change.
"""


EXPLAIN_ASSIGNMENT_SYSTEM_PROMPT = """You are an academic scheduling analyst.
You will be given FACTS about a faculty member, a course, the current plan,
and the applicable policies/constraints.

Your job is to explain, in clear professional language for a Department Chair,
WHY this faculty member was assigned (or not assigned) to the course.

Rules:
- Use ONLY the facts provided; do not invent extra data.
- Refer to policies/constraints explicitly when they are relevant.
- If multiple factors contributed, mention them all.
- If the explanation is speculative, say that clearly.
"""

EXPLAIN_ASSIGNMENT_USER_TEMPLATE = """Explain the assignment decision.

FACTS:
- Faculty: {faculty_name} (ID: {faculty_id}, Rank: {rank})
- Course of interest: {course_name}
- Faculty qualified courses: {qualified_courses}
- Faculty required load: {required_load} credits
- Faculty assigned credits (overall): {assigned_credits}
- Faculty preferences: {preferences}

ASSIGNMENTS IN CURRENT PLAN RELATED TO THIS COURSE:
{related_assignments_text}

OTHER SECTIONS ASSIGNED TO THIS FACULTY (for context):
{other_sections_text}

POLICY / CONSTRAINT SUMMARY:
{policy_summary}

Now, in 1-3 short paragraphs, explain why {faculty_name} was
(or was not) assigned to {course_name} in this plan.
"""

SUGGEST_IMPROVEMENTS_SYSTEM_PROMPT = """You are an academic scheduling advisor
writing for a Department Chair.

You are given a list of policy violations in the current teaching plan.
For each violation, the system has ALREADY COMPUTED the valid fix options
under current policies (qualifications, spare load capacity, evening consent).
These pre-computed candidates are the ONLY legal options.

Your job:
- For each violation, write a short, concrete recommendation choosing ONLY
  from the listed candidates.
- If a violation has no candidates (or 'NONE under current rules'), state
  plainly that it cannot be fixed by reassignment under current policies.
- NEVER mention any faculty member, course, or section that does not appear
  in the provided data.
- NEVER suggest changing a policy value (loads, limits, consent rules).
- Be brief: one or two sentences per violation.
"""



# =====================================================================
# CLIENT-CONFIG SECTION
# All of these are client-specific; move to config files when customizing.
# =====================================================================

# CLIENT-CONFIG: file locations
CURRENT_PLAN_PATH = "data/processed/plan_draft_v1.json"
CONSTRAINTS_PATH = "data/processed/constraints.json"

# CLIENT-CONFIG: violation prefix -> policy name
VIOLATION_POLICY_MAP = {
    "UNASSIGNED": "Coverage Policy",
    "DUPLICATE": "Coverage Policy",
    "UNQUALIFIED": "Course Qualifications Policy",
    "EVENING CONSENT": "Evening Classes Policy",
    "OVERLOAD": "Teaching Load Policy",
    "UNDERLOAD": "Teaching Load Policy",
    "TOO MANY PREPS": "Course Preparations Policy",
    "TOO MANY EVENINGS": "Evening Classes Policy",
    "TIME CONFLICT": "Scheduling / Time Conflict Policy",
    "NO ROOM": "Room Assignment Policy",
    "ROOM NOT ALLOWED": "Room Assignment Policy",
    "ROOM OVER CAPACITY": "Room Assignment Policy",
    "ROOM CONFLICT": "Room Assignment Policy",
    "ROOM UNAVAILABLE": "Room Assignment Policy",   # if added availability windows
}

# CLIENT-CONFIG: fixed descriptions for constraint keys
CONSTRAINT_DESCRIPTIONS = {
    "standard_load_tenure_track":
        "Standard teaching load for tenure-track faculty (Professor, Associate, "
        "Assistant): {value} credit hours per semester. Assignments must not exceed this.",
    "standard_load_lecturer":
        "Standard teaching load for Lecturers: {value} credit hours per semester. "
        "Assignments must not exceed this.",
    "min_load_full_time":
        "Minimum teaching load: no full-time faculty member may teach fewer than "
        "{value} credit hours per semester unless on approved leave.",
    "max_evening_sections":
        "Evening classes: no faculty member may be assigned more than {value} "
        "evening sections per semester.",
    "max_preparations":
        "Course preparations: no faculty member may be assigned more than {value} "
        "distinct courses (preps) per semester.",
    "qualification_required":
        "Course qualifications: faculty may only be assigned to courses for which "
        "they are listed as qualified. (Active: {value})",
    "evening_consent_required":
        "Evening consent: faculty who have declined evening classes cannot be "
        "assigned evening sections without their own written consent. (Active: {value})",
}


# =====================================================================
# PREFERENCE CHECKER REGISTRY
# To support a NEW preference: map its Excel column in excel_loader.py,
# then register ONE checker function here. Nothing else changes.
# =====================================================================

PREFERENCE_CHECKERS = {}

def preference_checker(pref_key: str):
    def decorator(fn):
        PREFERENCE_CHECKERS[pref_key] = fn
        return fn
    return decorator

def _is_yes(value) -> bool:
    return str(value).strip().lower() in ("yes", "true", "1")

# CLIENT-CONFIG: checkers for current preference types

@preference_checker("preferred_days")
def check_preferred_days(faculty, assigned_sections):
    pref = str(faculty.preferences.get("preferred_days", "Any")).strip()
    if pref.lower() in ("any", ""):
        return []
    return [
        {"faculty": faculty.name,
         "preference": f"Preferred days: {pref}",
         "issue": f"Assigned {s.section_id} on {s.days}"}
        for s in assigned_sections if s.days != pref
    ]

@preference_checker("accepts_evening")
def check_accepts_evening(faculty, assigned_sections):
    if _is_yes(faculty.preferences.get("accepts_evening", "Yes")):
        return []
    return [
        {"faculty": faculty.name,
         "preference": "Does not accept evening classes",
         "issue": f"Assigned evening section {s.section_id}"}
        for s in assigned_sections if s.evening
    ]


# =====================================================================
# SHARED HELPERS
# =====================================================================

def load_current_plan(path: str = CURRENT_PLAN_PATH):
    with open(path) as f:
        return json.load(f)

def get_lookup_tables():
    faculty_objs = load_faculty()
    section_objs = load_sections()
    faculty_by_id = {f.faculty_id: f.model_dump() | {"required_load": f.required_load}
                     for f in faculty_objs}
    sections_by_id = {s.section_id: s.model_dump() | {"section_id": s.section_id}
                      for s in section_objs}
    return faculty_objs, section_objs, faculty_by_id, sections_by_id

def _is_yes_value(value) -> bool:
    return str(value).strip().lower() in ("yes", "true", "1")

def build_improvement_options(plan, faculty_by_id, sections_by_id, metrics):
    """For each violation in the plan, compute the VALID fix candidates
    deterministically (qualifications, spare capacity, evening consent).
    The LLM only narrates these; it does not invent its own."""
    options = []
    per_fac = metrics["per_faculty"]

    def spare_capacity(fid: str) -> float:
        p = per_fac[fid]
        return p["required_load"] - p["assigned_credits"]

    def accepts_evening(fid: str) -> bool:
        prefs = faculty_by_id[fid].get("preferences", {}) or {}
        return _is_yes_value(prefs.get("accepts_evening", "Yes"))

    def qualified_candidates(sec: dict, exclude_fid: str | None = None) -> list[str]:
        """Faculty who could legally take this section right now."""
        out = []
        for fid, f in faculty_by_id.items():
            if fid == exclude_fid:
                continue
            if sec["course_code"] not in f["qualified_courses"]:
                continue
            if spare_capacity(fid) < sec["credits"]:
                continue
            if sec["evening"] and not accepts_evening(fid):
                continue
            out.append(f"{f['name']} (spare capacity: {spare_capacity(fid)} credits)")
        return out

    for v in plan.get("violations", []):
        prefix = v.split(":", 1)[0].strip()

        # Section needs a (different) instructor
        if prefix in ("UNASSIGNED", "UNQUALIFIED", "EVENING CONSENT"):
            # Find the section id mentioned in the violation text
            sid = next((tok.strip("().,")
                        for tok in v.replace("(", " ").replace(")", " ").split()
                        if tok.strip("().,") in sections_by_id), None)
            if not sid:
                options.append({"violation": v,
                                "note": "Could not identify the section in this violation."})
                continue
            sec = sections_by_id[sid]
            candidates = qualified_candidates(sec)
            options.append({
                "violation": v,
                "section": sid,
                "valid_reassignment_candidates":
                    candidates if candidates else ["NONE under current rules"],
            })

        # Faculty is overloaded: which sections could move away? 
        elif prefix == "OVERLOAD":
            fid = next((i for i, f in faculty_by_id.items() if f["name"] in v), None)
            if not fid:
                options.append({"violation": v,
                                "note": "Could not identify the faculty in this violation."})
                continue
            movable = []
            for a in plan["assignments"]:
                if a["faculty_id"] != fid:
                    continue
                sec = sections_by_id.get(a["section_id"])
                if not sec:
                    continue
                takers = qualified_candidates(sec, exclude_fid=fid)
                if takers:
                    movable.append({"section": a["section_id"],
                                    "could_move_to": takers})
            options.append({
                "violation": v,
                "overloaded_faculty": faculty_by_id[fid]["name"],
                "movable_sections":
                    movable if movable else ["NONE under current rules"],
            })

        # Faculty below policy minimum: can they take an unassigned section? 
        elif prefix == "UNDERLOAD":
            fid = next((i for i, f in faculty_by_id.items() if f["name"] in v), None)
            if not fid:
                options.append({"violation": v,
                                "note": "Could not identify the faculty."})
                continue

            assigned_sids = {a["section_id"] for a in plan["assignments"]}
            unassigned = [sid for sid in sections_by_id if sid not in assigned_sids]

            takeable = []
            for sid in unassigned:
                sec = sections_by_id[sid]
                if (sec["course_code"] in faculty_by_id[fid]["qualified_courses"]
                        and spare_capacity(fid) >= sec["credits"]
                        and (not sec["evening"] or accepts_evening(fid))):
                    takeable.append(sid)

            if takeable:
                options.append({
                    "violation": v,
                    "fixable": True,
                    "unassigned_sections_this_faculty_could_take": takeable,
                })
            else:
                options.append({
                    "violation": v,
                    "fixable": False,
                    "note": ("All sections are already assigned (or none are legal "
                             "for this faculty). This underload CANNOT be fixed by "
                             "reassignment; it requires offering additional sections."),
                })

        # Other violation types: report, no computed options yet ---
        else:
            # CLIENT-CONFIG: add candidate logic for new violation types here
            options.append({"violation": v,
                            "note": "No automated fix options computed for this "
                                    "violation type."})

    return options

def resolve_plan_filename(name: str) -> str:
    if not name:
        return ""
    n = name.strip().lower()
    if n.startswith("plan "):
        n = n.split(" ", 1)[1]
    fname = f"data/processed/plan_{n}.json"
    if os.path.exists(fname):
        return fname
    direct = f"data/processed/{name}.json"
    return direct if os.path.exists(direct) else ""

def find_course_sections_by_name_or_code(section_objs, query: str):
    q = (query or "").lower().strip()
    if not q:
        return []
    exact_code = [s for s in section_objs if q == s.course_code.lower()]
    if exact_code:
        return exact_code
    exact_title = [s for s in section_objs if q == s.title.lower()]
    if exact_title:
        return exact_title
    THRESHOLD = 0.7  # CLIENT-CONFIG: fuzzy match sensitivity
    return [s for s in section_objs
            if difflib.SequenceMatcher(None, q, s.title.lower()).ratio() >= THRESHOLD
            or q in s.title.lower() or s.title.lower() in q]

# =====================================================================
# HANDLERS — each returns a result dict (no printing)
# =====================================================================

def handle_show_rooms(params: dict) -> dict:
    """Show all rooms with basic details (from rooms.xlsx)."""
    try:
        rooms = load_rooms()
    except FileNotFoundError:
        return {"type": "error",
                "content": "No rooms.xlsx found in data/raw/. "
                           "Add it and rerun the constraints/plan generation."}

    rows = []
    for r in rooms:
        avail = r.availability or {}
        if avail:
            parts = []
            for day, windows in avail.items():
                for ws, we in windows:
                    parts.append(f"{day} {ws}-{we}")
            avail_str = "; ".join(parts)
        else:
            avail_str = "Always open"

        rows.append({
            "RoomID": r.room_id,
            "Building": r.building,
            "Capacity": r.capacity,
            "Available": r.available,
            "RoomType": getattr(r, "room_type", "Lecture"),
            "Availability": avail_str,
        })

    return {"type": "table", "title": "Rooms", "rows": rows}


def handle_show_courses_and_rooms(params: dict) -> dict:
    """Show all offered courses with their assigned faculty and room."""
    try:
        plan = load_current_plan()
    except FileNotFoundError:
        return {"type": "error",
                "content": "No current plan found. Generate a plan first."}

    faculty_objs = load_faculty()
    section_objs = load_sections()
    faculty_by_id = {f.faculty_id: f.name for f in faculty_objs}
    sections_by_id = {s.section_id: s for s in section_objs}

    rows = []
    for a in plan["assignments"]:
        sid = a["section_id"]
        fid = a["faculty_id"]
        sec = sections_by_id.get(sid)
        if not sec:
            continue
        rows.append({
            "SectionID": sid,
            "CourseCode": sec.course_code,
            "Title": sec.title,
            "Credits": sec.credits,
            "Days": sec.days,
            "StartTime": sec.start_time,
            "EndTime": sec.end_time,
            "Faculty": faculty_by_id.get(fid, fid),
            "Room": a.get("room", ""),
        })

    if not rows:
        return {"type": "text", "title": "Courses and rooms",
                "content": "There are no assignments in the current plan."}

    # Optional: sort for readability
    rows.sort(key=lambda r: (r["CourseCode"], r["SectionID"]))
    return {"type": "table", "title": "Teaching Load Assignment Report", "rows": rows}


def handle_show_courses_offered(params: dict) -> dict:
    """Show all offered course sections from courses.xlsx."""
    try:
        section_objs = load_sections()
    except FileNotFoundError:
        return {"type": "error",
                "content": "No courses.xlsx found in data/raw/. Add it and rerun."}

    if not section_objs:
        return {"type": "text", "title": "Courses offered",
                "content": "No course sections found."}

    rows = []
    for s in section_objs:
        rows.append({
            "SectionID": s.section_id,
            "CourseCode": s.course_code,
            "Title": s.title,
            "Credits": s.credits,
            "Days": s.days,
            "StartTime": s.start_time,
            "EndTime": s.end_time,
            "Evening": s.evening,
        })

    # Sort for readability
    rows.sort(key=lambda r: (r["CourseCode"], r["SectionID"]))
    return {"type": "table", "title": "Courses offered", "rows": rows}


def handle_list_considered_policies(params: dict) -> dict:
    try:
        with open(CONSTRAINTS_PATH) as f:
            constraints = json.load(f)
    except FileNotFoundError:
        return {"type": "error",
                "content": "No constraints.json found. Run the constraints agent first."}

    lines = []
    for i, (key, value) in enumerate(constraints.items(), start=1):
        template = CONSTRAINT_DESCRIPTIONS.get(key)
        if template:
            lines.append(f"{i}. {template.format(value=value)}")
        else:
            lines.append(f"{i}. {key} = {value} (no description on file)")
    return {"type": "text",
            "title": "Policies and constraints used during assignment generation",
            "content": "\n".join(lines)}


def handle_policy_violations(params: dict) -> dict:
    try:
        plan = load_current_plan()
    except FileNotFoundError:
        return {"type": "error",
                "content": "No current plan found. Generate a plan first."}

    violations = plan.get("violations", [])
    if not violations:
        return {"type": "text", "title": "Policy Violations",
                "content": "The current plan has no recorded violations."}

    grouped: dict[str, list[str]] = {}
    for v in violations:
        prefix = v.split(":", 1)[0].strip()
        policy_name = VIOLATION_POLICY_MAP.get(prefix, "Other / Unmapped Policy")
        grouped.setdefault(policy_name, []).append(v)

    original_query = (params.get("original_query") or "").lower()
    matched = [name for name in grouped
               if any(w in original_query
                      for w in name.lower().replace("policy", "").split()
                      if len(w) > 3)]

    shown = matched if matched else list(grouped.keys())
    rows = [{"policy": name, "violation": v}
            for name in shown for v in grouped[name]]
    title = (f"Violations related to: {', '.join(matched)}"
             if matched else "Violations grouped by related policy")
    return {"type": "table", "title": title, "rows": rows}


def handle_misassigned_or_unqualified(params: dict) -> dict:
    try:
        plan = load_current_plan()
    except FileNotFoundError:
        return {"type": "error",
                "content": "No current plan found. Generate a plan first."}

    unqualified = [v for v in plan.get("violations", []) if v.startswith("UNQUALIFIED")]
    if not unqualified:
        return {"type": "text", "title": "Unqualified Assignments",
                "content": "No courses with unqualified faculty assignments in the current plan."}
    return {"type": "table", "title": "Courses with unqualified faculty assignments",
            "rows": [{"violation": v} for v in unqualified]}


def handle_who_can_teach_course(params: dict) -> dict:
    course_name = params.get("course_name") or params.get("course_code")
    if not course_name:
        return {"type": "error",
                "content": "Which course? Please specify a course name or code."}

    faculty = load_faculty()
    section_objs = load_sections()

    # Resolve names like "Machine Learning" to a course code via sections
    matched_sections = find_course_sections_by_name_or_code(section_objs, course_name)
    codes = ({s.course_code for s in matched_sections}
             if matched_sections else {course_name.strip().upper()})

    qualified = [f for f in faculty
                 if any(code in f.qualified_courses for code in codes)]
    if not qualified:
        return {"type": "text", "title": "Qualified Faculty",
                "content": f"No faculty marked as qualified for {', '.join(sorted(codes))}."}
    return {"type": "table",
            "title": f"Faculty qualified to teach {', '.join(sorted(codes))}",
            "rows": [{"id": f.faculty_id, "name": f.name, "rank": f.rank}
                     for f in qualified]}


def handle_show_faculty(params: dict) -> dict:
    faculty = load_faculty()
    return {"type": "table", "title": "Faculty and required loads",
            "rows": [{"id": f.faculty_id, "name": f.name, "rank": f.rank,
                      "required_load": f.required_load} for f in faculty]}


def handle_overloaded_faculty(params: dict) -> dict:
    try:
        plan = load_current_plan()
    except FileNotFoundError:
        return {"type": "error",
                "content": "No current plan found. Generate a plan first."}

    _, _, faculty_by_id, sections_by_id = get_lookup_tables()
    metrics = compute_metrics(plan["assignments"], faculty_by_id, sections_by_id)
    overloaded = [p for p in metrics["per_faculty"].values() if p["load_gap"] > 0]

    if not overloaded:
        return {"type": "text", "title": "Overloaded Faculty",
                "content": "No faculty exceed their recommended teaching load in the current plan."}
    return {"type": "table", "title": "Faculty exceeding recommended load",
            "rows": [{"name": p["name"], "rank": p["rank"],
                      "assigned": p["assigned_credits"],
                      "required": p["required_load"],
                      "excess": p["load_gap"]} for p in overloaded]}


def handle_show_fairness_issues(params: dict) -> dict:
    try:
        plan = load_current_plan()
    except FileNotFoundError:
        return {"type": "error",
                "content": "No current plan found. Generate a plan first."}

    _, _, faculty_by_id, sections_by_id = get_lookup_tables()
    metrics = compute_metrics(plan["assignments"], faculty_by_id, sections_by_id)
    s = metrics["summary"]

    summary_text = (
        f"Faculty at exact load: {s['faculty_at_exact_load']}\n"
        f"Faculty below target load:  {s['faculty_underloaded']}\n"
        f"Overloaded faculty:   {s['faculty_overloaded']}\n"
        f"Load gap std dev:     {s['load_gap_std_dev']}\n"
        f"Evening sections std dev: {s['evening_sections_std_dev']}"
    )
    rows = [{"name": p["name"], "rank": p["rank"],
             "assigned": p["assigned_credits"], "required": p["required_load"],
             "gap": p["load_gap"]}
            for p in metrics["per_faculty"].values() if abs(p["load_gap"]) > 1]
    return {"type": "table", "title": "Fairness summary",
            "content": summary_text, "rows": rows}


def handle_unmet_preferences(params: dict) -> dict:
    try:
        plan = load_current_plan()
    except FileNotFoundError:
        return {"type": "error",
                "content": "No current plan found. Generate a plan first."}

    faculty_objs = load_faculty()
    section_by_id = {s.section_id: s for s in load_sections()}

    unmet = []
    for f in faculty_objs:
        assigned = [section_by_id[a["section_id"]]
                    for a in plan["assignments"]
                    if a["faculty_id"] == f.faculty_id
                    and a["section_id"] in section_by_id]
        for pref_key, checker in PREFERENCE_CHECKERS.items():
            if pref_key in f.preferences:
                unmet.extend(checker(f, assigned))

    if not unmet:
        return {"type": "text", "title": "Unmet Preferences",
                "content": "All recorded faculty preferences are satisfied in the current plan."}
    return {"type": "table", "title": "Unmet faculty preferences", "rows": unmet}


def handle_explain_assignment(params: dict) -> dict:
    faculty_name = (params.get("faculty_name") or params.get("professor_name")
                    or params.get("instructor_name"))
    course_name = (params.get("course_name") or params.get("course_code")
                   or params.get("assignment_name"))
    if not faculty_name or not course_name:
        return {"type": "error",
                "content": "Please specify both a faculty name and a course "
                           "(e.g., 'Prof. Santos' and 'Database Systems')."}

    try:
        plan = load_current_plan()
    except FileNotFoundError:
        return {"type": "error",
                "content": "No current plan found. Generate a plan first."}

    faculty_objs = load_faculty()
    section_objs = load_sections()

    fac_match = [f for f in faculty_objs if faculty_name.lower() in f.name.lower()]
    if not fac_match:
        return {"type": "error", "content": f"No faculty found matching '{faculty_name}'."}
    faculty = fac_match[0]

    course_sections = find_course_sections_by_name_or_code(section_objs, course_name)
    if not course_sections:
        available = "\n".join(f" - {s.course_code}: {s.title}" for s in section_objs)
        return {"type": "error",
                "content": f"No course found matching '{course_name}'. "
                           f"Available titles include:\n{available}"}

    course_code_set = {s.course_code for s in course_sections}
    section_by_id = {s.section_id: s for s in section_objs}
    faculty_assignments = [a for a in plan["assignments"]
                           if a["faculty_id"] == faculty.faculty_id]
    assigned_sections = [a for a in faculty_assignments
                         if a["section_id"] in {s.section_id for s in course_sections}]

    assigned_credits = sum(section_by_id[a["section_id"]].credits
                           for a in faculty_assignments
                           if a["section_id"] in section_by_id)

    if assigned_sections:
        related_assignments_text = "\n".join(
            f"- {sec.section_id}: {sec.title}, {sec.days} "
            f"{sec.start_time}-{sec.end_time}, {sec.credits} credits"
            for a in assigned_sections
            if (sec := section_by_id.get(a["section_id"])))
    else:
        related_assignments_text = (f"- {faculty.name} is NOT assigned to any section "
                                    "of this course in the current plan.")

    other_lines = [
        f"- {sec.section_id}: {sec.title} ({sec.course_code}), {sec.days} "
        f"{sec.start_time}-{sec.end_time}, {sec.credits} credits"
        for a in faculty_assignments
        if (sec := section_by_id.get(a["section_id"]))
        and sec.course_code not in course_code_set]
    other_sections_text = "\n".join(other_lines) if other_lines else "None."

    try:
        with open(CONSTRAINTS_PATH) as f:
            policy_summary = json.dumps(json.load(f), indent=2)
    except FileNotFoundError:
        policy_summary = "(No structured policy constraints file found.)"

    user_prompt = EXPLAIN_ASSIGNMENT_USER_TEMPLATE.format(
        faculty_name=faculty.name, faculty_id=faculty.faculty_id,
        rank=faculty.rank, course_name=course_name,
        qualified_courses=", ".join(faculty.qualified_courses),
        required_load=faculty.required_load,
        assigned_credits=assigned_credits,
        preferences=json.dumps(faculty.preferences),
        related_assignments_text=related_assignments_text,
        other_sections_text=other_sections_text,
        policy_summary=policy_summary,
    )
    explanation = ask_llm(EXPLAIN_ASSIGNMENT_SYSTEM_PROMPT, user_prompt, json_mode=False)
    return {"type": "text",
            "title": f"Why {faculty.name} and '{course_name}'",
            "content": explanation}


def handle_compare_plans(params: dict) -> dict:
    plan_a_name = params.get("plan_a") or params.get("plan1") or "A"
    plan_b_name = params.get("plan_b") or params.get("plan2") or "B"
    path_a = resolve_plan_filename(plan_a_name)
    path_b = resolve_plan_filename(plan_b_name)

    if not path_a:
        return {"type": "error",
                "content": f"Could not find file for Plan A ('{plan_a_name}'). "
                           "Expected something like data/processed/plan_a.json"}
    if not path_b:
        return {"type": "error",
                "content": f"Could not find file for Plan B ('{plan_b_name}'). "
                           "Expected something like data/processed/plan_b.json"}

    with open(path_a) as f:
        plan_a = json.load(f)
    with open(path_b) as f:
        plan_b = json.load(f)

    _, _, faculty_by_id, sections_by_id = get_lookup_tables()
    ma = compute_metrics(plan_a["assignments"], faculty_by_id, sections_by_id)
    mb = compute_metrics(plan_b["assignments"], faculty_by_id, sections_by_id)
    sa, sb = ma["summary"], mb["summary"]

    content = (
        f"Plan A: load gap std dev = {sa['load_gap_std_dev']}, "
        f"overloaded = {sa['faculty_overloaded']}, underloaded = {sa['faculty_underloaded']}\n"
        f"Plan B: load gap std dev = {sb['load_gap_std_dev']}, "
        f"overloaded = {sb['faculty_overloaded']}, underloaded = {sb['faculty_underloaded']}"
    )
    rows = []
    for fid, p_a in ma["per_faculty"].items():
        p_b = mb["per_faculty"].get(fid)
        if not p_b:
            continue
        diff = p_b["assigned_credits"] - p_a["assigned_credits"]
        if abs(diff) >= 1:
            rows.append({"name": p_a["name"],
                         "plan_a_credits": p_a["assigned_credits"],
                         "plan_b_credits": p_b["assigned_credits"],
                         "difference": diff})
    return {"type": "table",
            "title": f"Comparison: Plan '{plan_a_name}' vs Plan '{plan_b_name}'",
            "content": content, "rows": rows}


def handle_suggest_compliance_improvements(params: dict) -> dict:
    try:
        plan = load_current_plan()
    except FileNotFoundError:
        return {"type": "error",
                "content": "No current plan found. Generate a plan first."}

    violations = plan.get("violations", [])
    if not violations:
        return {"type": "text",
                "title": "Compliance improvements",
                "content": "The current plan has no recorded violations; "
                           "no improvements needed."}

    _, _, faculty_by_id, sections_by_id = get_lookup_tables()
    metrics = compute_metrics(plan["assignments"], faculty_by_id, sections_by_id)

    # CODE decides what is legally possible
    options = build_improvement_options(plan, faculty_by_id, sections_by_id, metrics)

    # Split: LLM narrates only violations with real options;
    # unfixable ones get a deterministic statement (no hallucination possible).
    fixable = [o for o in options if o.get("fixable", True) and not o.get("note")]
    unfixable = [o for o in options if o not in fixable]

    parts = []
    if fixable:
        facts = {"violations_with_valid_options": fixable,
                 "summary_metrics": metrics["summary"]}
        parts.append(ask_llm(SUGGEST_IMPROVEMENTS_SYSTEM_PROMPT,
                             json.dumps(facts, indent=2), json_mode=False))
    if unfixable:
        lines = ["**Not fixable by reassignment under current policies:**"]
        for o in unfixable:
            lines.append(f"- {o['violation']}")
        lines.append("\nThese require structural changes (e.g., offering more "
                     "sections), which are outside this system's authority.")
        parts.append("\n".join(lines))

    content = "\n\n".join(parts) if parts else "No violations to address."
    return {"type": "text",
            "title": "Suggested compliance improvements "
                     "(reassignments only, no policy changes)",
            "content": content}


def handle_recalculate_plan(params: dict) -> dict:
    run_assignment_agent()  # same constraints, same data; agent prints its own progress
    return {"type": "text", "title": "Recalculation complete",
            "content": "A new draft plan was generated under the existing policies. "
                       "Ask for violations or an admin report to review it."}


def handle_what_if_change(params: dict) -> dict:
    return {"type": "text", "title": "What-if changes not supported",
            "content": "Policies and loads come only from the official Excel/PDF files. "
                       "To change them, update the source documents and rerun the "
                       "constraints agent."}


def handle_build_constraints(params: dict) -> dict:
    run_constraints_agent()
    return {"type": "text", "title": "Constraints rebuilt",
            "content": "Constraints and faculty profiles were rebuilt from the official files."}


def handle_generate_plan(params: dict) -> dict:
    run_assignment_agent()
    return {"type": "text", "title": "Plan generated",
            "content": "A new draft plan was generated (plan_draft_v1.json)."}


def handle_admin_report(params: dict) -> dict:
    result = run_governance_agent()

    if not result:
        # Fallback if run_governance_agent returns None
        return {"type": "file", "title": "Administrative report generated",
                "path": "data/processed/final_plan.xlsx",
                "content": "Report saved to data/processed/governance_report.md and "
                           "Excel plan to data/processed/final_plan.xlsx."}

    content = (
        result.get("report_markdown", "").strip()
        + "\n\n_Excel written to `data/processed/final_plan.xlsx`_"
    )

    return {
        "type": "file",
        "title": "Teaching Assignment Review Report & Excel",
        "path": "data/processed/final_plan.xlsx",
        "content": content,
    }

def handle_unknown(params: dict) -> dict:
    query = params.get("original_query", "")

    return {
        "type": "text",
        "title": "Please clarify your request",
        "content": (
            f"I could not confidently determine what you meant by: "
            f"“{query}”\n\n"
            "You can ask me to:\n"
            "- show the teaching-load assignment or current schedule;\n"
            "- show faculty, courses, rooms, or policy;\n"
            "- identify overloads, underloads, violations, or unmet preferences;\n"
            "- explain an assignment;\n"
            "- suggest compliance improvements;\n"
            "- adjust a faculty member's load; or\n"
            "- generate the administrative report."
        ),
    }

def handle_negotiate_plan(params: dict) -> dict:
    outcome = propose_negotiated_plan(params.get("original_query", ""))

    if outcome["status"] == "no_directives":
        return {"type": "text", "title": "Negotiation",
                "content": "I could not extract any supported directives. "
                           "Try: 'Reduce Dr. Chen's load to 6 credits'."}
    if outcome["status"] == "no_current_plan":
        return {"type": "error",
                "content": "No current plan to negotiate against. Generate a plan first."}
    if outcome["status"] == "no_changes":
        return {"type": "text", "title": "Negotiation",
                "content": "The directive produced no changes — the current plan "
                           "already satisfies it."}

    if outcome["status"] == "already_satisfied":
        return {"type": "text", "title": "Negotiation",
                "content": f"{outcome['faculty']} is already assigned "
                           f"{outcome['assigned']} credits, which is at or below "
                           f"the requested {outcome['target']}. No change needed."}

    note = ("(The previous pending proposal was replaced.)\n\n"
            if outcome.get("replaced_previous") else "")
    return {"type": "table",
            "title": "Proposed negotiated plan (not yet applied)",
            "content": note + outcome["narrative"] +
                       "\n\n---\n**Accept this plan? (Y/N)**",
            "rows": outcome["diff"]["load_changes"]}


def handle_accept_negotiation(params: dict) -> dict:
    outcome = accept_pending_plan()
    if outcome["status"] == "nothing_pending":
        return {"type": "error", "content": "No pending negotiated plan to accept."}
    return {"type": "text", "title": "Proposal accepted",
            "content": "The negotiated plan is now the current plan. "
                       "Run the admin report to regenerate the Excel."}


def handle_reject_negotiation(params: dict) -> dict:
    outcome = reject_pending_plan()
    if outcome["status"] == "nothing_pending":
        return {"type": "error", "content": "No pending negotiated plan to reject."}
    return {"type": "text", "title": "Proposal rejected",
            "content": "The pending plan was discarded. The original plan is unchanged."}


def try_handle_pending_decision(user_input: str) -> dict | None:
    """If a negotiation is pending and input is a yes/no answer, resolve it.
    Returns a result dict, or None to fall through to normal routing."""
    if not negotiation_pending():
        return None
    answer = user_input.strip().lower()
    YES = {"y", "yes", "accept", "ok", "approve", "apply"}          # CLIENT-CONFIG
    NO  = {"n", "no", "reject", "discard", "cancel"}
    if answer in YES:
        return handle_accept_negotiation({})
    if answer in NO:
        return handle_reject_negotiation({})
    return None

def handle_underloaded_faculty(params: dict) -> dict:
    """Show faculty below the policy minimum load."""
    try:
        plan = load_current_plan()
        with open(CONSTRAINTS_PATH) as f:
            constraints = json.load(f)
    except FileNotFoundError:
        return {
            "type": "error",
            "content": "A current plan and constraints are required.",
        }

    _, _, faculty_by_id, sections_by_id = get_lookup_tables()
    metrics = compute_metrics(
        plan["assignments"],
        faculty_by_id,
        sections_by_id,
    )

    min_load = float(constraints.get("min_load_full_time", 0))
    applicable_ranks = {
        "Professor",
        "Associate",
        "Assistant",
        "Lecturer",
    }

    rows = []
    for fid, p in metrics["per_faculty"].items():
        if p["rank"] not in applicable_ranks:
            continue
        if p["assigned_credits"] < min_load:
            rows.append({
                "name": p["name"],
                "rank": p["rank"],
                "assigned": p["assigned_credits"],
                "policy_minimum": min_load,
                "shortfall": min_load - p["assigned_credits"],
            })

    if not rows:
        return {
            "type": "text",
            "title": "Faculty Below Policy Minimum",
            "content": (
                f"No applicable faculty are below the policy minimum "
                f"of {min_load:g} credits."
            ),
        }

    return {
        "type": "table",
        "title": "Faculty Below Policy Minimum",
        "rows": rows,
    }


# =====================================================================
# ROUTING
# =====================================================================

INTENT_HANDLERS = {
    "build_constraints": handle_build_constraints,
    "generate_plan": handle_generate_plan,
    "recalculate_plan": handle_recalculate_plan,
    "what_if_change": handle_what_if_change,
    "explain_assignment": handle_explain_assignment,
    "compare_plans": handle_compare_plans,
    "who_can_teach_course": handle_who_can_teach_course,
    "overloaded_faculty": handle_overloaded_faculty,
    "underloaded_faculty": handle_underloaded_faculty,
    "courses_misassigned_or_unqualified": handle_misassigned_or_unqualified,
    "unmet_preferences": handle_unmet_preferences,
    "show_fairness_issues": handle_show_fairness_issues,
    "generate_admin_report": handle_admin_report,
    "govern_plan": handle_admin_report,
    "suggest_compliance_improvements": handle_suggest_compliance_improvements,
    "list_considered_policies": handle_list_considered_policies,
    "show_policy": handle_list_considered_policies,
    "policy_violations": handle_policy_violations,
    "show_faculty": handle_show_faculty,
    "negotiate_plan": handle_negotiate_plan,
    "accept_negotiation": handle_accept_negotiation,
    "reject_negotiation": handle_reject_negotiation,
    "show_rooms": handle_show_rooms,
    "show_courses_and_rooms": handle_show_courses_and_rooms,
    "show_courses_offered": handle_show_courses_offered,
}

def handle_intent(intent: str, params: dict) -> dict:
    """Route a classified or direct intent to the appropriate handler."""
    params = params if isinstance(params, dict) else {}

    original_query = str(params.get("original_query") or "").lower().strip()
    intent_norm = str(intent or "unknown").lower().strip()

    assignment_phrases = (
    "show teaching load assignment",
    "show teaching-load assignment",
    "show teaching assignment",
    "show assignment table",
    "show current assignments",
    "show course assignments",
    "show courses and rooms",
    )
    if (
        intent_norm == "show_courses_and_rooms"
        or any(phrase in original_query for phrase in assignment_phrases)
        ):
        return handle_show_courses_and_rooms(params)

    # 1. Pending negotiation decisions have highest priority.
    if negotiation_pending():
        if original_query in {"y", "yes", "accept", "ok", "approve", "apply"}:
            return handle_accept_negotiation(params)
        if original_query in {"n", "no", "reject", "discard", "cancel"}:
            return handle_reject_negotiation(params)

    # 2. Load negotiation requests.
    load_change_words = {
        "reduce",
        "increase",
        "decrease",
        "lighter load",
        "adjust load",
        "change load",
        "negotiate",
    }
    if intent_norm == "negotiate_plan" or (
        "load" in original_query
        and any(word in original_query for word in load_change_words)
    ):
        return handle_negotiate_plan(params)

    # 3. Compliance-improvement requests before broad policy matching.
    if intent_norm == "suggest_compliance_improvements" or (
        any(word in original_query for word in ("suggest", "improve", "fix"))
        and any(word in original_query for word in (
            "compliance",
            "violation",
            "assignment",
            "balance",
        ))
    ):
        return handle_suggest_compliance_improvements(params)

    # 4. Plan generation/recalculation before policy matching.
    if intent_norm in {"build_constraints", "generate_plan", "recalculate_plan"}:
        return INTENT_HANDLERS[intent_norm](params)

    # 5. Overload and policy-underload questions.
    if intent_norm == "overloaded_faculty" or (
        "load" in original_query
        and any(word in original_query for word in (
            "overload",
            "exceed",
            "above",
            "over their",
        ))
    ):
        return handle_overloaded_faculty(params)

    if intent_norm == "underloaded_faculty" or (
        any(word in original_query for word in (
            "underload",
            "below minimum",
            "minimum load",
        ))
        and "load" in original_query
    ):
        return handle_underloaded_faculty(params)

    # 6. Policy violations.
    if intent_norm == "policy_violations" or (
        any(word in original_query for word in (
            "violation",
            "violations",
            "violat",
            "breaking policy",
            "broken policy",
            "non-compliance",
            "noncompliance",
        ))
    ):
        return handle_policy_violations(params)

    # 7. Unmet preferences.
    if intent_norm == "unmet_preferences" or "preference" in original_query:
        return handle_unmet_preferences(params)

    # 8. Show/list policy.
    if intent_norm in {"show_policy", "list_considered_policies"} or (
        any(word in original_query for word in ("policy", "policies", "constraints"))
        and any(word in original_query for word in (
            "show",
            "list",
            "considered",
            "used",
            "what",
        ))
    ):
        return handle_list_considered_policies(params)

    # 9. Exact handler dispatch.
    handler = INTENT_HANDLERS.get(intent_norm)
    if handler:
        return handler(params)

    return handle_unknown(params)


# =====================================================================
# INTENT CLASSIFICATION
# =====================================================================

def normalize_query(message: str) -> str:
    """Lowercase a query and remove unnecessary punctuation/spacing."""
    message = str(message or "").lower()
    message = re.sub(r"[^\w\s-]", " ", message)
    return " ".join(message.split())


def contains_any(query: str, terms) -> bool:
    return any(term in query for term in terms)


def infer_intent_deterministically(user_message: str) -> str | None:
    """
    Recognize common requests using concepts rather than exact sentences.

    Returns an intent string or None when the query should go to the LLM.
    """
    query = normalize_query(user_message)
    words = set(query.split())

    view_words = {
        "show", "display", "view", "list", "see", "give",
        "present", "provide", "print",
    }

    # -----------------------------------------------------------
    # Negotiation: check before general assignment/load queries.
    # -----------------------------------------------------------
    change_terms = (
        "reduce", "increase", "decrease", "adjust",
        "change", "lighter", "raise", "lower", "negotiate",
    )
    load_terms = (
        "load", "loads", "credit", "credits", "unit", "units",
    )

    if contains_any(query, change_terms) and contains_any(query, load_terms):
        return "negotiate_plan"

    # -----------------------------------------------------------
    # Compliance improvements: check before general policy display.
    # -----------------------------------------------------------
    improvement_terms = (
        "suggest", "improve", "improvement", "recommend",
        "fix", "correct", "resolve",
    )
    compliance_terms = (
        "compliance", "policy", "violation",
        "violations", "assignment", "balance",
    )

    if (
        contains_any(query, improvement_terms)
        and contains_any(query, compliance_terms)
    ):
        return "suggest_compliance_improvements"

    # -----------------------------------------------------------
    # Underload / overload
    # -----------------------------------------------------------
    if contains_any(query, (
        "underload",
        "underloaded",
        "below minimum",
        "below the minimum",
        "minimum load violation",
        "less than minimum",
        "fewer than minimum",
    )):
        return "underloaded_faculty"

    if contains_any(query, (
        "overload",
        "overloaded",
        "above required load",
        "exceeding the load",
        "exceeds the load",
        "too many credits",
    )):
        return "overloaded_faculty"

    # -----------------------------------------------------------
    # Policy violations: check before general policy display.
    # -----------------------------------------------------------
    if contains_any(query, (
        "policy violation",
        "policy violations",
        "show violations",
        "list violations",
        "breaking policy",
        "violating policy",
        "noncompliance",
        "non-compliance",
    )):
        return "policy_violations"

    # -----------------------------------------------------------
    # Teaching-load assignment / current schedule
    # -----------------------------------------------------------
    assignment_terms = (
        "assignment", "assignments", "load plan",
        "teaching plan", "teaching schedule",
        "course allocation", "faculty allocation",
        "who teaches", "courses and rooms",
    )
    schedule_terms = (
        "current schedule", "class schedule", "assigned courses",
    )

    if (
        (words & view_words)
        and (
            contains_any(query, assignment_terms)
            or contains_any(query, schedule_terms)
        )
    ):
        return "show_courses_and_rooms"

    # Also recognize short noun-style requests.
    if query in {
        "teaching load assignment",
        "teaching assignments",
        "current assignments",
        "assignment table",
        "load plan",
        "current schedule",
    }:
        return "show_courses_and_rooms"

    # -----------------------------------------------------------
    # Basic data views
    # -----------------------------------------------------------
    if (words & view_words) and contains_any(query, (
        "room", "rooms", "classroom", "classrooms", "laboratory", "laboratories",
    )):
        return "show_rooms"

    if (words & view_words) and contains_any(query, (
        "courses offered", "course offerings",
        "offered courses", "offered sections",
    )):
        return "show_courses_offered"

    if (words & view_words) and contains_any(query, (
        "faculty", "faculty members", "instructors", "professors",
    )):
        return "show_faculty"

    # -----------------------------------------------------------
    # Preferences and fairness
    # -----------------------------------------------------------
    if contains_any(query, (
        "unmet preference", "unmet preferences",
        "preferences not met", "preferences not accommodated",
        "preference issues",
    )):
        return "unmet_preferences"

    if contains_any(query, (
        "fairness", "fair", "balanced loads",
        "load balance", "unequal loads", "inequitable",
    )):
        return "show_fairness_issues"

    # -----------------------------------------------------------
    # Reports
    # -----------------------------------------------------------
    if (
        contains_any(query, ("report", "excel", "export"))
        and contains_any(query, (
            "generate", "create", "produce", "print",
            "download", "administrative", "teaching load",
        ))
    ):
        return "generate_admin_report"

    # -----------------------------------------------------------
    # Plan generation
    # -----------------------------------------------------------
    if (
        contains_any(query, ("generate", "create", "build", "make"))
        and contains_any(query, (
            "plan", "assignment plan", "teaching plan", "schedule",
        ))
    ):
        return "generate_plan"

    if (
        contains_any(query, ("recalculate", "regenerate", "rerun", "recompute"))
        and contains_any(query, ("plan", "assignment", "schedule"))
    ):
        return "recalculate_plan"

    # -----------------------------------------------------------
    # General policy display
    # -----------------------------------------------------------
    if (
        (words & view_words)
        and contains_any(query, (
            "policy", "policies", "constraint", "constraints", "rules",
        ))
    ):
        return "show_policy"

    if query in {
        "policy", "policies", "constraints",
        "show policy", "show constraints",
    }:
        return "show_policy"

    # The query is ambiguous; allow the LLM to classify it.
    return None

INTENT_ALIASES = {
    "show_teaching_load_assignment": "show_courses_and_rooms",
    "show_teaching_assignments": "show_courses_and_rooms",
    "show_assignment": "show_courses_and_rooms",
    "show_assignments": "show_courses_and_rooms",
    "show_schedule": "show_courses_and_rooms",
    "teaching_load_assignment": "show_courses_and_rooms",

    "show_policy_constraints": "show_policy",
    "list_policies": "show_policy",
    "list_constraints": "show_policy",

    "show_violations": "policy_violations",
    "show_policy_violations": "policy_violations",

    "show_underloaded_faculty": "underloaded_faculty",
    "underload": "underloaded_faculty",

    "show_overloaded_faculty": "overloaded_faculty",
    "overload": "overloaded_faculty",

    "compliance_improvements": "suggest_compliance_improvements",
    "suggest_improvements": "suggest_compliance_improvements",

    "show_courses": "show_courses_offered",
    "list_courses": "show_courses_offered",
    "list_rooms": "show_rooms",
    "list_faculty": "show_faculty",

    "admin_report": "generate_admin_report",
    "generate_report": "generate_admin_report",
}

CLASSIFIABLE_INTENTS = {
    "build_constraints",
    "generate_plan",
    "recalculate_plan",
    "what_if_change",
    "explain_assignment",
    "compare_plans",
    "who_can_teach_course",
    "overloaded_faculty",
    "underloaded_faculty",
    "courses_misassigned_or_unqualified",
    "unmet_preferences",
    "show_fairness_issues",
    "generate_admin_report",
    "suggest_compliance_improvements",
    "show_policy",
    "policy_violations",
    "show_faculty",
    "show_rooms",
    "show_courses_and_rooms",
    "show_courses_offered",
    "negotiate_plan",
    "unknown",
}


def classify_intent(user_message: str) -> tuple[str, dict]:
    """
    First recognize common requests deterministically.
    Use the LLM only for requests that remain ambiguous.
    """
    params = {"original_query": user_message}

    deterministic_intent = infer_intent_deterministically(user_message)
    if deterministic_intent:
        return deterministic_intent, params

    try:
        reply = ask_llm(
            INTENT_SYSTEM_PROMPT,
            f"""User message:
\"\"\"{user_message}\"\"\"

Classify the intent and extract relevant parameters.
Return only the required JSON object.""",
            json_mode=True,
        )

        data = json.loads(reply)

        if not isinstance(data, dict):
            return "unknown", params

        intent = str(data.get("intent", "unknown")).strip().lower()
        intent = INTENT_ALIASES.get(intent, intent)

        if intent not in CLASSIFIABLE_INTENTS:
            intent = "unknown"

        extracted_params = data.get("params", {})
        if not isinstance(extracted_params, dict):
            extracted_params = {}

        extracted_params["original_query"] = user_message
        return intent, extracted_params

    except (
        json.JSONDecodeError,
        TypeError,
        ValueError,
        RuntimeError,
    ):
        return "unknown", params
