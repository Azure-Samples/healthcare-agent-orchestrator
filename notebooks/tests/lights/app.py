from fastapi import FastAPI
import uvicorn

from v1 import app_v1
from v2 import app_v2


app = FastAPI()
app.mount("/v1", app_v1.app)
app.mount("/v2", app_v2.app)

if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=3978)
