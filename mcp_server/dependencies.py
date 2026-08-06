from functools import lru_cache
from mcp_server.config import get_csv_path
from mcp_server.repositories import AdsRepository
from mcp_server.services import AdsService

@lru_cache
def get_ads_service() -> AdsService:
    return AdsService(AdsRepository(get_csv_path()))
