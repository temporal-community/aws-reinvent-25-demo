"""
FastAPI Backend for Temporal Research UI
=========================================
Production-ready backend connecting to Temporal workflows.

Environment Variables Required:
- TEMPORAL_ENDPOINT: Temporal server address (default: localhost:7233)
- TEMPORAL_NAMESPACE: Temporal namespace (default: default)
- TEMPORAL_TASK_QUEUE: Task queue name (default: research-queue)
- TEMPORAL_API_KEY: API key for Temporal Cloud (optional)
- CONNECT_CLOUD: Set to 'Y' for Temporal Cloud connection
"""

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, List
import asyncio
import json
import os
from pathlib import Path
from dotenv import load_dotenv
import uuid

# Load environment variables
load_dotenv()

# ============================================
# Configuration
# ============================================
load_dotenv(dotenv_path=".env", override=True)
TEMPORAL_ENDPOINT = os.getenv("TEMPORAL_ENDPOINT")
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
TEMPORAL_TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "research-queue")
TEMPORAL_API_KEY = os.getenv("TEMPORAL_API_KEY")
CONNECT_CLOUD = os.getenv("CONNECT_CLOUD", "N")

# ============================================
# FastAPI App Setup
# ============================================
app = FastAPI(
    title="Temporal Research API",
    description="Backend API for the Temporal Research Demo UI",
    version="1.0.0"
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for your domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# Temporal Client Setup
# ============================================
# TODO: Uncomment and configure when ready to connect to Temporal
#
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

# Ensure repository root is importable when Streamlit changes cwd
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(REPO_ROOT))

from openai_agents.workflows.interactive_research_workflow import (
    InteractiveResearchWorkflow,
    InteractiveResearchResult,
)
from openai_agents.workflows.research_agents.research_models import (
    SingleClarificationInput,
    UserQueryInput,
)

temporal_client: Optional[Client] = None

async def get_temporal_client() -> Client:
    global temporal_client
    if temporal_client:
        return temporal_client

    if CONNECT_CLOUD == 'Y':
        temporal_client = await Client.connect(
            TEMPORAL_ENDPOINT,
            namespace=TEMPORAL_NAMESPACE,
            api_key=TEMPORAL_API_KEY,
            tls=True,
            data_converter=pydantic_data_converter,
        )
    else:
        temporal_client = await Client.connect(
            "localhost:7233",
            data_converter=pydantic_data_converter,
        )
    return temporal_client

# ============================================
# Request/Response Models
# ============================================
class StartResearchRequest(BaseModel):
    query: str

class AnswerRequest(BaseModel):
    answer: str

class WorkflowStatusResponse(BaseModel):
    workflow_id: str
    status: str  # "pending", "awaiting_clarifications", "researching", "complete"
    original_query: Optional[str] = None
    current_question: Optional[str] = None
    current_question_index: int = 0
    total_questions: int = 0
    clarification_responses: Dict[str, str] = {}

class ResearchResultResponse(BaseModel):
    workflow_id: str
    markdown_report: str
    short_summary: str
    follow_up_questions: List[str]

# ============================================
# Static File Serving
# ============================================
@app.get("/")
async def serve_index():
    """Serve the main chat interface"""
    index_path = Path(__file__).parent.parent / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text())
    raise HTTPException(status_code=404, detail="Index page not found")

@app.get("/success")
async def serve_success():
    """Serve the success/results page"""
    success_path = Path(__file__).parent.parent / "success.html"
    if success_path.exists():
        return HTMLResponse(content=success_path.read_text())
    raise HTTPException(status_code=404, detail="Success page not found")

# Serve static assets (JS, CSS, fonts, images)
static_path = Path(__file__).parent.parent
if static_path.exists():
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
images_path = Path(__file__).parent.parent.parent / "temp_images"
if images_path.exists():
    app.mount("/temp_images", StaticFiles(directory=str(images_path)), name="images")


# ============================================
# API Endpoints
# ============================================

@app.post("/api/start-research")
async def start_research(request: StartResearchRequest):
    """
    Start a new research workflow.
    
    Returns:
        workflow_id: Unique identifier for tracking the workflow
        status: Initial status ("started")
    """
    client = await get_temporal_client()
    workflow_id = f"interactive-research-{uuid.uuid4().hex[:8]}"

    handle = await client.start_workflow(
        InteractiveResearchWorkflow.run,
        args=[None, False],
        id=workflow_id,
        task_queue=TEMPORAL_TASK_QUEUE,
    )

    status = await handle.execute_update(
        InteractiveResearchWorkflow.start_research,
        UserQueryInput(query=request.query.strip()),
    )

    return {
        "workflow_id": workflow_id,
        "status": "started",
    }
    

@app.get("/api/status/{workflow_id}")
async def get_status(workflow_id: str):
    """
    Get current workflow status.
    
    Returns:
        workflow_id: Workflow identifier
        status: Current status (awaiting_clarifications, researching, completed)
        current_question: The clarification question to display (if awaiting)
        current_question_index: Index of current question
        total_questions: Total number of clarification questions
    """
    client = await get_temporal_client()
    handle = client.get_workflow_handle(workflow_id)
    status = await handle.query(InteractiveResearchWorkflow.get_status)

    response = {
        "workflow_id": workflow_id,
        "status": status.status,
        "original_query": status.original_query,
        "current_question": status.current_question,
        "current_question_index": status.current_question_index,
        "total_questions": len(status.clarification_questions or []),
        "clarification_responses": status.clarification_responses or {},
    }

    if status.status == "awaiting_clarifications":
        response["current_question"] = status.get_current_question()

    return response
    

@app.post("/api/answer/{workflow_id}/{current_question_index}")
async def submit_answer(workflow_id: str, current_question_index: int, request: AnswerRequest):
    """
    Submit an answer to a clarification question.
    
    Returns:
        status: "accepted" if answer was recorded
        workflow_status: Current workflow status after answer
        questions_remaining: Number of questions left
    """
    client = await get_temporal_client()
    handle = client.get_workflow_handle(workflow_id)

    await handle.execute_update(
        InteractiveResearchWorkflow.provide_single_clarification,
        SingleClarificationInput(question_index=current_question_index, answer=request.answer.strip()),
    )

    status = await handle.query(InteractiveResearchWorkflow.get_status)

    return {
        "status": "accepted",
        "workflow_status": status.status,
        "questions_remaining": len(status.clarification_questions or []) - status.current_question_index,
    }
    
    raise HTTPException(
        status_code=501,
        detail="Temporal integration not configured. See backend/main.py for setup instructions."
    )


@app.get("/api/result/{workflow_id}")
async def get_result(workflow_id: str):
    """
    Get final research result.
    
    Returns:
        workflow_id: Workflow identifier
        markdown_report: Full markdown research report
        short_summary: Brief summary of findings
        follow_up_questions: Suggested follow-up questions
    """
    client = await get_temporal_client()
    handle = client.get_workflow_handle(workflow_id)

    # Check if workflow is complete
    desc = await handle.describe()
    if desc.status.name != "COMPLETED":
        raise HTTPException(status_code=400, detail="Research not complete yet")

    result: InteractiveResearchResult = await handle.result()

    # return {
    #     "workflow_id": workflow_id,
    #     "markdown_report": result.markdown_report,
    #     "short_summary": result.short_summary,
    #     "follow_up_questions": result.follow_up_questions or [],
    # }

    return result
    

@app.get("/api/stream/{workflow_id}")
async def stream_status(workflow_id: str):
    """
    Server-Sent Events endpoint for live status updates.
    
    Streams status updates every second until workflow completes.
    """
    # TODO: Implement SSE streaming with Temporal
    #
    # async def event_generator():
    #     client = await get_temporal_client()
    #     handle = client.get_workflow_handle(workflow_id)
    #
    #     while True:
    #         status = await handle.query(InteractiveResearchWorkflow.get_status)
    #
    #         data = {
    #             "status": status.status,
    #             "current_question_index": status.current_question_index,
    #             "total_questions": len(status.clarification_questions or []),
    #         }
    #
    #         yield f"data: {json.dumps(data)}\n\n"
    #
    #         if status.status == "complete":
    #             break
    #
    #         await asyncio.sleep(1)
    #
    # return StreamingResponse(
    #     event_generator(),
    #     media_type="text/event-stream",
    #     headers={
    #         "Cache-Control": "no-cache",
    #         "Connection": "keep-alive",
    #     }
    # )
    
    raise HTTPException(
        status_code=501,
        detail="Temporal integration not configured. See backend/main.py for setup instructions."
    )


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "temporal_endpoint": TEMPORAL_ENDPOINT,
        "temporal_namespace": TEMPORAL_NAMESPACE,
        "task_queue": TEMPORAL_TASK_QUEUE,
        "cloud_connection": CONNECT_CLOUD == 'Y',
    }


# ============================================
# Main Entry Point
# ============================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8234)
