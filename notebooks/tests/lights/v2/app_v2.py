import asyncio
from pathlib import Path
from typing import Annotated
from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse
from sse_starlette import EventSourceResponse

from data_model import ChangeStateRequest, LightStateModel


app = FastAPI()

@app.get('/swagger.json')
def get_swagger_json():
    cur_path = Path(__file__).parent
    swagger_path = cur_path / "swagger.json"
    return FileResponse(swagger_path)

@app.get('/Light')
def get_lights() -> list[LightStateModel]:
    return [
        LightStateModel(
            id='123',
            name='Lamp',
            on=False,
            brightness=50,
        ),
        LightStateModel(
            id='234',
            name='Bathroom Light',
            on=False,
            brightness=100,
        )
    ]

@app.post('/Light/{id}')
def set_light(id: str, csr: ChangeStateRequest, request: Request,
    authorization: Annotated[str | None, Header()],
    teams_chat_id: Annotated[str | None, Header()] = None,
) -> LightStateModel:
    print(f"Authorization: {authorization}, Teams Chat ID: {teams_chat_id}")
    print(f"Setting light {id} to {csr.isOn}, brightness: {csr.brightness}, color: {csr.hex_color}, fade duration: {csr.fadeDurationInMilliseconds}")

    async def event_generator():
        # Simulate a long-running process or event stream
        # Send 2 events with the last event turning off the light
        for i in range(2):
            # If client closes connection, stop sending events
            if await request.is_disconnected():
                break

            # Checks for new messages and return them to client if any
            yield LightStateModel(
                id=id,
                name='Lamp',
                on=i % 2 == 0,
                brightness=100,
            )

            print(f"Sent event {i + 1}. isOn: {i % 2 == 0}")
            await asyncio.sleep(1) # Simulate some delay

    return EventSourceResponse(event_generator())
