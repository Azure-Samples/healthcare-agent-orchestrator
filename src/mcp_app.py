# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import contextlib
import logging
from secrets import token_hex

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER, StreamableHTTPServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount

import group_chat
from data_models.app_context import AppContext

logger = logging.getLogger(__name__)


def create_fast_mcp_app(app_ctx: AppContext) -> Starlette:
    agent_config = app_ctx.all_agent_configs
    data_access = app_ctx.data_access
    task_group = None

    @contextlib.asynccontextmanager
    async def lifespan(app):
        """Application lifespan context manager for managing task group."""
        nonlocal task_group

        async with anyio.create_task_group() as tg:
            task_group = tg

            logger.info("Application started, task group initialized!")
            try:
                yield
            finally:
                logger.info("Application shutting down, cleaning up resources...")
                if task_group:
                    tg.cancel_scope.cancel()
                    task_group = None
                logger.info("Resources cleaned up successfully.")

    def create_app(session_id):

        app = FastMCP("mcp-streamable-http-demo")
        logger.info("Creating multi MCP app...")

        async def process_chat(agent_name: str, message: str) -> dict[str, str]:
            nonlocal session_id
            logger.info(f"Processing chat with question: {message}, agent: {agent_name}")

            chat_ctx = await data_access.chat_context_accessor.read(session_id)
            chat_ctx.chat_history.add_user_message(message)
            (chat, chat_ctx) = group_chat.create_group_chat(app_ctx, chat_ctx)
            logger.info(f"Processing chat with question: {message}")
            chat.is_complete = False
            responses = []
            agent = next(agent for agent in chat.agents if agent.name == agent_name)

            chat.is_complete = False
            async for response in chat.invoke(agent=agent):
                responses.append({
                    "name": response.name,
                    "content": response.content,
                })
            # Save chat context
            try:
                await data_access.chat_context_accessor.write(chat_ctx)
            except:
                logger.exception("Failed to save chat context.")

            return responses

        logger.info("Adding tools to the app")
        for agent in agent_config:
            if agent["name"] == "magentic":
                continue

            logger.info(f"Adding tool for agent: {agent['name']}")

            def generate_tool_function(agent_name: str):
                async def inner_process_chat(message: str) -> dict[str, str]:
                    return await process_chat(agent_name, message)
                return inner_process_chat

            app.add_tool(
                name=agent["name"],
                description=agent["description"],
                fn=generate_tool_function(agent["name"]),
            )

        @app.tool(description="Reset the conversation state")
        async def reset_conversation() -> dict[str, str]:
            nonlocal session_id
            chat_ctx = await data_access.chat_context_accessor.read(session_id)

            await data_access.chat_context_accessor.archive(chat_ctx)
            await data_access.chat_artifact_accessor.archive(session_id)

            return "Conversation reset!"

        return app

    async def handle_streamable_http(scope, receive, send):
        nonlocal task_group

        logger.info("Handling handle_multi_streamable_http HTTP request")
        request = Request(scope, receive)
        logger.info(f"Request headers: {request.headers}")
        logger.info(f"Request path: {request.url.path}")
        logger.info(f"Request method: {request.method}")
        request_mcp_session_id = request.headers.get(MCP_SESSION_ID_HEADER)
        if not request_mcp_session_id:
            request_mcp_session_id = token_hex(16)

        http_transport = StreamableHTTPServerTransport(
            mcp_session_id=request_mcp_session_id,
            is_json_response_enabled=False,
        )

        def _check_accept_headers(*args, **kwargs) -> tuple[bool, bool]:
            """Check if the request accepts the required media types."""
            logger.debug("Overriding accept headers")
            has_json = True
            has_sse = True

            return has_json, has_sse

        http_transport._check_accept_headers = _check_accept_headers

        async with http_transport.connect() as streams:
            read_stream, write_stream = streams

            async def run_server():
                app = create_app(session_id=request_mcp_session_id)
                try:
                    logger.info("Running MCP server...")
                    await app._mcp_server.run(
                        read_stream=read_stream,
                        write_stream=write_stream,
                        initialization_options=app._mcp_server.create_initialization_options(),
                        stateless=True
                    )
                except Exception as e:
                    logger.error(f"Error running MCP server: {e}")
                    pass

            if not task_group:
                raise RuntimeError("Task group is not initialized")

            task_group.start_soon(run_server)

            await http_transport.handle_request(scope, receive, send)

    logger.setLevel(logging.DEBUG)
    # Create an ASGI application using the transport
    starlette_app = Starlette(
        debug=True,
        routes=[
            Mount("/orchestrator/", app=handle_streamable_http),
        ],
    )

    return starlette_app, lifespan
