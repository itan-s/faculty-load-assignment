# Teaching Load Assignment System (A multi-agent system)

This app helps automate faculty teaching load assignment using a local LLM, Python
agents, and a Streamlit UI. Once installed, you only need to run **Streamlit** and
use the browser interface.

---

## Application Overview

The **Faculty Teaching Load Assignment System** is a local, policy-aware decision-support application that helps academic departments create, review, revise, and report faculty teaching-load and room assignments.

The system combines a locally hosted large language model with deterministic optimization and validation tools. The LLM handles language-oriented tasks, while all scheduling decisions, policy checks, calculations, and exports are performed by conventional Python code. The department head remains responsible for reviewing and approving proposed changes.

### Core Technologies

- **Python 3**
  - Implements the agents, routing, data processing, validation, reporting, and application logic.

- **Streamlit**
  - Provides the web-based user interface, chat box, sidebar actions, tables, status messages, and download controls.

- **Ollama with `llama3.2:1b`**
  - Runs the LLM locally on the host machine.
  - No institutional data need to be sent to an external LLM service.
  - The model is used for:
    - extracting structured rules from the workload-policy document,
    - classifying ambiguous natural-language requests,
    - interpreting load-negotiation requests,
    - explaining assignment decisions,
    - narrating differences between current and proposed plans,
    - and writing report summaries from code-computed facts.

- **Google OR-Tools CP-SAT**
  - Performs deterministic faculty-to-section optimization.
  - The model considers:
    - course qualifications,
    - faculty load limits,
    - release credits,
    - evening consent,
    - maximum evening assignments,
    - maximum course preparations,
    - faculty schedule conflicts,
    - load fairness,
    - coverage,
    - and stability during plan negotiation.

- **OR-Tools Room Solver**
  - Assigns rooms and laboratories to sections.
  - It checks:
    - room capacity,
    - room availability,
    - course-room restrictions,
    - preassigned rooms,
    - room double-booking,
    - and preferences for preserving laboratories for restricted courses.

- **Deterministic Python Validator**
  - Independently checks every generated plan.
  - It detects:
    - unassigned or duplicate sections,
    - overloaded or policy-underloaded faculty,
    - unqualified assignments,
    - evening-consent violations,
    - excessive preparations or evening sections,
    - faculty time conflicts,
    - missing or prohibited rooms,
    - room-capacity violations,
    - unavailable rooms,
    - and room double-booking.

- **Deterministic Metrics Module**
  - Calculates exact workload and fairness values, including:
    - assigned credits per faculty,
    - required-versus-assigned load gaps,
    - number of assigned sections,
    - number of course preparations,
    - evening-section counts,
    - overload and underload counts,
    - and department-level load-gap variation.

- **Pandas and openpyxl**
  - Read faculty, course, and room data from Excel files.
  - Support tabular processing and creation of downloadable Excel outputs.

- **PyMuPDF**
  - Extracts text from the workload-policy PDF before the policy rules are structured by the local LLM.

- **JSON, Markdown, and Excel**
  - Store inspectable intermediate and final outputs, including policy constraints, faculty profiles, plans, negotiation proposals, governance reports, and final schedules.

### Multi-Agent Architecture

The system uses a supervisory layer and three specialist agents:

1. **Supervisor Agent**
   - Interprets user requests and routes them to the correct function.
   - Uses deterministic keyword rules for common requests and the LLM as a fallback for ambiguous language.

2. **Constraints and Faculty Intelligence Agent**
   - Reads the workload-policy PDF and faculty Excel file.
   - Uses the LLM to translate policy text into structured JSON constraints.
   - Uses deterministic code to build faculty profiles and calculate required loads.

3. **Assignment and Negotiation Agent**
   - Uses OR-Tools to generate faculty and room assignments.
   - Interprets requests to increase or decrease individual teaching loads.
   - Re-optimizes the plan and presents proposed changes for acceptance or rejection.

4. **Decision Support and Governance Agent**
   - Computes workload, fairness, room, and violation summaries.
   - Produces the governance report and downloadable Excel schedule.
   - Uses the LLM only to convert verified facts into a readable narrative.

### Human-in-the-Loop Operation

The application is designed as an assistant rather than an autonomous decision-maker. It generates draft plans, identifies violations, explains trade-offs, and proposes negotiated changes. A proposed negotiation is stored separately and does not replace the current plan until the user explicitly accepts it.

### Deterministic and LLM Responsibilities

| Function | Implementation |
|---|---|
| Policy text extraction | PyMuPDF |
| Policy rule structuring | Local Ollama LLM |
| Excel data ingestion | Pandas and openpyxl |
| Faculty assignment | OR-Tools CP-SAT |
| Room assignment | OR-Tools CP-SAT |
| Policy and schedule validation | Deterministic Python |
| Workload and fairness metrics | Deterministic Python |
| Common request routing | Deterministic keyword routing |
| Ambiguous intent classification | Local Ollama LLM |
| Negotiation directive extraction | Local Ollama LLM |
| Plan-difference calculation | Deterministic Python |
| Explanations and report narration | Local Ollama LLM |
| Report and schedule export | Python, Pandas, and openpyxl |
| Final approval | Department head |

This separation ensures that the LLM assists with understanding and communication, while authoritative scheduling, validation, and numerical calculations remain inspectable, reproducible, and code-controlled.

---

## Prerequisites

Before running the app, you need:

1. **Python** 3.10 or later
2. **Ollama** installed and running locally  
   Download from: https://ollama.com/download
3. At least one local LLM model pulled, for example:
```bash
ollama pull llama3.2:1b
```

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


## HOW TO USE THE APPLICATION VIA UI

The application can be controlled through the (1) sidebar quick actions or by (2) entering natural-language requests in the chat box.

### 0. Input Data
The application reads the following files:

1. data/raw/faculty.xlsx --> contains: 
    - FacultyID, 
    - Name (faculty name), 
    - Rank, BaseLoadCredits (standard load credits), 
    - ReleaseCredits (pre-assigned credits, if any), 
    - QualifiedCourses (course codes separated by comma), 
    - PreferredDays (e.g., M, T, W, Th, F, S, or any), 
    - AcceptsEvening (Y or N).

2. data/raw/courses.xlsx --> contains: 
    - CourseCode, 
    - Section, 
    - Title (course title), 
    - Credits, 
    - Days, 
    - StartTime, 
    - EndTime, 
    - Evening (Y or N), 
    - Enrollment (Number of students), 
    - AllowedRooms (room numbers preferred for the course), 
    - Room (preferred room type e.g., Laboratory or Lecture)  

3. data/raw/rooms.xlsx --> contains:
    - RoomID
    - Building
    - Capacity
    - Availability (Y or N)
    - RoomType (i.e., Lecture or Laboratory)

4. data/raw/workload_policy.pdf --> workload policies in natural language

The above four (4) files can be generated synthetically by running:
create_sample_data*.py files

For institutional use, replace these files while preserving the expected columns and formats. Generate a new plan afterward so that the policy constraints and assignments are rebuilt.

### 1. Sidebar Quick Actions

#### Generate Policy-Constrained Teaching Load Assignment Plan

Runs the main planning workflow:

1. Reads the faculty, course, room, and workload-policy files.
2. Extracts structured policy constraints.
3. Assigns qualified faculty to course sections using OR-Tools.
4. Assigns classrooms and laboratories.
5. Validates the completed plan.
6. Saves the draft plan to:

data/processed/plan_draft_v1.json

#### Show Teaching Load Assignment Table

Displays three views of the current plan:

1. Assignment by Section

    Course and section
    Assigned faculty
    Credits and schedule
    Assigned room
    Related violations
    
2. Teaching Load Summary by Faculty

    Required load
    Assigned credits
    Load gap
    Number of assigned sections
    Overload or underload status
    Related violations

3. Room Assignment Schedule

    Room, building, and capacity
    Assigned section and faculty
    Meeting schedule
    Room-related violations
    A plan must be generated before these tables can be displayed.

#### Print Teaching Load Report + Excel
Generates:
    A teaching-load governance report
    A downloadable Excel schedule containing:
        - all assignments,
        - a time-conflict sheet,
        - and one timetable sheet per faculty member.

The files are written to:

    data/processed/governance_report.md
    data/processed/final_plan.xlsx

#### Show Faculty
Displays:

    Faculty ID and name
    Academic rank
    Required teaching load
    Specialization or qualified courses
    Recorded preferences

#### Show Courses Offered
    Lists all course sections, including course codes, titles, credits, and meeting schedules.

#### Show Rooms
Lists classrooms and laboratories, including capacity, room type, availability, and operating hours.

#### Show Policy
Displays the workload policies and constraints extracted from the policy PDF.

#### Fairness Issues
Displays workload-distribution information, including:

    Faculty at their exact required load
    Faculty below their target load
    Overloaded faculty
    Load-gap variation
    Evening-section distribution

A faculty member who is below their target load is not necessarily violating the minimum-load policy. A policy underload occurs only when the assigned load is below the minimum stated in the policy.

#### Policy Violations
Lists violations in the current plan, including:

    Unassigned or duplicate sections
    Overloads and policy underloads
    Unqualified assignments
    Evening-consent violations
    Excessive preparations or evening sections
    Faculty time conflicts
    Room capacity, availability, restriction, or double-booking issues

#### Unmet Preferences
Shows faculty preferences that could not be accommodated, such as preferred teaching days or evening-class preferences.

#### Suggest Improvements
Suggests valid reassignment options for current violations.

Candidate changes are computed deterministically using faculty qualifications, available load capacity, and evening consent. The LLM only explains the valid options produced by the application.

### 2. Recommended Workflow
A complete workflow can be performed using the sidebar:

1. Click Generate Policy-Constrained Teaching Load Assignment Plan.
2. Click Show Teaching Load Assignment Table.
3. Review the section, faculty-load, and room-assignment tables.
4. Inspect Fairness Issues, Policy Violations, and Unmet Preferences.
5. Use Suggest Improvements if violations remain.
6. Click Print Teaching Load Report + Excel.
7. Download the generated Excel schedule.

### 3. Natural-Language Chat
The chat box accepts natural-language requests. A guide containing suggested phrases is also displayed in the application.

Example requests include:

- Show teaching load assignment.
- Show faculty.
- Show courses offered.
- Show rooms.
- Show policy.
- Show policy violations.
- Who is overloaded?
- Who is below the minimum load?
- Show fairness issues.
- Which faculty preferences were not accommodated?
- Who can teach <COURSE_CODE>?
- Why was <FACULTY_NAME> assigned to <COURSE_CODE>?
- Suggest policy compliance improvements.
- Generate the administrative report.

Replace placeholders such as <FACULTY_NAME> and <COURSE_CODE> with values from the current dataset.

Depending on the request, the system may return:

    - A text response
    - One or more tables
    - A proposed negotiated plan
    - A downloadable Excel file

Common commands are routed using deterministic rules. The local LLM is used as a fallback for ambiguous language and parameter extraction.

### 4. Teaching-Load Negotiation
The chat supports requests to increase or decrease individual faculty teaching loads.

Example:
Reduce <FACULTY_A>'s load to 6 credits and increase <FACULTY_B>'s load to 9 credits.

The system will:

1. Convert the request into structured load directives.
2. Check the current faculty loads.
3. Re-run the assignment solver using the requested caps and targets.
4. Attempt to preserve existing assignments where possible.
5. Compare the proposed plan with the current plan.
6. Present the proposed changes for review.

The proposed plan is not applied automatically. The user must select Accept or Reject, or reply with Yes or No.

- Accept makes the proposed plan the current plan.
- Reject discards the proposal and preserves the original plan.

A request may produce no change if it is already satisfied or cannot be achieved under the current qualifications, course offerings, schedules, rooms, and policy constraints.

### 5. Generated Files
The application creates inspectable artifacts in data/processed/, including:

    1. constraints.json
    2. faculty_profiles.json
    3. plan_draft_v1.json
    4. plan_negotiation_pending.json
    5. negotiation_context.json
    6. governance_report.md
    7. final_plan.xlsx

These files contain the extracted constraints, generated plans, pending negotiations, reports, and exports.

### 6. Role of the Local LLM
The LLM is used for language-related tasks:

Extracting structured rules from the policy PDF
Interpreting ambiguous user requests
Extracting negotiation directives
Explaining assignment decisions
Narrating proposed plan changes
Writing report summaries from computed facts
The LLM does not independently validate or approve schedules.

Faculty assignment, room assignment, constraint enforcement, validation, and metric calculation are performed by deterministic Python code and OR-Tools. The department head retains final authority over negotiated changes.


## HOW TO RUN THE TEST/EVALUATION

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


## SYSTEM OPERATION

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