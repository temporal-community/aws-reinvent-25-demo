from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from dotenv import load_dotenv

from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.contrib.openai_agents import OpenAIAgentsPlugin, ModelActivityParameters

from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.envconfig import ClientConfig
from temporalio.worker import Worker

from openai_agents.workflows.image_generation_activity import generate_image
from openai_agents.workflows.interactive_research_workflow import (
    InteractiveResearchWorkflow,
    process_clarification,
)
from openai_agents.workflows.pdf_generation_activity import generate_pdf


# Load environment variables
load_dotenv()

# Configure logging
logging.getLogger("openai").setLevel(logging.ERROR)
logging.getLogger("openai.agents").setLevel(logging.CRITICAL)


async def main():
    logging.basicConfig(level=logging.INFO)

    config = ClientConfig.load_client_connect_config()
    config.setdefault('target_host', 'localhost:7233')
    config.setdefault('namespace', 'default')

    print(f"Connecting to Temporal at {config['target_host']} in namespace {config['namespace']}")

    client = await Client.connect(
        **config,
        plugins=[
            OpenAIAgentsPlugin(
                model_params=ModelActivityParameters(
                    start_to_close_timeout=timedelta(seconds=200),
                    schedule_to_close_timeout=timedelta(seconds=500),
                    retry_policy=RetryPolicy(
                        backoff_coefficient=2.0,
                        initial_interval=timedelta(seconds=1),
                        maximum_interval=timedelta(seconds=5)
                    ),
                )
            ),
        ],
        data_converter=pydantic_data_converter,
    )

    print("Starting worker...")
    worker = Worker(
        client,
        task_queue="research-queue",
        workflows=[
            InteractiveResearchWorkflow,
        ],
        activities=[
            generate_pdf,
            generate_image,
            process_clarification,
        ],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
