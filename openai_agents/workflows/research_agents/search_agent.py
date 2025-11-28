from agents import set_default_openai_key, Agent, WebSearchTool
from agents.model_settings import ModelSettings
from dotenv import load_dotenv
import os

load_dotenv(dotenv_path='../../.env',override=True)

set_default_openai_key(os.getenv('OPENAI_API_KEY'))

INSTRUCTIONS = (
    "You are a research assistant. Given a search term, you search the web for that term and "
    "produce a concise summary of the results. The summary must 1-2 paragraphs and less than 250 "
    "words. Capture the main points. Write succinctly, no need to have complete sentences or good "
    "grammar. This will be consumed by someone synthesizing a report, so its vital you capture the "
    "essence and ignore any fluff. Do not include any additional commentary other than the summary "
    "itself."
)


def new_search_agent():
    return Agent(
        name="Search agent",
        instructions=INSTRUCTIONS,
        tools=[WebSearchTool()],
        model_settings=ModelSettings(tool_choice="required"),
    )
