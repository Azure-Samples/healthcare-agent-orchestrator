import logging
import os
from typing import Awaitable, Callable

from botbuilder.core import Middleware, TurnContext
from botbuilder.schema import ActivityTypes
from botbuilder.schema.teams import TeamsChannelAccount, TeamsChannelData
from botframework.connector import Channels

from errors import NotAuthorizedError

ALLOW_ALL_IDS = ["*"]

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
            return await logic()

        # Check if the activity is from Teams channel
        if context.activity.channel_id != Channels.ms_teams:
            raise NotAuthorizedError(
                f"Activity is not from Teams channel. Channel ID: {context.activity.channel_id}"
            )

        # Deserialize channel account and channel data
        channel_account = TeamsChannelAccount().deserialize(
            context.activity.from_property
        )
        channel_data = TeamsChannelData().deserialize(
            context.activity.channel_data
        )

        # Check if the turn context's activity has a user ID
        if not channel_account or not channel_account.aad_object_id:
            raise NotAuthorizedError("No user ID found in channel account.")

        # Check if the turn context's activity has a tenant ID
        if not channel_data or not channel_data.tenant or not channel_data.tenant.id:
            raise NotAuthorizedError("No tenant ID found in channel data.")

        # Check if the user is allowed
        user_id = channel_account.aad_object_id
        allowed_user_ids = self._get_allowed_ids(
            "AZURE_DEPLOYER_OBJECT_ID", "ADDITIONAL_ALLOWED_USER_IDS")
        is_user_allowed = user_id in allowed_user_ids or allowed_user_ids == ALLOW_ALL_IDS
        if not is_user_allowed:
            raise NotAuthorizedError(
                f"Access denied for user {user_id}."
            )

        # Check if the tenant is allowed
        tenant_id = channel_data.tenant.id
        allowed_tenant_ids = self._get_allowed_ids(
            "MicrosoftAppTenantId", "ADDITIONAL_ALLOWED_TENANT_IDS")
        is_tenant_allowed = tenant_id in allowed_tenant_ids or allowed_tenant_ids == ALLOW_ALL_IDS
        if not is_tenant_allowed:
            raise NotAuthorizedError(
                f"Access denied for tenant {tenant_id}."
            )

        return await logic()

    @staticmethod
    def _get_allowed_ids(default_allowed_id_name: str, additional_allowed_ids_name: str) -> list[str]:
        """
        Helper method to retrieve allowed IDs from environment variables.
        Always includes the default allowed ID and appends any additional IDs.
        """
        # Get the default allowed ID
        default_allowed_id = os.getenv(default_allowed_id_name)
        if default_allowed_id is None:
            raise ValueError(f"{default_allowed_id_name} environment variable is not set.")

        # Retrieve additional allowed IDs from environment variable
        additional_allowed_ids = os.getenv(additional_allowed_ids_name)
        if additional_allowed_ids is None:
            return [default_allowed_id]

        if additional_allowed_ids == "*":
            # If the additional allowed IDs is "*", allow all IDs
            return ALLOW_ALL_IDS

        # Allow the default ID and split additional IDs by comma
        return [default_allowed_id] + [id.strip() for id in additional_allowed_ids.split(",")]
