import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import close_pool, init_db, open_pool
from app.routers import admin, applications, jds, match, policies, students
from app.services import auto_apply

logger = logging.getLogger("uvicorn.error")


def check_startup_settings() -> None:
    settings = get_settings()
    if settings.dev_auth_bypass and settings.database_url:
        raise RuntimeError("DEV_AUTH_BYPASS is only allowed with the local SQLite database.")


async def _release_sweep(interval: float) -> None:
    """Release auto-apply applications whose withdraw window closed. Reads also release
    lazily, so this only keeps statuses and notifications moving while nobody is looking."""
    while True:
        await asyncio.sleep(interval)
        await run_in_threadpool(auto_apply.release_due_quietly)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    check_startup_settings()
    open_pool()
    init_db()
    interval = get_settings().release_sweep_seconds
    sweep = asyncio.create_task(_release_sweep(interval)) if interval > 0 else None
    yield
    if sweep is not None:
        sweep.cancel()
        with suppress(asyncio.CancelledError):
            await sweep
    close_pool()


app = FastAPI(title="Campus Placement Agent", lifespan=lifespan)


class UnhandledErrorMiddleware:
    """Turns an unexpected exception into a JSON 500 *inside* the CORS layer.

    Without this, Starlette answers crashes from its outermost layer, after CORS, so the
    browser gets a response with no CORS header, hides it, and the web app can only say
    "can't reach the API". The traceback goes to the server log; the client gets no internals.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def tracking_send(message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            logger.exception("Unhandled error on %s %s", scope["method"], scope["path"])
            if response_started:
                raise
            response = JSONResponse({"detail": "Internal server error. Check the API log."}, status_code=500)
            await response(scope, receive, send)


class SettingsCORSMiddleware(CORSMiddleware):
    """CORS for the Next.js app. Starlette builds middleware on the first request, so the
    origins come from settings at that point (not at import time, which would read .env
    in tests). Auth is a bearer token, not cookies, so credentials stay off."""

    def __init__(self, app) -> None:
        super().__init__(
            app,
            allow_origins=get_settings().cors_origins,
            allow_methods=["GET", "POST", "PUT"],
            allow_headers=["Authorization", "Content-Type"],
        )


# Starlette runs the last-added middleware first, so CORS wraps the error handler and
# even 500s carry CORS headers.
app.add_middleware(UnhandledErrorMiddleware)
app.add_middleware(SettingsCORSMiddleware)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(admin.router)
app.include_router(policies.router)
app.include_router(jds.router)
app.include_router(students.router)
app.include_router(match.router)
app.include_router(applications.router)
