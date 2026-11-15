import json
from src.ingestion.excel_loader import load_faculty, load_sections, load_rooms
from src.llm.client import ask_llm
from src.validation.validators import validate_plan
from src.solvers.ortools_solver import solve_assignments_with_ortools
from src.solvers.room_solver import solve_room_assignments

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


def run_assignment_agent(engine: str = "solver", output_name: str = "draft_v1"):
    """Generate an assignment plan using the chosen engine:
       - "solver": OR-Tools CP-SAT (deterministic, respects all hard constraints)
       - "llm":    LLM proposal with validator-driven revision loop
    Validation and output format are identical for both engines."""
    faculty = load_faculty()
    sections = load_sections()
    with open("data/processed/constraints.json") as f:
        constraints = json.load(f)

    faculty_by_id = {f.faculty_id: f.model_dump() | {"required_load": f.required_load}
                     for f in faculty}
    sections_by_id = {s.section_id: s.model_dump() | {"section_id": s.section_id}
                      for s in sections}

    # Engine selection
    if engine == "solver":
        print("\n[Assignment Agent] Engine: OR-Tools solver")
        assignments = solve_assignments_with_ortools()
        violations = validate_plan(assignments, faculty_by_id,
                                   sections_by_id, constraints)
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

        # --- Stage 2: optional room assignment ---
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
    

if __name__ == "__main__":
    run_assignment_agent()
