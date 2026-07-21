from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from fastapi import HTTPException, status, Depends
from fastapi.security import OAuth2PasswordBearer

from app.config import settings
from app.models.user import User
from app.database import get_db
from app.schemas.user import TokenData

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def role_value(user: User) -> str:
    """Normaliza el rol a string: Enum en Postgres, str plano en SQLite."""
    return user.role.value if hasattr(user.role, "value") else str(user.role)


def _create_token(data: dict, expires_delta: timedelta, token_type: str) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(timezone.utc) + expires_delta
    to_encode["type"] = token_type
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Token corto (ver settings.ACCESS_TOKEN_EXPIRE_MINUTES). Solo sirve
    para autenticar requests -- get_current_user rechaza cualquier otro
    "type" de token, incluido un refresh token."""
    return _create_token(
        data,
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        token_type="access",
    )


def create_refresh_token(data: dict) -> str:
    """Token largo (ver settings.REFRESH_TOKEN_EXPIRE_DAYS). Solo sirve para
    canjear por un access_token nuevo en POST /api/auth/refresh -- nunca
    autentica un request directamente (ver get_current_user)."""
    return _create_token(
        data,
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        token_type="refresh",
    )


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudo validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        # Un refresh token no debe poder autenticar requests directamente
        # (ni tokens de antes de SEC-2, que no traen "type" -> None).
        if payload.get("type") != "access":
            raise credentials_exception
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username, role=payload.get("role"))
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == token_data.username).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def verify_refresh_token(db: Session, refresh_token: str) -> User:
    """Valida un refresh token y devuelve el usuario asociado.

    Lanza 401 si el token es invalido, expirado, no es de tipo "refresh",
    o el usuario ya no existe o esta inactivo. No rota ni revoca el refresh
    token (esa infraestructura -- blacklist de Redis -- llega en SEC-3);
    por ahora un refresh token filtrado sigue siendo valido hasta que expira
    (REFRESH_TOKEN_EXPIRE_DAYS), igual que ya documentaba el pentest.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Refresh token inválido o expirado",
    )
    try:
        payload = jwt.decode(refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "refresh":
            raise credentials_exception
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if user is None:
        raise credentials_exception
    return user


def require_role(*roles: str):
    """Dependencia para requerir uno de los roles especificados."""
    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        if role_value(current_user) not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Se requiere uno de los roles: {', '.join(roles)}",
            )
        return current_user
    return dependency


require_admin = require_role("admin")
require_admin_or_analyst = require_role("admin", "analyst")
