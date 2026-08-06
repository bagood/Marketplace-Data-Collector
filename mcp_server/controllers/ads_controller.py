from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from mcp_server.dependencies import get_ads_service
from mcp_server.models import AdsPage, DatasetMetadata
from mcp_server.repositories import DatasetNotFoundError
from mcp_server.services import AdsService

router = APIRouter(prefix="/api/v1/ads", tags=["ads"])

@router.get("", response_model=AdsPage)
def fetch_ads(limit: int = Query(100, ge=1, le=AdsService.MAX_PAGE_SIZE),
              offset: int = Query(0, ge=0), source: str | None = None,
              condition_rating: str | None = None, query: str | None = None,
              service: AdsService = Depends(get_ads_service)) -> dict:
    try:
        return service.fetch_ads(limit=limit, offset=offset, source=source,
                                 condition_rating=condition_rating, query=query)
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.get("/metadata", response_model=DatasetMetadata)
def dataset_metadata(service: AdsService = Depends(get_ads_service)) -> dict:
    try:
        return service.metadata()
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

@router.get("/by-link")
def get_ad(link: str, service: AdsService = Depends(get_ads_service)) -> dict:
    try:
        ad = service.get_ad(link)
    except DatasetNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if ad is None:
        raise HTTPException(status_code=404, detail="Advertisement not found")
    return ad
