"""
Utility module for Streamlit-Temporal integration
==================================================
Provides helper functions and classes for seamless integration
between the Streamlit frontend and Temporal backend.
"""

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from temporalio import workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

# from temporalio.service import RPCError, StatusCode

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WorkflowStatus(Enum):
    """Workflow status enumeration"""

    IDLE = "idle"
    STARTING = "starting"
    TRIAGING = "triaging"
    CLARIFYING = "clarifying"
    PLANNING = "planning"
    SEARCHING = "searching"
    WRITING = "writing"
    GENERATING_PDF = "generating_pdf"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ResearchProgress:
    """Track research workflow progress"""

    status: WorkflowStatus = WorkflowStatus.IDLE
    current_stage: str = ""
    progress_percentage: int = 0
    details: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "status": self.status.value,
            "current_stage": self.current_stage,
            "progress_percentage": self.progress_percentage,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


class TemporalManager:
    """Manages Temporal client and workflow operations"""

    def __init__(
        self, server_address: str = "localhost:7233", namespace: str = "default"
    ):
        self.server_address = server_address
        self.namespace = namespace
        self.client: Optional[Client] = None
        self._connected = False

    async def connect(self) -> bool:
        """Establish connection to Temporal server"""
        if self._connected and self.client:
            return True

        try:
            self.client = await Client.connect(
                self.server_address, namespace=self.namespace
            )
            self._connected = True
            logger.info(f"Connected to Temporal server at {self.server_address}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Temporal server: {e}")
            self._connected = False
            return False

    async def disconnect(self):
        """Disconnect from Temporal server"""
        if self.client:
            await self.client.close()
            self._connected = False
            logger.info("Disconnected from Temporal server")

    def is_connected(self) -> bool:
        """Check if connected to Temporal server"""
        return self._connected

    async def start_workflow(
        self,
        workflow_class: type,
        workflow_input: Any,
        workflow_id: str,
        task_queue: str = "research-queue",
        retry_policy: Optional[RetryPolicy] = None,
    ):
        """Start a new workflow"""
        if not self._connected or not self.client:
            raise RuntimeError("Not connected to Temporal server")

        try:
            handle = await self.client.start_workflow(
                workflow_class.run,
                workflow_input,
                id=workflow_id,
                task_queue=task_queue,
                retry_policy=retry_policy or RetryPolicy(maximum_attempts=3),
            )
            logger.info(f"Started workflow with ID: {workflow_id}")
            return handle
        except WorkflowAlreadyStartedError:
            logger.warning(f"Workflow {workflow_id} already exists, getting handle...")
            return await self.get_workflow_handle(workflow_id)
        except Exception as e:
            logger.error(f"Failed to start workflow: {e}")
            raise

    async def get_workflow_handle(self, workflow_id: str):
        """Get handle to existing workflow"""
        if not self._connected or not self.client:
            raise RuntimeError("Not connected to Temporal server")

        try:
            handle = self.client.get_workflow_handle(workflow_id)
            return handle
        except Exception as e:
            logger.error(f"Failed to get workflow handle: {e}")
            raise

    async def query_workflow(self, handle, query_name: str):
        """Query workflow for status or data"""
        try:
            result = await handle.query(query_name)
            return result
        except Exception as e:
            logger.error(f"Failed to query workflow: {e}")
            return None

    async def signal_workflow(self, handle, signal_name: str, signal_input: Any):
        """Send signal to workflow"""
        try:
            await handle.signal(signal_name, signal_input)
            logger.info(f"Sent signal {signal_name} to workflow")
            return True
        except Exception as e:
            logger.error(f"Failed to signal workflow: {e}")
            return False


class MessageFormatter:
    """Format messages for display in the chat interface"""

    @staticmethod
    def format_research_query(query: str) -> str:
        """Format initial research query"""
        return f"🔍 **Research Query**: {query}"

    @staticmethod
    def format_clarification_questions(questions: List[str]) -> str:
        """Format clarification questions"""
        formatted = "**📋 Clarifying Questions:**\n\n"
        for i, question in enumerate(questions, 1):
            formatted += f"{i}. {question}\n"
        return formatted

    @staticmethod
    def format_research_plan(plan: Dict[str, Any]) -> str:
        """Format research plan"""
        formatted = "**📝 Research Plan:**\n\n"
        if "searches" in plan:
            formatted += "**Planned Searches:**\n"
            for search in plan["searches"]:
                formatted += f"• {search}\n"
        if "focus_areas" in plan:
            formatted += "\n**Focus Areas:**\n"
            for area in plan["focus_areas"]:
                formatted += f"• {area}\n"
        return formatted

    @staticmethod
    def format_search_results(results: List[Dict[str, str]]) -> str:
        """Format search results summary"""
        formatted = "**🔎 Search Results:**\n\n"
        for i, result in enumerate(results[:5], 1):  # Show top 5
            formatted += f"**{i}. {result.get('title', 'Untitled')}**\n"
            formatted += f"   {result.get('snippet', 'No description available')}\n\n"
        if len(results) > 5:
            formatted += f"*...and {len(results) - 5} more results*\n"
        return formatted

    @staticmethod
    def format_report_summary(report: str, word_limit: int = 200) -> str:
        """Format report summary"""
        words = report.split()
        if len(words) <= word_limit:
            return report

        summary = " ".join(words[:word_limit])
        return f"{summary}... [Report continues - {len(words)} total words]"

    @staticmethod
    def format_error(error: str) -> str:
        """Format error message"""
        return f"❌ **Error**: {error}"

    @staticmethod
    def format_success(message: str) -> str:
        """Format success message"""
        return f"✅ {message}"


class FileManager:
    """Manage files for research reports and PDFs"""

    def __init__(self, output_dir: str = "./research_outputs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_report(self, content: str, filename: Optional[str] = None) -> Path:
        """Save research report to file"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"research_report_{timestamp}.md"

        filepath = self.output_dir / filename
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"Saved report to {filepath}")
        return filepath

    def save_pdf(self, pdf_bytes: bytes, filename: Optional[str] = None) -> Path:
        """Save PDF report to file"""
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"research_report_{timestamp}.pdf"

        filepath = self.output_dir / filename
        filepath.write_bytes(pdf_bytes)
        logger.info(f"Saved PDF to {filepath}")
        return filepath

    def get_recent_reports(self, limit: int = 10) -> List[Tuple[str, datetime]]:
        """Get list of recent reports"""
        reports = []
        for filepath in self.output_dir.glob("*.md"):
            mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
            reports.append((filepath.name, mtime))

        # Sort by modification time, most recent first
        reports.sort(key=lambda x: x[1], reverse=True)
        return reports[:limit]

    def load_report(self, filename: str) -> Optional[str]:
        """Load a report from file"""
        filepath = self.output_dir / filename
        if filepath.exists():
            return filepath.read_text(encoding="utf-8")
        return None


class ResearchCache:
    """Cache research results to avoid redundant workflows"""

    def __init__(self, cache_dir: str = "./.research_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "cache.json"
        self._cache = self._load_cache()

    def _load_cache(self) -> Dict[str, Any]:
        """Load cache from file"""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load cache: {e}")
        return {}

    def _save_cache(self):
        """Save cache to file"""
        try:
            with open(self.cache_file, "w") as f:
                json.dump(self._cache, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")

    def get(self, query: str) -> Optional[Dict[str, Any]]:
        """Get cached result for query"""
        query_hash = self._hash_query(query)
        if query_hash in self._cache:
            entry = self._cache[query_hash]
            # Check if cache is still valid (e.g., less than 24 hours old)
            timestamp = datetime.fromisoformat(entry["timestamp"])
            age = datetime.now() - timestamp
            if age.total_seconds() < 86400:  # 24 hours
                logger.info(f"Cache hit for query: {query[:50]}...")
                return entry["result"]
        return None

    def set(self, query: str, result: Dict[str, Any]):
        """Cache result for query"""
        query_hash = self._hash_query(query)
        self._cache[query_hash] = {
            "query": query,
            "result": result,
            "timestamp": datetime.now().isoformat(),
        }
        self._save_cache()
        logger.info(f"Cached result for query: {query[:50]}...")

    def _hash_query(self, query: str) -> str:
        """Generate hash for query"""
        import hashlib

        return hashlib.md5(query.encode()).hexdigest()

    def clear(self):
        """Clear all cached results"""
        self._cache = {}
        self._save_cache()
        logger.info("Cache cleared")


# Async helper for Streamlit
def run_async(coro):
    """Helper to run async functions in Streamlit"""
    loop = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're in an existing loop (e.g., Jupyter or some Streamlit contexts)
        import nest_asyncio

        nest_asyncio.apply()
        return loop.run_until_complete(coro)
    else:
        # Create new loop
        return asyncio.run(coro)


# Export main classes and functions
__all__ = [
    "TemporalManager",
    "MessageFormatter",
    "FileManager",
    "ResearchCache",
    "WorkflowStatus",
    "ResearchProgress",
    "run_async",
]
