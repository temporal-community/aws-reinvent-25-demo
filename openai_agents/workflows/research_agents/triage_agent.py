from __future__ import annotations

from temporalio import workflow
from dotenv import load_dotenv
from agents import set_default_openai_key
import os

load_dotenv(dotenv_path='../../.env',override=True)

set_default_openai_key(os.getenv('OPENAI_API_KEY'))

with workflow.unsafe.imports_passed_through():
    from agents import Agent

    from openai_agents.workflows.research_agents.clarifying_agent import (
        new_clarifying_agent,
    )
    from openai_agents.workflows.research_agents.instruction_agent import (
        new_instruction_agent,
    )


TRIAGE_AGENT_PROMPT = """
You are a triage agent that determines if a research query needs clarifying questions to provide better results.

**Always route to CLARIFYING AGENT**

• Always call transfer_to_clarifying_questions_agent

Return exactly ONE function-call.
"""


def new_triage_agent() -> Agent:
    """Create a new triage agent for routing research requests"""
    clarifying_agent = new_clarifying_agent()
    instruction_agent = new_instruction_agent()

    return Agent(
        name="Triage Agent",
        model="gpt-4o-mini",
        instructions=TRIAGE_AGENT_PROMPT,
        handoffs=[clarifying_agent, instruction_agent],
    )
