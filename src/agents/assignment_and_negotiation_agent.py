import json
import os
import shutil
from src.ingestion.excel_loader import load_faculty, load_sections, load_rooms
from src.llm.client import ask_llm
from src.validation.validators import validate_plan
from src.solvers.ortools_solver import solve_assignments_with_ortools
from src.solvers.room_solver import solve_room_assignments
from src.validation.metrics import compute_metrics

CURRENT_PLAN_PATH = "data/processed/plan_draft_v1.json"           # CLIENT-CONFIG
PENDING_PLAN_PATH = "data/processed/plan_negotiation_pending.json"
NEGOTIATION_CONTEXT_PATH = "data/processed/negotiation_context.json"


def extract_assignments(reply: str) -> list[dict] | None:
    """Pull the assignment list out of the LLM reply, tolerating
    different JSON shapes. Returns None if nothing usable is found."""
    try:
        data = json.loads(reply)
    except json.JSONDecodeError:
        return None

    # Case 1: it's already a bare list of assignments
    if isinstance(data, list):
        candidate = data
    # Case 2: it's a dict — look for a list under common key names
    elif isinstance(data, dict):
        candidate = None
        for key in ("assignments", "plan", "schedule", "result"):
            if isinstance(data.get(key), list):
                candidate = data[key]
                break
            # Case 3: nested one level deeper, e.g. {"schedule": {"assignments": [...]}}
            if isinstance(data.get(key), dict):
                inner = data[key].get("assignments")
                if isinstance(inner, list):
                    candidate = inner
                    break
        if candidate is None:
            return None
    else:
        return None

    # Final sanity check: each item must have the two required fields
    valid = [a for a in candidate
             if isinstance(a, dict) and "section_id" in a and "faculty_id" in a]
    return valid if valid else None


SYSTEM_PROMPT = """You are a university scheduling assistant.
Your job is to ASSIGN FACULTY TO SECTIONS while OBEYING HARD RULES.

HARD RULES (must NEVER be violated):
- A section must be assigned to EXACTLY ONE faculty.
- A faculty member must be QUALIFIED for every course they teach.
- A faculty member's total assigned credits must NOT EXCEED their required load.
- Faculty with 'evening OK: False' must NEVER be assigned evening sections.

SOFT GOALS (good but not required):
- Try to assign everyone close to their required load.
- Try not to give people too many different course preparations.

If you cannot assign a section without breaking a HARD RULE,
LEAVE IT UNASSIGNED and explain in your own reasoning (but NOT in the JSON). 
You must still output JSON only, as instructed."""


def build_prompt(faculty, sections, constraints):
    fac_lines = "\n".join(
        f"- {f.faculty_id} ({f.name}, {f.rank}): must teach {f.required_load} credits, "
        f"qualified for [{', '.join(f.qualified_courses)}], "
        f"evening OK: {f.preferences.get('accepts_evening', 'Yes')}"
        for f in faculty)

    sec_lines = "\n".join(
        f"- {s.section_id}: {s.title}, {s.credits}cr, {s.days} {s.start_time}, "
        f"evening: {s.evening}"
        for s in sections)
    return f"""Assign every section to exactly one qualified faculty member.

RULES:
- A faculty member's total credits must NOT exceed their required load.
- Never assign evening sections to faculty with evening OK: False.
- Max {constraints['max_evening_sections']} evening sections per person.
- Max {constraints['max_preparations']} distinct course codes per person.
- Never assign a faculty member to two sections that overlap in time on the same day.

FACULTY:
{fac_lines}

SECTIONS TO ASSIGN:
{sec_lines}

Reply with ONLY a JSON object with exactly one top-level key "assignments".
No other keys, no explanations, no markdown.
Example of the EXACT required format:
{{"assignments": [{{"section_id": "CS101-01", "faculty_id": "F001"}}, {{"section_id": "CS101-02", "faculty_id": "F002"}}]}}"""


MAX_ATTEMPTS = 3  # you can raise this later if you like

def build_revision_prompt(previous_assignments, violations):
    return f"""Your previous plan violated important rules.
You MUST FIX ALL of these violations. Keep as many correct assignments as possible.

PREVIOUS ASSIGNMENTS:
{json.dumps(previous_assignments, indent=2)}

VIOLATIONS:
{chr(10).join("- " + v for v in violations)}

Produce a NEW full assignment list that fixes ALL violations.
Return ONLY the JSON object with key "assignments" as before.
"""

def generate_plan_with_llm(faculty, sections, constraints,
                           faculty_by_id, sections_by_id):
    """LLM engine: propose a plan, revise against validator feedback.
    Returns (assignments, violations) — assignments may be None if all
    attempts fail to produce parseable output."""
    base_prompt = build_prompt(faculty, sections, constraints)

    best_assignments = None
    best_violations = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"\n--- LLM attempt {attempt}/{MAX_ATTEMPTS} ---")

        if attempt == 1 or best_assignments is None:
            prompt = base_prompt
        else:
            prompt = base_prompt + "\n\n" + build_revision_prompt(
                best_assignments, best_violations)

        reply = ask_llm(SYSTEM_PROMPT, prompt, json_mode=True)
        assignments = extract_assignments(reply)

        if assignments is None:
            print("  ⚠️ Could not parse a usable plan. Raw reply (first 400 chars):")
            print("  " + reply[:400].replace("\n", "\n  "))
            continue

        violations = validate_plan(assignments, faculty_by_id,
                                   sections_by_id, constraints)
        print(f"  {len(assignments)} assignments, {len(violations)} violation(s)")

        if best_violations is None or len(violations) < len(best_violations):
            best_assignments = assignments
            best_violations = violations

        if not violations:
            print("  ✅ Found a violation-free plan.")
            break

    return best_assignments, best_violations


def apply_negotiation_directives_to_loads(
    directives: list[dict], faculty
) -> dict[str, float]:
    """Return a dict faculty_id -> adjusted required_load (<= original),
    based on negotiation directives. Policies are not changed; we only tighten."""
    # Start from baseline
    adjusted = {f.faculty_id: f.required_load for f in faculty}

    for d in directives:
        if d.get("type") != "reduce_load":
            continue
        target = d.get("target_max_load")
        if target is None:
            continue
        try:
            target = float(target)
        except ValueError:
            continue

        # Find the matching faculty (simple name contains, first match)
            # Accept either a faculty_id or a (partial) name, in either field
        ident = str(d.get("faculty_id") or d.get("faculty_name") or "").strip().lower()
        if not ident:
            continue
        match = next(
            (f for f in faculty
             if ident == f.faculty_id.lower() or ident in f.name.lower()),
            None)
        if not match:
            continue

        fid = match.faculty_id
        # Tighten load: cannot exceed current required, cannot go below 0
        new_load = min(adjusted[fid], max(0.0, target))
        adjusted[fid] = new_load

    return adjusted


def run_assignment_agent(engine: str = "solver", 
                         output_name: str = "draft_v1",
                         directives: list[dict] | None = None,
                         previous_assignments: list[dict] | None = None):
    """Generate an assignment plan using the chosen engine:
       - "solver": OR-Tools CP-SAT (deterministic, respects all hard constraints)
       - "llm":    LLM proposal with validator-driven revision loop
    Validation and output format are identical for both engines."""

    if output_name != "negotiation_pending" and os.path.exists(PENDING_PLAN_PATH):
        os.remove(PENDING_PLAN_PATH)

    faculty = load_faculty()
    sections = load_sections()
    with open("data/processed/constraints.json") as f:
        constraints = json.load(f)

    adjusted_loads = apply_negotiation_directives_to_loads(directives or [], faculty)

    faculty_by_id = {f.faculty_id: f.model_dump() | {"required_load": f.required_load}
                     for f in faculty}
    sections_by_id = {s.section_id: s.model_dump() | {"section_id": s.section_id}
                      for s in sections}

    # Engine selection
    if engine == "solver":
        print("\n[Assignment Agent] Engine: OR-Tools solver")
        assignments = solve_assignments_with_ortools(adjusted_loads=adjusted_loads,
                                                     previous_assignments=previous_assignments)
    else:
        print("\n[Assignment Agent] Engine: LLM with revision loop")
        assignments, violations = generate_plan_with_llm(
            faculty, sections, constraints, faculty_by_id, sections_by_id)

    # Guard: engine produced nothing usable
    if not assignments:
        print("\n❌ No usable plan produced "
              f"({'solver found no feasible solution' if engine == 'solver' else 'all LLM attempts failed'}).")
        output_path = f"data/processed/plan_{output_name}.json"
        with open(output_path, "w") as f:
            json.dump({"assignments": [], "violations": ["NO PLAN: engine produced no assignments"],
                       "engine": engine}, f, indent=2)
        return {"assignments": [], "violations": [], "engine": engine}

    # Stage 2: optional room assignment
    rooms_by_id = None
    if assignments:
        try:
            rooms = load_rooms()
            room_map = solve_room_assignments(sections, rooms)
            for a in assignments:
                a["room"] = room_map.get(a["section_id"])
            rooms_by_id = {r.room_id: r.model_dump() for r in rooms}
            n_roomed = sum(1 for a in assignments if a.get("room"))
            print(f"[Assignment Agent] Rooms assigned: {n_roomed}/{len(assignments)}")
        except FileNotFoundError:
            print("[Assignment Agent] No rooms.xlsx found; skipping room assignment.")

    # Validation (now room-aware when rooms exist)
    violations = validate_plan(assignments, faculty_by_id, sections_by_id,
                               constraints, rooms_by_id=rooms_by_id)


    # Shared reporting and save
    print("\n" + "=" * 50)
    print(f"PLAN ({engine}): {len(assignments)} assignments, "
          f"{len(violations)} violation(s)")
    for a in assignments:
        name = faculty_by_id.get(a["faculty_id"], {}).get("name", "???")
        print(f"  {a['section_id']:<10} -> {name}")
    for v in violations:
        print(f"  ❌ {v}")

    output_path = f"data/processed/plan_{output_name}.json"
    with open(output_path, "w") as f:
        json.dump({"assignments": assignments, "violations": violations,
                   "engine": engine}, f, indent=2)
    print(f"\nSaved {output_path}")
    return {"assignments": assignments, "violations": violations, "engine": engine}


# Negotiation lifecycle

NEGOTIATION_SYSTEM_PROMPT = """You are an assistant helping a Department Chair
negotiate adjustments to a teaching load plan.

You will receive:
- The Chair's natural language request.
- The list of faculty with their IDs and names.

Translate the Chair's request into a JSON list of "directives".

Supported directive types:

1) "reduce_load":
   {
     "type": "reduce_load",
     "faculty_name": "<name as stated>",
     "target_max_load": <number>
   }

EXAMPLE:
Chair's request: "Reduce Dr. Chen's load to 6 credits."
Correct output:
[{"type": "reduce_load", "faculty_name": "Dr. Chen", "target_max_load": 6}]

IMPORTANT:
- "target_max_load" must be the NUMBER STATED IN THE CHAIR'S REQUEST.
- You may use "faculty_id" instead of "faculty_name" if an ID is given.
- If no supported directive matches, return [].
Return ONLY a JSON list, nothing else."""


DIFF_EXPLAIN_SYSTEM_PROMPT = """You are an academic scheduling analyst.
You are given an EXACT, code-computed comparison between the current teaching
plan and a proposed negotiated plan. Write a short summary (3-6 sentences)
for a Department Chair covering:
- which sections moved and to whom,
- whose loads changed and by how much,
- whether violations or fairness got better or worse.
Use ONLY the provided data. Do not invent moves, numbers, or reasons."""


def negotiation_pending() -> bool:
    return os.path.exists(PENDING_PLAN_PATH)


def extract_negotiation_directives(user_message: str) -> list[dict]:
    faculty = load_faculty()
    fac_lines = "\n".join(f"- {f.faculty_id}: {f.name}" for f in faculty)
    user_prompt = f"""Chair's request:
\"\"\"{user_message}\"\"\"

FACULTY:
{fac_lines}

Return the list of directives."""
    reply = ask_llm(NEGOTIATION_SYSTEM_PROMPT, user_prompt, json_mode=True)
    try:
        data = json.loads(reply)
        if isinstance(data, dict):
            if isinstance(data.get("directives"), list):
                data = data["directives"]
            elif "type" in data:
                data = [data]
            else:
                return []
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict) and "type" in d]
        return []
    except json.JSONDecodeError:
        return []


def _build_lookup_tables():
    """Agent builds its own lookups; it must not import from the supervisor."""
    faculty = load_faculty()
    sections = load_sections()
    faculty_by_id = {f.faculty_id: f.model_dump() | {"required_load": f.required_load}
                     for f in faculty}
    sections_by_id = {s.section_id: s.model_dump() | {"section_id": s.section_id}
                      for s in sections}
    return faculty, sections, faculty_by_id, sections_by_id


def compute_plan_diff(old_plan: dict, new_plan: dict,
                      faculty_by_id: dict, sections_by_id: dict) -> dict:
    old_map = {a["section_id"]: a["faculty_id"] for a in old_plan["assignments"]}
    new_map = {a["section_id"]: a["faculty_id"] for a in new_plan["assignments"]}

    def fac_name(fid):
        return faculty_by_id.get(fid, {}).get("name", fid or "(unassigned)")

    moves = []
    for sid in sorted(set(old_map) | set(new_map)):
        old_f, new_f = old_map.get(sid), new_map.get(sid)
        if old_f != new_f:
            sec = sections_by_id.get(sid, {})
            moves.append({"section": sid, "title": sec.get("title", ""),
                          "from": fac_name(old_f), "to": fac_name(new_f)})

    old_m = compute_metrics(old_plan["assignments"], faculty_by_id, sections_by_id)
    new_m = compute_metrics(new_plan["assignments"], faculty_by_id, sections_by_id)

    load_changes = []
    for fid, p_old in old_m["per_faculty"].items():
        p_new = new_m["per_faculty"].get(fid)
        if p_new and p_new["assigned_credits"] != p_old["assigned_credits"]:
            load_changes.append({
                "name": p_old["name"],
                "before": p_old["assigned_credits"],
                "after": p_new["assigned_credits"],
                "change": p_new["assigned_credits"] - p_old["assigned_credits"]})

    return {"moves": moves, "load_changes": load_changes,
            "violations_before": old_plan.get("violations", []),
            "violations_after": new_plan.get("violations", []),
            "fairness_before": old_m["summary"],
            "fairness_after": new_m["summary"]}


def narrate_diff(diff: dict, directives: list[dict]) -> str:
    facts = {"applied_directives": directives, **diff}
    return ask_llm(DIFF_EXPLAIN_SYSTEM_PROMPT,
                   json.dumps(facts, indent=2), json_mode=False)


def propose_negotiated_plan(user_query: str) -> dict:
    """Full negotiation proposal: extract -> re-solve -> diff -> narrate.
    Writes the pending plan file. Returns a plain-data dict:
      {"status": "no_directives" | "no_current_plan" | "no_changes" | "proposed",
       "directives": [...], "diff": {...}, "narrative": str}
    """
    directives = extract_negotiation_directives(user_query)
    if not directives:
            return {"status": "no_directives"}

    if not os.path.exists(CURRENT_PLAN_PATH):
        return {"status": "no_current_plan"}
    with open(CURRENT_PLAN_PATH) as f:
        old_plan = json.load(f)

    # Sanity: does the directive actually bind against the CURRENT plan?
    _, _, faculty_by_id, sections_by_id = _build_lookup_tables()
    current_metrics = compute_metrics(old_plan["assignments"],
                                          faculty_by_id, sections_by_id)
    for d in directives:
        if d.get("type") != "reduce_load":
            continue
        ident = str(d.get("faculty_id") or d.get("faculty_name") or "").lower()
        fid = next((i for i, f in faculty_by_id.items()
                    if ident == i.lower() or ident in f["name"].lower()), None)
        if fid:
            assigned_now = current_metrics["per_faculty"][fid]["assigned_credits"]
            if assigned_now <= float(d.get("target_max_load", 0)):
                return {"status": "already_satisfied",
                        "faculty": faculty_by_id[fid]["name"],
                        "assigned": assigned_now,
                        "target": d["target_max_load"]}

    replaced_previous = negotiation_pending()

    new_plan = run_assignment_agent(engine="solver",
                                    output_name="negotiation_pending",
                                    directives=directives,
                                    previous_assignments=old_plan["assignments"])

    diff = compute_plan_diff(old_plan, new_plan, faculty_by_id, sections_by_id)

    if not diff["moves"] and not diff["load_changes"]:
        if negotiation_pending():
            os.remove(PENDING_PLAN_PATH)
        return {"status": "no_changes", "directives": directives}

    with open(NEGOTIATION_CONTEXT_PATH, "w") as f:
        json.dump({"directives": directives, "diff": diff}, f, indent=2)

    return {"status": "proposed",
            "directives": directives,
            "diff": diff,
            "narrative": narrate_diff(diff, directives),
            "replaced_previous": replaced_previous}


def accept_pending_plan() -> dict:
    if not negotiation_pending():
        return {"status": "nothing_pending"}
    shutil.copy(PENDING_PLAN_PATH, CURRENT_PLAN_PATH)
    os.remove(PENDING_PLAN_PATH)
    return {"status": "accepted"}


def reject_pending_plan() -> dict:
    if not negotiation_pending():
        return {"status": "nothing_pending"}
    os.remove(PENDING_PLAN_PATH)
    return {"status": "rejected"}



if __name__ == "__main__":
    run_assignment_agent()
