from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp_server.dependencies import get_ads_service

mcp = FastMCP("Combined Marketplace Ads",
              instructions="Read and search the local combined marketplace ad dataset. All tools are read-only.",
              stateless_http=True, json_response=True)

@mcp.tool()
def fetch_ads(limit: int = 100, offset: int = 0, source: str | None = None,
              condition_rating: str | None = None, query: str | None = None) -> dict:
    """Fetch a page of ads, optionally filtering by source, rating, or text."""
    return get_ads_service().fetch_ads(limit=limit, offset=offset, source=source,
                                       condition_rating=condition_rating, query=query)

@mcp.tool()
def get_ad_by_link(link: str) -> dict:
    """Fetch one advertisement using its exact marketplace URL."""
    ad = get_ads_service().get_ad(link)
    return ad or {"error": "Advertisement not found", "link": link}

@mcp.tool()
def get_dataset_metadata() -> dict:
    """Return columns, row count, sources, and condition ratings."""
    return get_ads_service().metadata()
