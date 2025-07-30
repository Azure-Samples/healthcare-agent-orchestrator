from datetime import datetime, timezone

from fastapi import APIRouter


def time_routes():
    """
    This module is used by OpenAPI plugin example.
    See https://github.com/Azure-Samples/healthcare-agent-orchestrator/blob/main/docs/agent_development.md#agent-with-a-openapi-plugin-example
    """
    router = APIRouter()

    @router.get("/api/current_time")
    async def get_current_time():
        return {"current_time": datetime.now(tz=timezone.utc).isoformat(timespec="seconds")}

    return router
