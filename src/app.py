# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import os

from azure.identity import AzureCliCredential, ManagedIdentityCredential
from azure.storage.blob.aio import BlobServiceClient
from botbuilder.integration.aiohttp import CloudAdapter, ConfigurationBotFrameworkAuthentication
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.responses import FileResponse

from bots import AssistantBot, MagenticBot
from bots.show_typing_middleware import ShowTypingMiddleware
from config import DefaultConfig, load_agent_config, setup_logging
from data_models.app_context import AppContext
from data_models.data_access import DataAccess
from mcp_app import create_fast_mcp_app
from routes.api.messages import messages_routes
from routes.api.user import user_routes
from routes.api.chats import chats_routes
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
    app.include_router(chats_routes(app_context))
    app.include_router(user_routes())
    app.include_router(patient_data_routes(app_context.blob_service_client))
    app.include_router(patient_data_answer_source_routes(app_context.data_access))
    app.include_router(patient_timeline_entry_source_routes(app_context.data_access))

    # Serve static files from the React build directory
    static_files_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    if os.path.exists(static_files_path):
        app.mount("/static", StaticFiles(directory=os.path.join(static_files_path, "static")), name="static")
        
        # Add a route for the root URL to serve index.html
        @app.get("/")
        async def serve_root():
            index_path = os.path.join(static_files_path, "index.html")
            if os.path.exists(index_path):
                return FileResponse(index_path)
            return {"detail": "React app not built yet"}
        
        # Add a catch-all route to serve index.html for client-side routing only triggered if the path falls through to the static files
        @app.get("/{full_path:path}")
        async def serve_react_app(full_path: str):
            index_path = os.path.join(static_files_path, "index.html")
            if os.path.exists(index_path):
                return FileResponse(index_path)
            return {"detail": "React app not built yet"}

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
