from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from db.prisma import prisma
from config.auth_settings import AuthSettings
from .schemas import LoginRequest, RegisterRequest, TokenResponse, RefreshRequest, MeResponse
from .service import register_user, login_user, refresh_access_token, logout_session
from .dependencies import get_current_user


router = APIRouter(prefix="/auth", tags=["Auth"])
settings = AuthSettings()


@router.post("/register", response_model=MeResponse)
async def register(payload: RegisterRequest):
    user, err = await register_user(prisma, payload.email, payload.password)
    if err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    return MeResponse(id=user.id, email=user.email, roles=user.roles or [], permissions=getattr(user, "permissions", []) or [])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, response: Response):
    user_agent = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    tokens, refresh, err = await login_user(prisma, payload.email, payload.password, user_agent, ip)
    if err:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=err)
    if settings.REFRESH_TOKEN_TRANSPORT == "cookie":
        # Auto-toggle secure based on scheme for local dev (HTTP) vs prod (HTTPS)
        cookie_secure = request.url.scheme == "https"
        response.set_cookie(
            key="refresh_token",
            value=refresh,
            httponly=True,
            samesite="strict",
            secure=cookie_secure,
            max_age=int(settings.REFRESH_TOKEN_TTL_DAYS * 24 * 60 * 60),
            path="/auth",
        )
    else:
        # Include refresh token in response header if not using cookies
        response.headers["X-Refresh-Token"] = refresh
    return TokenResponse(access_token=tokens["access_token"]) 


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, request: Request, response: Response):
    presented = payload.refresh_token
    if settings.REFRESH_TOKEN_TRANSPORT == "cookie":
        presented = request.cookies.get("refresh_token")
    tokens, new_refresh, err = await refresh_access_token(prisma, presented or "", request.headers.get("user-agent"), request.client.host if request.client else None)
    if err:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=err)
    if settings.REFRESH_TOKEN_TRANSPORT == "cookie":
        cookie_secure = request.url.scheme == "https"
        response.set_cookie(
            key="refresh_token",
            value=new_refresh,
            httponly=True,
            samesite="strict",
            secure=cookie_secure,
            max_age=int(settings.REFRESH_TOKEN_TTL_DAYS * 24 * 60 * 60),
            path="/auth",
        )
    else:
        response.headers["X-Refresh-Token"] = new_refresh
    return TokenResponse(access_token=tokens["access_token"]) 


@router.post("/logout")
async def logout(request: Request, response: Response, payload: RefreshRequest | None = None):
    presented = payload.refresh_token if payload else None
    cookie_value = request.cookies.get("refresh_token")
    if not presented and cookie_value:
        presented = cookie_value
    await logout_session(prisma, presented)
    if cookie_value:
        response.delete_cookie("refresh_token", path="/auth")
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
async def me(user=Depends(get_current_user)):
    return MeResponse(id=user.id, email=user.email, roles=user.roles or [], permissions=getattr(user, "permissions", []) or [])