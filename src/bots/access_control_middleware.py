import logging
import os
from typing import Awaitable, Callable

from botbuilder.core import Middleware, TurnContext
from botbuilder.schema import ActivityTypes
from botbuilder.schema.teams import TeamsChannelData
from botframework.connector import Channels

from errors import NotAuthorizedError

logger = logging.getLogger(__name__)


class AccessControlMiddleware(Middleware):
    """
    Middleware to enforce access control based on tenant ID for Teams channel.
    https://learn.microsoft.com/en-us/azure/bot-service/bot-service-resources-faq-security?view=azure-bot-service-4.0
    """

    async def on_turn(
        self, context: TurnContext, logic: Callable[[TurnContext], Awaitable]
    ):
        # Skip middleware for non-message activities or installation updates
        if context.activity.type not in [ActivityTypes.message, ActivityTypes.installation_update]:
            return await logic(context)

        app_tenant_id = os.getenv("MicrosoftAppTenantId")
        if app_tenant_id is None:
            raise ValueError("MicrosoftAppTenantId environment variable is not set.")

        # Check if the activity is from Teams channel
        if context.activity.channel_id == Channels.ms_teams:
            channel_data = TeamsChannelData().deserialize(
                context.activity.channel_data
            )

            # Check if the turn context's activity has a tenant ID
            if channel_data and channel_data.tenant and channel_data.tenant.id:
                tenant_id = channel_data.tenant.id
                if tenant_id == app_tenant_id:
                    return await logic()
                else:
                    raise NotAuthorizedError(
                        f"Access denied for tenant {tenant_id}."
                    )
            else:
                raise NotAuthorizedError("No tenant ID found in channel data.")
        else:
            raise NotAuthorizedError(
                f"Activity is not from Teams channel. Channel ID: {context.activity.channel_id}"
            )
