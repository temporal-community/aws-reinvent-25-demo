from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta

from dotenv import load_dotenv
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.contrib.openai_agents import ModelActivityParameters, OpenAIAgentsPlugin
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.envconfig import ClientConfigProfile
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

    profile = ClientConfigProfile.load()
    config = profile.to_client_connect_config()

    # For local development, remove cloud-specific config that interferes
    if os.getenv('CONNECT_CLOUD') == 'Y':
        # Cloud mode - use environment variables
        config['target_host'] = os.getenv('TEMPORAL_ENDPOINT')
        config['namespace'] = os.getenv('TEMPORAL_NAMESPACE')
        config['api_key'] = os.getenv('TEMPORAL_API_KEY')
        config['tls'] = True
    else:
        # Local mode
        config.pop('api_key', None)
        config.pop('tls', None)
        config['target_host'] = 'localhost:7233'
        config['namespace'] = 'default'

    

    print(
        f"Connecting to Temporal at {config.get('target_host')} in namespace {config.get('namespace')}"
    )

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
                        maximum_interval=timedelta(seconds=5),
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
