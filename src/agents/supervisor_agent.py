import json
import difflib
import os

from src.llm.client import ask_llm
from src.agents.constraints_and_faculty_intel_agent import run_constraints_agent
from src.agents.assignment_and_negotiation_agent import run_assignment_agent
from src.agents.decision_support_and_governance_agent import run_governance_agent
from src.ingestion.excel_loader import load_faculty, load_sections
from src.validation.metrics import compute_metrics

# =====================================================================
# RESULT CONVENTION (used by CLI today, UI tomorrow)
#   {"type": "text",  "title": str, "content": str}
#   {"type": "table", "title": str, "rows": [dict, ...], "content": str (optional)}
#   {"type": "file",  "title": str, "path": str, "content": str}
#   {"type": "error", "content": str}
# =====================================================================


# =====================================================================
# PROMPTS
# =====================================================================

INTENT_SYSTEM_PROMPT = """You are a router for a teaching-load assistant system.
Given a user's message, classify it into ONE intent and, when possible, also extract parameters.

Allowed intents and their meanings:

- "generate_plan": create or regenerate a teaching assignment plan for a given term/year.
- "recalculate_plan": regenerate a plan under the EXISTING constraints.
- "what_if_change": simulate a hypothetical change to constraints or faculty status.
- "explain_assignment": explain why a specific assignment was (or was not) made.
- "compare_plans": compare two named plans (e.g., Plan A vs Plan B).
- "who_can_teach_course": list faculty qualified to teach a named course.
- "overloaded_faculty": show faculty exceeding their required load.
- "courses_misassigned_or_unqualified": find courses where assigned faculty are unqualified.
- "unmet_preferences": identify faculty preferences that were not satisfied.
- "show_fairness_issues": describe fairness problems in current plan.
- "generate_admin_report": generate a high-level administrative report.
- "suggest_compliance_improvements": suggest changes to improve policy compliance.
- "list_considered_policies": list which policies/constraints were used in plan generation.
- "show_faculty": list all faculty and their loads.
- "build_constraints": rebuild constraints from the official Excel/PDF files.
- "unknown": does not match any of the above.

Return a JSON object with at least:
{
  "intent": "<one of the above>",
  "params": { ... }
}

For example:
- For "generate_plan", params might include {"year": "2027-2028"}.
- For "compare_plans", params might include {"plan_a": "Plan A", "plan_b": "Plan B"}.
- For "who_can_teach_course", params might include {"course_name": "Artificial Intelligence"}.
- For "explain_assignment", params might include {"faculty_name": "Dr. Adams", "course_name": "Intro to Programming"}.
- For "unmet_preferences", params might include {} for
  "Which faculty preferences could not be accommodated?".
- "what_if_change" should ONLY be used for explicit hypothetical changes to constraints
  or faculty status.
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
    "TOO MANY PREPS": "Course Preparations Policy",
    "TOO MANY EVENINGS": "Evening Classes Policy",
    "TIME CONFLICT": "Scheduling / Time Conflict Policy",
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

        # --- Section needs a (different) instructor ---
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

        # --- Faculty is overloaded: which sections could move away? ---
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

        # --- Other violation types: report, no computed options yet ---
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
# INTENT CLASSIFICATION
# =====================================================================

def classify_intent(user_message: str) -> tuple[str, dict]:
    reply = ask_llm(
        INTENT_SYSTEM_PROMPT,
        f'User message: """{user_message}"""\nClassify intent and extract parameters.',
        json_mode=True,
    )
    try:
        data = json.loads(reply)
        intent = data.get("intent", "unknown")
        params = data.get("params", {}) or {}
        params.setdefault("original_query", user_message)
        return intent, params
    except json.JSONDecodeError:
        return "unknown", {"original_query": user_message}


# =====================================================================
# HANDLERS — each returns a result dict (no printing)
# =====================================================================

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
        f"Underloaded faculty:  {s['faculty_underloaded']}\n"
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

    # LLM only narrates the pre-computed options
    facts = {
        "violations_with_valid_options": options,
        "summary_metrics": metrics["summary"],
    }
    suggestions = ask_llm(SUGGEST_IMPROVEMENTS_SYSTEM_PROMPT,
                          json.dumps(facts, indent=2), json_mode=False)

    return {"type": "text",
            "title": "Suggested compliance improvements "
                     "(reassignments only, no policy changes)",
            "content": suggestions}


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
    run_governance_agent()
    return {"type": "file", "title": "Administrative report generated",
            "path": "data/processed/final_plan.xlsx",
            "content": "Report saved to data/processed/governance_report.md and "
                       "Excel plan to data/processed/final_plan.xlsx."}


def handle_unknown(params: dict) -> dict:
    return {"type": "text", "title": "I didn't understand that request",
            "content": ("Try something like:\n"
                        " - 'Rebuild constraints from the Excel and policy PDF'\n"
                        " - 'Generate a new assignment plan'\n"
                        " - 'Recalculate the plan under the existing policies'\n"
                        " - 'Generate an administrative report'\n"
                        " - 'Show all faculty members exceeding their recommended load'\n"
                        " - 'Which faculty preferences could not be accommodated?'\n"
                        " - 'Which faculty can teach Artificial Intelligence?'\n"
                        "Note: to change policies, update the official files and "
                        "rerun constraints.")}


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
    "courses_misassigned_or_unqualified": handle_misassigned_or_unqualified,
    "unmet_preferences": handle_unmet_preferences,
    "show_fairness_issues": handle_show_fairness_issues,
    "generate_admin_report": handle_admin_report,
    "govern_plan": handle_admin_report,
    "suggest_compliance_improvements": handle_suggest_compliance_improvements,
    "list_considered_policies": handle_list_considered_policies,
    "show_faculty": handle_show_faculty,
}

def handle_intent(intent: str, params: dict) -> dict:
    """Route to the right handler. Returns a result dict."""
    original_query = (params.get("original_query") or "").lower()
    intent_norm = (intent or "").lower()

    # --- Keyword safety nets (checked before exact intent match) ---

    # Overload questions
    if any(w in original_query for w in ["exceed", "overload", "over their", "above their"]) \
       and "load" in original_query:
        return handle_overloaded_faculty(params)

    # Policy questions
    if "policy" in intent_norm or "policies" in intent_norm or \
       "policy" in original_query or "policies" in original_query:
        if any(w in original_query for w in
               ["violat", "breaking", "broken", "not followed",
                "non-compliance", "noncompliance"]):
            return handle_policy_violations(params)
        return handle_list_considered_policies(params)

    # Preference questions
    if "preference" in intent_norm or "preference" in original_query:
        return handle_unmet_preferences(params)

    # Improvement suggestions
    if ("suggest" in original_query or "improve" in original_query) and \
       ("complian" in original_query or "balance" in original_query
        or "assignment" in original_query):
        return handle_suggest_compliance_improvements(params)

    # --- Exact intent match ---
    handler = INTENT_HANDLERS.get(intent_norm)
    if handler:
        return handler(params)
    return handle_unknown(params)


# =====================================================================
# CLI RENDERING — the only place that prints
# (A future Streamlit UI will render the same dicts its own way.)
# =====================================================================

def render_result(result: dict):
    rtype = result.get("type", "text")

    if rtype == "error":
        print(f"\n⚠️  {result.get('content', 'Unknown error')}\n")
        return

    title = result.get("title")
    if title:
        print(f"\n=== {title} ===")

    content = result.get("content")
    if content:
        print(content)

    if rtype == "table":
        rows = result.get("rows", [])
        if rows:
            headers = list(rows[0].keys())
            widths = {h: max(len(h), max(len(str(r.get(h, ""))) for r in rows))
                      for h in headers}
            print("  " + "  ".join(h.ljust(widths[h]) for h in headers))
            print("  " + "  ".join("-" * widths[h] for h in headers))
            for r in rows:
                print("  " + "  ".join(str(r.get(h, "")).ljust(widths[h])
                                       for h in headers))

    if rtype == "file":
        print(f"File: {result.get('path')}")
    print()


# =====================================================================
# CHAT LOOP
# =====================================================================

def supervisor_chat_loop():
    print("=== Teaching Load Supervisor ===")
    print("Type 'quit' or 'exit' to stop.\n")

    while True:
        try:
            user_input = input("Chair> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting supervisor.")
            break
        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit"}:
            print("Goodbye.")
            break

        intent, params = classify_intent(user_input)
        print(f"[Supervisor] Detected intent: {intent}")

        result = handle_intent(intent, params)
        render_result(result)


if __name__ == "__main__":
    supervisor_chat_loop()
