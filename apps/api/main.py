import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routers import graphs as graphs_router
from apps.api.routers import jobs as jobs_router
from apps.api.routers import messages as messages_router
from apps.api.routers import pipeline as pipeline_router
from apps.api.routers import portfolio as portfolio_router
from apps.api.routers import portfolio_manage as portfolio_manage_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        yield
        return

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncPostgresSaver.from_conn_string(database_url) as checkpointer:
        await checkpointer.setup()
        graphs_router.configure_checkpointer(checkpointer)
        try:
            yield
        finally:
            graphs_router.configure_checkpointer(None)


app = FastAPI(title="GigBid API", version="0.1.0", lifespan=lifespan)
allowed_origins = [
    origin.strip()
    for origin in os.environ.get("GIGBID_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(graphs_router.router)
app.include_router(jobs_router.router)
app.include_router(messages_router.router)
app.include_router(pipeline_router.router)
app.include_router(portfolio_router.router)
app.include_router(portfolio_manage_router.router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
