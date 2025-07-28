from pydantic import BaseModel


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