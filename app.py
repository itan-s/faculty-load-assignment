"""Streamlit UI for the Faculty Teaching Load Assignment System.
Run with:  streamlit run app.py
"""
import os
import streamlit as st
from src.agents.supervisor_agent import (
    classify_intent, handle_intent, try_handle_pending_decision,
)
from src.agents.assignment_and_negotiation_agent import negotiation_pending

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
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"download_{key}",          # ← unique per render position
                )
        elif path:
            st.warning(f"File not found yet: {path}")

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

    # CLIENT-CONFIG: adjust quick actions per client
    QUICK_ACTIONS = {
        "🔄 Generate Policy-Constrained Teaching Load Assignment": "rebuild_and_generate",
        "📚 Show Teaching Load Assignment Table": "show_courses_and_rooms",
        "📊 Print Teaching Load Report + Excel": "generate_admin_report",
        "👥 Show faculty": "show_faculty",
        "📘 Show courses offered": "show_courses_offered",
        "🏫 Show rooms": "show_rooms",                
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

                    # Combine messages (optional)
                    content = "\n\n".join(
                        filter(None, [r1.get("content"), r2.get("content")])
                    ).strip()
                    result = {
                        "type": "text",
                        "title": "Generate Policy-Constrained Teaching Load Assignment safely",
                        "content": (
                            content
                            or "Constraints rebuilt and new policy-constrained teaching load "
                               "assignment generated."
                        ),
                    }

                else:
                    # Diagnostics, reports, data views
                    result = handle_intent(intent, params)

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
        render_result_st(turn["result"], key=str(i))

question = st.chat_input("Ask about teaching assignments, policies, fairness...")

if question:
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        # Pending negotiation decision takes priority over intent routing
        decision_result = try_handle_pending_decision(question)
        if decision_result is not None:
            result = decision_result
        else:
            with st.spinner("Thinking..."):
                intent, params = classify_intent(question)
                result = handle_intent(intent, params)
        render_result_st(result)
    st.session_state.history.append({"question": question, "result": result})
    st.rerun()