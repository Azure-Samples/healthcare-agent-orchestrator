# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import logging
from http import HTTPStatus

from botbuilder.integration.aiohttp import CloudAdapter
from botbuilder.schema import Activity
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from bots.assistant_bot import AssistantBot

logger = logging.getLogger(__name__)


def create_router(botName: str, bot: AssistantBot, adapter: CloudAdapter, router: APIRouter):
    @router.post(f"/api/{botName}/messages")
    async def messages(request: Request):
        body = await request.json()
        activity = Activity().deserialize(body)
        auth_header = (
            request.headers["Authorization"]
            if "Authorization" in request.headers
            else ""
        )

        # add explicit auth check
        authentication_result = await adapter.bot_framework_authentication.authenticate_request(
            activity, auth_header
        )

        if not authentication_result or not authentication_result.claims_identity.is_authenticated:
            # Optionally could check the aud claim to make sure it matches the requested bot. Though I am fairly certain this is already done in the adapter.
            return Response(
                status=HTTPStatus.UNAUTHORIZED,
                text="Authentication failed",
            )

        response = await adapter.process_activity(
            auth_header, activity, bot.on_turn
        )

        if response:
            return JSONResponse(content=response.body, status_code=response.status)
        return Response(status_code=HTTPStatus.OK)


def messages_routes(adapters: dict[str, CloudAdapter], bots: dict[str, AssistantBot]):
    router = APIRouter()

    # Listen for incoming requests on /api/{botname/messages.
    for botName, bot in bots.items():
        create_router(botName, bot, adapters.get(botName), router)

    return router
