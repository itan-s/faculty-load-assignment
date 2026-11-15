import json
from ortools.sat.python import cp_model
from src.validation.validators import times_overlap
from datetime import datetime
from typing import Sequence

TIME_FMT = "%H:%M"

def parse_day_string(s: str) -> list[str]:
    """
    Turn a day string like 'MW' or 'TTh' or 'MTWTh' into tokens ['M','W'] or ['T','Th'] etc.
    Assumes tokens are from {'M','T','W','Th','F'}.
    """
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


def parse_availability(spec: str) -> dict[str, list[tuple[str, str]]]:
    """
    Parse availability like 'MW 07:00-17:00; TTh 07:00-12:00' into:
      {'M': [('07:00','17:00')], 'W': [('07:00','17:00')],
       'T': [('07:00','12:00')], 'Th': [('07:00','12:00')]}
    Blank/NaN => {} meaning 'always available'.
    """
    result: dict[str, list[tuple[str, str]]] = {}
    if not spec or str(spec).strip().lower() in ("", "nan"):
        return result
    for part in str(spec).split(";"):
        part = part.strip()
        if not part:
            continue
        days_str, times = part.split(" ", 1)
        start, end = times.strip().split("-")
        day_tokens = parse_day_string(days_str)
        for d in day_tokens:
            result.setdefault(d, []).append((start.strip(), end.strip()))
    return result


def _within(start: str, end: str, w_start: str, w_end: str) -> bool:
    """Return True if [start, end] is fully within [w_start, w_end]."""
    to_time = lambda t: datetime.strptime(t, TIME_FMT).time()
    return to_time(w_start) <= to_time(start) and to_time(end) <= to_time(w_end)


def room_open_for_section(section, room) -> bool:
    """
    True if the room is open on every day/time the section meets.
    Empty availability dict means 'always open'.
    - section.days: e.g. "MW", "TTh" -> tokens ["M","W"], ["T","Th"]
    - room.availability: dict[str, list[(start,end)]], keys are tokens "M","T","W","Th","F".
    """
    avail = getattr(room, "availability", {}) or {}
    if not avail:
        return True

    sec_days = parse_day_string(section.days)
    for d in sec_days:
        windows = avail.get(d)
        if not windows:
            # room has no windows for this day => closed that day
            return False
        # at least one window must fully cover the section time
        if not any(_within(section.start_time, section.end_time, ws, we)
                   for ws, we in windows):
            return False
    return True



def sections_clash(a, b) -> bool:
    if not set(a.days) & set(b.days):
        return False
    return times_overlap(a.start_time, a.end_time, b.start_time, b.end_time)


def solve_room_assignments(sections, rooms) -> dict[str, str]:
    """Assign rooms to sections lacking one. Pre-assigned rooms are fixed.
    Hard rule: no two time-overlapping sections share a room.
    Returns {section_id: room_id} for ALL sections that end up roomed."""
    usable = [r for r in rooms if r.available]
    fixed = {s.section_id: s.room for s in sections if s.room}
    free_sections = [s for s in sections if not s.room]

    model = cp_model.CpModel()
    S = range(len(free_sections))
    R = range(len(usable))

    y = {(si, ri): model.NewBoolVar(f"y_s{si}_r{ri}") for si in S for ri in R}

    # Block illegal pairings (restrictions + capacity)
    for si in S:
        for ri in R:
            if not room_allowed_for_section(free_sections[si], usable[ri]):
                model.Add(y[(si, ri)] == 0)

    # Each free section gets at most one room (prefer exactly one via objective)
    for si in S:
        model.Add(sum(y[(si, ri)] for ri in R) <= 1)

    # Hard rule 1: two clashing free sections cannot share a room
    for si in S:
        for sj in S:
            if sj <= si:
                continue
            if sections_clash(free_sections[si], free_sections[sj]):
                for ri in R:
                    model.Add(y[(si, ri)] + y[(sj, ri)] <= 1)

    # Hard rule 2: a free section cannot clash with a PRE-ASSIGNED room's section
    room_index = {r.room_id: ri for ri, r in enumerate(usable)}
    for s_fixed in sections:
        if not s_fixed.room or s_fixed.room not in room_index:
            continue
        ri = room_index[s_fixed.room]
        for si in S:
            if sections_clash(free_sections[si], s_fixed):
                model.Add(y[(si, ri)] == 0)

    # Objective
    # Priority 1: room as many sections as possible (big weight)
    # Priority 2: unrestricted sections should avoid laboratory rooms,
    #             keeping labs free for lab-restricted courses.
    ROOM_WEIGHT = 100        # one roomed section outweighs any lab penalty
    LAB_PENALTY = 1          # CLIENT-CONFIG: cost of putting an unrestricted
                             # section into a lab

    lab_terms = []
    for si in S:
        if free_sections[si].allowed_rooms:
            continue  # restricted sections pay no penalty — labs may be their only option
        for ri in R:
            if usable[ri].room_type == "Laboratory":
                lab_terms.append(y[(si, ri)])

    model.Maximize(
        ROOM_WEIGHT * sum(y[(si, ri)] for si in S for ri in R)
        - LAB_PENALTY * sum(lab_terms)
    )


    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30.0
    status = solver.Solve(model)

    result = dict(fixed)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for si in S:
            for ri in R:
                if solver.Value(y[(si, ri)]) == 1:
                    result[free_sections[si].section_id] = usable[ri].room_id
    return result


def room_allowed_for_section(section, room) -> bool:
    """Static legality of a (section, room) pairing:
       1) course-room restriction (empty allowed_rooms = unrestricted)
       2) capacity >= enrollment
       3) room open during section time on all meeting days
    """
    if section.allowed_rooms and room.room_id not in section.allowed_rooms:
        return False
    if section.enrollment > room.capacity:
        return False
    if not room_open_for_section(section, room):
        return False
    return True


