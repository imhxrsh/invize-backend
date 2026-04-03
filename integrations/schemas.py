from typing import List, Optional
from pydantic import BaseModel


class IntegrationItem(BaseModel):
    id: str
    name: str
    description: str
    connected: bool
    type: Optional[str] = None  # e.g. "demo", "rest", "tally", "sap"


class IntegrationsListResponse(BaseModel):
    integrations: List[IntegrationItem]


class SetERPRequest(BaseModel):
    type: str  # "demo" | "rest" | "stub" (tally/sap use "rest" with base_url)


class SetERPResponse(BaseModel):
    type: str
    message: str
