"""Streamlit UI for the Faculty Teaching Load Assignment System.
Run with:  streamlit run app.py
"""
import os
import streamlit as st

from src.agents.supervisor_agent import classify_intent, handle_intent

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
def render_result_st(result: dict):
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
        "📋 Rebuild constraints": "build_constraints",
        "🗓 Generate new plan": "generate_plan",
        "♻️ Recalculate plan": "recalculate_plan",
        "📊 Admin report + Excel": "generate_admin_report",
        "⚖️ Fairness issues": "show_fairness_issues",
        "🚨 Policy violations": "policy_violations",
        "👥 Show faculty": "show_faculty",
        "💤 Unmet preferences": "unmet_preferences",
        "💡 Suggest improvements": "suggest_compliance_improvements",
    }

    for label, intent in QUICK_ACTIONS.items():
        if st.button(label, use_container_width=True):
            with st.spinner("Working..."):
                # Direct routing; keyword nets still apply inside handle_intent
                params = {"original_query": label.lower()}
                if intent == "policy_violations":
                    # routed via keyword net: query contains "violations"
                    params["original_query"] = "which policies are violated"
                    result = handle_intent("unknown", params)
                else:
                    result = handle_intent(intent, params)
            st.session_state.history.append(
                {"question": label, "result": result})
            st.rerun()

    st.divider()
    if st.button("🧹 Clear conversation", use_container_width=True):
        st.session_state.history = []
        st.rerun()

# ---------------------------------------------------------------
# Main area: conversation history + chat input
# ---------------------------------------------------------------
for turn in st.session_state.history:
    with st.chat_message("user"):
        st.write(turn["question"])
    with st.chat_message("assistant"):
        render_result_st(turn["result"])

question = st.chat_input("Ask about teaching assignments, policies, fairness...")

if question:
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            intent, params = classify_intent(question)
            result = handle_intent(intent, params)
        render_result_st(result)
    st.session_state.history.append({"question": question, "result": result})
