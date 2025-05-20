# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os

from azure.identity import ManagedIdentityCredential
from azure.storage.blob.aio import BlobServiceClient
from botbuilder.integration.aiohttp import CloudAdapter, ConfigurationBotFrameworkAuthentication
from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.routing import Mount

from bots import AssistantBot, MagenticBot
from bots.show_typing_middleware import ShowTypingMiddleware
from config import DefaultConfig, load_agent_config, setup_logging
from data_models.data_access import DataAccess
from mcp_app import create_fast_mcp_app
from routes.api.messages import messages_routes
from routes.patient_data.patient_data_routes import patient_data_routes
from routes.views.patient_data_answer_routes import patient_data_answer_source_routes
from routes.views.patient_timeline_routes import patient_timeline_entry_source_routes

load_dotenv(".env")

setup_logging()


def create_app(
    adapters: dict,
    bots: dict,
    blob_service_client: BlobServiceClient,
    data_access: DataAccess,
) -> FastAPI:
    app = FastAPI()
    app.include_router(messages_routes(adapters, bots))
    app.include_router(patient_data_routes(blob_service_client))
    app.include_router(patient_data_answer_source_routes(data_access))
    app.include_router(patient_timeline_entry_source_routes(data_access))

    return app


# Set up service authentication
credential = ManagedIdentityCredential(
    client_id=os.getenv("AZURE_CLIENT_ID")
)

# Set up blob service client
blob_service_client = BlobServiceClient(
    account_url=os.getenv("APP_BLOB_STORAGE_ENDPOINT"),
    credential=credential,
)
data_access = DataAccess(blob_service_client)

turn_contexts = {}

# Load agent configuration
scenario = os.getenv("SCENARIO")
agent_config = load_agent_config(scenario)

adapters = {
    agent["name"]: CloudAdapter(ConfigurationBotFrameworkAuthentication(
        DefaultConfig(botId=agent["bot_id"]))).use(ShowTypingMiddleware())
    for agent in agent_config
}
bots = {
    agent["name"]: AssistantBot(
        agent,
        all_agents=agent_config,
        turn_contexts=turn_contexts,
        adapters=adapters,
        data_access=data_access,
    ) if agent["name"] != "magentic" else MagenticBot(
        agent,
        adapters=adapters,
        all_agents=agent_config,
        turn_contexts=turn_contexts,
        data_access=data_access,
    )
    for agent in agent_config
}

teams_app = create_app(adapters, bots, blob_service_client, data_access)
fast_mcp_app, lifespan = create_fast_mcp_app(agent_config, data_access)

app = Starlette(
    routes=[
        Mount('/mcp', app=fast_mcp_app),
        Mount('/', teams_app),
    ], lifespan=lifespan)
