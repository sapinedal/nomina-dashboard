from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import datetime, timezone, UTC

from app.database import get_db
from app.services.auth_service import authenticate_user, create_access_token, get_current_user
from app.models.user import User
from app.schemas.user import Token, UserResponse

router = APIRouter(prefix="/api/auth", tags=["Autenticación"])


@router.post("/token", response_model=Token, summary="Iniciar sesión")
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Autenticar usuario y obtener token JWT."""
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

    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    access_token = create_access_token(
        data={"sub": user.username, "role": role_val}
    )
    return Token(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse, summary="Perfil del usuario actual")
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/logout", summary="Cerrar sesión")
async def logout():
    """El logout se gestiona en el cliente eliminando el token."""
    return {"message": "Sesión cerrada correctamente"}
