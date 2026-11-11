# Demo Case 1 – End-to-end workflow (synthetic data)

## Steps

1. `streamlit run app.py`
2. Sidebar: **Rebuild constraints**
3. Sidebar: **Generate new plan**
4. Chat: "Which policies are being violated?"
5. Chat: "Which faculty preferences could not be accommodated?"
6. Sidebar: **Admin report + Excel**, then download `final_plan.xlsx`.

## Key outputs

- Violations grouped by policy:
  - Coverage Policy: UNASSIGNED CS101-01, CS101-02
  - Evening Classes Policy: EVENING CONSENT (Dr. Adams, CS101-03)
  - Course Qualifications Policy: UNQUALIFIED assignments for Dr. Chen, etc.
  - Teaching Load Policy: OVERLOAD (Dr. Chen 15.0 vs 12.0)

- Unmet preferences:
  - Dr. Adams: Preferred days MW → assigned CS101-04 on TTh; does not accept evening → assigned CS101-03 (evening)
  - Dr. Baker: Preferred days TTh → assigned CS201-01 on MW
  - ...

- `final_plan.xlsx`: contains AllAssignments, Conflicts, and per-faculty sheets.
