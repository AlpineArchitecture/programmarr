#!/usr/bin/env python3
"""Programmarr web server — FastAPI backend."""

import asyncio
import base64
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# asyncio.create_subprocess_exec requires ProactorEventLoop on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from routers import channels_router, config_router, logs_router, pipeline_router, recipes_router, status_router

DATA_DIR = Path(os.environ.get("PROGRAMMARR_DATA", Path(__file__).parent.parent))
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure data directories exist before serving any requests
    (DATA_DIR / "logs").mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Programmarr", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    config_path = DATA_DIR / "config.json"
    try:
        with open(config_path) as f:
            config = json.load(f)
    except Exception:
        config = {}

    auth_user = config.get("auth_username", "")
    auth_pass = config.get("auth_password", "")

    if auth_user and auth_pass:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Basic "):
            return Response(
                content="Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Programmarr"'},
            )
        try:
            decoded = base64.b64decode(auth_header[6:]).decode()
            username, password = decoded.split(":", 1)
            if username != auth_user or password != auth_pass:
                raise ValueError("bad credentials")
        except Exception:
            return Response(
                content="Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Programmarr"'},
            )

    return await call_next(request)


app.include_router(config_router.router, prefix="/api")
app.include_router(status_router.router, prefix="/api")
app.include_router(channels_router.router, prefix="/api")
app.include_router(pipeline_router.router, prefix="/api")
app.include_router(recipes_router.router, prefix="/api")
app.include_router(logs_router.router, prefix="/api")

if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon():
        return Response(content=(STATIC_DIR / "favicon.svg").read_bytes(), media_type="image/svg+xml")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        return HTMLResponse(content=(STATIC_DIR / "index.html").read_text())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=7979, reload=False)
