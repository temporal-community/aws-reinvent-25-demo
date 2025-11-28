from agents import set_default_openai_key, Agent
from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv(dotenv_path='../../.env',override=True)

set_default_openai_key(os.getenv('OPENAI_API_KEY'))

PROMPT = (
    "You are a helpful research assistant. Given a query, come up with a set of web searches "
    "to perform to best answer the query. Output between 5 and 20 terms to query for."
)


class WebSearchItem(BaseModel):
    reason: str
    "Your reasoning for why this search is important to the query."

    query: str
    "The search term to use for the web search."


class WebSearchPlan(BaseModel):
    searches: list[WebSearchItem]
    """A list of web searches to perform to best answer the query."""


def new_planner_agent():
    return Agent(
        name="PlannerAgent",
        instructions=PROMPT,
        model="gpt-4o",
        output_type=WebSearchPlan,
    )
