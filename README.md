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
#bash
python -m venv .venv
source .venv/bin/activate   # on macOS/Linux

2. Install Python dependencies:
#bash
pip install -r requirements.txt

3. (Optional, first-time only) Generate sample data for testing:
#bash
python create_sample_data.py

This creates example faculty.xlsx, courses.xlsx, and workload_policy.pdf in data/raw/. These are fake, for demonstration only.

4. Run the application. Start the Streamlit UI:
#bash
streamlit run app.py

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