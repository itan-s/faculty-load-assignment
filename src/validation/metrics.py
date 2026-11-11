"""Fairness and workload metrics — pure code, exact numbers."""
import statistics

def compute_metrics(assignments: list[dict], faculty_by_id: dict,
                    sections_by_id: dict) -> dict:
    per_faculty = {}
    for fid, f in faculty_by_id.items():
        per_faculty[fid] = {
            "name": f["name"],
            "rank": f["rank"],
            "required_load": f["required_load"],
            "assigned_credits": 0.0,
            "num_sections": 0,
            "preps": set(),
            "evening_sections": 0,
        }

    for a in assignments:
        fid = a["faculty_id"]
        sec = sections_by_id.get(a["section_id"])
        if fid not in per_faculty or sec is None:
            continue  # validator already reports these as violations
        p = per_faculty[fid]
        p["assigned_credits"] += sec["credits"]
        p["num_sections"] += 1
        p["preps"].add(sec["course_code"])
        if sec["evening"]:
            p["evening_sections"] += 1

    # Finalize per-faculty numbers
    for p in per_faculty.values():
        p["preps"] = len(p["preps"])
        p["load_gap"] = p["assigned_credits"] - p["required_load"]

    # Department-level fairness statistics
    gaps = [p["load_gap"] for p in per_faculty.values()]
    evenings = [p["evening_sections"] for p in per_faculty.values()]
    summary = {
        "total_sections_assigned": len(assignments),
        "faculty_at_exact_load": sum(1 for g in gaps if g == 0),
        "faculty_underloaded": sum(1 for g in gaps if g < 0),
        "faculty_overloaded": sum(1 for g in gaps if g > 0),
        "load_gap_std_dev": round(statistics.pstdev(gaps), 2) if gaps else 0,
        "evening_sections_std_dev": round(statistics.pstdev(evenings), 2) if evenings else 0,
    }
    return {"per_faculty": per_faculty, "summary": summary}
