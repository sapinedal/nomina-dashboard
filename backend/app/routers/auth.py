from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import datetime

from app.config import settings
from app.database import get_db
from app.middleware.rate_limit import limiter
from app.services.auth_service import (
    ACCESS_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    authenticate_user,
    create_access_token,
    create_refresh_token,
    extract_access_token,
    get_current_user,
    oauth2_scheme,
    revoke_token,
    role_value,
    verify_refresh_token,
)
from app.models.user import User
from app.schemas.user import Token, UserResponse, AccessTokenResponse, RefreshTokenRequest, LogoutRequest

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])


def _access_token_ttl_seconds() -> int:
    return settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def _refresh_token_ttl_seconds() -> int:
    return settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60


def _set_auth_cookies(response: Response, access_token: str, refresh_token: Optional[str] = None) -> None:
    """DEF-0003: tokens solo en cookies HttpOnly (no legibles por JS)."""
    common = {
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "path": "/",
    }
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=access_token,
        max_age=_access_token_ttl_seconds(),
        **common,
    )
    if refresh_token:
        response.set_cookie(
            key=REFRESH_COOKIE_NAME,
            value=refresh_token,
            max_age=_refresh_token_ttl_seconds(),
            **common,
        )


def _clear_auth_cookies(response: Response) -> None:
    for name in (ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME):
        response.delete_cookie(
            key=name,
            path="/",
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
        )


@router.post("/token", response_model=Token, summary="Iniciar sesión")
@limiter.limit(settings.RATE_LIMIT_LOGIN)
async def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Autenticar usuario y obtener access_token (corto) + refresh_token
    (largo, ver settings.REFRESH_TOKEN_EXPIRE_DAYS).

    Además fija ambos tokens en cookies HttpOnly (DEF-0003). El body JSON
    se mantiene por compatibilidad con clientes API; el frontend web no
    debe persistir los JWT en localStorage.

    Rate-limited (SEC-4, settings.RATE_LIMIT_LOGIN) contra fuerza bruta y
    credential stuffing. El límite cuenta CADA intento, exitoso o no, por IP
    real del cliente (ver middleware.rate_limit.client_ip)."""
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user.last_login = datetime.utcnow()
    db.commit()

    claims = {"sub": user.username, "role": role_value(user)}
    access_token = create_access_token(data=claims)
    refresh_token = create_refresh_token(data=claims)
    _set_auth_cookies(response, access_token, refresh_token)
    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=_access_token_ttl_seconds(),
        user=UserResponse.model_validate(user),
    )


@router.post("/refresh", response_model=AccessTokenResponse, summary="Renovar token de acceso")
async def refresh_access_token(
    request: Request,
    response: Response,
    payload: Optional[RefreshTokenRequest] = None,
    db: Session = Depends(get_db),
):
    """Canjea un refresh_token vigente por un access_token nuevo, sin pedir
    contraseña de nuevo. No emite un refresh_token nuevo (no rota).

    Acepta refresh_token en el body JSON o en cookie HttpOnly."""
    refresh = None
    if payload and payload.refresh_token:
        refresh = payload.refresh_token
    if not refresh:
        refresh = request.cookies.get(REFRESH_COOKIE_NAME)
    if not refresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token inválido o expirado",
        )
    user = verify_refresh_token(db, refresh)
    access_token = create_access_token(data={"sub": user.username, "role": role_value(user)})
    _set_auth_cookies(response, access_token)
    return AccessTokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=_access_token_ttl_seconds(),
    )


@router.get("/me", response_model=UserResponse, summary="Perfil del usuario actual")
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/logout", summary="Cerrar sesión")
async def logout(
    request: Request,
    response: Response,
    payload: Optional[LogoutRequest] = None,
    bearer: Optional[str] = Depends(oauth2_scheme),
):
    """Revoca access (+ refresh si aplica) y limpia cookies HttpOnly."""
    access = extract_access_token(request, bearer)
    refresh = None
    if payload and payload.refresh_token:
        refresh = payload.refresh_token
    if not refresh:
        refresh = request.cookies.get(REFRESH_COOKIE_NAME)

    if access:
        revoke_token(access)
    if refresh:
        revoke_token(refresh)

    _clear_auth_cookies(response)
    return {"message": "Sesión cerrada correctamente"}
