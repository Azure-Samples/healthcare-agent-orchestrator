from datetime import datetime, timezone

from fastapi import APIRouter


def time_routes():
    router = APIRouter()

    @router.get("/api/current_time")
    async def get_current_time():
        return {"current_time": datetime.now(tz=timezone.utc).isoformat(timespec="seconds")}

    return router
