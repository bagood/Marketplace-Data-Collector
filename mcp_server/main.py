from contextlib import asynccontextmanager
from fastapi import FastAPI
from mcp_server.config import get_csv_path
from mcp_server.controllers import router
from mcp_server.mcp_tools import mcp
from mcp_server.models import HealthResponse

@asynccontextmanager
async def lifespan(_: FastAPI):
    async with mcp.session_manager.run():
        yield

app = FastAPI(title="Combined Marketplace Ads MCP",
              description="Read-only API and MCP server backed by combined_rated_ads.csv.",
              version="1.0.0", lifespan=lifespan)
app.include_router(router)

@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    exists = get_csv_path().is_file()
    return HealthResponse(status="ok" if exists else "degraded", dataset_available=exists)

# FastMCP's mounted ASGI app provides the Streamable HTTP endpoint at /mcp.
app.mount("/", mcp.streamable_http_app())
