from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import datetime
from app.models.user import UserRole


class UserBase(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str = "readonly"
    is_active: bool = True


class UserCreate(UserBase):
    password: str
    areas: Optional[list[str]] = None

    @field_validator("areas")
    @classmethod
    def _sin_areas_repetidas(cls, v):
        if v is None:
            return v
        # Normaliza espacios y quita duplicados exactos preservando el orden
        # de la primera aparición -- el usuario pudo seleccionar la misma
        # área dos veces sin darse cuenta en el multi-select del frontend.
        vistos, limpio = set(), []
        for area in v:
            a = (area or "").strip()
            if a and a not in vistos:
                vistos.add(a)
                limpio.append(a)
        return limpio


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None
    areas: Optional[list[str]] = None

    @field_validator("areas")
    @classmethod
    def _sin_areas_repetidas(cls, v):
        if v is None:
            return v
        vistos, limpio = set(), []
        for area in v:
            a = (area or "").strip()
            if a and a not in vistos:
                vistos.add(a)
                limpio.append(a)
        return limpio


class UserResponse(UserBase):
    id: int
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    areas: list[str] = []

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # segundos de vida del access_token
    user: UserResponse


class AccessTokenResponse(BaseModel):
    """Respuesta de POST /api/auth/refresh -- solo el access_token nuevo,
    el refresh_token no rota (ver auth_service.verify_refresh_token)."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    """A diferencia de RefreshTokenRequest, el refresh_token es opcional
    aquí: revocar solo el access_token ya es mejor que no revocar nada."""
    refresh_token: Optional[str] = None


class TokenData(BaseModel):
    username: Optional[str] = None
    role: Optional[str] = None
