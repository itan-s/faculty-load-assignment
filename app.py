"""Streamlit UI for the Faculty Teaching Load Assignment System.
Run with:  streamlit run app.py
"""
import os
import json
from collections import defaultdict
import re

import pandas as pd
import streamlit as st

from src.agents.supervisor_agent import (
    classify_intent, handle_intent, try_handle_pending_decision,
)
from src.agents.assignment_and_negotiation_agent import negotiation_pending
from src.ingestion.excel_loader import load_faculty, load_sections, load_rooms
from src.validation.validators import validate_plan
from src.validation import metrics as metrics_module


# ---------------------------------------------------------------
# Page setup
# ---------------------------------------------------------------
st.set_page_config(
    page_title="Teaching Load Assignment System",
    page_icon="🎓",
    layout="wide",
)

# Main title with Marian-colored accent line
st.markdown(
    """
    <h1 style="margin-bottom:0;">Teaching Load Assignment System</h1>
    <p style="margin-top:0.25rem; color:#00338D; font-weight:600;">
        (A multi-agent system)
    </p>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    "<hr style='border: 2px solid #FFCC00; margin-top:0.5rem; margin-bottom:1.5rem;'/>",
    unsafe_allow_html=True,
)

st.caption("Ask questions in natural language, or use the quick actions in the sidebar.")


# ---------------------------------------------------------------
# Suggested chat phrases
# ---------------------------------------------------------------
CHAT_GUIDE = [
    (
        "Planning",
        "Generate a new teaching load assignment plan",
        "Builds a policy-constrained faculty and room assignment plan.",
    ),
    (
        "Assignments",
        "Show teaching load assignment",
        "Shows section, faculty-load, and room-assignment tables with violations.",
    ),
    (
        "Faculty",
        "Show faculty",
        "Lists faculty, required loads, qualifications, and preferences.",
    ),
    (
        "Courses",
        "Show courses offered",
        "Lists all offered course sections and schedules.",
    ),
    (
        "Rooms",
        "Show rooms",
        "Lists classrooms, laboratories, capacities, and availability.",
    ),
    (
        "Policy",
        "Show policy",
        "Shows the workload policies and constraints used by the system.",
    ),
    (
        "Violations",
        "Show policy violations",
        "Lists the current plan's violations grouped by policy.",
    ),
    (
        "Underload",
        "Who is below the minimum load?",
        "Shows faculty below the policy minimum teaching load.",
    ),
    (
        "Overload",
        "Who is overloaded?",
        "Shows faculty whose assigned credits exceed their required load.",
    ),
    (
        "Fairness",
        "Show fairness issues",
        "Shows workload gaps and department-level fairness statistics.",
    ),
    (
        "Preferences",
        "Which faculty preferences were not accommodated?",
        "Shows recorded faculty preferences that were not satisfied.",
    ),
    (
        "Qualifications",
        "Who can teach <COURSE_CODE>?",
        "Lists faculty qualified to teach the specified course.",
    ),
    (
        "Explanation",
        "Why was <FACULTY_NAME> assigned to <COURSE_CODE>?",
        "Explains an assignment using plan facts and policy constraints.",
    ),
    (
        "Negotiation",
        "Reduce <FACULTY_A>'s load to <CREDITS> credits and increase <FACULTY_B>'s load to <CREDITS> credits",
        "Proposes a re-optimized plan when the requested adjustment is feasible.",
    ),
    (
        "Improvement",
        "Suggest policy compliance improvements",
        "Suggests valid reassignment options for current violations.",
    ),
    (
        "Report",
        "Generate the administrative report",
        "Produces the teaching-load report and downloadable Excel schedule.",
    ),
]


def render_chat_guide(expanded: bool = False, title: str = "Suggested Chat Phrases"):
    """Display a guide to supported natural-language requests."""
    with st.expander(f"💬 {title}", expanded=expanded):
        st.caption(
            "Type any of the example phrases below in the chat box. "
        )
        st.caption(
            "Replace placeholders such as <FACULTY_NAME>, <COURSE_CODE>, and "
            "<CREDITS> with values from the current dataset."
            )


        guide_rows = [
            {
                "Function": category,
                "Example phrase": phrase,
                "What it does": description,
            }
            for category, phrase, description in CHAT_GUIDE
        ]

        st.dataframe(
            pd.DataFrame(guide_rows),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Function": st.column_config.TextColumn(width="small"),
                "Example phrase": st.column_config.TextColumn(width="large"),
                "What it does": st.column_config.TextColumn(width="large"),
            },
        )

# Display a one-time startup notification.
if "chat_guide_toast_shown" not in st.session_state:
    st.toast(
        "💬 New here? Open the Suggested Chat Phrases guide below.",
        icon="ℹ️",
    )
    st.session_state.chat_guide_toast_shown = True

# Display the full guide near the top of the app.
render_chat_guide(
    expanded=True,
    title="What You Can Ask the System",
)


# ---------------------------------------------------------------
# Result renderer — the UI twin of render_result() in the CLI
# ---------------------------------------------------------------
def render_result_st(result: dict, key: str = "live"):
    rtype = result.get("type", "text")

    if rtype == "error":
        st.error(result.get("content", "Unknown error"))
        return

    title = result.get("title")
    if title:
        st.subheader(title)

    content = result.get("content")
    if content:
        st.markdown(content)

    if rtype == "table":
        rows = result.get("rows", [])
        if rows:
            st.dataframe(rows, use_container_width=True)

    if rtype == "file":
        path = result.get("path", "")
        if path and os.path.exists(path):
            with open(path, "rb") as f:
                st.download_button(
                    label=f"⬇️ Download {os.path.basename(path)}",
                    data=f.read(),
                    file_name=os.path.basename(path),
                    mime=(
                        "application/vnd.openxmlformats-"
                        "officedocument.spreadsheetml.sheet"
                    ),
                    key=f"download_{key}",
                )
        elif path:
            st.warning(f"File not found yet: {path}")


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------
def index_violations_by_faculty_and_section(violations: list[str]):
    by_faculty = defaultdict(list)
    by_section = defaultdict(list)

    for v in violations:
        # faculty after OVERLOAD/UNDERLOAD/TIME CONFLICT
        m_fac = re.search(r"(OVERLOAD|UNDERLOAD|TIME CONFLICT):\s+(.+?)\s+has", v)
        if m_fac:
            faculty_name = m_fac.group(2).strip()
            by_faculty[faculty_name].append(v)

        # section IDs like CS101-01
        m_secs = re.findall(r"\b[A-Z]{2,}\d{3}-\d{2}\b", v)
        for sid in m_secs:
            by_section[sid].append(v)

        # NO ROOM: CS201-01 has no room assigned
        m_sec2 = re.search(r"NO ROOM:\s+([A-Z]{2,}\d{3}-\d{2})", v)
        if m_sec2:
            by_section[m_sec2.group(1).strip()].append(v)

    return by_faculty, by_section


def build_dict_views_from_current_plan(plan_path: str = "data/processed/plan_draft_v1.json"):
    """Load the current plan JSON and build
    assignments + faculty_by_id + sections_by_id + rooms_by_id + constraints.
    """
    if not os.path.exists(plan_path):
        return None, None, None, None, None

    with open(plan_path, "r") as f:
        plan = json.load(f)

    # Expect plan["assignments"] as list of dicts with faculty_id, section_id, room
    assignments = plan.get("assignments", [])

    # Load full faculty/sections/rooms from Excel so required_load, etc. are correct
    faculty = load_faculty()
    sections = load_sections()
    rooms = load_rooms()

    faculty_by_id = {
        f.faculty_id: {
            "faculty_id": f.faculty_id,
            "name": f.name,
            "rank": f.rank,
            "required_load": f.required_load,
            "qualified_courses": list(f.qualified_courses),
            "preferences": f.preferences or {},
        }
        for f in faculty
    }

    sections_by_id = {
        s.section_id: {
            "section_id": s.section_id,
            "course_code": s.course_code,
            "title": s.title,
            "credits": s.credits,
            "days": s.days,
            "start_time": s.start_time,
            "end_time": s.end_time,
            "evening": bool(s.evening),
            "enrollment": s.enrollment,
            "allowed_rooms": list(s.allowed_rooms or []),
        }
        for s in sections
    }

    rooms_by_id = {
        r.room_id: {
            "room_id": r.room_id,
            "building": r.building,
            "capacity": r.capacity,
            "available": r.available,
            "availability": r.availability,
            "room_type": r.room_type,
        }
        for r in rooms
    }

    # Load constraints.json for caps, min load, preps, etc.
    constraints_path = "data/processed/constraints.json"
    if os.path.exists(constraints_path):
        with open(constraints_path, "r") as f:
            constraints = json.load(f)
    else:
        constraints = {
            "max_preparations": 3,
            "max_evening_sections": 2,
            "min_load_full_time": 6,
        }

    return assignments, faculty_by_id, sections_by_id, rooms_by_id, constraints


def show_assignment_and_faculty_summaries():
    """Show section-level assignment table, faculty summary, and room schedule with violations."""
    plan_path = "data/processed/plan_draft_v1.json"
    assignments, faculty_by_id, sections_by_id, rooms_by_id, constraints = \
        build_dict_views_from_current_plan(plan_path)

    if not assignments:
        st.info("No current plan found yet. Generate a plan first.")
        return

    # Validate and compute metrics
    violations = validate_plan(
        assignments=assignments,
        faculty_by_id=faculty_by_id,
        sections_by_id=sections_by_id,
        constraints=constraints,
        rooms_by_id=rooms_by_id,
    )

    m = metrics_module.compute_metrics(
        assignments=assignments,
        faculty_by_id=faculty_by_id,
        sections_by_id=sections_by_id,
    )
    per_faculty = m["per_faculty"]

    by_faculty, by_section = index_violations_by_faculty_and_section(violations)

    # 1) Per-section assignment table
    rows_sec = []
    for a in assignments:
        sid = a["section_id"]
        fid = a["faculty_id"]
        sec = sections_by_id.get(sid)
        f = faculty_by_id.get(fid)
        if not sec or not f:
            continue
        sec_violations = by_section.get(sid, [])
        rows_sec.append({
            "SectionID": sid,
            "CourseCode": sec["course_code"],
            "Title": sec.get("title", ""),
            "Credits": sec["credits"],
            "Days": sec["days"],
            "Time": f"{sec['start_time']}-{sec['end_time']}",
            "Faculty": f["name"],
            "Room": a.get("room"),
            "#Violations": len(sec_violations),
            "Violations": "; ".join(sec_violations),
        })
    df_sections = pd.DataFrame(rows_sec)

    # 2) Per-faculty summary table
    rows_fac = []
    for fid, info in per_faculty.items():
        name = info["name"]
        fac_violations = by_faculty.get(name, [])
        rows_fac.append({
            "Faculty": name,
            "Rank": info["rank"],
            "Required Load": info["required_load"],
            "Assigned Credits": info["assigned_credits"],
            "Load Gap": info["load_gap"],
            "#Sections": info["num_sections"],
            "Overload?": any("OVERLOAD" in v.upper() for v in fac_violations),
            "Underload?": any("UNDERLOAD" in v.upper() for v in fac_violations),
            "#Violations": len(fac_violations),
            "Violations": "; ".join(fac_violations),
        })
    df_faculty = pd.DataFrame(rows_fac)

    # 3) Room schedule table with violations
    rows_rooms = []
    for a in assignments:
        sid = a["section_id"]
        rid = a.get("room")
        if not rid:
            continue
        sec = sections_by_id.get(sid)
        room = rooms_by_id.get(rid)
        fid = a["faculty_id"]
        f = faculty_by_id.get(fid)
        if not sec or not room or not f:
            continue

        sec_violations = by_section.get(sid, [])
        room_related = [v for v in sec_violations if "ROOM" in v.upper()]

        rows_rooms.append({
            "Room": rid,
            "Building": room["building"],
            "Capacity": room["capacity"],
            "SectionID": sid,
            "CourseCode": sec["course_code"],
            "Credits": sec["credits"],
            "Days": sec["days"],
            "Time": f"{sec['start_time']}-{sec['end_time']}",
            "Faculty": f["name"],
            "#Room Violations": len(room_related),
            "Room Violations": "; ".join(room_related),
        })
    df_rooms = pd.DataFrame(rows_rooms).sort_values(["Room", "Days", "Time"])

    # Render all three tables
    st.subheader("Teaching Load Assignment by Section (with Violations)")
    st.dataframe(df_sections, use_container_width=True)

    st.subheader("Teaching Load Summary by Faculty")
    st.dataframe(df_faculty, use_container_width=True)

    st.subheader("Room Assignment Schedule (with Room Violations)")
    st.dataframe(df_rooms, use_container_width=True)


def show_faculty_details():
    """Show enriched faculty table with specialization and preferences."""
    faculty = load_faculty()

    rows = []
    for f in faculty:
        specialization = ", ".join(f.qualified_courses)
        prefs_str = ", ".join(f"{k}={v}" for k, v in (f.preferences or {}).items())

        rows.append({
            "Faculty ID": f.faculty_id,
            "Name": f.name,
            "Rank": f.rank,
            "Required Load": f.required_load,
            "Specialization (Qualified Courses)": specialization,
            "Preferences": prefs_str,
        })

    df = pd.DataFrame(rows)
    st.subheader("Faculty Details (with Specialization and Preferences)")
    st.dataframe(df, use_container_width=True)


# ---------------------------------------------------------------
# Chat history (survives reruns within a session)
# ---------------------------------------------------------------
if "history" not in st.session_state:
    st.session_state.history = []   # list of {"question": str, "result": dict}


# ---------------------------------------------------------------
# Sidebar: quick actions (bypass the classifier — direct intents)
# ---------------------------------------------------------------
with st.sidebar:
    st.markdown(
        "<h3 style='color:#00338D;'>Quick Actions</h3>",
        unsafe_allow_html=True,
    )

    QUICK_ACTIONS = {
        "🔄 Generate Policy-Constrained Teaching Load Assignment Plan": "rebuild_and_generate",
        "📚 Show Teaching Load Assignment Table": "show_courses_and_rooms",
        "📊 Print Teaching Load Report + Excel": "generate_admin_report",
        "👥 Show faculty": "show_faculty",
        "📘 Show courses offered": "show_courses_offered",
        "🏫 Show rooms": "show_rooms",
        "📜 Show policy": "show_policy",
        "⚖️ Fairness issues": "show_fairness_issues",
        "🚨 Policy violations": "policy_violations",
        "💤 Unmet preferences": "unmet_preferences",
        "💡 Suggest improvements": "suggest_compliance_improvements",
    }

    for label, intent in QUICK_ACTIONS.items():
        if st.button(label, width="stretch", key=f"qa_{intent}"):
            with st.spinner("Working..."):
                params = {"original_query": label.lower()}

                if intent == "rebuild_and_generate":
                    # 1. Rebuild constraints
                    params = {"original_query": "build constraints"}
                    r1 = handle_intent("build_constraints", params)
                    # 2. Generate plan
                    params = {"original_query": "generate plan"}
                    r2 = handle_intent("generate_plan", params)

                    content = "\n\n".join(
                        filter(None, [r1.get("content"), r2.get("content")])
                    ).strip()
                    result = {
                        "type": "text",
                        "title": "Generate Policy-Constrained Teaching Load Assignment",
                        "content": (
                            content
                            or "Constraints rebuilt and new policy-constrained teaching load "
                               "assignment generated."
                        ),
                    }
                else:
                    # For "📜 Show policy", "👥 Show faculty", and others, let Supervisor handle it
                    result = handle_intent(intent, params)
                    
                    # Tell the UI to render the three detailed assignment tables.
                    if intent == "show_courses_and_rooms":
                        result["show_assignment_details"] = True

                st.session_state.history.append({"question": label, "result": result})
                st.rerun()

    # --- Pending negotiation proposal: Accept / Reject ---
    if negotiation_pending():
        st.divider()
        st.markdown("<h4 style='color:#00338D;'>Pending proposal</h4>",
                    unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        if col1.button("✅ Accept", use_container_width=True, key="accept_proposal"):
            result = try_handle_pending_decision("yes")
            st.session_state.history.append(
                {"question": "Accept proposal", "result": result})
            st.rerun()
        if col2.button("❌ Reject", use_container_width=True, key="reject_proposal"):
            result = try_handle_pending_decision("no")
            st.session_state.history.append(
                {"question": "Reject proposal", "result": result})
            st.rerun()

    st.divider()
    if st.button("🧹 Clear conversation", width="stretch", key="clear_history"):
        st.session_state.history = []
        st.rerun()


# ---------------------------------------------------------------
# Main area: conversation history + chat input
# ---------------------------------------------------------------
for i, turn in enumerate(st.session_state.history):
    with st.chat_message("user"):
        st.write(turn["question"])

    with st.chat_message("assistant"):
        result = turn["result"]

        if result.get("show_assignment_details"):
            show_assignment_and_faculty_summaries()
        else:
            render_result_st(result, key=str(i))

        if turn["question"] == "👥 Show faculty":
            show_faculty_details()

    # Only display suggestions after the latest response.
    if i == len(st.session_state.history) - 1:
        render_chat_guide(
            expanded=False,
            title="What Would You Like to Do Next?",
        )

question = st.chat_input("Ask about teaching assignments, policies, fairness...")

if question:
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        decision_result = try_handle_pending_decision(question)

        if decision_result is not None:
            result = decision_result
        else:
            with st.spinner("Thinking..."):
                intent, params = classify_intent(question)
                
                if intent == "show_courses_and_rooms":
                    # Do not generate the original courses table.
                    result = {"type": "text", "show_assignment_details": True,}
                else: result = handle_intent(intent, params)

        render_result_st(result)

    st.session_state.history.append({
        "question": question,
        "result": result,
    })
    st.rerun()
