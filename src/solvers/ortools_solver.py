from typing import List, Dict

from ortools.sat.python import cp_model

from src.ingestion.excel_loader import load_faculty, load_sections
import json


def solve_assignments_with_ortools(
    constraints_path: str = "data/processed/constraints.json",
    adjusted_loads=None,
    previous_assignments=None,
) -> List[Dict[str, str]]:
    """Solve the assignment problem using OR-Tools CP-SAT.

    Hard constraints enforced (may change upon customization):
    - Each section assigned to exactly one faculty (or left unassigned if no legal option).
    - Only qualified faculty can teach a section.
    - Load per faculty <= required_load (base_load - release_credits).
    - Evening sections only assigned to faculty who accept evenings.
    - Max_evening_sections per faculty (from constraints).
    - Max_preparations per faculty (distinct course codes).

    Objective (first version): maximize number of assigned sections
    while softly penalizing overload of prep and evening limits.
    """

    with open(constraints_path) as f:
        constraints = json.load(f)

    max_evening_sections = constraints.get("max_evening_sections", 2)
    max_preps = constraints.get("max_preparations", 3)
    adjusted_loads = adjusted_loads or {}


    faculty = load_faculty()
    sections = load_sections()

    model = cp_model.CpModel()

    # Indexing helpers
    F = range(len(faculty))
    S = range(len(sections))

    # Decision variables:
    # x[f, s] = 1 if faculty f teaches section s
    x = {}
    for fi in F:
        for si in S:
            x[(fi, si)] = model.NewBoolVar(f"x_f{fi}_s{si}")

    # Each section assigned to at most one faculty
    for si in S:
        model.Add(sum(x[(fi, si)] for fi in F) <= 1)

    # Qualification + consent + load structure
    # Pre-compute useful mappings
    # CP-SAT requires integers: scale credits by 10 ("deci-credits")
    SCALE = 10
    credits = [int(round(s.credits * SCALE)) for s in sections]
    required_load = [
        int(round((adjusted_loads.get(f.faculty_id, f.required_load)) * SCALE))
        for f in faculty
    ]
    course_codes = [s.course_code for s in sections]
    is_evening = [s.evening for s in sections]
    min_load = int(round(constraints.get("min_load_full_time", 0) * SCALE))
    faculty_qualified = [
        set(f.qualified_courses) for f in faculty
    ]

    def accepts_evening_flag(f) -> bool:
        prefs = f.preferences or {}
        val = str(prefs.get("accepts_evening", "Yes")).strip().lower()
        return val in ("yes", "true", "1")

    faculty_accepts_evening = [accepts_evening_flag(f) for f in faculty]

    # 1) Qualification + evening consent
    for fi in F:
        for si in S:
            f = faculty[fi]
            s = sections[si]

            # Only qualified faculty can teach
            if s.course_code not in faculty_qualified[fi]:
                model.Add(x[(fi, si)] == 0)
            # If faculty does not accept evenings, block evening sections
            if is_evening[si] and not faculty_accepts_evening[fi]:
                model.Add(x[(fi, si)] == 0)

    # 2) No time conflicts: a faculty cannot teach two overlapping sections
    from src.validation.validators import times_overlap

    def sections_clash(a, b) -> bool:
        if not set(a.days) & set(b.days):
            return False
        return times_overlap(a.start_time, a.end_time, b.start_time, b.end_time)

    for si in S:
        for sj in S:
            if sj <= si:
                continue
            if sections_clash(sections[si], sections[sj]):
                for fi in F:
                    # at most one of the two clashing sections per faculty
                    model.Add(x[(fi, si)] + x[(fi, sj)] <= 1)


    # 3) Load limits: sum(credits * x) <= required_load
    for fi in F:
        model.Add(
            sum(credits[si] * x[(fi, si)] for si in S) <= required_load[fi]
        )

    # 4) Evening sections per faculty
    for fi in F:
        model.Add(
            sum(x[(fi, si)] for si in S if is_evening[si]) <= max_evening_sections
        )

    # 5) Prep limits (distinct courses)
    # We approximate distinct preps with helper bool vars y[f, c] indicating
    # whether faculty f teaches ANY section of course c.
    course_list = sorted(set(course_codes))
    C = range(len(course_list))
    y = {}
    for fi in F:
        for ci in C:
            y[(fi, ci)] = model.NewBoolVar(f"y_f{fi}_c{ci}")

    # Link y and x: if any section of course c is taught by f, y[f,c] = 1
    for fi in F:
        for ci, code in enumerate(course_list):
            # sections indices with this course code
            si_list = [si for si in S if course_codes[si] == code]
            if not si_list:
                continue
            # y[f,c] >= x[f,si] for all si in si_list
            for si in si_list:
                model.Add(y[(fi, ci)] >= x[(fi, si)])
            # y[f,c] <= sum x[f,si]
            model.Add(y[(fi, ci)] <= sum(x[(fi, si)] for si in si_list))

    for fi in F:
        model.Add(
            sum(y[(fi, ci)] for ci in C) <= max_preps
        )

    # 6) Fairness: minimize the WORST load gap, not the sum
    # (sum of gaps is constant under full coverage, so it cannot drive fairness)
    gaps = []
    for fi in F:
        assigned = sum(credits[si] * x[(fi, si)] for si in S)
        gap = model.NewIntVar(0, required_load[fi], f"gap_f{fi}")
        model.Add(gap == required_load[fi] - assigned)
        gaps.append(gap)

    max_gap = model.NewIntVar(0, max(required_load), "max_gap")
    model.AddMaxEquality(max_gap, gaps)

    # Soft minimum load: penalize shortfall below min_load_full_time
    # Hard-enforcing this would be infeasible when total offered credits
    # < sum of minimums, so we penalize instead and let the validator report it.

    # CLIENT-CONFIG: which ranks the minimum-load policy applies to
    MIN_LOAD_RANKS = {"Professor", "Associate", "Assistant", "Lecturer"}

    shortfalls = []
    for fi in F:
        if faculty[fi].rank not in MIN_LOAD_RANKS or min_load == 0:
            continue
        assigned = sum(credits[si] * x[(fi, si)] for si in S)
        # shortfall = max(0, min_load - assigned)
        shortfall = model.NewIntVar(0, min_load, f"shortfall_f{fi}")
        model.Add(shortfall >= min_load - assigned)
        # (shortfall can be 0 when assigned >= min_load; the solver will
        #  push it down because it's penalized in the objective)
        shortfalls.append(shortfall)

    # Also count faculty with zero assignments (secondary fairness signal)
    teaches_nothing = []
    for fi in F:
        tn = model.NewBoolVar(f"nothing_f{fi}")
        model.Add(sum(x[(fi, si)] for si in S) == 0).OnlyEnforceIf(tn)
        model.Add(sum(x[(fi, si)] for si in S) >= 1).OnlyEnforceIf(tn.Not())
        teaches_nothing.append(tn)

    # 7) Stability: reward keeping previous (faculty, section) pairs
    prev_pairs = set()
    if previous_assignments:
        fac_index = {f.faculty_id: fi for fi, f in enumerate(faculty)}
        sec_index = {s.section_id: si for si, s in enumerate(sections)}
        for a in previous_assignments:
            fi = fac_index.get(a["faculty_id"])
            si = sec_index.get(a["section_id"])
            if fi is not None and si is not None:
                prev_pairs.add((fi, si))

    STABILITY_WEIGHT = 200   # CLIENT-CONFIG: cost of moving one section
    stability_terms = [x[(fi, si)] for (fi, si) in prev_pairs]

    COVERAGE_WEIGHT = 10000   # coverage always comes first
    model.Maximize(
        COVERAGE_WEIGHT * sum(x[(fi, si)] for fi in F for si in S)
        - 10 * max_gap                      # primary: help the worst-off
        - 50 * sum(teaches_nothing)         # secondary: nobody should have zero
        - 5 * sum(shortfalls)               # NEW: push everyone toward min load
        + STABILITY_WEIGHT * sum(stability_terms) 
    )

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60.0 # limit time for safety

    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # No feasible solution found
        return []

    assignments = []
    for fi in F:
        for si in S:
            if solver.Value(x[(fi, si)]) == 1:
                assignments.append({
                    "faculty_id": faculty[fi].faculty_id,
                    "section_id": sections[si].section_id,
                })

    return assignments
