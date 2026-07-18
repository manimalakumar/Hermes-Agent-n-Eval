from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from retail_agent.db import reset_demo_db, resolve_db_path
from retail_agent.tools import get_audit_trace, read_order
from retail_agent.workflow import RetailWorkflow


st.set_page_config(page_title="Retail Agent", page_icon="RA", layout="wide")

st.markdown(
    """
    <style>
    .main .block-container {padding-top: 1.25rem; max-width: 1180px;}
    div[data-testid="stMetric"] {background: #ffffff; border: 1px solid #e5e7eb; padding: 0.65rem; border-radius: 8px;}
    .agent-step {background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 0.75rem; margin-bottom: 0.5rem;}
    .small-muted {color: #667085; font-size: 0.85rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


DB_PATH = resolve_db_path()


def reset_session() -> None:
    reset_demo_db(DB_PATH)
    st.session_state.workflow_state = RetailWorkflow.empty_state()
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "Hi - how can I help you today!",
        }
    ]
    st.session_state.last_steps = []
    st.session_state.last_extracted = {}


if "messages" not in st.session_state:
    reset_session()

with st.sidebar:
    st.subheader("Demo Controls")
    if st.button("Reset Demo Data", use_container_width=True):
        reset_session()
        st.rerun()
    st.caption(f"Database: `{Path(DB_PATH).name}`")
    key_status = "set" if os.getenv("NVIDIA_API_KEY") else "using Hermes auth"
    backend = os.getenv("RETAIL_AGENT_LLM_MODE", "auto")
    st.metric("NVIDIA Key", key_status)
    st.metric("LLM Backend", backend)
    st.metric("Model", os.getenv("RETAIL_AGENT_MODEL", "nvidia/nemotron-3-super-120b-a12b"))

    st.subheader("Demo Customer")
    st.code("jamie@example.com\n98101\nORD-1001", language="text")

st.title("Retail Address Update Agent")

top_left, top_right = st.columns([0.62, 0.38], gap="large")

with top_left:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    prompt = st.chat_input("Message the support agent")
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        workflow = RetailWorkflow(DB_PATH)
        try:
            result = workflow.handle(prompt, st.session_state.workflow_state)
            st.session_state.workflow_state = result.state
            st.session_state.last_steps = result.steps
            st.session_state.last_extracted = result.extracted
            st.session_state.messages.append({"role": "assistant", "content": result.reply})
        except Exception as exc:
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": f"The live model call failed: {exc}",
                }
            )
        st.rerun()

with top_right:
    state = st.session_state.workflow_state
    st.subheader("Case State")
    cols = st.columns(3)
    cols[0].metric("Verified", "yes" if state.get("customer_id") else "no")
    cols[1].metric("Order", state.get("order_id") or "-")
    cols[2].metric("Stage", state.get("awaiting") or "-")

    st.subheader("Agent Trace")
    if not st.session_state.last_steps:
        st.caption("No tool steps yet.")
    for step in st.session_state.last_steps:
        status = "pass" if step.ok else "needs attention"
        st.markdown(
            f"""
            <div class="agent-step">
              <strong>{step.agent}</strong><br/>
              <span class="small-muted">{step.task} · {status}</span><br/>
              {step.detail}
            </div>
            """,
            unsafe_allow_html=True,
        )

    if state.get("order_id"):
        st.subheader("Order Snapshot")
        order_result = read_order(state["order_id"], DB_PATH)
        if order_result.get("ok"):
            st.json(order_result["order"])

    with st.expander("Last LLM Extraction", expanded=False):
        st.json(st.session_state.last_extracted)

    with st.expander("Audit Events", expanded=False):
        st.json(get_audit_trace(DB_PATH).get("events", []))
