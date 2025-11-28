"""
Streamlit Frontend for the Interactive Research Workflow
========================================================

This application mirrors the clarifications-first workflow defined in
`run_interactive_research_workflow.py` and provides a richer UI for:
• launching or resuming Temporal workflows
• answering clarifying questions
• tracking live status
• downloading Markdown outputs once research completes
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import streamlit as st
from dotenv import load_dotenv
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

# Ensure repository root is importable when Streamlit changes cwd
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(REPO_ROOT))

from openai_agents.workflows.interactive_research_workflow import (
    InteractiveResearchResult,
    InteractiveResearchWorkflow,
)
from openai_agents.workflows.research_agents.research_models import (
    SingleClarificationInput,
    UserQueryInput,
)
from streamlit_utils import FileManager, run_async

# ---------------------------------------------------------------------------
# Environment + configuration
# ---------------------------------------------------------------------------
load_dotenv(dotenv_path=".env", override=True)

TEMPORAL_ENDPOINT = os.getenv("TEMPORAL_ENDPOINT")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
TEMPORAL_API_KEY = os.getenv("TEMPORAL_API_KEY")
TEMPORAL_TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "research-queue")
TEMPORAL_CONNECT_CLOUD = os.getenv("CONNECT_CLOUD", "N")
TEMPORAL_TLS = os.getenv("TEMPORAL_TLS", "true").lower() in {"1", "true", "yes"}
DEFAULT_WORKFLOW_PREFIX = os.getenv(
    "STREAMLIT_WORKFLOW_PREFIX", "interactive-research"
)

file_manager = FileManager(output_dir="./ui/reports")


# ---------------------------------------------------------------------------
# Streamlit set up
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Interactive Research Orchestrator",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
        .status-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.35rem 0.85rem;
            border-radius: 999px;
            font-weight: 600;
            background: rgba(102, 126, 234, 0.12);
            border: 1px solid rgba(102, 126, 234, 0.35);
        }
        .question-card {
            border-radius: 12px;
            padding: 1rem;
            border: 1px solid rgba(118, 75, 162, 0.2);
            background: rgba(118, 75, 162, 0.05);
        }
        .result-card {
            border-radius: 16px;
            padding: 1.5rem;
            background: #ffffff;
            border: 1px solid rgba(0,0,0,0.05);
            box-shadow: 0px 10px 25px rgba(0,0,0,0.08);
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Session state helpers
# ---------------------------------------------------------------------------
def init_session_state() -> None:
    defaults = {
        "temporal_client": None,
        "workflow_handle": None,
        "workflow_id": "",
        "latest_status": None,
        "workflow_execution_status": "",
        "status_error": None,
        "awaiting_user_input": False,
        "polling_active": False,
        "research_result": None,
        "clarification_answer_input": "",
        "session_history": [],
        "saved_report_path": None,
        "reset_clarification_answer_input": False,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


async def get_temporal_client() -> Client:
    if st.session_state.temporal_client:
        return st.session_state.temporal_client

    if not TEMPORAL_ENDPOINT and TEMPORAL_CONNECT_CLOUD == 'Y':
        raise RuntimeError(
            "TEMPORAL_ENDPOINT is missing. Set it in .env or the environment."
        )

    if TEMPORAL_CONNECT_CLOUD == 'Y':
        client = await Client.connect(
            TEMPORAL_ENDPOINT,
            namespace=TEMPORAL_NAMESPACE,
            api_key=TEMPORAL_API_KEY,
            tls=TEMPORAL_TLS,
            data_converter=pydantic_data_converter,
        )
    else:
        client = await Client.connect(
            "localhost:7233",
            data_converter=pydantic_data_converter,
        )
    st.session_state.temporal_client = client
    return client


async def start_new_session(query: str, label: Optional[str]) -> None:
    client = await get_temporal_client()
    suffix = uuid.uuid4().hex[:8]
    workflow_id = f"{(label or DEFAULT_WORKFLOW_PREFIX).strip()}-{suffix}"

    handle = await client.start_workflow(
        InteractiveResearchWorkflow.run,
        args=[None, False],
        id=workflow_id,
        task_queue=TEMPORAL_TASK_QUEUE,
    )

    status = await handle.execute_update(
        InteractiveResearchWorkflow.start_research,
        UserQueryInput(query=query.strip()),
    )

    _store_session_state(workflow_id, handle, status)


async def resume_session(workflow_id: str, query: Optional[str]) -> None:
    client = await get_temporal_client()
    handle = client.get_workflow_handle(workflow_id.strip())

    status = await handle.query(InteractiveResearchWorkflow.get_status)
    if status.status == "pending":
        if not query:
            raise ValueError(
                "Workflow is awaiting an initial query. Provide one to continue."
            )
        status = await handle.execute_update(
            InteractiveResearchWorkflow.start_research,
            UserQueryInput(query=query.strip()),
        )

    _store_session_state(workflow_id, handle, status)


def _store_session_state(workflow_id, handle, status) -> None:
    st.session_state.workflow_handle = handle
    st.session_state.workflow_id = workflow_id
    st.session_state.latest_status = status
    st.session_state.workflow_execution_status = "RUNNING"
    st.session_state.polling_active = True
    st.session_state.research_result = None
    st.session_state.awaiting_user_input = status.status in (
        "awaiting_clarifications",
        "collecting_answers",
    )
    st.session_state.saved_report_path = None
    st.session_state.session_history.append(
        {
            "workflow_id": workflow_id,
            "query": status.original_query,
            "started_at": datetime.utcnow().isoformat(),
        }
    )


def refresh_status() -> None:
    handle = st.session_state.workflow_handle
    if not handle or not st.session_state.polling_active:
        return

    try:
        status = run_async(handle.query(InteractiveResearchWorkflow.get_status))
        st.session_state.latest_status = status

        awaiting = status.status in ("awaiting_clarifications", "collecting_answers")
        st.session_state.awaiting_user_input = awaiting

        if awaiting:
            st.session_state.workflow_execution_status = "WAITING_FOR_USER"
            return

        desc = run_async(handle.describe())
        exec_status = getattr(desc.status, "name", str(desc.status))
        st.session_state.workflow_execution_status = exec_status

        if exec_status not in ("RUNNING", "CONTINUED_AS_NEW"):
            st.session_state.polling_active = False
            if exec_status == "COMPLETED" and st.session_state.research_result is None:
                st.session_state.research_result = run_async(handle.result())
    except Exception as exc:
        st.session_state.status_error = str(exc)
        st.session_state.polling_active = False


async def send_clarification(answer: str) -> None:
    handle = st.session_state.workflow_handle
    status = st.session_state.latest_status

    if not handle or not status:
        raise RuntimeError("No active workflow to send clarifications to.")

    await handle.execute_update(
        InteractiveResearchWorkflow.provide_single_clarification,
        SingleClarificationInput(
            question_index=status.current_question_index,
            answer=answer.strip(),
        ),
    )


async def end_current_session() -> None:
    handle = st.session_state.workflow_handle
    if not handle:
        return
    await handle.signal(InteractiveResearchWorkflow.end_workflow_signal)
    st.session_state.polling_active = False
    st.session_state.workflow_execution_status = "ENDED"


def save_report_to_disk(result: InteractiveResearchResult) -> Path:
    filename = f"{st.session_state.workflow_id}_report.md"
    return file_manager.save_report(result.markdown_report, filename=filename)


def get_absolute_image_path(image_path: str | None) -> str | None:
    """Convert relative image path to absolute for display."""
    if not image_path:
        return None
    path = Path(image_path)
    if path.exists():
        return str(path.resolve())
    # Try relative to repo root
    repo_path = REPO_ROOT / image_path
    if repo_path.exists():
        return str(repo_path.resolve())
    return image_path


def embed_image_in_markdown(report: str, image_path: str | None) -> str:
    """Embed image in markdown report as base64 (works in st.markdown and downloads)."""
    import base64
    
    abs_path = get_absolute_image_path(image_path)
    if not abs_path or not Path(abs_path).exists():
        return report
    
    try:
        with open(abs_path, "rb") as img_file:
            b64 = base64.b64encode(img_file.read()).decode()
            ext = Path(abs_path).suffix.lower()
            mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(ext, "image/png")
            image_uri = f"data:{mime};base64,{b64}"
    except Exception:
        return report
    
    lines = report.split('\n')
    image_md = f"\n![Research Visualization]({image_uri})\n"
    
    # Find first heading and insert image after it
    for i, line in enumerate(lines):
        if line.startswith('# '):
            lines.insert(i + 1, image_md)
            return '\n'.join(lines)
    
    # No heading found, prepend image
    return image_md + report


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def status_badge(label: str) -> str:
    emoji_map = {
        "pending": "⏳",
        "awaiting_clarifications": "❓",
        "collecting_answers": "✍️",
        "researching": "🔍",
        "completed": "✅",
        "ended": "🛑",
    }
    return f'<span class="status-pill">{emoji_map.get(label, "ℹ️")} {label.replace("_", " ").title()}</span>'


def render_query_form() -> None:
    st.subheader("Launch or Resume Research")
    with st.form("query_form"):
        query = st.text_area(
            "Research prompt",
            placeholder="e.g., Compare the 2024 and 2025 climate-tech investment landscape…",
            height=110,
        )

        col_left, col_right = st.columns(2)
        session_mode = col_left.radio(
            "Session mode", ["Start new session", "Resume existing"], horizontal=True
        )

        label = (
            col_right.text_input(
                "Custom workflow ID (optional)",
                placeholder="research-topic",
                help="Used to build workflow IDs when starting a new session.",
            )
            if session_mode == "Start new session"
            else None
        )

        workflow_id = (
            col_right.text_input(
                "Existing workflow ID",
                value=st.session_state.workflow_id,
                help="Attach to a running workflow to continue clarifications or fetch the report.",
            )
            if session_mode == "Resume existing"
            else None
        )

        submitted = st.form_submit_button("Run interactive research", use_container_width=True)

    if submitted:
        if session_mode == "Start new session":
            if not query.strip():
                st.warning("Please provide a research prompt to get started.")
                return
            with st.spinner("Starting Temporal workflow..."):
                run_async(start_new_session(query, label))
                st.success("Research workflow launched.")
                st.rerun()
        else:
            if not workflow_id:
                st.warning("Provide a workflow ID to resume.")
                return
            with st.spinner("Attaching to existing workflow..."):
                run_async(resume_session(workflow_id, query if query.strip() else None))
                st.success(f"Attached to workflow `{workflow_id}`.")
                st.rerun()


def render_status_panel() -> None:
    status = st.session_state.latest_status
    if not status:
        st.info("No active workflow yet. Submit a research query to begin.")
        return

    st.subheader("Workflow status")
    cols = st.columns(3)
    cols[0].markdown(status_badge(status.status), unsafe_allow_html=True)
    cols[1].metric("Workflow ID", st.session_state.workflow_id)
    cols[2].metric("Execution", st.session_state.workflow_execution_status)

    if st.session_state.status_error:
        st.error(st.session_state.status_error)

    with st.expander("Clarification progress", expanded=True):
        questions = status.clarification_questions or []
        answered = len(status.clarification_responses or {})
        st.write(f"{answered} / {len(questions)} questions answered")

        if questions:
            for idx, question in enumerate(questions):
                answer = status.clarification_responses.get(f"question_{idx}", "—")
                st.markdown(
                    f"**Q{idx + 1}:** {question}\n\n> **Answer:** {answer}"
                )
        else:
            st.caption("No clarifications required so far.")

    col_refresh, col_end = st.columns([1, 1])
    if col_refresh.button("🔄 Refresh status", use_container_width=True):
        refresh_status()
        st.rerun()

    if col_end.button("🛑 End workflow", type="secondary", use_container_width=True):
        run_async(end_current_session())
        st.rerun()


def render_clarification_prompt() -> None:
    status = st.session_state.latest_status
    if (
        not status
        or status.get_current_question() is None
        or not st.session_state.awaiting_user_input
    ):
        return

    st.subheader("Clarifying question")
    with st.container():
        st.markdown(
            f"""
            <div class="question-card">
                <strong>Question {status.current_question_index + 1}</strong><br>
                {status.get_current_question()}
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.session_state.get("reset_clarification_answer_input"):
            st.session_state["clarification_answer_input"] = ""
            st.session_state["reset_clarification_answer_input"] = False

        answer = st.text_area(
            "Your answer",
            key="clarification_answer_input",
            placeholder="Provide details so the research team can focus on what matters.",
            height=120,
        )

        col_submit, col_skip = st.columns([2, 1])
        if col_submit.button("Submit answer", type="primary"):
            if not answer.strip():
                st.warning("Answer cannot be empty.")
            else:
                with st.spinner("Sending clarification..."):
                    run_async(send_clarification(answer))
                st.session_state.reset_clarification_answer_input = True
                st.success("Clarification submitted.")
                st.rerun()

        if col_skip.button("Skip question"):
            st.session_state.reset_clarification_answer_input = True
            run_async(send_clarification("No specific preference"))
            st.rerun()


def render_result_section() -> None:
    result: InteractiveResearchResult | None = st.session_state.research_result
    if not result:
        if st.session_state.polling_active and not st.session_state.awaiting_user_input:
            st.info(
                "Research agents are working. Refresh periodically to check for completion."
            )
        return

    st.subheader("📑 Research deliverables")
    
    # Display generated image if available
    abs_image_path = get_absolute_image_path(result.image_file_path)
    if abs_image_path and Path(abs_image_path).exists():
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.image(
                abs_image_path,
                caption="AI-Generated Research Visualization",
            )
    
    with st.container():
        st.markdown(
            f"""
            <div class="result-card">
                <h3 style="color:#0B0F19;">Summary</h3>
                <p style="color:#0B0F19;">{result.short_summary}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Embed image in markdown for display/download
    markdown_with_image = embed_image_in_markdown(result.markdown_report, result.image_file_path)

    download_cols = st.columns(3)
    download_cols[0].download_button(
        "📝 Download Markdown",
        data=markdown_with_image,
        file_name=f"{st.session_state.workflow_id}_report.md",
        mime="text/markdown",
        use_container_width=True,
    )

    if abs_image_path and Path(abs_image_path).exists():
        with open(abs_image_path, "rb") as img_file:
            download_cols[1].download_button(
                "🖼️ Download Image",
                data=img_file.read(),
                file_name=Path(abs_image_path).name,
                mime="image/png",
                use_container_width=True,
            )
    else:
        download_cols[1].caption("Image not generated.")

    saved_path = st.session_state.saved_report_path
    if download_cols[2].button("💾 Save to workspace", use_container_width=True):
        path = save_report_to_disk(result)
        st.session_state.saved_report_path = path
        st.success(f"Saved report to {path}")

    if saved_path:
        st.caption(f"Last saved copy: `{saved_path}`")

    st.markdown("### Follow-up questions")
    if result.follow_up_questions:
        for question in result.follow_up_questions:
            st.markdown(f"- {question}")
    else:
        st.caption("Workflow did not return additional follow-up questions.")

    with st.expander("Full Markdown report", expanded=False):
        st.markdown(markdown_with_image, unsafe_allow_html=True)


def render_history_panel() -> None:
    history = st.session_state.session_history[-5:]
    if not history:
        return
    st.sidebar.subheader("Recent sessions")
    for entry in reversed(history):
        st.sidebar.markdown(
            f"- `{entry['workflow_id']}` · {entry.get('query') or '—'}"
        )


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------
def main():
    init_session_state()

    if st.session_state.workflow_handle:
        refresh_status()

    st.title("🧠 Interactive Research Orchestrator")
    st.markdown(
        '<p style="font-size:1.1rem;font-weight:600;margin-top:-0.8rem;">'
        "Deep Research Orchestrated with Temporal Durable Workflows!"
        "</p>",
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.header("Temporal connection")
        st.markdown(f"- Endpoint: `{TEMPORAL_ENDPOINT or 'not set'}`")
        st.markdown(f"- Namespace: `{TEMPORAL_NAMESPACE}`")
        st.markdown(f"- Task queue: `{TEMPORAL_TASK_QUEUE}`")
        render_history_panel()

    render_query_form()
    render_status_panel()
    render_clarification_prompt()
    render_result_section()


if __name__ == "__main__":
    main()
