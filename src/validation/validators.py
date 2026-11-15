"""Deterministic rule checks — pure code, no AI involved."""
from datetime import datetime
TIME_FMT = "%H:%M"


def validate_plan(assignments: list[dict], faculty_by_id: dict,
                  sections_by_id: dict, constraints: dict,
                  rooms_by_id: dict | None = None) -> list[str]:

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

    # 6. Minimum load (policy: min_load_full_time) reported, not enforced
    min_load = constraints.get("min_load_full_time", 0)
    # CLIENT-CONFIG: ranks subject to the minimum-load policy
    MIN_LOAD_RANKS = {"Professor", "Associate", "Assistant", "Lecturer"}
    if min_load:
        for fid, f in faculty_by_id.items():
            if f["rank"] not in MIN_LOAD_RANKS:
                continue
            load = loads.get(fid, 0)
            if load < min_load:
                violations.append(
                    f"UNDERLOAD: {f['name']} has {load} credits "
                    f"(policy minimum {min_load})")

    # 7. Room checks (only if plan entries carry room info)
    for a in assignments:
        sec = sections_by_id.get(a["section_id"])
        if not sec:
            continue
        room_id = a.get("room")

        # 7a. Section without a room
        if not room_id:
            # Only flag if the plan is supposed to have rooms at all
            # (i.e., at least one assignment has a room)
            if any(x.get("room") for x in assignments):
                violations.append(
                    f"NO ROOM: {a['section_id']} has no room assigned")
            continue

        # 7b. Course-room restriction
        allowed = sec.get("allowed_rooms") or []
        if allowed and room_id not in allowed:
            violations.append(
                f"ROOM NOT ALLOWED: {a['section_id']} is in {room_id}; "
                f"allowed: {', '.join(allowed)}")

        # 7c. Capacity — needs rooms_by_id; skip gracefully if not provided
        if rooms_by_id:
            room = rooms_by_id.get(room_id)
            if room and sec.get("enrollment", 0) > room.get("capacity", 0):
                violations.append(
                    f"ROOM OVER CAPACITY: {a['section_id']} has "
                    f"{sec.get('enrollment', 0)} students in {room_id} "
                    f"(capacity {room.get('capacity', 0)})")

        # 7d. Room availability (pre-assigned or solver-assigned)
        if rooms_by_id:
            room = rooms_by_id.get(room_id)
            if room:
                if not room_open_for_section_dict(sec, room):
                    violations.append(
                        f"ROOM UNAVAILABLE: {a['section_id']} meets "
                        f"{sec['days']} {sec['start_time']}-{sec['end_time']} "
                        f"outside {room_id}'s available hours")


    # 8. Room double-booking (hard rule)
    roomed = [a for a in assignments if a.get("room")]
    for i in range(len(roomed)):
        for j in range(i + 1, len(roomed)):
            if roomed[i]["room"] != roomed[j]["room"]:
                continue
            s1 = sections_by_id.get(roomed[i]["section_id"])
            s2 = sections_by_id.get(roomed[j]["section_id"])
            if not s1 or not s2:
                continue
            if set(s1["days"]) & set(s2["days"]) and \
               times_overlap(s1["start_time"], s1["end_time"],
                             s2["start_time"], s2["end_time"]):
                violations.append(
                    f"ROOM CONFLICT: {roomed[i]['section_id']} and "
                    f"{roomed[j]['section_id']} overlap in {roomed[i]['room']}")

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


def _within(start: str, end: str, w_start: str, w_end: str) -> bool:
    """Return True if [start, end] is fully within [w_start, w_end]."""
    to_time = lambda t: datetime.strptime(t, TIME_FMT).time()
    return to_time(w_start) <= to_time(start) and to_time(end) <= to_time(w_end)


def parse_day_string(s: str) -> list[str]:
    """Turn 'MW' or 'TTh' into ['M','W'] or ['T','Th']."""
    s = s.strip()
    tokens = []
    i = 0
    while i < len(s):
        if s[i:i+2] == "Th":
            tokens.append("Th")
            i += 2
        else:
            tokens.append(s[i])
            i += 1
    return tokens


def room_open_for_section_dict(sec: dict, room: dict) -> bool:
    """
    Availability check for dict data:
    - sec: {'days', 'start_time', 'end_time', ...}
    - room: {'availability': {'M':[(start,end),...], ...}, ...}
    Empty availability dict => always open.
    """
    avail = room.get("availability") or {}
    if not avail:
        return True

    sec_days = parse_day_string(sec["days"])
    for d in sec_days:
        windows = avail.get(d)
        if not windows:
            return False
        if not any(_within(sec["start_time"], sec["end_time"], ws, we)
                   for ws, we in windows):
            return False
    return True


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

