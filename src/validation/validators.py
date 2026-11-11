"""Deterministic rule checks — pure code, no AI involved."""

def validate_plan(assignments: list[dict], faculty_by_id: dict,
                  sections_by_id: dict, constraints: dict) -> list[str]:
    violations = []

    # 1. Every section assigned exactly once
    assigned = [a["section_id"] for a in assignments]
    for sid in sections_by_id:
        if assigned.count(sid) == 0:
            violations.append(f"UNASSIGNED: {sid} has no instructor")
        elif assigned.count(sid) > 1:
            violations.append(f"DUPLICATE: {sid} assigned {assigned.count(sid)} times")

    # Per-faculty tallies
    loads, preps, evenings = {}, {}, {}
    for a in assignments:
        fid, sid = a["faculty_id"], a["section_id"]
        if fid not in faculty_by_id:
            violations.append(f"UNKNOWN FACULTY: {fid} on {sid}")
            continue
        sec = sections_by_id[sid]
        loads[fid] = loads.get(fid, 0) + sec["credits"]
        preps.setdefault(fid, set()).add(sec["course_code"])
        if sec["evening"]:
            evenings[fid] = evenings.get(fid, 0) + 1

        # 2. Qualification check
        if sec["course_code"] not in faculty_by_id[fid]["qualified_courses"]:
            violations.append(
                f"UNQUALIFIED: {faculty_by_id[fid]['name']} not qualified for {sid}")

        # 3. Evening consent check
        accepts = str(faculty_by_id[fid].get("preferences", {})
              .get("accepts_evening", "Yes")).strip().lower() in ("yes", "true", "1")
        if sec["evening"] and not accepts:
            violations.append(
                f"EVENING CONSENT: {faculty_by_id[fid]['name']} does not accept evening ({sid})")

    # 4. Load, preps, evening-count limits
    for fid, f in faculty_by_id.items():
        load = loads.get(fid, 0)
        if load > f["required_load"]:
            violations.append(
                f"OVERLOAD: {f['name']} has {load} credits (max {f['required_load']})")
        if len(preps.get(fid, set())) > constraints["max_preparations"]:
            violations.append(f"TOO MANY PREPS: {f['name']} has {len(preps[fid])} preps")
        if evenings.get(fid, 0) > constraints["max_evening_sections"]:
            violations.append(f"TOO MANY EVENINGS: {f['name']} has {evenings[fid]}")

    # 5. Time conflicts per faculty
    for fid, f in faculty_by_id.items():
        # collect this faculty's assigned sections
        fac_secs = []
        for a in assignments:
            if a["faculty_id"] != fid:
                continue
            sid = a["section_id"]
            sec = sections_by_id.get(sid)
            if not sec:
                continue
            fac_secs.append({
                "section_id": sid,
                "days": sec["days"],
                "start_time": sec["start_time"],
                "end_time": sec["end_time"],
            })
        # find overlapping pairs
        for s1, s2 in find_time_conflicts_for_faculty(fac_secs):
            violations.append(
                f"TIME CONFLICT: {f['name']} has overlapping sections {s1} and {s2}"
            )

    return violations


from datetime import datetime

TIME_FMT = "%H:%M"

def times_overlap(start1: str, end1: str, start2: str, end2: str) -> bool:
    """Return True if time ranges [start1,end1] and [start2,end2] overlap."""
    t1_start = datetime.strptime(start1, TIME_FMT).time()
    t1_end = datetime.strptime(end1, TIME_FMT).time()
    t2_start = datetime.strptime(start2, TIME_FMT).time()
    t2_end = datetime.strptime(end2, TIME_FMT).time()
    return (t1_start < t2_end) and (t2_start < t1_end)

def find_time_conflicts_for_faculty(sections_for_faculty: list[dict]) -> list[tuple[str, str]]:
    """
    Given a list of section dicts (each with section_id, days, start_time, end_time),
    return pairs of section_ids that conflict in time on at least one common day.
    """
    conflicts = []
    n = len(sections_for_faculty)
    for i in range(n):
        s1 = sections_for_faculty[i]
        for j in range(i + 1, n):
            s2 = sections_for_faculty[j]
            # Check overlapping days
            days1 = set(s1["days"])
            days2 = set(s2["days"])
            common_days = days1.intersection(days2)
            if not common_days:
                continue
            # Check time overlap
            if times_overlap(s1["start_time"], s1["end_time"],
                             s2["start_time"], s2["end_time"]):
                conflicts.append((s1["section_id"], s2["section_id"]))
    return conflicts

