import json
from src.ingestion.pdf_loader import extract_pdf_text
from src.ingestion.excel_loader import load_faculty
from src.llm.client import ask_llm

SYSTEM_PROMPT = """You are a university policy analyst. You extract teaching
workload rules from policy documents and express them as precise JSON.
Only use information explicitly stated in the document."""

USER_PROMPT_TEMPLATE = """Read this policy document and extract the rules into JSON
with EXACTLY this structure:

{{
  "standard_load_tenure_track": <number>,
  "standard_load_lecturer": <number>,
  "min_load_full_time": <number>,
  "max_evening_sections": <number>,
  "max_preparations": <number>,
  "qualification_required": <true/false>,
  "evening_consent_required": <true/false>
}}

POLICY DOCUMENT:
{policy_text}
"""

def run_constraints_agent():
    # --- LLM job: extract rules from the policy PDF ---
    print("Reading policy PDF...")
    policy_text = extract_pdf_text("data/raw/workload_policy.pdf")

    print("Asking LLM to extract rules (this may take ~30s)...")
    reply = ask_llm(SYSTEM_PROMPT,
                    USER_PROMPT_TEMPLATE.format(policy_text=policy_text),
                    json_mode=True)
    constraints = json.loads(reply)

    with open("data/processed/constraints.json", "w") as f:
        json.dump(constraints, f, indent=2)
    print("Saved data/processed/constraints.json:")
    print(json.dumps(constraints, indent=2))

    # --- Code job: build faculty profiles from Excel (deterministic) ---
    profiles = [f.model_dump() | {"required_load": f.required_load}
                for f in load_faculty()]
    with open("data/processed/faculty_profiles.json", "w") as f:
        json.dump(profiles, f, indent=2)
    print(f"Saved {len(profiles)} profiles to data/processed/faculty_profiles.json")

if __name__ == "__main__":
    run_constraints_agent()
