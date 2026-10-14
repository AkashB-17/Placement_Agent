from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import init_db
from app.routers import jds, policies, students


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Campus Placement Agent", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(policies.router)
app.include_router(jds.router)
app.include_router(students.router)
