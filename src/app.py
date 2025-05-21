# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os

from azure.identity import AzureCliCredential, ManagedIdentityCredential
from azure.storage.blob.aio import BlobServiceClient
from botbuilder.integration.aiohttp import CloudAdapter, ConfigurationBotFrameworkAuthentication
from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.routing import Mount

from bots import AssistantBot, MagenticBot
from bots.show_typing_middleware import ShowTypingMiddleware
from config import DefaultConfig, load_agent_config, setup_logging
from data_models.app_context import AppContext
from data_models.data_access import DataAccess
from mcp_app import create_fast_mcp_app
from routes.api.messages import messages_routes
from routes.patient_data.patient_data_routes import patient_data_routes
from routes.views.patient_data_answer_routes import patient_data_answer_source_routes
from routes.views.patient_timeline_routes import patient_timeline_entry_source_routes

load_dotenv(".env")

setup_logging()


def create_app_context():
    '''Create the application context for commonly used object used in application.'''

    # Load agent configuration
    scenario = os.getenv("SCENARIO")
    agent_config = load_agent_config(scenario)

    # Load Azure Credential
    credential = ManagedIdentityCredential(client_id=os.getenv("AZURE_CLIENT_ID")) \
        if os.getenv("WEBSITE_SITE_NAME") is not None \
        else AzureCliCredential()   # used for local development

    # Setup data access
    blob_service_client = BlobServiceClient(
        account_url=os.getenv("APP_BLOB_STORAGE_ENDPOINT"),
        credential=credential,
    )
    data_access = DataAccess(blob_service_client)

    return AppContext(
        all_agent_configs=agent_config,
        blob_service_client=blob_service_client,
        credential=credential,
        data_access=data_access,
    )


def create_app(
    bots: dict,
    app_context: AppContext,
) -> FastAPI:
    app = FastAPI()
    app.include_router(messages_routes(adapters, bots))
    app.include_router(patient_data_routes(app_context.blob_service_client))
    app.include_router(patient_data_answer_source_routes(app_context.data_access))
    app.include_router(patient_timeline_entry_source_routes(app_context.data_access))

    return app


app_context = create_app_context()

# Create Teams specific objects
adapters = {
    agent["name"]: CloudAdapter(ConfigurationBotFrameworkAuthentication(
        DefaultConfig(botId=agent["bot_id"]))).use(ShowTypingMiddleware())
    for agent in app_context.all_agent_configs
}
bot_config = {
    "adapters": adapters,
    "app_context": app_context,
    "turn_contexts": {}
}
bots = {
    agent["name"]: AssistantBot(agent, **bot_config) if agent["name"] != "magentic"
    else MagenticBot(agent, **bot_config)
    for agent in app_context.all_agent_configs
}

teams_app = create_app(bots, app_context)
fast_mcp_app, lifespan = create_fast_mcp_app(app_context)

app = Starlette(
    routes=[
        Mount('/mcp', app=fast_mcp_app),
        Mount('/', teams_app),
    ], lifespan=lifespan)
