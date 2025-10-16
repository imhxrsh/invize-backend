from fastapi import APIRouter, Depends
from prisma import Prisma
from db.prisma import prisma
from auth.dependencies import get_current_user
from .schemas import ProfileContext
from .service import build_profile_context


router = APIRouter(prefix="/profile", tags=["Profile"])


@router.get("/context", response_model=ProfileContext)
async def profile_context(user=Depends(get_current_user)):
    ctx = await build_profile_context(prisma, user)
    return ctx