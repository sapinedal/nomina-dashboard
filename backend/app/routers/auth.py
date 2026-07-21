from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import datetime

from app.config import settings
from app.database import get_db
from app.services.auth_service import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
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


@router.post("/token", response_model=Token, summary="Iniciar sesión")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Autenticar usuario y obtener access_token (corto) + refresh_token
    (largo, ver settings.REFRESH_TOKEN_EXPIRE_DAYS)."""
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Actualizar último acceso (sin zona horaria para compatibilidad SQLite)
    user.last_login = datetime.utcnow()
    db.commit()

    claims = {"sub": user.username, "role": role_value(user)}
    return Token(
        access_token=create_access_token(data=claims),
        refresh_token=create_refresh_token(data=claims),
        token_type="bearer",
        expires_in=_access_token_ttl_seconds(),
        user=UserResponse.model_validate(user),
    )


@router.post("/refresh", response_model=AccessTokenResponse, summary="Renovar token de acceso")
async def refresh_access_token(
    payload: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    """Canjea un refresh_token vigente por un access_token nuevo, sin pedir
    contraseña de nuevo. No emite un refresh_token nuevo (no rota)."""
    user = verify_refresh_token(db, payload.refresh_token)
    return AccessTokenResponse(
        access_token=create_access_token(data={"sub": user.username, "role": role_value(user)}),
        token_type="bearer",
        expires_in=_access_token_ttl_seconds(),
    )


@router.get("/me", response_model=UserResponse, summary="Perfil del usuario actual")
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/logout", summary="Cerrar sesión")
async def logout(
    payload: Optional[LogoutRequest] = None,
    token: str = Depends(oauth2_scheme),
    _: User = Depends(get_current_user),
):
    """Revoca el access_token usado en esta llamada y, si el cliente lo
    envía, el refresh_token asociado -- ambos dejan de servir de inmediato,
    incluso si aún no expiraron (ver auth_service.revoke_token).

    Revocar solo el access_token no bastaría: el refresh_token seguiría
    vigente hasta REFRESH_TOKEN_EXPIRE_DAYS y podría canjearse por un
    access_token nuevo en /api/auth/refresh, dejando el "logout" sin efecto
    real para quien tenga ambos tokens."""
    revoke_token(token)
    if payload and payload.refresh_token:
        revoke_token(payload.refresh_token)
    return {"message": "Sesión cerrada correctamente"}
