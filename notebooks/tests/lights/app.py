from typing import Annotated
from pydantic import BaseModel
import uvicorn
from fastapi import FastAPI, Header
from fastapi.staticfiles import StaticFiles

app = FastAPI()


class LightStateModel(BaseModel):
    id: str
    name: str
    on: bool
    brightness: int = None
    hex_color: str = None

class ChangeStateRequest(BaseModel):
    isOn: bool
    brightness: int = None
    hex_color: str = None
    fadeDurationInMilliseconds: int = None

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
def set_light(id: str, csr: ChangeStateRequest,
    authorization: Annotated[str | None, Header()],
    teams_chat_id: Annotated[str | None, Header()] = None
) -> LightStateModel:
    print(f"Authorization: {authorization}, Teams Chat ID: {teams_chat_id}")
    print(f"Setting light {id} to {csr.isOn}, brightness: {csr.brightness}, color: {csr.hex_color}, fade duration: {csr.fadeDurationInMilliseconds}")
    return LightStateModel(
        id=id,
        name='Lamp',
        on=csr.isOn,
        brightness=100,
    )

app.mount("/v1", StaticFiles(directory="v1"), name="v1")

if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=3978)
