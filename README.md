# Teaching Load Assignment System (A multi-agent system)

This app helps automate faculty teaching load assignment using a local LLM, Python
agents, and a Streamlit UI. Once installed, you only need to run **Streamlit** and
use the browser interface.

---

## Prerequisites

Before running the app, you need:

1. **Python** 3.10 or later
2. **Ollama** installed and running locally  
   Download from: https://ollama.com/download
3. At least one local LLM model pulled, for example:
#bash
ollama pull llama3.1:8b

## Setup
From the project root folder (the one containing app.py and requirements.txt):

1. (Optional) Create and activate a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate   # on macOS/Linux
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. (Optional, first-time only) Generate sample data for testing:
```bash
python create_sample_data.py
```
This creates example faculty.xlsx, courses.xlsx, and workload_policy.pdf in data/raw/. These are fake, for demonstration only.

4. Run the application. Start the Streamlit UI:
```bash
streamlit run app.py
```
Then open the browser URL shown in the terminal (typically http://localhost:8501). You should see the main page titled: Teaching Load Assignment System (A multi-agent system)


## HOW TO USE THE UI

1. Sidebar quick actions
On the left, the sidebar provides buttons (labels may vary slightly), for example:

- Rebuild constraints
Reads the Excel and PDF files and rebuilds: (1) faculty profiles, (2) policy constraints

- Generate new plan
Creates a new draft teaching load assignment plan.

- Recalculate plan
Regenerates a plan under the same policies (useful after changing input files).

- Admin report in Excel
Generates: (1) a governance report, and (2) an Excel file (downloadable) with:
    all assignments,
    time-conflict sheet,
    one sheet per faculty.

- Fairness issues
Shows fairness metrics and which faculty are under/over their required load.

- Policy violations
Shows current plan violations, grouped by policy (coverage, load, evening classes, etc.).

- Show faculty
Lists all faculty and their required teaching loads.

- Unmet preferences
Shows which recorded faculty preferences (e.g., days, evenings) were not met.

- Suggest improvements
Suggests possible reassignments (no policy changes) that would reduce violations.

You can drive a full workflow using only these buttons:

Rebuild constraints
Generate new plan
Inspect fairness / violations / unmet preferences
Run Admin report (Excel) and download the file

2. Chat box (ask natural-language questions)
In the main area, use the chat input at the bottom to ask questions such as:

“Which faculty preferences could not be accommodated?”
“Why was Dr. Adams assigned Intro to Programming?”
“Which policies are being violated in the current plan?”
“Show all faculty exceeding their recommended load.”
“Who can teach Machine Learning?”
“What policies were considered during assignment generation?”

The system will interpret the question and display:

    a text answer, and/or
    a table (using the current plan and constraints), and/or
    a download link (for the Excel schedule).

## Notes:
- All examples in this repository use synthetic data by default.
- For real use, place your institution’s Excel and PDF policy files in data/raw/ and click Rebuild constraints before generating a plan.
- All constraint enforcement (loads, qualifications, time conflicts, etc.) is done by code. The LLM is used only to:
    (1) interpret your questions,
    (2) explain assignments or policies, and 
    (3) narrate suggested reassignments based on valid options computed by the app.


## How to Run the Evaluation

The evaluation runs the full pipeline (constraints extraction → OR‑Tools solver → room solver → validation → metrics) on synthetic data. Two scenarios are provided:
- **Case 1:** Low demand (fewer courses than faculty capacity)
- **Case 2:** High demand (more courses than faculty capacity)
All commands below assume you are in the project root (`faculty-load-assignment`).

### 1. Setup
Create and activate a virtual environment (if you haven’t already):

```bash
python -m venv .venv
source .venv/bin/activate      # macOS / Linux
# or
.venv\Scripts\activate         # Windows
```

Install dependencies and pytest:
```bash
python -m pip install -r requirements.txt
python -m pip install pytest
```

### 2. Case 1 – Low-demand scenario
Step 1 – Generate synthetic data
```bash
python create_sample_data_large.py
```
This creates:
data/raw/faculty.xlsx (20 synthetic faculty),
data/raw/courses.xlsx (≈25 sections),
data/raw/rooms.xlsx (7 rooms),
data/raw/workload_policy.pdf (synthetic policy).

Step 2 – Generate constraints
```bash
python -m src.agents.constraints_and_faculty_intel_agent
```
This reads the policy PDF and writes:
data/processed/constraints.json
data/processed/faculty_profiles.json

Step 3 – Run Evaluation
```bash
pytest tests/test_policy_consistency.py -vv -s
```
This will:
-run the OR‑Tools teaching‑load solver and the room solver
-validate the plan
-compute summary metrics

### 3. Case 2 – High-demand scenario
Step 1 – Generate synthetic data
```bash
python create_sample_data_large2.py
```
This creates:
data/raw/faculty.xlsx (20 synthetic faculty),
data/raw/courses.xlsx (41 sections),
data/raw/rooms.xlsx (7 rooms),
data/raw/workload_policy.pdf (same policy).

Step 2 – Generate constraints
```bash
python -m src.agents.constraints_and_faculty_intel_agent
```
This reads the policy PDF and writes:
data/processed/constraints.json
data/processed/faculty_profiles.json

Step 3 – Run Evaluation
```bash
pytest tests/test_policy_consistency.py -vv -s
```
This will:
-run the OR‑Tools teaching‑load solver and the room solver
-validate the plan
-compute summary metrics


## System Operation

1. Starting the System
The user launches the application by running the command "streamlit run app.py". On startup, app.py initializes the chat history, renders the sidebar quick actions, and waits for input. All subsequent operations begin either from a sidebar button or a typed message in the chat box.

2. Generating a Policy-Constrained Teaching Load Plan
This operation is triggered by the sidebar button "Generate Policy-constrained Teaching Load Assignment."

Step 2.1 — UI dispatch. The file app.py calls the handle_intent() function in supervisor_agent.py twice in sequence: first with the build_constraints intent, then with generate_plan.
Step 2.2 — Constraint extraction. The build_constraints intent invokes run_constraints_agent() in constraints_and_faculty_intel_agent.py. This agent performs four tasks: 
o	it calls load_faculty() in excel_loader.py, which parses faculty.xlsx into FacultyProfile objects (defined in faculty.py), including the preference dictionary mapped through PREFERENCE_COLUMNS; 
o	it calls extract_pdf_text() in pdf_loader.py to read workload_policy.pdf; 
o	it sends the policy text to the local LLM through ask_llm() in client.py (JSON mode, temperature 0), which returns the rules in a fixed schema; and 
o	it writes constraints.json and faculty_profiles.json to the processed data folder.
Step 2.3 — Faculty assignment (Stage 1). The generate_plan intent invokes run_assignment_agent() in assignment_and_negotiation_agent.py. With the default solver engine, it calls solve_assignments_with_ortools() in ortools_solver.py. The solver loads faculty and sections, scales credits to integers, builds the CP-SAT model (coverage, qualification, load-cap, evening-consent, preparation, and time-conflict constraints plus the weighted fairness objective), solves it, and returns a list of faculty–section assignments.
Step 2.4 — Room assignment (Stage 2). The function run_assignment_agent() then calls load_rooms() in excel_loader.py, which parses rooms.xlsx into Room objects (defined in room.py), and passes sections and rooms to solve_room_assignments() in room_solver.py. The room solver respects pre-assigned rooms, eliminates illegal pairings through room_allowed_for_section() (capacity, course-room restrictions, availability windows), forbids double-booking, and returns a section-to-room map, which is merged into the assignment records.
Step 2.5 — Independent validation (Validator). The complete plan is passed to validate_plan() in validators.py, which checks each rule category and returns a list of violations (for example, UNDERLOAD or ROOM UNAVAILABLE).
Step 2.6 — Persistence and display. The agent writes plan_draft_v1.json, containing the assignments, violations, and engine tag. Control returns to the Supervisor via app.py, which renders a confirmation message using render_result_st().

3. Answering a Natural-Language Query
Example: "Which faculty preferences could not be accommodated?"

Step 3.1 — Classification. The file app.py forwards the text to classify_intent() in supervisor_agent.py, which calls the LLM to produce an intent label and parameters. The original query text is preserved in the parameters.
Step 3.2 — Routing with safety nets. The handle_intent() function first applies deterministic keyword checks on the raw query (for example, any query containing "preference" routes to the preferences handler, regardless of the LLM's label). If no keyword rule matches, the intent label selects the handler from the INTENT_HANDLERS table.
Step 3.3 — Handler execution. The handler handle_unmet_preferences() loads the current plan, retrieves faculty and sections through the loaders, and runs each registered checker in the PREFERENCE_CHECKERS registry against each faculty member's assigned sections. The result is returned as a typed table structure.
Step 3.4 — Rendering. The file app.py receives the result dictionary and displays it as a table. The same pattern applies to all query intents: overloads and fairness through compute_metrics() in metrics.py, policy violations grouped through VIOLATION_POLICY_MAP, assignment explanations through an LLM call grounded in plan facts, and the data views for faculty, rooms, and courses.

4. Negotiating a Load Adjustment
Example: "Reduce Dr. Chen's load to 6 credits and increase Dr. Baker's to 9."

Step 4.1 — Routing. The Supervisor's keyword rules (terms such as "reduce" or "increase" together with "load") route the raw query to handle_negotiate_plan(), which delegates immediately to propose_negotiated_plan() in assignment_and_negotiation_agent.py. All negotiation logic resides in the agent, not the Supervisor.
Step 4.2 — Directive extraction. The function extract_negotiation_directives() sends the request and the faculty roster to the LLM, which returns typed directives (reduce_load or increase_load with target values). The parser defensively accepts format variations and discards malformed entries.
Step 4.3 — Sanity checks. The agent loads the current plan, computes present loads through compute_metrics(), and verifies that each directive is binding (a request already satisfied returns an "already satisfied" status without re-solving) and plausible (implausible extracted targets are rejected).
Step 4.4 — Constrained re-solve. The function run_assignment_agent() is called with the directives and the current assignments. The helper apply_negotiation_directives_to_loads() converts directives into per-faculty load caps and target minimums; the solver receives these along with the previous assignments, whose retention is rewarded by the stability term, ensuring the smallest change that satisfies the request. The result is written to plan_negotiation_pending.json, not to the current plan.
Step 4.5 — Diff and narration. The function compute_plan_diff() compares the old and new plans (moved sections, per-faculty load changes, violation and fairness changes), and narrate_diff() has the LLM summarize this computed difference in plain language.
Step 4.6 — Human decision. The proposal, difference table, and narrative are rendered with the question "Accept this plan? (Y/N)." The next user input is intercepted by try_handle_pending_decision() in the Supervisor before any classification occurs: an affirmative answer calls accept_pending_plan(), which promotes the pending file to the current plan; a negative answer calls reject_pending_plan(), which deletes the pending file and leaves the original plan untouched. Equivalent Accept and Reject buttons in the sidebar call the same functions.

5. Producing the Teaching Load Report
This operation is triggered by the sidebar button "Print Teaching Load Report + Excel."

Step 5.1 — Dispatch. The Supervisor's handle_admin_report() calls run_governance_agent() in decision_support_and_governance_agent.py.
Step 5.2 — Metrics computation. The agent loads the current plan and calls compute_metrics() in metrics.py to compute per-faculty loads, gaps, preparation, and evening counts, as well as department-level fairness statistics; room-related violations are summarized separately in the code.
Step 5.3 — Narrative generation. The computed metrics, violation list, and room summary are embedded into a report template and sent to the LLM, which composes the review narrative strictly from the provided figures.
Step 5.4 — Export. The function export_plan_to_excel() writes final_plan.xlsx with three views: the full assignment table (including rooms), a time-conflict sheet, and one timetable sheet per faculty member. The markdown report is saved alongside it.
Step 5.5 — Display. The report text and a download button for the Excel file are returned to app.py and rendered in the chat.

6. Cross-Cutting Observations
Three patterns recur across all five operations. First, agents coordinate through files: constraints.json, the plan JSON files, and the report artifacts form the interfaces between modules, making every intermediate state inspectable. Second, every plan passes through validate_plan() regardless of its origin (solver, LLM baseline, or human pre-assignment), so no unchecked schedule can reach the user. Third, every LLM invocation is bounded: classification, extraction, and narration all operate on code-prepared inputs, and their outputs are either verified (directives, assignments) or purely presentational (narratives), never authoritative.

7. Known Limitations
Evaluation completeness:  
•	Evaluation to date is qualitative on synthetic data; formal baseline comparison is scheduled as remaining work.
Model variability: 
•	Even with temperature=0, the LLM’s natural-language explanations can drift in style and sometimes emphasize weaker reasoning (e.g., weird narratives) even when the facts provided are correct. Classifier noise from the model is mitigated by keyword safety nets rather than eliminated.
-	Negotiation directive extraction occasionally requires exact phrasing; implausible targets are rejected by code-side sanity checks.
Privacy/design risks for real deployment: 
-	Currently uses only synthetic data. For real faculty data, it must be ensured that:
o	no raw data is committed or uploaded
o	it runs on an institution-controlled machine
