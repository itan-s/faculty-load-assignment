import json
import pandas as pd
from src.ingestion.excel_loader import load_faculty, load_sections
from src.validation.metrics import compute_metrics
from src.validation.validators import find_time_conflicts_for_faculty
from src.llm.client import ask_llm

SYSTEM_PROMPT = """You are a university governance analyst writing for a
Department Chair. You are given EXACT metrics and violations computed by
software. Write a clear, professional report. NEVER invent numbers — use
only the data provided. Be concise and specific."""

REPORT_TEMPLATE = """Write a teaching assignment review report with these sections:
1. Overall Summary (2-3 sentences: is this plan ready, or does it need work?)
2. Compliance Issues (list each violation plainly; if none, say so)
3. Workload Fairness (comment on load gaps and evening distribution)
4. Recommendations (2-3 concrete next actions for the Chair)

VIOLATIONS FOUND BY VALIDATOR:
{violations}

PER-FACULTY METRICS:
{per_faculty}

DEPARTMENT SUMMARY METRICS:
{summary}
"""

def build_assignment_table(assignments, faculty_by_id, sections_by_id):
    """Return a list of rows for the final Excel table."""
    rows = []
    for a in assignments:
        sid = a["section_id"]
        fid = a["faculty_id"]
        sec = sections_by_id.get(sid)
        fac = faculty_by_id.get(fid)
        if not sec or not fac:
            continue
        rows.append({
            "FacultyID": fid,
            "FacultyName": fac["name"],
            "Rank": fac["rank"],
            "CourseCode": sec["course_code"],
            "Section": sec["section"],
            "SectionID": sid,
            "Title": sec["title"],
            "Credits": sec["credits"],
            "Days": sec["days"],
            "StartTime": sec["start_time"],
            "EndTime": sec["end_time"],
            "Evening": sec["evening"],
        })
    return rows


def export_plan_to_excel(assignments, faculty_by_id, sections_by_id,
                         output_path="data/processed/final_plan.xlsx"):
    """Create an Excel workbook with:
       - Sheet 'AllAssignments': full schedule
       - Sheet 'Conflicts': any time overlaps
       - One sheet per faculty with their personal schedule
    """
    rows = build_assignment_table(assignments, faculty_by_id, sections_by_id)
    if not rows:
        print("No assignments to export.")
        return

    all_df = pd.DataFrame(rows)

    # Detect time conflicts per faculty
    conflict_records = []
    for fid, f in faculty_by_id.items():
        fac_rows = [r for r in rows if r["FacultyID"] == fid]
        simple_secs = [{
            "section_id": r["SectionID"],
            "days": r["Days"],
            "start_time": r["StartTime"],
            "end_time": r["EndTime"],
        } for r in fac_rows]
        pairs = find_time_conflicts_for_faculty(simple_secs)
        for s1, s2 in pairs:
            conflict_records.append({
                "FacultyID": fid,
                "FacultyName": f["name"],
                "Section1": s1,
                "Section2": s2,
            })

    # Write to Excel
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        # 1) Full assignment sheet
        all_df.sort_values(["FacultyName", "Days", "StartTime"]).to_excel(
            writer, sheet_name="AllAssignments", index=False
        )

        # 2) Conflicts sheet (if any)
        if conflict_records:
            pd.DataFrame(conflict_records).to_excel(
                writer, sheet_name="Conflicts", index=False
            )

        # 3) One sheet per faculty
        for fid, f in faculty_by_id.items():
            fac_df = all_df[all_df["FacultyID"] == fid].copy()
            if fac_df.empty:
                continue  # skip faculty with no assignments
            # Optional: drop FacultyID/Name columns since sheet is per-faculty
            fac_df = fac_df.drop(columns=["FacultyID", "FacultyName"])
            sheet_name = f["name"][:31]  # Excel sheet name limit
            fac_df.sort_values(["Days", "StartTime"]).to_excel(
                writer, sheet_name=sheet_name, index=False
            )

    print(f"Final plan Excel written to {output_path}")


def run_governance_agent(plan_path: str = "data/processed/plan_draft_v1.json"):
    with open(plan_path) as f:
        plan = json.load(f)
    faculty_objs = load_faculty()
    section_objs = load_sections()

    faculty_by_id = {f.faculty_id: f.model_dump() | {"required_load": f.required_load}
                     for f in faculty_objs}
    sections_by_id = {s.section_id: s.model_dump() | {"section_id": s.section_id}
                      for s in section_objs}

    # 1) Metrics for fairness/compliance
    metrics = compute_metrics(plan["assignments"], faculty_by_id, sections_by_id)

    print("Per-faculty summary (computed by code):")
    print(f"{'Name':<12} {'Req':>4} {'Got':>4} {'Gap':>5} {'Preps':>5} {'Eve':>4}")
    for p in metrics["per_faculty"].values():
        print(f"{p['name']:<12} {p['required_load']:>4} {p['assigned_credits']:>4} "
              f"{p['load_gap']:>5} {p['preps']:>5} {p['evening_sections']:>4}")
    print(f"\nFairness: load gap std dev = {metrics['summary']['load_gap_std_dev']}")
    print(f"Violations in plan: {len(plan['violations'])}")

    # 2) Narrative report via LLM (unchanged)
    print("\nAsking LLM to write the Chair's report...")
    report = ask_llm(
        SYSTEM_PROMPT,
        REPORT_TEMPLATE.format(
            violations=json.dumps(plan["violations"], indent=2),
            per_faculty=json.dumps(metrics["per_faculty"], indent=2),
            summary=json.dumps(metrics["summary"], indent=2),
        ),
    )

    with open("data/processed/governance_report.md", "w") as f:
        f.write(report)
    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)
    print("\nSaved data/processed/governance_report.md")

    # 3) Export final plan to Excel
    export_plan_to_excel(plan["assignments"], faculty_by_id, sections_by_id)

if __name__ == "__main__":
    run_governance_agent()

