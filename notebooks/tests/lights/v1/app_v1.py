from pathlib import Path
from typing import Annotated
from fastapi import FastAPI, Header
from fastapi.responses import FileResponse

from data_model import ChangeStateRequest, LightStateModel


app = FastAPI()

@app.get('/swagger.json')
def get_swagger_json():
    cur_path = Path(__file__).parent
    swagger_path = cur_path / "swagger.json"
    return FileResponse(swagger_path)

@app.get('/Light')
def get_lights(
    authorization: Annotated[str | None, Header()],
    teams_chat_id: Annotated[str | None, Header()],
) -> list[LightStateModel]:
    print(f"Authorization: {authorization}, Teams Chat ID: {teams_chat_id}")
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
def set_light(id: str, csr: ChangeStateRequest,
    authorization: Annotated[str | None, Header()],
    teams_chat_id: Annotated[str | None, Header()],
) -> LightStateModel:
    print(f"Authorization: {authorization}, Teams Chat ID: {teams_chat_id}")
    print(f"Setting light {id} to {csr.isOn}, brightness: {csr.brightness}, color: {csr.hex_color}, fade duration: {csr.fadeDurationInMilliseconds}")
    return LightStateModel(
        id=id,
        name='Lamp',
        on=csr.isOn,
        brightness=100,
    )
