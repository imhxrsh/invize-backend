from fastapi import APIRouter, Depends, HTTPException
from db.prisma import prisma
from auth.dependencies import get_current_user
from .schemas import IntegrationsListResponse, IntegrationItem, SetERPRequest, SetERPResponse
from .service import get_erp_type, set_erp_type

router = APIRouter(prefix="/integrations", tags=["Integrations"])

ERP_OPTIONS = [
    {"id": "demo", "name": "Demo ERP", "description": "Built-in demo data for PO matching and vendor validation"},
    {"id": "rest", "name": "SAP / Tally (REST)", "description": "Connect to SAP, Tally or any REST-compatible ERP via API"},
    {"id": "stub", "name": "Stub (no ERP)", "description": "No external ERP; matching only"},
]


@router.get("", response_model=IntegrationsListResponse)
async def list_integrations(user=Depends(get_current_user)):
    """List available integrations and current connection status."""
    current = await get_erp_type(prisma)
    integrations = [
        IntegrationItem(
            id=opt["id"],
            name=opt["name"],
            description=opt["description"],
            connected=(current == opt["id"]),
            type=opt["id"],
        )
        for opt in ERP_OPTIONS
    ]
    return IntegrationsListResponse(integrations=integrations)


@router.patch("/erp", response_model=SetERPResponse)
async def set_erp(payload: SetERPRequest, user=Depends(get_current_user)):
    """Set active ERP integration (demo, rest, or stub)."""
    try:
        value = await set_erp_type(prisma, payload.type)
        return SetERPResponse(type=value, message=f"ERP set to {value}. Matching & ERP agent will use this on next run.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
