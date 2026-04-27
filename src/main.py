from fastapi import FastAPI
from src.api.routes import router

app = FastAPI()

@app.get("/")
def root():
    return {"status": "root working"}

app.include_router(router)
