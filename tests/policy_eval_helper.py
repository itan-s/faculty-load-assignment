# tests/policy_eval_helper.py
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Dict, Any
import json

from src.ingestion.excel_loader import load_faculty, load_sections, load_rooms
from src.solvers.ortools_solver import solve_assignments_with_ortools
from src.solvers.room_solver import solve_room_assignments
from src.validation.validators import validate_plan
from src.validation import metrics as metrics_module


@dataclass
class PolicyConsistencyMetrics:
    # teaching load
    num_faculty: int
    num_faculty_overload: int
    num_faculty_underload: int
    avg_load: float
    max_load: float

    # coverage
    num_sections: int
    num_sections_assigned: int

    # rooms / timing
    num_room_violations: int
    num_time_clash_violations: int
    num_total_violations: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _faculty_to_dict(faculty) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for f in faculty:
        out[f.faculty_id] = {
            "faculty_id": f.faculty_id,
            "name": f.name,
            "rank": f.rank,
            "required_load": f.required_load,
            "qualified_courses": list(f.qualified_courses),
            "preferences": f.preferences or {},
        }
    return out


def _sections_to_dict(sections) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for s in sections:
        out[s.section_id] = {
            "section_id": s.section_id,
            "course_code": s.course_code,
            "credits": s.credits,
            "days": s.days,
            "start_time": s.start_time,
            "end_time": s.end_time,
            "evening": bool(s.evening),
            "enrollment": s.enrollment,
            "allowed_rooms": list(s.allowed_rooms or []),
        }
    return out


def _rooms_to_dict(rooms) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for r in rooms:
        out[r.room_id] = {
            "room_id": r.room_id,
            "building": r.building,
            "capacity": r.capacity,
            "available": r.available,
            "availability": r.availability,
            "room_type": r.room_type,
        }
    return out


def _build_assignments_with_rooms(
    raw_assignments: List[Dict[str, str]],
    room_map: Dict[str, str],
) -> List[Dict[str, Any]]:
    """
    Turn [{'faculty_id','section_id'}] + room_map into the list-of-dicts that
    validate_plan() and compute_metrics() use.
    """
    out: List[Dict[str, Any]] = []
    for a in raw_assignments:
        sec_id = a["section_id"]
        out.append(
            {
                "faculty_id": a["faculty_id"],
                "section_id": sec_id,
                "room": room_map.get(sec_id),
            }
        )
    return out


def _load_constraints(path: str) -> Dict[str, Any]:
    with open(path, "r") as f:
        return json.load(f)


def run_policy_eval(
    constraints_path: str = "data/processed/constraints.json",
) -> PolicyConsistencyMetrics:
    """
    Run OR-Tools assignment + room solver on the current data/raw Excel files,
    then validate and compute high-level policy-consistency metrics.
    """

    # 1) Load data
    faculty = load_faculty()
    sections = load_sections()
    rooms = load_rooms()
    constraints = _load_constraints(constraints_path)

    # 2) OR-Tools faculty assignment
    raw_assignments = solve_assignments_with_ortools(
        constraints_path=constraints_path
    )
    if not raw_assignments:
        return PolicyConsistencyMetrics(
            num_faculty=len(faculty),
            num_faculty_overload=0,
            num_faculty_underload=0,
            avg_load=0.0,
            max_load=0.0,
            num_sections=len(sections),
            num_sections_assigned=0,
            num_room_violations=0,
            num_time_clash_violations=0,
            num_total_violations=0,
        )

    # 3) Room solver
    room_map = solve_room_assignments(sections, rooms)

    # 4) Build dict views
    faculty_by_id = _faculty_to_dict(faculty)
    sections_by_id = _sections_to_dict(sections)
    rooms_by_id = _rooms_to_dict(rooms)
    assignments = _build_assignments_with_rooms(raw_assignments, room_map)

    # 5) Validation
    violations = validate_plan(
        assignments=assignments,
        faculty_by_id=faculty_by_id,
        sections_by_id=sections_by_id,
        constraints=constraints,
        rooms_by_id=rooms_by_id,
    )

    # 6) Metrics
    m = metrics_module.compute_metrics(
        assignments=assignments,
        faculty_by_id=faculty_by_id,
        sections_by_id=sections_by_id,
    )

    per_faculty = m["per_faculty"]
    print("\n=== Per-faculty loads (required vs assigned) ===")
    for fid, info in per_faculty.items():
        print(
            f"{info['name']:<15} "
            f"required={info['required_load']:>4} "
            f"assigned={info['assigned_credits']:>4} "
            f"gap={info['load_gap']:>4}"
        )

    loads = [p["assigned_credits"] for p in per_faculty.values()] or [0.0]

    num_faculty_overload = m["summary"]["faculty_overloaded"]

    # Policy underload means assigned load is below min_load_full_time,
    # not merely below the faculty member's required/target load.
    min_load = float(constraints.get("min_load_full_time", 0))

    MIN_LOAD_RANKS = {
        "Professor",
        "Associate",
        "Assistant",
        "Lecturer",
    }

    num_faculty_underload = sum(
        1
        for p in per_faculty.values()
        if p["rank"] in MIN_LOAD_RANKS
        and p["assigned_credits"] < min_load
    )

    avg_load = sum(loads) / len(loads)
    max_load = max(loads)


    # Coverage
    num_sections = len(sections)
    assigned_sec_ids = {a["section_id"] for a in assignments}
    num_sections_assigned = len(assigned_sec_ids)

    # Violations are strings; classify by substring
    num_room_violations = sum(
        1 for v in violations if "ROOM" in v.upper()
    )
    num_time_clash_violations = sum(
        1 for v in violations if "TIME CONFLICT" in v.upper()
    )
    num_total_violations = len(violations)

    return PolicyConsistencyMetrics(
        num_faculty=len(faculty),
        num_faculty_overload=num_faculty_overload,
        num_faculty_underload=num_faculty_underload,
        avg_load=avg_load,
        max_load=max_load,
        num_sections=num_sections,
        num_sections_assigned=num_sections_assigned,
        num_room_violations=num_room_violations,
        num_time_clash_violations=num_time_clash_violations,
        num_total_violations=num_total_violations,
    )
